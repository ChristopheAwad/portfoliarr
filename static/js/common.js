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

        // Escape cancels. The listener sits on DOCUMENT while the modal is
        // open — keydowns land wherever focus is (often inside the input),
        // and only document-level listeners see them regardless.
        function onKeyDown(event) {
            if (event.key === "Escape") finish(cancelResult);
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
    // The type picks the palette: "error" (the default) or "success".
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

// Mirror of style.css's palette custom properties: the up/down lines are
// --green-pos (#059669) / --red-neg (#dc2626) (the fills are the same hues
// at low alpha), the crosshair mirrors --border-color (#e4e7ec), and the
// tooltip plate mirrors --text-primary (#1a1f36). Canvas code can't read
// CSS custom properties ("var(--green-pos)" is meaningless outside CSS),
// so the hex values are duplicated here — the comment anchors them
// together for whoever changes one side later.
const CHART_COLORS = {
    up:   { line: "#059669", fill: "rgba(5, 150, 105, 0.12)" },
    down: { line: "#dc2626", fill: "rgba(220, 38, 38, 0.10)" },
};

// The hover CROSSHAIR: a thin vertical line through whatever point the
// tooltip is showing, drawn the full height of the plot. A Chart.js plugin
// is just an object with an id and hook functions the chart calls during
// its draw cycle — afterDatasetsDraw runs after the line is painted (so
// the crosshair sits on top of it) but before the tooltip. Passed only to
// this factory's charts, so nothing else on any page is affected.
const crosshairPlugin = {
    id: "crosshair",
    afterDatasetsDraw(chart) {
        // No tooltip showing → nothing to draw through. getActiveElements()
        // returns the data point(s) the tooltip is currently attached to.
        const active = chart.tooltip?.getActiveElements();
        if (!active || active.length === 0) return;
        const x = active[0].element.x; // the hovered point's x pixel
        const { top, bottom } = chart.chartArea;
        const ctx = chart.ctx;         // the canvas's 2D drawing pen
        ctx.save();                    // snapshot pen styles, restore below
        ctx.beginPath();
        ctx.moveTo(x, top);
        ctx.lineTo(x, bottom);
        ctx.strokeStyle = "#e4e7ec";   // --border-color's hairline gray
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.restore();
    },
};

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

    // Chart.js paints onto the canvas's "2D context" — the object whose
    // methods actually put pixels on it.
    const chart = new Chart(canvas.getContext("2d"), {
        // "line" connects each point to the next — the classic stock-chart
        // look. (Other families: "bar", "doughnut".)
        type: "line",

        // Chart-local plugins: passed HERE they apply to this chart only
        // (a global registry would leak into every chart we don't own).
        plugins: [crosshairPlugin],

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
                        gradient.addColorStop(1, "rgba(255, 255, 255, 0)");
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
                    // displayColors: false drops the colored square before
                    // the value — the line above is the color story already.
                    displayColors: false,
                    backgroundColor: "#1a1f36", // --text-primary, as the plate
                    padding: 10,
                    cornerRadius: 8,
                    titleFont: { size: 11, weight: "normal" },
                    bodyFont: { size: 13, weight: 600 },
                    callbacks: {
                        // Same formatting rule as everywhere else in the
                        // app: the backend sends raw floats, the browser
                        // formats ("7711.759" -> "7,711.76").
                        label: (item) => formatPrice(item.parsed.y),
                    },
                },
            },
            scales: {
                x: {
                    grid: { display: false },   // no vertical gridlines
                    border: { display: false }, // no axis line either
                    // Cap the label count and forbid angled text — crowded
                    // or slanted date labels were part of the old mess.
                    ticks: { maxTicksLimit: 8, maxRotation: 0 },
                },
                y: {
                    grid: { color: "#eef1f5" }, // hairline gray, border-adjacent
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

    return { chart, refresh };
}
