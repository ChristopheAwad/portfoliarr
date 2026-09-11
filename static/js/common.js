// common.js — code shared by EVERY page (dashboard + stock detail).
//
// This file is loaded by base.html BEFORE each page's own script, so
// everything defined here becomes a plain global the page scripts can
// use. It contains:
//   1. Formatting helpers (backend sends raw floats; formatting is
//      frontend-only — a permanent rule of this app)
//   2. paintChange — the signed "change pill" painter
//   3. The UI kit — SVG icons, promise-based modals (showConfirm /
//      showPrompt), and toasts: the styled replacements for the browser's
//      built-in prompt/confirm/alert dialogs
//   4. The navbar search dropdown (fetch -> JSON -> DOM, like everything
//      else here; knows nothing about yfinance, Flask, or Python)
//   5. The shared timeframe-chart factory (both pages' price charts)

// How often the page scripts re-fetch quotes, in milliseconds. Matches
// the backend's design: the 120s TTL means at most every other poll
// touches Yahoo.
const REFRESH_MS = 60000;

// ---------------------------------------------------------------------------
// FORMATTERS — the browser's built-in human formatting engine.
// 7711.759765625 -> "7,711.76". This is why the backend sends raw floats.
// ---------------------------------------------------------------------------

function formatPrice(value) {
    return new Intl.NumberFormat("en-US", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    }).format(value);
}

// Grouped-thousands formatter with a flexible decimal cap. Unlike
// formatPrice (fixed at 2), maxDigits lets a qty column show fractional
// amounts ("0.0050" BTC) without trailing-zero spam on whole numbers.
function formatNumber(value, maxDigits = 2) {
    return new Intl.NumberFormat("en-US", {
        minimumFractionDigits: 2,
        maximumFractionDigits: maxDigits,
    }).format(value);
}

// Signed money text: 12.3 -> "+12.30 CAD", -7.1 -> "-7.10 CAD".
// Gains are signed in the DATA; the sign character is presentation,
// so it belongs here (same rule as the chips' "+" prefix).
function formatSigned(value, currency) {
    const sign = value >= 0 ? "+" : "";
    return `${sign}${formatNumber(value)} ${currency}`;
}

// Paint one signed "change pill" beside a big price:
//   "+30.00 (+5.00%) Today"
// Same presentation rules as the ledger's signed cells: the sign lives in
// the DATA as a raw float, so adding the "+" character here is presentation.
// pct === null means "no meaningful base to divide by" (e.g. a fully-sold
// portfolio) — the amount still shows, only the % degrades away.
function paintChange(el, value, pct, label) {
    const sign = value >= 0 ? "+" : "";
    el.textContent = pct === null
        ? `${sign}${formatNumber(value)} ${label}`
        : `${sign}${formatNumber(value)} (${sign}${pct.toFixed(2)}%) ${label}`;
    // One call each: set green (pos) or red (neg), replacing the other.
    el.classList.toggle("pos", value >= 0);
    el.classList.toggle("neg", value < 0);
}

// ---------------------------------------------------------------------------
// UI KIT — the app's small presentation toolbox: SVG icons, promise-based
// dialogs, and toasts. These exist so no page ever falls back to the
// browser's built-in prompt/confirm/alert dialogs, which freeze the whole
// page while open, can't be styled, and would look alien next to everything
// else here. Same iron rule as everywhere else: everything is built with
// createElement/createElementNS + textContent, never innerHTML — titles and
// messages here come from OUR code, but one DOM habit everywhere is easier
// to trust than two.
// ---------------------------------------------------------------------------

// SVG's namespace URI. HTML elements live in the HTML namespace, but an
// <svg> and its children belong to SVG's own — createElementNS must be told
// which to use. A plain createElement("svg") creates an element the browser
// refuses to render as graphics (a boring "HTMLUnknownElement").
const SVG_NS = "http://www.w3.org/2000/svg";

// The icon library: each name maps to a STATIC list of child shapes
// (tag + attributes) drawn inside the 24×24 viewBox. Path data is written
// out literally and never assembled from runtime strings — the same
// "no string-built DOM" rule as everywhere else, applied to SVG, so no
// runtime value could ever bend an icon into something else. The shapes
// are feather-style outlines: stroke-drawn, unfilled, inheriting their
// color from the text around them via stroke="currentColor" (CSS colors an
// icon exactly like it colors a word).
const ICONS = {
    pencil: [
        { tag: "path",
          attrs: { d: "M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z" } },
    ],
    trash: [
        { tag: "polyline", attrs: { points: "3 6 5 6 21 6" } },
        { tag: "path",
          attrs: { d: "M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" } },
        { tag: "line", attrs: { x1: "10", y1: "11", x2: "10", y2: "17" } },
        { tag: "line", attrs: { x1: "14", y1: "11", x2: "14", y2: "17" } },
    ],
    x: [
        { tag: "line", attrs: { x1: "18", y1: "6", x2: "6", y2: "18" } },
        { tag: "line", attrs: { x1: "6", y1: "6", x2: "18", y2: "18" } },
    ],
    plus: [
        { tag: "line", attrs: { x1: "12", y1: "5", x2: "12", y2: "19" } },
        { tag: "line", attrs: { x1: "5", y1: "12", x2: "19", y2: "12" } },
    ],
    search: [
        { tag: "circle", attrs: { cx: "11", cy: "11", r: "8" } },
        { tag: "line", attrs: { x1: "21", y1: "21", x2: "16.65", y2: "16.65" } },
    ],
    // A chevron pointing RIGHT. CSS rotates the wrapper (e.g. the ledger's
    // .caret span) for the expanded state, so one shape serves both.
    caret: [
        { tag: "polyline", attrs: { points: "9 18 15 12 9 6" } },
    ],
    check: [
        { tag: "polyline", attrs: { points: "20 6 9 17 4 12" } },
    ],
    // Sun icon for the dark-mode toggle (shown when dark mode is ON).
    sun: [
        { tag: "circle", attrs: { cx: "12", cy: "12", r: "5" } },
        { tag: "line", attrs: { x1: "12", y1: "1", x2: "12", y2: "3" } },
        { tag: "line", attrs: { x1: "12", y1: "21", x2: "12", y2: "23" } },
        { tag: "line", attrs: { x1: "4.22", y1: "4.22", x2: "5.64", y2: "5.64" } },
        { tag: "line", attrs: { x1: "18.36", y1: "18.36", x2: "19.78", y2: "19.78" } },
        { tag: "line", attrs: { x1: "1", y1: "12", x2: "3", y2: "12" } },
        { tag: "line", attrs: { x1: "21", y1: "12", x2: "23", y2: "12" } },
        { tag: "line", attrs: { x1: "4.22", y1: "19.78", x2: "5.64", y2: "18.36" } },
        { tag: "line", attrs: { x1: "18.36", y1: "5.64", x2: "19.78", y2: "4.22" } },
    ],
    // Moon icon for the dark-mode toggle (shown when dark mode is OFF).
    moon: [
        { tag: "path",
          attrs: { d: "M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" } },
    ],
};

// Build one icon as a live SVG element (never an HTML string). className
// is optional extra styling layered on top of the shared "icon" base
// class. aria-hidden marks the picture as decorative for screen readers —
// the buttons carrying these icons announce themselves via title/label.
function icon(name, className) {
    const svg = document.createElementNS(SVG_NS, "svg");
    for (const [attr, value] of Object.entries({
        viewBox: "0 0 24 24",
        fill: "none",
        stroke: "currentColor",
        "stroke-width": "2",
        "stroke-linecap": "round",
        "stroke-linejoin": "round",
        class: "icon" + (className ? " " + className : ""),
        "aria-hidden": "true",
    })) {
        svg.setAttribute(attr, value);
    }
    // Stamp in the shape list. An unknown name degrades to a valid empty
    // SVG rather than a crash — same forgiving-degradation spirit as "—".
    for (const { tag, attrs } of ICONS[name] || []) {
        const shape = document.createElementNS(SVG_NS, tag);
        for (const [attr, value] of Object.entries(attrs)) {
            shape.setAttribute(attr, value);
        }
        svg.append(shape);
    }
    return svg;
}

// The ONE modal builder both dialogs share — internal to this kit: page
// scripts call showConfirm/showPrompt below, and this function exists so
// the overlay/dialog/input/focus plumbing is written exactly once.
//
// It returns a PROMISE, and that is what makes the swap from the browser's
// dialogs possible at all: the built-ins BLOCK the script (which is also
// why they can't be styled), while a promise lets the caller `await` the
// answer and lets this code paint real DOM for the question meanwhile.
function openModal({ title, message, wantsInput, placeholder = "",
                     confirmLabel = "Confirm", cancelLabel = "Cancel",
                     danger = false }) {
    return new Promise((resolve) => {
        // Remember where focus was BEFORE we took over, so it can go back
        // when the modal closes (usually the very button that opened us).
        const previouslyFocused = document.activeElement;

        // --- Build the pieces (createElement only — no innerHTML) ---
        const overlay = document.createElement("div");
        overlay.className = "modal-overlay"; // the dimmed backdrop

        const dialog = document.createElement("div");
        dialog.className = "modal";
        // ARIA: announce this as a modal dialog labelled by its question,
        // so screen readers introduce it properly.
        dialog.setAttribute("role", "dialog");
        dialog.setAttribute("aria-modal", "true");
        dialog.setAttribute("aria-label", title);

        const titleEl = document.createElement("h3");
        titleEl.className = "modal-title";
        titleEl.textContent = title;

        const messageEl = document.createElement("p");
        messageEl.className = "modal-message";
        messageEl.textContent = message;

        // The prompt-only piece: a text field. Created only when asked
        // for, so a confirm dialog ships no stray input.
        let inputEl = null;
        if (wantsInput) {
            inputEl = document.createElement("input");
            inputEl.type = "text";
            inputEl.className = "modal-input";
            inputEl.placeholder = placeholder;
        }

        const actionsEl = document.createElement("div");
        actionsEl.className = "modal-actions";
        const cancelBtn = document.createElement("button");
        cancelBtn.type = "button"; // type="button": never a form submit
        cancelBtn.className = "btn btn-quiet";
        cancelBtn.textContent = cancelLabel;
        const confirmBtn = document.createElement("button");
        confirmBtn.type = "button";
        // danger=true hands the confirm button the destructive styling.
        confirmBtn.className = danger ? "btn btn-danger" : "btn btn-primary";
        confirmBtn.textContent = confirmLabel;
        actionsEl.append(cancelBtn, confirmBtn);

        dialog.append(titleEl, messageEl);
        if (inputEl) dialog.append(inputEl);
        dialog.append(actionsEl);
        overlay.append(dialog);
        document.body.append(overlay);

        // --- One exit for every path ---
        // Every way out (confirm, cancel, Escape, backdrop click) funnels
        // through finish(): it cleans up listeners and DOM, restores
        // focus, and only THEN resolves — so a caller can never observe a
        // half-torn-down modal. (Resolving twice is harmless — a promise
        // keeps its first answer — but cleanup only ever needs doing once.)
        // The two flavors cancel differently: a prompt resolves null (the
        // old browser prompt's cancel value), a confirm resolves false.
        const cancelResult = wantsInput ? null : false;

        function finish(result) {
            document.removeEventListener("keydown", onKeyDown);
            overlay.remove();
            // Hand focus back — without this, focus would fall onto <body>
            // and keyboard users would lose their place in the page.
            if (previouslyFocused && previouslyFocused.focus) {
                previouslyFocused.focus();
            }
            resolve(result);
        }

        // Escape cancels, and Tab is TRAPPED inside the dialog. The
        // listener sits on DOCUMENT while the modal is open — keydowns
        // land wherever focus is (often inside the input), and only
        // document-level listeners see them regardless.
        //
        // The Tab half is the focus trap: aria-modal announces this as a
        // modal to screen readers, but the page behind the overlay is NOT
        // focus-inert, so a plain Tab would happily walk focus out of the
        // dialog and into invisible background controls. When focus would
        // step past the dialog's last (or, with Shift+Tab, before its
        // first) control, it wraps to the other end instead; if focus
        // somehow ended up outside the dialog entirely, it's pulled back
        // to the first control. The focusable set is exactly what this
        // builder created, in DOM order: the optional input, then the two
        // action buttons.
        const focusables = inputEl ? [inputEl, cancelBtn, confirmBtn]
                                   : [cancelBtn, confirmBtn];

        function onKeyDown(event) {
            if (event.key === "Escape") {
                finish(cancelResult);
                return;
            }
            if (event.key === "Tab") {
                const first = focusables[0];
                const last = focusables[focusables.length - 1];
                if (!dialog.contains(document.activeElement)) {
                    event.preventDefault();
                    first.focus();
                } else if (event.shiftKey
                           && document.activeElement === first) {
                    event.preventDefault();
                    last.focus();
                } else if (!event.shiftKey
                           && document.activeElement === last) {
                    event.preventDefault();
                    first.focus();
                }
            }
        }
        document.addEventListener("keydown", onKeyDown);

        // A click on the dimmed BACKDROP cancels — but only when it truly
        // landed on the overlay: event.target is the topmost element
        // clicked, so a click anywhere inside the dialog reports the
        // dialog (or a button), not the overlay, and is ignored here.
        overlay.addEventListener("click", (event) => {
            if (event.target === overlay) finish(cancelResult);
        });

        cancelBtn.addEventListener("click", () => finish(cancelResult));
        confirmBtn.addEventListener("click", () => {
            // The RAW input value, on purpose: trimming and casing are the
            // CALLER's policy (each call site normalizes to its own rules),
            // so the kit collects text but never interprets it.
            finish(wantsInput ? inputEl.value : true);
        });

        // Prompt convenience: Enter inside the input means confirm — the
        // same reflex the old browser prompt trained into everyone.
        if (inputEl) {
            inputEl.addEventListener("keydown", (event) => {
                if (event.key === "Enter") {
                    event.preventDefault(); // no form here; Enter = confirm
                    confirmBtn.click();
                }
            });
        }

        // Focus the first thing the user needs — the input for a prompt,
        // the confirm button for a confirm — AFTER the overlay is in the
        // DOM: an element that isn't rendered cannot take focus.
        (inputEl || confirmBtn).focus();
    });
}

// Ask a yes/no question. Resolves true (Confirm) or false (cancelled).
function showConfirm({ title, message, confirmLabel = "Confirm",
                       cancelLabel = "Cancel", danger = false } = {}) {
    return openModal({
        title, message, confirmLabel, cancelLabel, danger,
        wantsInput: false,
    });
}

// Ask for a line of text. Resolves the RAW typed string, or null when
// cancelled — the exact null contract the old browser prompt had, so the
// callers' `=== null` abort checks survive the swap unchanged.
function showPrompt({ title, message, placeholder = "",
                      confirmLabel = "Confirm", danger = false } = {}) {
    return openModal({
        title, message, placeholder, confirmLabel, danger,
        wantsInput: true,
    });
}

// ---------------------------------------------------------------------------
// TOASTS — the small transient notices (bottom-right, per the CSS) that
// replaced the browser alert(). Fire-and-forget by design: showToast
// returns nothing, toasts stack with any others, and each removes itself
// after ~4 seconds.
// ---------------------------------------------------------------------------

// The shared container, created lazily on first use and reused forever —
// a module-level "singleton" that costs nothing until the first toast.
let toastContainer = null;

function showToast(message, type = "error") {
    if (!toastContainer) {
        toastContainer = document.createElement("div");
        toastContainer.id = "toast-container";
        document.body.append(toastContainer);
    }
    const toast = document.createElement("div");
    // The type picks the palette: "error" (the default) or "success" — and
    // the matching ARIA role makes screen readers announce the notice,
    // which the old alert() did for free. role="alert" is assertive
    // (failures are time-sensitive and the toast only lives ~4s);
    // role="status" is polite for success receipts. Both fire on the
    // element's insertion into the live page, no extra wiring needed.
    toast.setAttribute("role", type === "success" ? "status" : "alert");
    toast.className = type === "success"
        ? "toast toast-success"
        : "toast toast-error";
    toast.textContent = message;
    toastContainer.append(toast); // CSS animates it in
    // Each toast removes ITSELF — the timeout is scoped to this one
    // element, so stacked toasts never cancel each other's timers.
    setTimeout(() => toast.remove(), 4000);
}

// ---------------------------------------------------------------------------
// SEARCH DROPDOWN — the navbar's ticker suggestions, on every page.
//
// Flow: typing (debounced) -> GET /api/search?q=... -> one clickable row
// per hit -> click (or Enter) navigates to /stock/<symbol>, the detail
// page. Rows are rebuilt on every search, so the click listener is
// DELEGATED to the dropdown container — the same survive-a-rebuild trick
// the watchlist and ledger use.
//
// createElement + textContent only: suggestion names come from Yahoo and
// echo the user's own query — innerHTML would let any of it execute as
// markup.
// ---------------------------------------------------------------------------

const searchInput = document.getElementById("ticker-search");
const searchResultsEl = document.getElementById("search-results");

// Debounce — the concept: wait for the user to STOP typing before spending
// a network call. Every keypress resets the timer; only a pause of
// DEBOUNCE_MS actually fires the fetch. Typing "apple" costs one request,
// not five.
const DEBOUNCE_MS = 300;
let searchTimer = null;

function hideSearchResults() {
    searchResultsEl.hidden = true;
    searchResultsEl.textContent = "";
}

// Build one clickable suggestion row: symbol + name on the left, the
// security type and exchange on the right ("Equity · NASDAQ").
function buildSearchRow(result) {
    const row = document.createElement("div");
    row.className = "search-row";
    row.dataset.symbol = result.symbol; // the delegated click handler's hook

    const left = document.createElement("div");
    const symbolEl = document.createElement("strong");
    symbolEl.textContent = result.symbol;
    const nameEl = document.createElement("div");
    nameEl.className = "sub-text";
    // A missing name (Yahoo flake) degrades to blank, never an error.
    nameEl.textContent = result.name || "";
    left.append(symbolEl, nameEl);

    const right = document.createElement("span");
    right.className = "search-meta";
    // filter(Boolean) drops missing parts, so a hit with no exchange
    // renders "Equity" alone instead of "Equity · undefined".
    right.textContent =
        [result.type, result.exchange].filter(Boolean).join(" · ");

    row.append(left, right);
    return row;
}

// Fill the dropdown: one row per hit, plus (optionally) a status line
// ("No matches", "Search unavailable") that takes the dropdown's space so
// it never silently vanishes.
function renderSearchResults(results, message) {
    searchResultsEl.textContent = "";
    if (message) {
        const note = document.createElement("div");
        note.className = "search-empty";
        note.textContent = message;
        searchResultsEl.append(note);
    }
    for (const result of results) {
        searchResultsEl.append(buildSearchRow(result));
    }
    searchResultsEl.hidden = false;
}

// One search cycle: HTTP GET -> check status -> parse JSON -> paint.
async function runSearch(query) {
    try {
        // encodeURIComponent: queries are user text and may contain
        // URL-hostile characters ("&", "#", spaces).
        const response = await fetch(
            `/api/search?q=${encodeURIComponent(query)}`
        );
        // fetch does NOT throw on 4xx/5xx — only on network failure.
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();

        // Stale-guard: while this request was in flight the user may have
        // kept typing, and a SLOWER EARLIER request can land after a newer
        // one. Only paint if this answer is still about what the box
        // shows NOW — otherwise drop it (the newer runSearch will paint).
        if (searchInput.value.trim() !== query) return;

        renderSearchResults(
            payload.results,
            payload.results.length === 0 ? "No matches" : null
        );
    } catch (err) {
        console.error("search failed:", err);
        if (searchInput.value.trim() === query) {
            renderSearchResults([], "Search unavailable");
        }
    }
}

searchInput.addEventListener("input", () => {
    const query = searchInput.value.trim();
    clearTimeout(searchTimer); // reset the debounce window
    if (!query) {
        hideSearchResults();
        return;
    }
    searchTimer = setTimeout(() => runSearch(query), DEBOUNCE_MS);
});

// One keydown handler, two keys that mean "stop browsing suggestions":
//   Escape — just close the dropdown.
//   Enter  — navigate: to the FIRST suggestion when one has arrived, or
//            to the raw typed text as a symbol otherwise. The detail page
//            shows an honest "Unknown symbol" if Yahoo doesn't know it.
searchInput.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
        hideSearchResults();
        return;
    }
    if (event.key === "Enter") {
        event.preventDefault(); // no form here, but keep the habit explicit
        const first = searchResultsEl.querySelector(".search-row");
        const symbol = first ? first.dataset.symbol : searchInput.value.trim();
        if (symbol) {
            // encodeURIComponent: symbols can contain URL-hostile
            // characters ("^GSPC", "BRK.B") — encode the PATH segment,
            // never the whole URL.
            window.location.href = `/stock/${encodeURIComponent(symbol)}`;
        }
    }
});

// Clicking a suggestion navigates. Delegated on the dropdown container:
// the rows are rebuilt on every search, so listeners attached to the rows
// themselves would die with each rebuild — delegation survives it.
searchResultsEl.addEventListener("click", (event) => {
    const row = event.target.closest(".search-row");
    if (!row) return; // click landed on the padding or a message row
    window.location.href = `/stock/${encodeURIComponent(row.dataset.symbol)}`;
});

// Click anywhere OUTSIDE the search box closes the dropdown (the input's
// own listeners reopen it on the next keystroke).
document.addEventListener("click", (event) => {
    if (!event.target.closest(".search-container")) {
        hideSearchResults();
    }
});

// ---------------------------------------------------------------------------
// SHARED CHART FACTORY — the timeframe chart both pages plot.
//
// The dashboard and the stock detail page draw the SAME picture: a line
// over time, a 1D–MAX button bar, data fetched once per button click (not
// polled — history doesn't change on a 60s cadence, and re-fetching it
// would hammer Yahoo). Only the data's SOURCE differs, so that's the one
// thing the caller passes in: setupTimeframeChart({canvas, buttonBar,
// datasetLabel, endpoint, defaultPeriod}) builds the Chart.js line, wires
// the buttons, and hands back { chart, refresh }.
//
// The LOOK is the Google Finance signature: straight segments (no curve),
// no dots except under the cursor, a gradient fading out below the line,
// and — the part the eye reads first — the line is GREEN when the plotted
// period gained and RED when it lost, matching the change pills' palette.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// CHART COLORS — read from CSS custom properties so they follow the theme.
//
// Canvas code can't use var(--green-pos) directly, so we read the computed
// value at call time. getComputedStyle(document.documentElement) gives us
// the live value from whichever theme (.dark or light) is active.
// ---------------------------------------------------------------------------
function hexToRgba(hex, alpha) {
    // Strip # and parse RGB components from a 6-digit hex string.
    const h = hex.replace("#", "");
    const r = parseInt(h.substring(0, 2), 16);
    const g = parseInt(h.substring(2, 4), 16);
    const b = parseInt(h.substring(4, 6), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function getChartColors() {
    const style = getComputedStyle(document.documentElement);
    const up = style.getPropertyValue("--green-pos").trim();
    const down = style.getPropertyValue("--red-neg").trim();
    return {
        up:   { line: up, fill: hexToRgba(up, 0.12) },
        down: { line: down, fill: hexToRgba(down, 0.10) },
    };
}

// Keep a live reference so chart updates can swap colors without
// re-reading CSS on every frame. refresh() updates this when data lands.
let CHART_COLORS = getChartColors();

// The hover CROSSHAIR: a thin vertical line through whatever point the
// tooltip is showing, drawn the full height of the plot. A Chart.js plugin
// is just an object with an id and hook functions the chart calls during
// its draw cycle — afterDatasetsDraw runs after the line is painted (so
// the crosshair sits on top of it) but before the tooltip. Passed only to
// this factory's charts, so nothing else on any page is affected.
const crosshairPlugin = {
    id: "crosshair",
    afterDatasetsDraw(chart) {
        const active = chart.tooltip?.getActiveElements();
        if (!active || active.length === 0) return;
        const x = active[0].element.x;
        const { top, bottom } = chart.chartArea;
        const ctx = chart.ctx;
        ctx.save();
        ctx.beginPath();
        ctx.moveTo(x, top);
        ctx.lineTo(x, bottom);
        // Read --border-color from CSS so the crosshair follows the theme.
        ctx.strokeStyle = getComputedStyle(document.documentElement)
            .getPropertyValue("--border-color").trim();
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.restore();
    },
};

// ---------------------------------------------------------------------------
// X-AXIS LABELS — short, sparse, and placed by US.
//
// The backend's history replies label each bar with a plain string in
// one of three fixed shapes (PERIOD_MAP's "label" format, market_data.py):
//   1D   -> "09:30"             clock time (one trading day)
//   5D   -> "2026-09-04 14:30"  date + time (one day carries many bars)
//   rest -> "2026-09-04"        date (one bar per day)
// Painted verbatim, those strings crowd the axis — eight 16-character
// labels is noise, not information. So the axis text is REFORMATTED at
// display time here. The raw labels themselves are never touched: they
// are load-bearing backend-side (merge keys for the portfolio series,
// lexicographic sort keys, transaction-date comparisons) — the app's
// "backend sends data, the browser formats" rule applied to ticks.
//
// The format is keyed on the DATA, not on which button was clicked:
//   - a window spanning >= 2 calendar years shows "Sep 2025" — the month
//     is the natural unit at that zoom, and the tooltip still has the
//     exact day (1Y/5Y/MAX always; 3M/6M/1M flip across New Year);
//   - a window inside one calendar year shows "Sep 4";
//   - 5D shows the DATE at each day's FIRST bar only ("Sep 3", "Sep 4")
//     — the Google Finance 5D look; across New Year it still reads
//     "Dec 30, Jan 2" with no year needed (unambiguous in five days);
//   - 1D passes its clock times straight through.
// ---------------------------------------------------------------------------

// Month number -> abbreviation. Our ISO labels carry months as "01".."12"
// but humans read "Sep". (+n on the parsed slice turns "09" into 9 here.)
const MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

// How many labels the x-axis paints, at most — scaled by the chart's
// pixel width so narrow mobile screens don't crowd. Desktop keeps 6;
// phones shrink to 3–4. Fewer than the old maxTicksLimit: 8 — real
// stock charts show a handful of sparse ticks, not a ruler.
const X_TICK_TARGET_DEFAULT = 6;
function tickTargetForWidth(width) {
    if (width <= 380) return 3;
    if (width <= 500) return 4;
    if (width <= 700) return 5;
    return X_TICK_TARGET_DEFAULT;
}

// The two parseable shapes above, as anchored regexes. exec() hands
// back capture groups to parse with; a label matching NEITHER (1D's
// clock times, or anything malformed) parses to null and falls through
// to pass-through. Anchored ($ at the end) so a weird label can't
// partially match and get mangled — it passes through raw.
const DATETIME_RE = /^(\d{4})-(\d{2})-(\d{2}) \d{2}:\d{2}$/;
const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

// One parsed date-ish label -> short text. The numeric month/day also
// strip the ISO leading zero ("Sep 04" would read wrong).
function monthDay(p) {
    return `${MONTHS[p.mo - 1]} ${p.d}`;
}

function monthYear(p) {
    return `${MONTHS[p.mo - 1]} ${p.y}`;
}

// Which bar indices get text when spreading `count` bars over the tick
// target? Even stride from index 0, then the LAST index forced in — but
// only when it sits at least half a stride away from the previous pick,
// so "the freshest point" (what 1D's last time tells you) never crowds
// the tick before it.
function stridedIndices(count, target) {
    const stride = Math.max(1, Math.ceil(count / target));
    const picks = [];
    for (let i = 0; i < count; i += stride) {
        picks.push(i);
    }
    const lastPick = picks[picks.length - 1];
    if (lastPick !== count - 1
        && (count - 1) - lastPick >= Math.ceil(stride / 2)) {
        picks.push(count - 1);
    }
    return picks;
}

// Build the axis-text plan: one entry per label, "" meaning "paint
// nothing on this bar". PURE — it reads only the labels array, which is
// what lets the chart factory rebuild the plan before every redraw and
// keeps the formatting testable in isolation. A series' labels are
// homogeneous by construction (one PERIOD_MAP format per request), but
// dispatch is defensive: anything unparseable passes through raw rather
// than crashing the chart (same forgiving spirit as the "—" path).
// `target` = max labels to paint (from tickTargetForWidth).
function buildXTickLabels(labels, target = X_TICK_TARGET_DEFAULT) {
    // Parse every label ONCE. Date-ish shapes keep their parts as
    // numbers plus a kind ("datetime" = 5D, "date" = daily); "time"
    // labels and unparseable ones parse to null.
    const parsed = labels.map((label) => {
        let m = DATETIME_RE.exec(label);
        if (m) return { kind: "datetime", y: +m[1], mo: +m[2], d: +m[3] };
        m = DATE_RE.exec(label);
        if (m) return { kind: "date", y: +m[1], mo: +m[2], d: +m[3] };
        return null;
    });

    // The year-span flag: do the first and last PARSEABLE labels sit in
    // different calendar years? This is what makes the "Sep 4" vs
    // "Sep 2025" choice data-driven — no per-button special cases.
    const firstYear = parsed.find(Boolean)?.y;
    const lastYear = parsed.findLast(Boolean)?.y;
    const spansYears = firstYear !== undefined && lastYear !== undefined
        && firstYear !== lastYear;

    // 5D: many bars per day, so the DAY is the story. Label a bar only
    // at a day boundary — its date differs from the previous bar's (or
    // it's the very first bar). Every other bar paints nothing.
    if (parsed[0]?.kind === "datetime") {
        const axisText = labels.map(() => "");
        const boundaries = [];
        for (let i = 0; i < parsed.length; i++) {
            const p = parsed[i];
            const prev = i > 0 ? parsed[i - 1] : null;
            if (!prev || prev.y !== p.y || prev.mo !== p.mo
                || prev.d !== p.d) {
                boundaries.push(i);
            }
        }
        // Five trading days give ~5 boundaries — under the target, so
        // this thinning is purely defensive: if the shape ever yields
        // more boundaries than the target, stride the boundary LIST.
        const shown = boundaries.length > target
            ? boundaries.filter((unused, k) =>
                  k % Math.ceil(boundaries.length / target) === 0)
            : boundaries;
        for (const i of shown) axisText[i] = monthDay(parsed[i]);
        return axisText;
    }

    // Daily bars (one per day): sparse stride, "Sep 4" or "Sep 2025".
    if (parsed[0]?.kind === "date") {
        const axisText = labels.map(() => "");
        for (const i of stridedIndices(parsed.length, target)) {
            axisText[i] = spansYears
                ? monthYear(parsed[i])
                : monthDay(parsed[i]);
        }
        return axisText;
    }

    // 1D time series (or fully unparseable): pass the raw text through
    // on the strided picks only.
    const axisText = labels.map(() => "");
    for (const i of stridedIndices(parsed.length, target)) {
        axisText[i] = labels[i];
    }
    return axisText;
}

function setupTimeframeChart(
    { canvas, buttonBar, datasetLabel, endpoint, defaultPeriod }
) {
    // Guard: the CDN could be unreachable (offline, blocked, down).
    // Without this, "new Chart(...)" would throw and kill EVERYTHING in
    // the page script below — one if/else buys graceful degradation.
    if (typeof Chart === "undefined") {
        console.error("Chart.js failed to load from the CDN — chart skipped");
        return null;
    }

    // Which way the CURRENT period moved — "up" (green) or "down" (red).
    // refresh() recomputes it from the data and BOTH presentational
    // readers below (borderColor, the gradient's fill color) derive from
    // it, so one flip recolors line + fill together.
    let direction = "up";

    // The previous day's closing price — fed in by callers (stock.js,
    // main.js) via updatePrevClose(). The prevCloseLine plugin reads
    // this and draws a horizontal dashed reference line, but ONLY when
    // the active period is "1D" (intraday).
    let prevClose = null;

    // Which period is currently displayed — tracked so the prevCloseLine
    // plugin can short-circuit when the user is on any timeframe except 1D.
    let currentPeriod = defaultPeriod;

    // The x-axis text plan: one entry per bar, "" = paint nothing there.
    // buildXTickLabels (above) rebuilds it inside refresh() BEFORE each
    // redraw; the tick callback below reads it at draw time — which is
    // why it lives in a closure the callback can see.
    let xTickLabels = [];

    // The raw labels from the last successful fetch — needed by the
    // resize plugin to rebuild the tick plan at the new width without
    // re-fetching data from the backend.
    let lastLabels = [];

    // Chart.js paints onto the canvas's "2D context" — the object whose
    // methods actually put pixels on it.
    const chart = new Chart(canvas.getContext("2d"), {
        // "line" connects each point to the next — the classic stock-chart
        // look. (Other families: "bar", "doughnut".)
        type: "line",

        // Chart-local plugins: passed HERE they apply to this chart only
        // (a global registry would leak into every chart we don't own).
        // crosshairPlugin draws the hover line; the resize plugin
        // recomputes the x-axis tick plan when the chart's width changes
        // (e.g. phone rotation) so labels never overlap at the new size;
        // prevCloseLine draws a horizontal dashed reference at yesterday's
        // close on 1D charts.
        plugins: [crosshairPlugin, {
            id: "responsiveXTicks",
            afterResize(chart) {
                const target = tickTargetForWidth(canvas.parentElement.clientWidth);
                xTickLabels = buildXTickLabels(lastLabels, target);
                chart.update("none");
            },
        }, {
            id: "prevCloseLine",
            // Fires DURING the scale update (before layout computes pixel
            // positions) — the only safe place to mutate scale limits.
            // beforeDraw is too late: the pixel mapping is already baked.
            afterDataLimits(chart, { scale }) {
                if (currentPeriod !== "1D" || prevClose == null) return;
                if (scale.id !== "y") return;
                const lo = scale.min;
                const hi = scale.max;
                if (prevClose < lo || prevClose > hi) {
                    const range = hi - lo || hi * 0.05;
                    const pad = range * 0.1;
                    scale.min = Math.min(lo, prevClose - pad);
                    scale.max = Math.max(hi, prevClose + pad);
                }
            },
            afterDraw(chart) {
                if (currentPeriod !== "1D" || prevClose == null) return;
                const y = chart.scales.y.getPixelForValue(prevClose);
                const { left, right, top } = chart.chartArea;
                const ctx = chart.ctx;
                ctx.save();
                // Dashed horizontal line across the full chart width.
                ctx.beginPath();
                ctx.setLineDash([5, 3]);
                ctx.moveTo(left, y);
                ctx.lineTo(right, y);
                ctx.strokeStyle = getComputedStyle(document.documentElement)
                    .getPropertyValue("--prev-close").trim();
                ctx.lineWidth = 1;
                ctx.stroke();
                // "Prev close $X.XX" label — positioned above the line by
                // default, but flipped below when too close to the top edge
                // to prevent clipping.
                const labelAbove = y - 18 > top;
                ctx.setLineDash([]);
                ctx.font = "11px sans-serif";
                ctx.textAlign = "right";
                ctx.textBaseline = labelAbove ? "bottom" : "top";
                ctx.fillStyle = getComputedStyle(document.documentElement)
                    .getPropertyValue("--prev-close").trim();
                ctx.fillText(
                    `Prev close ${formatPrice(prevClose)}`,
                    right, labelAbove ? y - 4 : y + 4
                );
                ctx.restore();
            },
        }],

        // Empty by design — refresh() fills these in. The dataset object is
        // created here so its presentational config lives in ONE place and
        // survives every refresh.
        data: {
            // labels = x-axis slots, one per data point, from the backend's
            // {"labels": [...], "values": [...]} reply.
            labels: [],
            datasets: [
                {
                    // ONE dataset = one line. datasetLabel names it (only
                    // visible in tooltips, since the legend is off below).
                    label: datasetLabel,
                    data: [],
                    // Direction-driven: refresh() swaps this between the
                    // green/red pair as soon as data lands.
                    borderColor: CHART_COLORS.up.line,
                    // A SCRIPTABLE option: Chart.js CALLS this function on
                    // every redraw instead of using a fixed value. That's
                    // how the fill stays a live gradient anchored to the
                    // plot area — the area's pixel bounds don't exist until
                    // the chart has laid out, hence the guard — and it
                    // picks up the current direction color.
                    backgroundColor: (ctx) => {
                        const area = ctx.chart.chartArea;
                        if (!area) return "transparent";
                        const gradient = ctx.chart.ctx.createLinearGradient(
                            0, area.top, 0, area.bottom
                        );
                        // Colored tint at the top fading to nothing at the
                        // bottom: the classic "glow under the line".
                        gradient.addColorStop(0, CHART_COLORS[direction].fill);
                        // Fade to the page background color (transparent).
                        // Using --bg-color keeps the gradient seamless in dark mode.
                        const bg = getComputedStyle(document.documentElement)
                            .getPropertyValue("--bg-color").trim();
                        gradient.addColorStop(1, hexToRgba(bg, 0));
                        return gradient;
                    },
                    fill: true,
                    // tension 0 = straight segments between points — the
                    // data as it IS, not a smoothed impression of it.
                    tension: 0,
                    // pointRadius 0 hides the per-point dots entirely (on
                    // MAX there are hundreds — they turned the line fuzzy);
                    // the hover dot appears only under the cursor.
                    pointRadius: 0,
                    pointHoverRadius: 4,
                },
            ],
        },

        options: {
            // responsive: redraw to match the parent .chart-box's size.
            // maintainAspectRatio: false lets the CSS height (300px) win —
            // otherwise Chart.js locks in its own width:height ratio.
            responsive: true,
            maintainAspectRatio: false,
            // The hover contract: mode "index" snaps to the nearest x slot
            // and intersect: false means the cursor does NOT have to touch
            // a point — the readout follows you anywhere on the chart.
            interaction: { mode: "index", intersect: false },
            plugins: {
                // With only one dataset, the legend swatch adds nothing.
                legend: { display: false },
                tooltip: {
                    displayColors: false,
                    // Fixed dark tooltip with white text — consistent contrast
                    // in both light and dark mode.
                    backgroundColor: "#1a1f36",
                    titleColor: "#fff",
                    bodyColor: "#fff",
                    padding: 10,
                    cornerRadius: 8,
                    titleFont: { size: 11, weight: "normal" },
                    bodyFont: { size: 13, weight: 600 },
                    callbacks: {
                        // Tooltip title: reformat the raw ISO label
                        // (e.g. "2026-09-13" or "2026-09-13 14:30")
                        // into human-friendly text ("Sep 13").
                        // 1D clock times pass through as-is.
                        title(items) {
                            const raw = lastLabels[items[0].dataIndex] || "";
                            let m = DATETIME_RE.exec(raw);
                            if (m) {
                                const p = { y: +m[1], mo: +m[2], d: +m[3] };
                                return monthDay(p);
                            }
                            m = DATE_RE.exec(raw);
                            if (m) {
                                const p = { y: +m[1], mo: +m[2], d: +m[3] };
                                // If the series spans two calendar years,
                                // show the year instead of the day — mirrors
                                // the x-axis tick logic in buildXTickLabels.
                                const first = lastLabels.find(
                                    (l) => DATE_RE.test(l));
                                const last = lastLabels.findLast(
                                    (l) => DATE_RE.test(l));
                                const spansYears = first && last
                                    && first.slice(0, 4) !== last.slice(0, 4);
                                return spansYears ? monthYear(p) : monthDay(p);
                            }
                            return raw;
                        },
                        // Same formatting rule as everywhere else in the
                        // app: the backend sends raw floats, the browser
                        // formats ("7711.759" -> "7,711.76").
                        label(item) {
                            return formatPrice(item.parsed.y);
                        },
                    },
                },
            },
            scales: {
                x: {
                    grid: { display: false },   // no vertical gridlines
                    border: { display: false }, // no axis line either
                    // Tick placement is OURS, not Chart.js's: autoSkip
                    // off (its skipper would pick arbitrary bars), no
                    // rotation (labels never slant), and the callback
                    // paints the precomputed plan — "" for bars we
                    // didn't pick, which paints NOTHING (with grid and
                    // border hidden, an empty tick leaves no trace).
                    ticks: {
                        maxRotation: 0,
                        autoSkip: false,
                        callback: (value, index) => xTickLabels[index] || "",
                    },
                },
                y: {
                    // Read --border-subtle from CSS so grid lines follow the theme.
                    grid: { color: getComputedStyle(document.documentElement)
                        .getPropertyValue("--border-subtle").trim() },
                    border: { display: false },
                    // beginAtZero: false starts the y-axis near the data's
                    // minimum instead of 0 — exactly how real stock charts
                    // make small daily moves visible.
                    beginAtZero: false,
                    ticks: { maxTicksLimit: 6 },
                },
            },
        },
    });

    // One refresh cycle: GET endpoint?period=... then swap the arrays and
    // redraw. The presentational config was set once at creation and is
    // untouched — except the direction color, which is DATA-derived and
    // therefore refreshed WITH the data.
    async function refresh(period = defaultPeriod) {
        try {
            const response = await fetch(`${endpoint}?period=${period}`);
            // fetch does NOT throw on 4xx/5xx — only on network failure. A
            // 400 (bad period key) arrives with ok === false; the buttons
            // only ever send valid keys, so this mainly guards against
            // drift between the two ends.
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json(); // {labels, values}

            // Green for a gaining period, red for a losing one: compare
            // the FIRST and LAST close. values.at(-1) is the LAST element;
            // the length guard keeps an empty reply from NaN-comparing
            // (empty data just keeps the previous color).
            const values = data.values;
            if (values.length > 0) {
                direction = values.at(-1) >= values[0] ? "up" : "down";
                chart.data.datasets[0].borderColor =
                    CHART_COLORS[direction].line;
            }
            chart.data.labels = data.labels;
            chart.data.datasets[0].data = data.values;
            // Rebuild the axis-text plan BEFORE the redraw: the tick
            // callback reads xTickLabels at draw time, so it must
            // describe the NEW series, not the previous one. The target
            // adapts to the chart's current width (fewer labels on phones).
            lastLabels = data.labels;
            const target = tickTargetForWidth(canvas.parentElement.clientWidth);
            xTickLabels = buildXTickLabels(data.labels, target);
            // Set currentPeriod BEFORE chart.update() so the prevCloseLine
            // plugin sees the correct period during the synchronous redraw.
            // If the fetch failed, we never reach here (the throw skips
            // this line), so the period stays correct for the old data.
            currentPeriod = period;
            chart.update();
        } catch (err) {
            console.error("chart refresh failed:", err);
        }
    }

    // Timeframe buttons: ONE delegated listener on the button bar. The
    // buttons are static HTML (never rebuilt), so a direct listener would
    // work too — delegation simply matches the watchlist/ledger pattern
    // and keeps every click handler in the same style.
    buttonBar.addEventListener("click", (event) => {
        // Ignore clicks that land on the bar itself (the gap between
        // buttons).
        const btn = event.target.closest(".time-btn");
        if (!btn) return;

        // textContent is the period key: "1D", "5D", "3M"... — exactly
        // what the backend's PERIOD_MAP expects. No separate map to keep
        // in sync.
        const period = btn.textContent.trim();

        // Swap the active highlight to the clicked button, then fetch+paint.
        buttonBar.querySelectorAll(".time-btn").forEach((b) =>
            b.classList.remove("active"));
        btn.classList.add("active");
        refresh(period);
    });

    return {
        chart,
        refresh,
        updatePrevClose(val) {
            prevClose = val;
            chart.update();
        },
    };
}

// ---------------------------------------------------------------------------
// PROFILE DROPDOWN — wires the user-menu dropdown in the navbar's
// top-right corner. The dropdown contains a single "Preferences" link
// that navigates to /preferences. All preference logic lives in
// preferences.js (loaded only on that page).
// ---------------------------------------------------------------------------

(function initProfileMenu() {
    const profileBtn = document.getElementById("profile-btn");
    const dropdown = document.getElementById("profile-dropdown");
    if (!profileBtn || !dropdown) return;

    // --- Dropdown open/close ---
    profileBtn.addEventListener("click", () => {
        const open = !dropdown.hidden;
        dropdown.hidden = open;
        profileBtn.setAttribute("aria-expanded", !open);
    });

    // Close on click outside (but not on the button or inside the dropdown).
    document.addEventListener("click", (e) => {
        if (!dropdown.hidden &&
            !dropdown.contains(e.target) &&
            !profileBtn.contains(e.target)) {
            dropdown.hidden = true;
            profileBtn.setAttribute("aria-expanded", "false");
        }
    });

    // Escape key closes the dropdown and returns focus to the button.
    dropdown.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            dropdown.hidden = true;
            profileBtn.setAttribute("aria-expanded", "false");
            profileBtn.focus();
        }
    });

    // Follow OS theme changes live when no explicit choice is saved.
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    mql.addEventListener("change", (e) => {
        if (!localStorage.getItem("theme")) {
            document.documentElement.classList.toggle("dark", e.matches);
            CHART_COLORS = getChartColors();
            document.dispatchEvent(new CustomEvent("themechange",
                { detail: { dark: e.matches } }));
        }
    });
})();
