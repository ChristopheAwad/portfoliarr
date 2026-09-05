// stock.js — the stock detail page (/stock/<symbol>).
//
// The dashboard prices a PORTFOLIO (ledger + quotes); this page prices ONE
// SECURITY, so the math collapses: the price IS the value, the quote's
// daily move IS the day change, and there is no total return (no cost
// basis exists). Like every page here: fetch -> JSON -> DOM, and common.js
// supplies the shared formatters + the chart factory.
//
// Refresh rhythms mirror the dashboard's, sized to the data:
//   quote   — polled every 60s (prices move)
//   stats   — once per page load (they reset daily; the endpoint behind
//             them is the heaviest yfinance offers)
//   chart   — once at load + per button click (history doesn't move on a
//             60s cadence; polling it would just hammer Yahoo)

// The page's identity, stamped by stock.html onto <body data-symbol>.
// The symbol in the URL is user-reachable and the route uppercases it, so
// this is already the canonical form every fetch below uses.
const symbol = document.body.dataset.symbol;

// The pieces this page manages, grabbed once at load time.
const stockNameEl = document.getElementById("stock-name");
const stockPriceEl = document.getElementById("stock-price");
const stockDayChangeEl = document.getElementById("stock-day-change");
const addToWatchlistBtn = document.getElementById("add-to-watchlist-btn");
const logTxBtn = document.getElementById("log-tx-btn");
const actionErrorEl = document.getElementById("stock-action-error");

// Once the symbol is known to be unquotable (404), later poll cycles have
// nothing to ask for — this flag silences them (the dashboard's sections
// poll forever because their data is a LIST that can change; here the
// symbol itself is fixed).
let symbolKnown = true;

// Inline error for the action buttons (cleared on every fresh attempt —
// the tx-form's error-line pattern).
function showActionError(text) {
    actionErrorEl.textContent = text;
    actionErrorEl.hidden = false;
}

// ---------------------------------------------------------------------------
// QUOTE — the header's price + day-change pill (the polled endpoint).
// ---------------------------------------------------------------------------

// Degraded states. (No tooltip story needed here: with ONE symbol, a failed
// quote IS the whole page's story, said in text — unlike the dashboard,
// where a tooltip lists which of many tickers went dark.)
function markUnknownSymbol() {
    stockNameEl.textContent = "Unknown symbol — check the ticker";
    stockPriceEl.textContent = "—";
    stockPriceEl.title = "";
    stockDayChangeEl.textContent = "";
    stockDayChangeEl.classList.remove("pos", "neg");
    // Both actions need a real symbol behind them — dead ends now.
    addToWatchlistBtn.disabled = true;
    logTxBtn.disabled = true;
}

// Backend unreachable (not a 404): degrade the header but keep polling —
// the server may come back, and the quote cache may yet answer.
function setQuoteUnavailable() {
    stockPriceEl.textContent = "—";
    stockDayChangeEl.textContent = "";
    stockDayChangeEl.classList.remove("pos", "neg");
}

async function refreshStockQuote() {
    if (!symbolKnown) return; // 404'd earlier; nothing left to ask

    try {
        const response = await fetch(`/api/stock/${encodeURIComponent(symbol)}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const quote = await response.json();

        // Name: Yahoo's heavier metadata endpoint, degrading to None —
        // show the bare symbol rather than an error (watchlist rule).
        stockNameEl.textContent = quote.name || "";

        // Native currency display (no FX conversion, per the brief) —
        // the same "182.52 USD" shape as the watchlist rows.
        stockPriceEl.textContent =
            `${formatPrice(quote.price)} ${quote.currency}`;

        // The day-change pill: "+2.30 (+1.02%) Today". The quote's change /
        // change_pct are exactly the pill's inputs — shared paintChange,
        // same pos/neg colouring as the dashboard's totals.
        paintChange(stockDayChangeEl, quote.change, quote.change_pct, "Today");
    } catch (err) {
        console.error("stock quote refresh failed:", err);
        // Distinguish "Yahoo doesn't know this symbol" (permanent — stop
        // asking) from "the network hiccuped" (temporary — keep polling).
        // fetch throws a bare TypeError for network failures, while our
        // !ok branch above throws Error("HTTP <status>") — matching the
        // message is what separates the two.
        if (err instanceof Error && err.message === "HTTP 404") {
            symbolKnown = false;
            markUnknownSymbol();
        } else {
            setQuoteUnavailable();
        }
    }
}

// ---------------------------------------------------------------------------
// STATS — the grid below the chart, fetched ONCE per page load.
// ---------------------------------------------------------------------------

// Volume is a share COUNT (whole units), market cap is huge — neither
// wants formatNumber's fixed two decimals. Two dedicated Intl formatters:
// integer grouping for volume ("55,000,000"), compact notation for market
// cap ("3.5T" — Intl's abbreviation for trillion, matching finance sites).
const integerFormat = new Intl.NumberFormat("en-US",
    { maximumFractionDigits: 0 });
const compactFormat = new Intl.NumberFormat("en-US",
    { notation: "compact", maximumFractionDigits: 2 });

// One grid cell, with the null-gap rule: a missing stat (an index has no
// market cap) renders "—", never "undefined" or an empty promise of data.
function setStat(id, text) {
    // `== null` (loose) covers BOTH null and undefined in one test — the
    // one place JavaScript's loose equality is the idiomatic choice.
    document.getElementById(id).textContent = text == null ? "—" : text;
}

// Yahoo's recommendationKey has no consistent case or formatting: "buy",
// "hold", and camelCase compounds like "strongBuy". Split on the camelCase
// boundary (strongBuy → strong Buy) and capitalize the first word → "Strong
// Buy". Unknown values fall through looking as good as they can.
function titleCaseRecommendation(key) {
    const spaced = key.replace(/([a-z])([A-Z])/g, "$1 $2");
    return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function paintStats(stats) {
    // Money cells: native currency figures, bare numbers — the currency
    // lives in the header's price ("229.50 USD") and repeating it in every
    // price-shaped cell would just be noise (Google Finance does the same).
    setStat("stat-open", stats.open === null ? null : formatPrice(stats.open));
    setStat("stat-day-high",
        stats.day_high === null ? null : formatPrice(stats.day_high));
    setStat("stat-day-low",
        stats.day_low === null ? null : formatPrice(stats.day_low));
    setStat("stat-prev-close",
        stats.prev_close === null ? null : formatPrice(stats.prev_close));
    setStat("stat-volume",
        stats.volume === null ? null : integerFormat.format(stats.volume));

    // 52W range: one cell for the pair. A range with one side missing
    // isn't a range — both must exist or the cell says "—".
    setStat("stat-week52-range",
        stats.week52_low === null || stats.week52_high === null
            ? null
            : `${formatPrice(stats.week52_low)} – ${formatPrice(stats.week52_high)}`);

    setStat("stat-market-cap",
        stats.market_cap === null ? null : compactFormat.format(stats.market_cap));

    // The 11 cheap additions (same already-fetched profile, more keys read
    // out of it). One formatter per kind of number:
    //   ratio (P/E, beta) → plain; EPS → price-shaped; moving averages →
    //   price-shaped; yield → backend-sent 0-100 figure + "%"; analyst
    //   target → price-shaped; volume → integer like Volume above.
    setStat("stat-pe",
        stats.pe_ratio === null ? null : formatNumber(stats.pe_ratio));
    setStat("stat-eps",
        stats.eps === null ? null : formatPrice(stats.eps));
    setStat("stat-dividend-yield",
        stats.dividend_yield === null
            ? null
            : `${formatNumber(stats.dividend_yield)}%`);
    setStat("stat-beta",
        stats.beta === null ? null : formatNumber(stats.beta));
    setStat("stat-50d-avg",
        stats.fifty_day_average === null
            ? null : formatPrice(stats.fifty_day_average));
    setStat("stat-200d-avg",
        stats.two_hundred_day_average === null
            ? null : formatPrice(stats.two_hundred_day_average));
    setStat("stat-avg-volume",
        stats.avg_volume === null
            ? null : integerFormat.format(stats.avg_volume));
    setStat("stat-target-price",
        stats.target_price === null ? null : formatPrice(stats.target_price));
    setStat("stat-rating",
        stats.recommendation === null
            ? null : titleCaseRecommendation(stats.recommendation));
    setStat("stat-sector", stats.sector === null ? null : stats.sector);
    setStat("stat-industry", stats.industry === null ? null : stats.industry);
}

// The grid's cell ids — used by the failure path to degrade the whole
// grid at once ("…" means waiting; "—" means this load couldn't price).
const STAT_IDS = ["stat-open", "stat-day-high", "stat-day-low",
                  "stat-prev-close", "stat-volume",
                  "stat-week52-range", "stat-market-cap",
                  "stat-pe", "stat-eps", "stat-dividend-yield", "stat-beta",
                  "stat-50d-avg", "stat-200d-avg", "stat-avg-volume",
                  "stat-target-price", "stat-rating", "stat-sector",
                  "stat-industry"];

async function refreshStockStats() {
    try {
        const response =
            await fetch(`/api/stock/${encodeURIComponent(symbol)}/stats`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        paintStats(await response.json());
    } catch (err) {
        console.error("stock stats refresh failed:", err);
        // The shipped "…" placeholders would imply endless loading —
        // degrade the whole grid to "—" (the failed-quote convention).
        for (const id of STAT_IDS) setStat(id, null);
    }
}

// ---------------------------------------------------------------------------
// ACTIONS — the two buttons in the header card.
// ---------------------------------------------------------------------------

// The watch button is a two-face STATE MACHINE painted by ONE function, so
// its markup can never drift between the faces (before this, the watched
// face was only ever built inside the click handler — which is why a page
// load never showed an already-watched symbol's check mark). The state
// itself lives in data-watched (stamped by the route from a DB read); the
// .watched class drives the green "state, not action" palette in CSS.
// Note there's no disabled here: a watched button stays CLICKABLE — its
// click now means "remove" (the old done-state was a dead end, which is
// why a watched symbol couldn't be unwatched from this page).
function paintWatchBtn(watched) {
    addToWatchlistBtn.dataset.watched = String(watched);
    addToWatchlistBtn.classList.toggle("watched", watched);
    // Content must be BUILT rather than assigned: a textContent assignment
    // would wipe the SVG element. Icon first, then a real text node —
    // icon("plus") for the action, icon("check") for the state.
    addToWatchlistBtn.textContent = "";
    addToWatchlistBtn.append(
        icon(watched ? "check" : "plus"),
        document.createTextNode(watched ? " On Watchlist" : " Add to Watchlist")
    );
}

// Click: ADD when unwatched; confirm-then-REMOVE when watched. Both halves
// go through the SAME endpoints the dashboard's watchlist uses (POST and
// DELETE /api/watchlist) — no duplicate API for the same fact.
addToWatchlistBtn.addEventListener("click", async () => {
    actionErrorEl.hidden = true; // fresh attempt, fresh error state

    // --- REMOVE path. Un-watching is destructive (a misclick on "add"
    // is harmless; silently deleting a watchlist entry is not), so it
    // passes through showConfirm's styled modal, resolving true/false.
    if (addToWatchlistBtn.dataset.watched === "true") {
        const confirmed = await showConfirm({
            title: "Remove from watchlist",
            message: `Remove ${symbol} from your watchlist?`,
            confirmLabel: "Remove",
            danger: true,
        });
        if (!confirmed) return; // changed their mind — leave state as-is
        try {
            const response = await fetch(
                `/api/watchlist/${encodeURIComponent(symbol)}`,
                { method: "DELETE" }
            );
            // 204 = removed. 404 = it vanished elsewhere (another tab, the
            // dashboard's ×) — that IS the wanted end state, so sync to
            // "unwatched" instead of relaying an error. Anything else is
            // a real failure worth a message.
            if (response.status === 204 || response.status === 404) {
                paintWatchBtn(false);
                return;
            }
            showActionError(
                `Could not remove ${symbol} (HTTP ${response.status})`
            );
        } catch (err) {
            console.error("remove from watchlist failed:", err);
            showActionError("Could not reach the server — is it running?");
        }
        return;
    }

    // --- ADD path. 201 (added) and 409 (already there — e.g. it raced in
    // via another tab) both mean "it's on the watchlist now", so both
    // flip the button to its watched face; anything else is an inline
    // error.
    try {
        const response = await fetch("/api/watchlist", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ symbol }),
        });
        if (response.status === 201 || response.status === 409) {
            paintWatchBtn(true);
            return;
        }
        // The backend's named error (unknown symbol...) is more useful
        // than a generic message — relay it. .catch(() => null) guards
        // against a response that isn't parseable JSON.
        const data = await response.json().catch(() => null);
        showActionError(
            data?.error || `Could not add ${symbol} (HTTP ${response.status})`
        );
    } catch (err) {
        console.error("add to watchlist failed:", err);
        showActionError("Could not reach the server — is it running?");
    }
});

// Log Transaction: the log form lives on the dashboard — ONE form, ONE
// submit handler, the same reuse rule the ledger's edit mode follows. The
// ?ticker= param is what main.js reads to prefill it, and the #tx-form
// anchor scrolls the browser straight to the form.
logTxBtn.addEventListener("click", () => {
    window.location.href = `/?ticker=${encodeURIComponent(symbol)}#tx-form`;
});

// ---------------------------------------------------------------------------
// CHART — the security's close price over time. The shared factory builds
// it; this page's only input is WHERE the data comes from.
// ---------------------------------------------------------------------------

const stockChartHandle = setupTimeframeChart({
    canvas: document.getElementById("stockChart"),
    buttonBar: document.querySelector(".chart-timeframe-selectors"),
    datasetLabel: symbol,
    endpoint: `/api/stock/${encodeURIComponent(symbol)}/history`,
    defaultPeriod: "5D", // must match the `active` button in stock.html
});

// ---------------------------------------------------------------------------
// BOOT — fetch everything immediately (no waiting for the first interval),
// then poll ONLY what moves on a quote cadence.
// ---------------------------------------------------------------------------

// paintWatchBtn BEFORE the fetches: it reads the data-watched stamp the
// route left in the HTML, so the button is correct the moment this script
// runs — no fetch, no flicker, no network on the critical path.
paintWatchBtn(addToWatchlistBtn.dataset.watched === "true");
refreshStockQuote();
refreshStockStats();
if (stockChartHandle) stockChartHandle.refresh();
setInterval(refreshStockQuote, REFRESH_MS);
