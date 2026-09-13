// Frontend logic for the DASHBOARD page: the live indices bar, the live
// watchlist, and the transaction ledger.
//
// Talks to the Flask backend over HTTP only (fetch -> JSON -> DOM).
// Knows nothing about yfinance, Flask, or Python.
//
// Shared helpers — REFRESH_MS, the formatters (formatPrice/formatNumber/
// formatSigned), paintChange, the UI kit (icon / showPrompt / showConfirm /
// showToast), and the whole navbar search dropdown — live in common.js,
// which base.html loads BEFORE this file. They are plain globals here;
// defining them again would just shadow the shared ones.

// Chips managed by JS = those carrying a data-symbol attribute.
// Chips without one (the static placeholders) are invisible to this code.
function managedChips() {
    return document.querySelectorAll(".chip[data-symbol]");
}

// Set every managed chip to a placeholder:
// EMPTY while waiting for data (the CSS :empty skeleton shimmer shows),
// "—" when the backend is unreachable.
function setChipState(text) {
    managedChips().forEach((chip) => {
        chip.querySelector(".index-price").textContent = text;
        chip.querySelector(".index-change").textContent = "";
    });
}

// Fill one chip from one quote object (a parsed piece of the JSON list).
function updateChip(quote) {
    // Find the chip by its data-symbol hook — by meaning, not position.
    const chip = document.querySelector(`.chip[data-symbol="${quote.symbol}"]`);
    if (!chip) return; // backend knows a symbol our HTML doesn't show yet

    const priceEl = chip.querySelector(".index-price");
    const changeEl = chip.querySelector(".index-change");

    const positive = quote.change >= 0;
    const sign = positive ? "+" : "";

    // textContent (never innerHTML): writes plain text, immune to HTML
    // injection. innerHTML would interpret strings as markup.
    // Every price carries its native currency code ("USD", "CAD", ...) —
    // per the brief: native currency display, no FX conversion.
    priceEl.textContent = `${formatPrice(quote.price)} ${quote.currency}`;
    changeEl.textContent =
        `${sign}${formatPrice(quote.change)} (${sign}${quote.change_pct.toFixed(2)}%)`;

    // One call each: set green (pos) or red (neg), replacing the other.
    changeEl.classList.toggle("pos", positive);
    changeEl.classList.toggle("neg", !positive);
}

// One refresh cycle: HTTP GET -> check status -> parse JSON -> paint DOM.
async function refreshIndices() {
    try {
        const response = await fetch("/api/indices");
        // fetch does NOT throw on 4xx/5xx — only on network failure.
        // A 503 arrives as a "successful" fetch with ok === false.
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const quotes = await response.json(); // raw bytes -> JS objects
        for (const quote of quotes) updateChip(quote);

        // Gap-fill: the backend returns successes only, so any managed chip
        // whose symbol did NOT arrive just failed while its siblings lived.
        // Set = O(1) membership test for "did this symbol answer?".
        const answered = new Set(quotes.map((q) => q.symbol));
        managedChips().forEach((chip) => {
            if (!answered.has(chip.dataset.symbol)) {
                chip.querySelector(".index-price").textContent = "—";
                chip.querySelector(".index-change").textContent = "";
            }
        });
    } catch (err) {
        console.error("indices refresh failed:", err);
        setChipState("—");
    }
}

// Boot sequence moved to the bottom of the file — every function above must
// be defined before it runs.

// ---------------------------------------------------------------------------
// WATCHLIST — same refresh rhythm as the indices bar, but the rows are
// dynamic. The chips are fixed HTML the backend merely fills; watchlist rows
// exist only because the backend's symbol list says so, so JS builds (and
// rebuilds) the <li> elements itself every cycle.
// ---------------------------------------------------------------------------

// Grab the pieces this section manages, once, at load time.
const watchlistEl = document.querySelector(".watchlist");
const addTickerBtn = document.querySelector("#add-ticker-btn");

// Replace the list's contents with one message row (used for the empty
// watchlist and for "the backend is unreachable" states).
function setWatchlistMessage(text) {
    // textContent = "" wipes all children in one assignment — the simple
    // way to clear a container before rebuilding it.
    watchlistEl.textContent = "";
    const row = document.createElement("li");
    row.className = "empty-state";
    row.textContent = text;
    watchlistEl.append(row);
}

// Rebuild the list: one <li class="watchlist-item"> per stored symbol, each
// carrying a data-symbol hook (same "find by meaning, not position" contract
// as the chips) and starting blank until a quote fills it in.
function renderWatchlistRows(symbols) {
    // Empty watchlist is a normal state, not an error — say so nicely.
    if (symbols.length === 0) {
        setWatchlistMessage("Nothing here yet — click + Add");
        return;
    }

    watchlistEl.textContent = "";
    for (const symbol of symbols) {
        // document.createElement builds real DOM nodes; textContent writes
        // plain text. Both together are immune to HTML injection — never
        // assemble rows with innerHTML from backend strings.
        const row = document.createElement("li");
        row.className = "watchlist-item";
        row.dataset.symbol = symbol; // the row's identity hook

        // Left side: the ticker and (when available) its company name.
        const left = document.createElement("div");
        const tickerEl = document.createElement("strong");
        tickerEl.textContent = symbol;
        const nameEl = document.createElement("div");
        nameEl.className = "sub-text";
        nameEl.textContent = "…"; // filled in when the quote arrives
        left.append(tickerEl, nameEl);

        // Right side: live price and the day's percentage change.
        const right = document.createElement("div");
        right.className = "text-right";
        const priceEl = document.createElement("div");
        priceEl.className = "watch-price";
        // Empty, not "…": an empty .watch-price is what the CSS :empty
        // skeleton shimmer keys on while the quote is in flight.
        priceEl.textContent = "";
        const changeEl = document.createElement("span");
        changeEl.className = "change-tag";
        right.append(priceEl, changeEl);

        // The remove button (an × SVG icon). It gets rebuilt with the rows
        // every cycle, so we never attach a click listener to it directly —
        // one delegated listener on the parent <ul> handles clicks for all
        // rows forever.
        const removeBtn = document.createElement("button");
        removeBtn.className = "remove-btn";
        removeBtn.append(icon("x"));
        removeBtn.title = `Remove ${symbol}`;
        removeBtn.dataset.symbol = symbol;

        row.append(left, right, removeBtn);
        watchlistEl.append(row);
    }
}

// Fill one row from one quote dict (a parsed piece of the JSON "quotes" list).
function updateWatchRow(quote) {
    const row = document.querySelector(
        `.watchlist-item[data-symbol="${quote.symbol}"]`
    );
    if (!row) return; // row was removed between cycles; harmless

    const nameEl = row.querySelector(".sub-text");
    const priceEl = row.querySelector(".watch-price");
    const changeEl = row.querySelector(".change-tag");

    // Native currency per security (same rule as the chips): "182.52 USD".
    // change_pct arrives as a float like 1.3012 — the backend never
    // pre-formats; display decisions stay here.
    priceEl.textContent = `${formatPrice(quote.price)} ${quote.currency}`;

    const positive = quote.change_pct >= 0;
    const sign = positive ? "+" : "";
    changeEl.textContent = `${sign}${quote.change_pct.toFixed(2)}%`;
    changeEl.classList.toggle("pos", positive);
    changeEl.classList.toggle("neg", !positive);

    // A failed name fetch came back as null — show the ticker alone.
    nameEl.textContent = quote.name || "";
}

// Mark every current row unavailable ("—"): used when a cycle could not
// reach the backend at all, or (gap-fill) when a specific symbol's quote
// didn't arrive while its siblings' did.
function markWatchlistUnavailable() {
    watchlistEl.querySelectorAll(".watchlist-item").forEach((row) => {
        row.querySelector(".watch-price").textContent = "—";
        row.querySelector(".sub-text").textContent = "";
        const changeEl = row.querySelector(".change-tag");
        changeEl.textContent = "";
        changeEl.classList.remove("pos", "neg");
    });
}

// One watchlist refresh cycle: GET -> rebuild rows -> fill quotes -> gap-fill.
async function refreshWatchlist() {
    try {
        const response = await fetch("/api/watchlist");
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        // One response, two payloads: "symbols" = which rows exist (source
        // of truth), "quotes" = successes only for this cycle.
        const payload = await response.json();

        renderWatchlistRows(payload.symbols);
        for (const quote of payload.quotes) updateWatchRow(quote);

        // Gap-fill, same Set-membership test as the indices bar: any stored
        // symbol whose quote didn't answer just failed while its siblings
        // lived.
        const answered = new Set(payload.quotes.map((q) => q.symbol));
        watchlistEl.querySelectorAll(".watchlist-item").forEach((row) => {
            if (!answered.has(row.dataset.symbol)) {
                row.querySelector(".watch-price").textContent = "—";
                row.querySelector(".sub-text").textContent = "";
                const changeEl = row.querySelector(".change-tag");
                changeEl.textContent = "";
                changeEl.classList.remove("pos", "neg");
            }
        });
    } catch (err) {
        console.error("watchlist refresh failed:", err);
        // If we have rows from an earlier successful cycle, degrade them to
        // "—" like the chips do. If we never got rows at all, we can't know
        // the symbol list — show a message instead.
        if (watchlistEl.querySelector(".watchlist-item")) {
            markWatchlistUnavailable();
        } else {
            setWatchlistMessage("Watchlist unavailable");
        }
    }
}

// + Add: ask for a ticker, POST it, let the next refresh pull the truth.
// The backend validates the ticker is real (404) and rejects duplicates
// (409) — the frontend just relays its error messages.
addTickerBtn.addEventListener("click", async () => {
    // showPrompt resolves null when the user cancels — abort quietly. (The
    // same contract the old browser prompt had, minus freezing the page.)
    const input = await showPrompt({
        title: "Add to watchlist",
        message: "Ticker symbol to watch (e.g. AAPL, SHOP.TO, BTC-USD):",
        placeholder: "AAPL, SHOP.TO, BTC-USD…",
        confirmLabel: "Add",
    });
    if (input === null) return;
    const symbol = input.trim().toUpperCase();
    if (!symbol) return;

    try {
        const response = await fetch("/api/watchlist", {
            method: "POST",
            // Without this header Flask would not know the body is JSON.
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ symbol }),
        });
        if (!response.ok) {
            // The backend's error JSON is more useful than a generic
            // message — relay it. .catch(() => null) guards against a
            // response that isn't parseable JSON.
            const data = await response.json().catch(() => null);
            showToast(
                data?.error || `Could not add ${symbol} (HTTP ${response.status})`,
                "error"
            );
            return;
        }
        // 201 Created: a refresh pulls the stored list (and the new row's
        // live quote — adding it warmed the backend's price cache).
        refreshWatchlist();
    } catch (err) {
        console.error("add ticker failed:", err);
        showToast("Could not reach the server — is it running?", "error");
    }
});

// Remove: ONE delegated listener on the parent <ul>. Click events bubble up
// from whatever was actually clicked (here, a remove button that gets
// rebuilt every cycle), and closest() walks back up the tree to find the
// button we care about. Attaching listeners to the buttons themselves would
// die with every rebuild — delegation survives it.
watchlistEl.addEventListener("click", async (event) => {
    const removeBtn = event.target.closest(".remove-btn");
    if (!removeBtn) return; // click landed somewhere else in the list
    const symbol = removeBtn.dataset.symbol;
    // encodeURIComponent: symbols can contain URL-hostile characters
    // ("^GSPC", "BTC-USD") — encode the PATH, never the whole URL.
    try {
        const response = await fetch(
            `/api/watchlist/${encodeURIComponent(symbol)}`,
            { method: "DELETE" }
        );
        // 204 (gone) is success; 404 means it was already gone elsewhere —
        // refreshing either way shows the stored truth.
        if (!response.ok && response.status !== 404) {
            throw new Error(`HTTP ${response.status}`);
        }
        refreshWatchlist();
    } catch (err) {
        console.error("remove ticker failed:", err);
        showToast("Could not reach the server — is it running?", "error");
    }
});

// Navigate: a watchlist ROW is a link to the detail page now (the search
// dropdown shouldn't be the only way there). A second delegated listener
// on the same <ul> — delegation again, since rows are rebuilt every cycle.
// The remove button lives INSIDE its row, so this listener must stand down
// when a click started on it: the remove listener above handles that
// click, and navigating on top of deleting would be a nasty surprise.
watchlistEl.addEventListener("click", (event) => {
    if (event.target.closest(".remove-btn")) return; // that's a removal
    const row = event.target.closest(".watchlist-item");
    if (!row) return; // click landed on the list itself
    window.location.href = `/stock/${encodeURIComponent(row.dataset.symbol)}`;
});

// Privacy toggle — hide sensitive values for screen sharing. State
// persists in localStorage so the user's preference survives refreshes.
// hidePortfolioToggle masks the portfolio total, day change and total
// return. (The LEDGER's eye moved to ledger.js with the ledger page.)
// The toggle is a <button> element with data-hidden="true"|"false".
const hidePortfolioToggle = document.getElementById("hide-portfolio-toggle");

// Restore persisted privacy state from localStorage. Strings "true"/"false"
// — same pattern as the column order persistence.
if (hidePortfolioToggle) {
    const hidden = localStorage.getItem("hidePortfolio") === "true";
    hidePortfolioToggle.dataset.hidden = hidden;
    hidePortfolioToggle.title = hidden
        ? "Show portfolio values" : "Hide portfolio values";
    // Keep screen-reader state in sync with the persisted toggle state.
    hidePortfolioToggle.setAttribute("aria-label", hidePortfolioToggle.title);
    hidePortfolioToggle.setAttribute("aria-pressed", String(hidden));
}

// ---------------------------------------------------------------------------
// PORTFOLIO HEADER — the "Your Portfolio" card's three live numbers: total
// value, today's move, and total return. Rendering only, like every section
// above: GET /api/portfolio/summary computes the raw floats from the ledger
// + live quotes; this code formats and paints them.
//
// The three spans ship blank in index.html ("…") so the old mockup numbers
// can never masquerade as live data — same rule as the indices chips.
// ---------------------------------------------------------------------------

// Grab the pieces this section manages, once, at load time.
const portfolioValueEl = document.getElementById("portfolio-value");
const portfolioDayChangeEl = document.getElementById("portfolio-day-change");
const portfolioTotalReturnEl =
    document.getElementById("portfolio-total-return");

// Degraded state: value "—", change lines blank. Used when the fetch fails
// entirely AND when the backend reports that nothing priced is contributing
// (every held ticker unquotable this cycle) — a bare "0.00" would imply the
// holdings are worthless, when the truth is "we couldn't price them".
// tooltipText (optional) explains WHY on hover.
function setPortfolioUnavailable(tooltipText = "") {
    // Privacy guard: a failed refresh cycle must not paint the degraded
    // "—" over the **** masks either — same reasoning as the guard in
    // refreshPortfolioSummary. While masked, keep the masks.
    if (portfolioMasked()) return;
    portfolioValueEl.textContent = "—";
    portfolioValueEl.title = tooltipText;
    for (const el of [portfolioDayChangeEl, portfolioTotalReturnEl]) {
        el.textContent = "";
        el.classList.remove("pos", "neg");
    }
    // Degraded content is painted — release the geometry locks here too,
    // same one-layout-pass reasoning as in refreshPortfolioSummary.
    clearPortfolioGeometryLocks();
}

// (The change-pill painter itself is common.js's paintChange — the stock
// detail page paints the exact same shape, so the helper moved there.)

// Is the portfolio header currently privacy-masked? The masking code and
// the refresh cycle consult this ONE helper, so both read the same source
// of truth (data-hidden on the button).
function portfolioMasked() {
    return !!(hidePortfolioToggle &&
              hidePortfolioToggle.dataset.hidden === "true");
}

// Snapshot of the three header spans as they were last painted with REAL
// values, captured at mask time. While masked the refresh cycle is
// guard-skipped, so the server is the only place the live numbers exist —
// without this cache, unmasking had to wait for a fetch before anything
// new could appear (hide was instant, show lagged a second). The cache
// makes unmask instant: repaint from memory, then let the background
// fetch swap in fresh numbers. Null when there's nothing restorable.
let lastPortfolioPaint = null;

// Release the privacy geometry locks (the inline display/min-width/
// min-height set while masked) and strip the privacy-masked class. ONLY
// call this AFTER real content has been painted back over the masks:
// the locks ride along during the unmask fetch so the row keeps its box,
// and releasing them in the same JS turn as the repaint means the
// browser computes layout exactly once — **** swaps to live values with
// no narrow intermediate frame. (paintChange only toggles pos/neg, it
// never removes privacy-masked — that's stripped here too.)
function clearPortfolioGeometryLocks() {
    for (const el of [portfolioValueEl, portfolioDayChangeEl,
                      portfolioTotalReturnEl]) {
        el.style.display = "";
        el.style.minWidth = "";
        el.style.minHeight = "";
        el.classList.remove("privacy-masked");
    }
}

// Apply or remove privacy masking on the portfolio header. When the button
// is in hidden state (data-hidden="true"), all three value spans show "****"
// instead of real numbers. When shown, a fresh refreshPortfolioSummary
// repaints live data.
//
// GEOMETRY LOCK (why the min-width/min-height dance): masked text is much
// narrower than the real numbers, and the value row is plain wrapping
// inline content. Real values are wide enough to push the two change
// pills onto their own wrapped line; **** values are so small that
// everything fits beside the value — so masking CHANGED THE WRAP POINT:
// the pills jumped up inline with the value and everything below shifted.
// The fix: measure each span's live box (offsetWidth/offsetHeight) and
// re-freeze it as inline min-width/min-height BEFORE overwriting the
// text. min-width is ignored on plain inline elements, so each span is
// also flipped to inline-block for the mask's duration. Unmasking clears
// every inline style so the browser reflows at natural size before the
// fresh paint.
function applyPortfolioPrivacy() {
    if (!hidePortfolioToggle) return;
    const masked = portfolioMasked();
    const targets = [portfolioValueEl, portfolioDayChangeEl,
                     portfolioTotalReturnEl];
    if (masked) {
        // Snapshot the values on screen NOW, while they're still real —
        // the unmask branch repaints them from memory so the wait for the
        // fresh fetch is invisible. Empty spans (masked before any fetch
        // ever landed) mean there's nothing worth restoring: keep the old
        // cache, if any.
        if (portfolioValueEl.textContent) {
            lastPortfolioPaint = {
                value: portfolioValueEl.textContent,
                day: portfolioDayChangeEl.textContent,
                dayClass: portfolioDayChangeEl.className,
                total: portfolioTotalReturnEl.textContent,
                totalClass: portfolioTotalReturnEl.className,
            };
        }
        // Freeze geometry FIRST, while the real values are still painted —
        // once textContent becomes "****" the original widths are gone.
        for (const el of targets) {
            const w = el.offsetWidth;
            const h = el.offsetHeight;
            el.style.display = "inline-block";
            el.style.minWidth = `${w}px`;
            el.style.minHeight = `${h}px`;
        }
        portfolioValueEl.textContent = "****";
        portfolioValueEl.title = "Portfolio value hidden for privacy";
        portfolioDayChangeEl.textContent = "****";
        portfolioDayChangeEl.className = "price-change privacy-masked";
        portfolioTotalReturnEl.textContent = "****";
        portfolioTotalReturnEl.className = "price-change privacy-masked";
    } else {
        // Unmask. The geometry locks stay on for now — releasing early
        // would let the still-painted **** collapse to natural (tiny)
        // width, the transition jump the GUI check caught. If the mask-
        // time snapshot holds real values, repaint them from memory in
        // the SAME JS turn as the lock release: instant values, exactly
        // one layout pass, no intermediate frame.
        if (lastPortfolioPaint && lastPortfolioPaint.value) {
            portfolioValueEl.textContent = lastPortfolioPaint.value;
            portfolioDayChangeEl.textContent = lastPortfolioPaint.day;
            portfolioDayChangeEl.className = lastPortfolioPaint.dayClass;
            portfolioTotalReturnEl.textContent = lastPortfolioPaint.total;
            portfolioTotalReturnEl.className = lastPortfolioPaint.totalClass;
            clearPortfolioGeometryLocks();
        }
        // No cache (masked before the first fetch ever landed): nothing
        // to restore instantly — the masked look holds via the locks
        // until the repaint below arrives, and that path releases the
        // locks itself.
        portfolioValueEl.title = "";
        // Fresh values always come from the server; the cache was only a
        // stopgap so the wait is invisible. Consume it either way.
        lastPortfolioPaint = null;
        refreshPortfolioSummary();
    }
}

// Wire up the privacy button event listeners. Each click toggles the
// data-hidden attribute, persists the state to localStorage, and
// immediately applies or removes the mask.
if (hidePortfolioToggle) {
    hidePortfolioToggle.addEventListener("click", () => {
        const hidden = hidePortfolioToggle.dataset.hidden === "true";
        hidePortfolioToggle.dataset.hidden = !hidden;
        hidePortfolioToggle.title = hidden
            ? "Hide portfolio values" : "Show portfolio values";
        // Screen-reader state: aria-label mirrors the title (icon-only
        // button — the accessible name IS the button), aria-pressed
        // reports the toggle state ("pressed" = values are hidden).
        hidePortfolioToggle.setAttribute("aria-label", hidePortfolioToggle.title);
        hidePortfolioToggle.setAttribute("aria-pressed", String(!hidden));
        localStorage.setItem("hidePortfolio", !hidden);
        applyPortfolioPrivacy();
    });
}

// One summary refresh cycle: GET -> paint the three spans.
async function refreshPortfolioSummary() {
    try {
        const response = await fetch("/api/portfolio/summary");
        // fetch does NOT throw on 4xx/5xx — only on network failure.
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();

        // Privacy guard: the setInterval poll keeps calling this function
        // even while the header is masked — without this check it would
        // repaint live numbers over the **** masks and silently lift the
        // mask within one refresh cycle. Skip ALL painting (success and
        // degraded alike); unmasking calls back in for a fresh paint.
        if (portfolioMasked()) {
            return;
        }

        // "unpriced" lists the tickers the backend couldn't quote this
        // cycle. They were excluded from EVERY sum, so if the sums are
        // all zero WHILE that list is non-empty, nothing priced is
        // contributing — degrade the whole header instead of showing a
        // hollow "0.00" that would imply worthless holdings.
        const nothingPriced = data.unpriced.length > 0 &&
            data.total_value === 0 &&
            data.day_gain === 0 &&
            data.total_gain === 0;
        if (nothingPriced) {
            setPortfolioUnavailable(
                `Couldn't price: ${data.unpriced.join(", ")}`
            );
            return;
        }

        // Partial case: paint the priced totals, but say on hover which
        // tickers are missing. title="" wipes a stale tooltip from an
        // earlier cycle — the hover text must always match THIS payload.
        portfolioValueEl.title = data.unpriced.length > 0
            ? `Excludes ${data.unpriced.join(", ")} — couldn't be priced`
            : "";
        // The summary is ALWAYS CAD (the ledger toggle never touches it)
        // and the reply declares that — paint the code so a converted
        // total can't be misread as native.
        portfolioValueEl.textContent =
            `${formatNumber(data.total_value)} ${data.currency || "CAD"}`;
        paintChange(portfolioDayChangeEl, data.day_gain, data.day_gain_pct,
                    "Today");
        paintChange(portfolioTotalReturnEl, data.total_gain,
                    data.total_gain_pct, "Total");
        // Real content is back over the masks — release the geometry locks
        // in the same JS turn so there's exactly one layout pass (no jump).
        clearPortfolioGeometryLocks();

        // Feed yesterday's portfolio value into the chart handle so the
        // 1D view can draw a horizontal reference line at yesterday's close.
        if (portfolioChartHandle) {
            portfolioChartHandle.updatePrevClose(
                data.total_value != null && data.day_gain != null
                    ? data.total_value - data.day_gain
                    : null
            );
        }
    } catch (err) {
        console.error("portfolio summary refresh failed:", err);
        setPortfolioUnavailable();
    }
}

// ---------------------------------------------------------------------------
// PORTFOLIO CHART — real portfolio value over time. (It began life as
// hardcoded placeholder data — a learning exercise — before the ledger
// made real numbers possible.) Chart.js itself comes from the CDN <script>
// tag in base.html's <head>, so a global "Chart" class already exists by
// the time this runs.
//
// The chart itself is built by common.js's setupTimeframeChart — the stock
// detail page plots the identical picture with a different endpoint, so
// the Chart.js config, the 1D–MAX button wiring, and the refresh cycle all
// moved there. This page's only input is WHERE the data comes from.
// ---------------------------------------------------------------------------

// The canvas from the HTML — our blank drawing pad — and the timeframe
// button bar above it.
const portfolioCanvas = document.getElementById("portfolioChart");
const chartButtonsEl = document.querySelector(".chart-timeframe-selectors");

// The default period — must match the `active` button in index.html (5D),
// so the first thing the chart shows is the same range the button bar
// claims is selected.
const DEFAULT_CHART_PERIOD = "5D";

// Build once at load with empty data; every refresh swaps the arrays and
// redraws — no re-creating the Chart, no page reload. The factory wires
// the delegated .time-btn listener too, so a click re-fetches with the
// clicked button's textContent as the PERIOD_MAP key.
const portfolioChartHandle = setupTimeframeChart({
    canvas: portfolioCanvas,
    buttonBar: chartButtonsEl,
    // The chart plots the CAD total in every mode — label it so the
    // currency is never guessed at.
    datasetLabel: "Portfolio Value (CAD)",
    endpoint: "/api/portfolio/history",
    defaultPeriod: DEFAULT_CHART_PERIOD,
});

// The boot section below calls this with no argument (the default 5D view);
// nothing else needs it — button clicks are wired inside the factory.
function refreshPortfolioChart(period = DEFAULT_CHART_PERIOD, opts) {
    // If Chart.js never loaded, the handle is null — nothing to paint.
    // Return the promise so callers can chain .then() (used by the
    // pre-fetch loop below to wait for the default chart before firing
    // off the remaining timeframes). opts forwards {silent: true} for
    // pre-fetches that should warm the cache without repainting.
    if (portfolioChartHandle) return portfolioChartHandle.refresh(period, opts);
}

// When the theme toggles, repaint the chart so grid/line colors pick up
// the new CSS variable values (the crosshair and gradient already read
// CSS on every draw, but grid color and line border are set at creation /
// refresh time and need an explicit update).
document.addEventListener("themechange", () => {
    if (portfolioChartHandle) portfolioChartHandle.chart.update();
});

// ---------------------------------------------------------------------------
// BOOT — the script's entry point. This block runs top-to-bottom the moment
// the browser reaches it, and only now are all the functions above defined.
// ---------------------------------------------------------------------------

// 1. Blank both managed sections so the outdated mockup numbers can never
//    masquerade as live data. The indices chips ship EMPTY — the CSS
//    :empty skeleton shimmer stands in until real data lands — and the
//    watchlist starts truly empty, painted by refreshWatchlist within the
//    second.
setChipState("");

// 2. Fetch all three quote-driven sections immediately — no waiting for the
//    first interval. (The fourth, the ledger, now lives on /ledger with
//    its own timer in ledger.js.)
refreshIndices();
refreshWatchlist();
refreshPortfolioSummary();
// If the persisted privacy state is masked, paint the **** now — the
// refresh above is guarded and will NOT paint over the mask, so without
// this the header would sit on its empty skeletons until the user clicks
// the eye off. Unmasked at load: a no-op is skipped entirely.
if (portfolioMasked()) {
    applyPortfolioPrivacy();
}
// The portfolio chart is fetched once at load (its default 5D view) and
// again only when a timeframe button is clicked — unlike the quote-driven
// sections, price history doesn't change on a 60s cadence, so it would be
// wasteful (and Yahoo rate-limit-hammering) to poll it too.
const chartReady = refreshPortfolioChart();

// Pre-fetch all other timeframes in the background so switching is instant.
// Fire-and-forget — no UI feedback needed. The frontend cache stores each
// response for its TTL (120s live, 600s settled), so by the time the user
// clicks a button, the data is already there. All 8 fire in parallel, and
// they start only AFTER the default 5D chart has rendered — avoids
// hammering Yahoo before the user sees their chart. Optional chain guards
// against Chart.js CDN failure (refreshPortfolioChart returns undefined).
const ALL_PERIODS = ["1D", "1M", "3M", "6M", "YTD", "1Y", "5Y", "MAX"];
chartReady?.then?.(() => {
    for (const period of ALL_PERIODS) {
        refreshPortfolioChart(period, { silent: true });
    }
});

// 3. Poll. ONE timer drives all cycles: the three sections' data changes at
//    the same rate (the summary is quote-driven too — prices move, totals
//    follow), so polling them together keeps them in lockstep and doubles
//    as the change-detector for anything added through other windows or
//    tabs (add/remove shows up within a minute even without its own
//    trigger; logging a transaction happens on /ledger, which has its own
//    poll).
setInterval(() => {
    refreshIndices();
    refreshWatchlist();
    refreshPortfolioSummary();
}, REFRESH_MS);
