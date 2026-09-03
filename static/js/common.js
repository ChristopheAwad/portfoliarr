// common.js — code shared by EVERY page (dashboard + stock detail).
//
// This file is loaded by base.html BEFORE each page's own script, so
// everything defined here becomes a plain global the page scripts can
// use. It contains:
//   1. Formatting helpers (backend sends raw floats; formatting is
//      frontend-only — a permanent rule of this app)
//   2. paintChange — the signed "change pill" painter
//   3. The navbar search dropdown (fetch -> JSON -> DOM, like everything
//      else here; knows nothing about yfinance, Flask, or Python)

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
// ---------------------------------------------------------------------------

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

    // Chart.js paints onto the canvas's "2D context" — the object whose
    // methods actually put pixels on it.
    const chart = new Chart(canvas.getContext("2d"), {
        // "line" connects each point to the next — the classic stock-chart
        // look. (Other families: "bar", "doughnut".)
        type: "line",

        // Empty by design — refresh() fills these in. The dataset object is
        // created here so its presentational config (line shade, fill,
        // tension) lives in ONE place and survives every refresh.
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
                    // Google blue line + a faint translucent fill under it.
                    borderColor: "#1a73e8",
                    backgroundColor: "rgba(26, 115, 232, 0.1)",
                    fill: true,
                    // tension bends the line between points: 0 = straight
                    // segments, higher = smoother curves. ~0.3 looks like
                    // a finance chart without distorting the data.
                    tension: 0.3,
                    pointRadius: 3,
                },
            ],
        },

        options: {
            // responsive: redraw to match the parent .chart-box's size.
            // maintainAspectRatio: false lets the CSS height (300px) win —
            // otherwise Chart.js locks in its own width:height ratio.
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                // With only one dataset, the legend swatch adds nothing.
                legend: { display: false },
            },
            scales: {
                x: { grid: { display: false } }, // no vertical gridlines
                y: {
                    grid: { color: "#e0e0e0" },
                    // beginAtZero: false starts the y-axis near the data's
                    // minimum instead of 0 — exactly how real stock charts
                    // make small daily moves visible.
                    beginAtZero: false,
                },
            },
        },
    });

    // One refresh cycle: GET endpoint?period=... then swap the arrays and
    // redraw. The presentational config was set once at creation and is
    // untouched — Chart.js redraws itself on update().
    async function refresh(period = defaultPeriod) {
        try {
            const response = await fetch(`${endpoint}?period=${period}`);
            // fetch does NOT throw on 4xx/5xx — only on network failure. A
            // 400 (bad period key) arrives with ok === false; the buttons
            // only ever send valid keys, so this mainly guards against
            // drift between the two ends.
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json(); // {labels, values}
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
