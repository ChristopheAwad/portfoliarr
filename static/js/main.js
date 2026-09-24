// Frontend logic for the DASHBOARD page: the tabbed market overview, the
// live watchlist, and the transaction ledger.
//
// Talks to the Flask backend over HTTP only (fetch -> JSON -> DOM).
// Knows nothing about yfinance, Flask, or Python.
//
// Shared helpers — REFRESH_MS, the formatters (formatPrice/formatNumber/
// formatSigned), paintChange, the UI kit (icon / showPrompt / showConfirm /
// showToast), and the whole navbar search dropdown — live in common.js,
// which base.html loads BEFORE this file. They are plain globals here;
// defining them again would just shadow the shared ones.

// MARKET OVERVIEW BEGIN
// The tabbed market strip above the portfolio. All categories load in
// parallel at startup, but only the active one is polled. Items live inside
// their category's panel and are found by data-symbol (never DOM position),
// so one category's response cannot touch another panel's cells.

// Which category tab is shown. North America is the default and matches the
// template's initially-selected tab. Not persisted: a fresh load always
// starts on the default.
let activeMarketCategory = "north-america";

// Per-category request tokens. A slow response that finishes after a NEWER
// request for the same category must not overwrite it — the token is checked
// before every paint, so only the latest request for a category wins.
const marketRequestTokens = {};

// Successful panels stay fresh for the quote cache's 120-second lifetime.
// A tab click reuses the painted cells (or its pending fetch), while the
// active-tab poll deliberately asks for current data. Failures aren't cached.
const MARKET_CACHE_TTL = 120_000;
const marketFetchedAt = {};
const marketPending = {};

// The panel element that holds one category's market items.
function marketPanel(category) {
    return document.querySelector(`.market-panel[data-category="${category}"]`);
}

// Managed items = the data-symbol anchors inside ONE panel. Scoping the
// query to a panel is what keeps a Europe response from touching North
// America's (or any hidden panel's) cells.
function managedMarketItems(panel) {
    return panel.querySelectorAll(".market-item[data-symbol]");
}

// Blank one panel's cells with ONE placeholder:
// "" while waiting (the CSS :empty shimmer shows, on BOTH rows),
// "—" when the backend is unreachable for the whole category.
// The change row takes the SAME placeholder as the level row: an empty
// change row would re-trigger its :empty shimmer, so the skeleton would
// outlive a failure. pos/neg are cleared too — a placeholder is not a move,
// and a green "—" would read as a gain.
function setMarketPanelValues(panel, text) {
    managedMarketItems(panel).forEach((item) => {
        item.querySelector(".market-item-price").textContent = text;
        const changeEl = item.querySelector(".market-item-change");
        changeEl.textContent = text;
        changeEl.classList.remove("pos", "neg");
    });
}

// Adaptive precision for MARKET levels (index points, FX rates). A value
// below 1 in absolute terms (CAD/USD ≈ 0.73) needs four decimals to be
// readable; everything else keeps two. Deliberately NOT formatPrice — that
// shared helper stays two-decimal for portfolio/ledger/stock money.
function formatMarketLevel(value) {
    const digits = Math.abs(value) < 1 ? 4 : 2;
    return new Intl.NumberFormat("en-US", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
    }).format(value);
}

// One text node with a className, built through createElement + textContent
// (never innerHTML) so a quote string can never be parsed as markup.
function marketTextSpan(className, text) {
    const span = document.createElement("span");
    span.className = className;
    span.textContent = text;
    return span;
}

// Fill one market item from one quote object (a parsed JSON piece).
function updateMarketItem(panel, quote) {
    // Find the item by its data-symbol hook — by meaning, not position.
    const item = panel.querySelector(`.market-item[data-symbol="${quote.symbol}"]`);
    if (!item) return; // backend knows a symbol our panel doesn't show yet

    const priceEl = item.querySelector(".market-item-price");
    const changeEl = item.querySelector(".market-item-change");

    // Zero counts as positive, matching the app's existing chip behavior.
    const positive = quote.change >= 0;
    const sign = positive ? "+" : "";

    // textContent (never innerHTML): plain text, immune to HTML injection.
    // Every price carries its native currency code — native display, no FX.
    priceEl.textContent = `${formatMarketLevel(quote.price)} ${quote.currency}`;

    // Absolute move and percentage are SEPARATE spans, not one string:
    // the percentage must carry the stronger weight (percentages compare
    // across instruments, point moves do not), and CSS cannot weigh half
    // of a single text node. Both still ship from one quote, in one paint.
    changeEl.replaceChildren(
        marketTextSpan("market-item-move", `${sign}${formatMarketLevel(quote.change)}`),
        marketTextSpan("market-item-pct", `(${sign}${quote.change_pct.toFixed(2)}%)`)
    );

    // One call each: green (pos) or red (neg), replacing the other.
    changeEl.classList.toggle("pos", positive);
    changeEl.classList.toggle("neg", !positive);
}

// One refresh cycle for ONE category. Tab clicks reuse a fresh or pending
// result; a poll can force a new request even if an older one is still slow.
function refreshMarketOverview(category = activeMarketCategory, { force = false } = {}) {
    const panel = marketPanel(category);
    if (!panel) return;

    if (!force) {
        if (marketPending[category]) return marketPending[category];
        if (marketFetchedAt[category] !== undefined &&
            Date.now() - marketFetchedAt[category] < MARKET_CACHE_TTL) return;
    }

    // Claim this request's token BEFORE the await; a response that finishes
    // after a newer request for the same category is discarded below.
    marketRequestTokens[category] = (marketRequestTokens[category] || 0) + 1;
    const requestToken = marketRequestTokens[category];

    setMarketPanelValues(panel, ""); // shimmer while loading

    const request = (async () => {
        try {
            const response = await fetch(
                `/api/indices?category=${encodeURIComponent(category)}`
            );
            // fetch does NOT throw on 4xx/5xx — only on network failure.
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const quotes = await response.json(); // raw bytes -> JS objects

            if (marketRequestTokens[category] !== requestToken) return; // stale

            for (const quote of quotes) updateMarketItem(panel, quote);

            // Gap-fill: the backend returns successes only, so any item whose
            // symbol did NOT arrive just failed while its siblings lived. BOTH
            // rows take "—" — an EMPTY change row would re-trigger its :empty
            // loading shimmer, i.e. the skeleton would outlive the failure —
            // and pos/neg clear, so a degraded cell cannot paint its dash green.
            const answered = new Set(quotes.map((q) => q.symbol));
            managedMarketItems(panel).forEach((item) => {
                if (!answered.has(item.dataset.symbol)) {
                    item.querySelector(".market-item-price").textContent = "—";
                    const changeEl = item.querySelector(".market-item-change");
                    changeEl.textContent = "—";
                    changeEl.classList.remove("pos", "neg");
                }
            });
            marketFetchedAt[category] = Date.now();
        } catch (err) {
            if (marketRequestTokens[category] !== requestToken) return; // stale
            delete marketFetchedAt[category];
            console.error(`market refresh failed for ${category}:`, err);
            setMarketPanelValues(panel, "—");
        } finally {
            // A superseded request cannot clear the newer request's marker.
            if (marketRequestTokens[category] === requestToken) {
                delete marketPending[category];
            }
        }
    })();
    marketPending[category] = request;
    return request;
}

// The rendered tabs are the category list. Start every request without
// awaiting the last one, so a slow market cannot delay its siblings.
function preloadMarketOverview() {
    document.querySelectorAll(".market-tab").forEach((tab) => {
        refreshMarketOverview(tab.dataset.category);
    });
}

// Activate a category tab: sync ARIA + roving tabindex, show its panel, hide
// the others, focus the tab, and reuse or fetch that category's quotes. Switching
// does NOT touch the portfolio/watchlist/chart — those have their own
// refresh cycles.
function activateMarketTab(tab) {
    const category = tab.dataset.category;
    if (category === activeMarketCategory) return;
    activeMarketCategory = category;

    document.querySelectorAll(".market-tab").forEach((t) => {
        const selected = t === tab;
        t.classList.toggle("active", selected);
        t.setAttribute("aria-selected", selected ? "true" : "false");
        t.tabIndex = selected ? 0 : -1;
    });
    document.querySelectorAll(".market-panel").forEach((p) => {
        p.hidden = p.dataset.category !== category;
    });

    tab.focus();
    refreshMarketOverview(category);
}

// Wire the six tabs: click to select, plus the WAI-ARIA keyboard model
// (ArrowLeft/ArrowRight move with wrap, Home/End jump to the ends).
function setupMarketTabs() {
    const tabs = Array.from(document.querySelectorAll(".market-tab"));
    tabs.forEach((tab) => {
        tab.addEventListener("click", () => activateMarketTab(tab));
    });

    const tabBar = document.querySelector(".market-tabs");
    if (!tabBar) return;
    tabBar.addEventListener("keydown", (event) => {
        const current = tabs.indexOf(document.activeElement);
        if (current === -1) return;

        let next = current;
        if (event.key === "ArrowRight") next = (current + 1) % tabs.length;
        else if (event.key === "ArrowLeft") next = (current - 1 + tabs.length) % tabs.length;
        else if (event.key === "Home") next = 0;
        else if (event.key === "End") next = tabs.length - 1;
        else return;

        event.preventDefault();
        activateMarketTab(tabs[next]);
    });
}
// MARKET OVERVIEW END

// Boot sequence moved to the bottom of the file — every function above must
// be defined before it runs.

// ---------------------------------------------------------------------------
// WATCHLIST — same refresh rhythm as the market overview, but the rows are
// dynamic. The market items are fixed HTML the backend merely fills;
// watchlist rows
// exist only because the backend's symbol list says so, so JS builds (and
// rebuilds) the <li> elements itself every cycle.
// ---------------------------------------------------------------------------

// Grab the pieces this section manages, once, at load time.
// The id (not the .watchlist class) is the hook: the sidebar now holds TWO
// .watchlist lists (this one and #volume-leaders), and identity by meaning
// beats DOM-order luck.
const watchlistEl = document.querySelector("#watchlist");
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
    // Empty watchlist is a normal state, not an error — say so AND say
    // what to do about it: actionable copy beats a shrug.
    if (symbols.length === 0) {
        setWatchlistMessage(
            "Your watchlist is empty — search a ticker above and press Add."
        );
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
    const row = watchlistTab.querySelector(
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

        // Gap-fill, same Set-membership test as the market overview: any
        // stored symbol whose quote didn't answer just failed while its
        // siblings lived.
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
// PORTFOLIO HEADER — the "Your Portfolio" card's live numbers: total value,
// today's move, total return, and the cost basis they're measured against.
// Rendering only, like every section above: GET /api/portfolio/summary
// computes the raw floats from the ledger + live quotes; this code formats
// and paints them.
//
// The spans ship blank in index.html so the old mockup numbers can never
// masquerade as live data — same rule as the market overview.
// ---------------------------------------------------------------------------

// Grab the pieces this section manages, once, at load time.
const portfolioValueEl = document.getElementById("portfolio-value");
const portfolioDayChangeEl = document.getElementById("portfolio-day-change");
const portfolioTotalReturnEl =
    document.getElementById("portfolio-total-return");
// The cost-basis caption's value span — the strip's fourth fact, sitting in
// its own quiet <p> under the big number. Same paint/mask lifecycle as the
// three above: it ships empty, the summary poll fills it, the privacy eye
// hides it.
const portfolioCostBasisEl = document.getElementById("portfolio-cost-basis");

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

// (The change-pill painter itself is common.js's paintChange. The stock
// detail page has its own paintPeriodChange because its pill leads with the
// timeframe and shows a "$" amount — a different shape.)

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
                      portfolioTotalReturnEl, portfolioCostBasisEl]) {
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
                     portfolioTotalReturnEl, portfolioCostBasisEl];
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
                dayValue: lastPortfolioPaint?.dayValue ?? null,
                dayPct: lastPortfolioPaint?.dayPct ?? null,
                total: portfolioTotalReturnEl.textContent,
                totalClass: portfolioTotalReturnEl.className,
                totalValue: lastPortfolioPaint?.totalValue ?? null,
                totalPct: lastPortfolioPaint?.totalPct ?? null,
                basis: portfolioCostBasisEl.textContent,
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
        // Show only the percentage part of the change pills — hide the
        // dollar amounts but keep relative performance visible.
        paintChange(portfolioDayChangeEl, lastPortfolioPaint?.dayValue ?? 0,
                    lastPortfolioPaint?.dayPct ?? null, "Today", true);
        portfolioDayChangeEl.classList.add("price-change", "privacy-masked");
        paintChange(portfolioTotalReturnEl, lastPortfolioPaint?.totalValue ?? 0,
                    lastPortfolioPaint?.totalPct ?? null, "Total", true);
        portfolioTotalReturnEl.classList.add("price-change", "privacy-masked");
        // The cost-basis span keeps its own (class-less) identity — the
        // mask rides on inline geometry locks plus the semantic
        // privacy-masked marker, not a className overwrite.
        portfolioCostBasisEl.textContent = "****";
        portfolioCostBasisEl.classList.add("privacy-masked");
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
            portfolioCostBasisEl.textContent = lastPortfolioPaint.basis || "";
        // Release geometry locks only when NOT masked — while masked,
        // the locks keep the layout stable around the shorter percentage-
        // only text. Unmasking calls this via applyPortfolioPrivacy.
        if (!masked) {
            clearPortfolioGeometryLocks();
        }
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
// SINGLE-FLIGHT: the boot call, the privacy-unmask call, and the 60s poll
// can all fire within one slow round-trip. Duplicate concurrent fetches
// would each hammer Yahoo AND race each other's paints. The first call
// owns the cycle; everyone behind it shares that one reply — a single
// response paints the same header, so joining costs nothing. The slot
// empties when the cycle settles so the NEXT cycle fetches fresh.
let summaryInflight = null;
let summaryFlightEpoch = null;

async function refreshPortfolioSummary() {
    if (!currentPortfolioId()) return;
    const epoch = portfolioEpoch();
    // Join the in-flight cycle instead of starting a duplicate request.
    if (summaryInflight && summaryFlightEpoch === epoch) return summaryInflight;
    summaryFlightEpoch = epoch;
    summaryInflight = (async () => {
        try {
            const response = await fetch(`/api/portfolio/summary${portfolioQuery()}`);
            // fetch does NOT throw on 4xx/5xx — only on network failure.
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            if (epoch !== portfolioEpoch()) return;

            // Privacy guard: when masked, skip painting dollar-only spans
            // (portfolio value and cost basis) but still paint the change
            // pills so percentages stay fresh during the refresh cycle.
            const masked = portfolioMasked();

            // "unpriced" lists the tickers the backend couldn't quote this
            // cycle. They were excluded from EVERY sum, so if the sums are
            // all zero WHILE that list is non-empty, nothing priced is
            // contributing — degrade the whole header instead of showing a
            // hollow "0.00" that would imply worthless holdings.
            const nothingPriced = data.unpriced.length > 0 &&
                data.total_value === 0 &&
                data.day_gain === 0 &&
                data.total_gain === 0;
            // Both the header's degradation path and the normal path must
            // update the donut. An all-unpriced reply is not an empty ledger.
            const tickerSlices = data.holdings.map(
                (h) => ({ key: h.ticker, value: h.value, weight: h.weight })
            );
            const tickerExcluded = data.unpriced.map(
                (ticker) => ({ ticker, reason: "couldn't be priced" })
            );
            lastSummaryHoldings = tickerSlices;
            lastSummaryExcluded = tickerExcluded;
            lastSummaryReady = true;
            lastSummaryFailed = false;
            if (allocViewIndex === 0) {
                paintAllocation(tickerSlices, tickerExcluded);
            }
            if (nothingPriced) {
                // While masked, keep the existing mask — don't overwrite with
                // error text that would break the privacy look.
                if (!masked) {
                    setPortfolioUnavailable(
                        `Couldn't price: ${data.unpriced.join(", ")}`
                    );
                }
                return;
            }

            // Partial case: paint the priced totals, but say on hover which
            // tickers are missing. title="" wipes a stale tooltip from an
            // earlier cycle — the hover text must always match THIS payload.
            // While masked, skip the title to avoid leaking which tickers
            // couldn't be priced over the privacy **** mask.
            if (!masked) {
                portfolioValueEl.title = data.unpriced.length > 0
                    ? `Excludes ${data.unpriced.join(", ")} — couldn't be priced`
                    : "";
            }
            // The summary is ALWAYS CAD (the ledger toggle never touches it)
            // and the reply declares that — paint the code so a converted
            // total can't be misread as native.
            if (!masked) {
                portfolioValueEl.textContent =
                    `${formatNumber(data.total_value)} ${data.currency || "CAD"}`;
            }
            // Cache raw values so applyPortfolioPrivacy can call paintChange
            // with hideValue=true when the toggle is activated mid-cycle.
            if (!lastPortfolioPaint) lastPortfolioPaint = {};
            lastPortfolioPaint.dayValue = data.day_gain;
            lastPortfolioPaint.dayPct = data.day_gain_pct;
            lastPortfolioPaint.totalValue = data.total_gain;
            lastPortfolioPaint.totalPct = data.total_gain_pct;
            paintChange(portfolioDayChangeEl, data.day_gain, data.day_gain_pct,
                        "Today", masked);
            paintChange(portfolioTotalReturnEl, data.total_gain,
                        data.total_gain_pct, "Total", masked);
            // The strip's fourth fact: what the position(s) cost. Raw float
            // from the backend — same formatter, same CAD label as the total
            // above (the cost basis is a CAD figure: stored per-transaction
            // rates make it so). The caption's "Cost basis" wording lives in
            // index.html; only the number is painted here.
            if (!masked) {
                portfolioCostBasisEl.textContent =
                    `${formatNumber(data.cost_basis)} ${data.currency || "CAD"}`;
            }
            // Release geometry locks only when NOT masked — while masked,
            // the locks keep the layout stable around the shorter percentage-
            // only text. Unmasking calls this via applyPortfolioPrivacy.
            if (!masked) {
                clearPortfolioGeometryLocks();
            }

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
            if (epoch !== portfolioEpoch()) return;
            console.error("portfolio summary refresh failed:", err);
            setPortfolioUnavailable();
            lastSummaryFailed = true;
            if (allocViewIndex === 0) {
                if (lastSummaryReady && lastAllocPayload?.by === null) {
                    setAllocState("stale-error");
                } else {
                    updateAllocExcluded([]);
                    setAllocState("unavailable");
                }
            }
        } finally {
            // Empty the slot so the next cycle starts a fresh request.
            if (epoch === summaryFlightEpoch) summaryInflight = null;
        }
    })();
    return summaryInflight;
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

// The chart card's period return readout: one percentage for the timeframe
// the canvas is showing, reported by the shared chart factory. It uses the
// backend's time-weighted return (cash flows removed), so a deposit cannot
// appear as a gain — which is why this is separate from the hero's live
// "Today" pill. The label and value ship in index.html; this code owns
// their content. No dollar amount, so privacy masking leaves it visible.
const periodReturnLabelEl = document.getElementById("period-return-label");
const periodReturnValueEl = document.getElementById("period-return-value");

function paintPeriodReturn({ period, returnPct }) {
    const nextLabel = `${period} return`;
    if (periodReturnLabelEl) {
        if (periodReturnLabelEl.textContent !== nextLabel) {
            periodReturnLabelEl.textContent = nextLabel;
        }
    }
    if (!periodReturnValueEl) return;
    if (!Number.isFinite(returnPct)) {
        if (periodReturnValueEl.textContent !== "Return unavailable") {
            periodReturnValueEl.textContent = "Return unavailable";
        }
        periodReturnValueEl.classList.remove("pos", "neg");
        return;
    }
    const sign = returnPct >= 0 ? "+" : "";
    const nextValue = `${sign}${returnPct.toFixed(2)}%`;
    const nextClass = returnPct >= 0 ? "pos" : "neg";
    if (periodReturnValueEl.textContent !== nextValue) {
        periodReturnValueEl.textContent = nextValue;
    }
    periodReturnValueEl.classList.toggle("pos", nextClass === "pos");
    periodReturnValueEl.classList.toggle("neg", nextClass === "neg");
}

// Build once at load with empty data; every refresh swaps the arrays and
// redraws — no re-creating the Chart, no page reload. The factory wires
// the delegated .time-btn listener too, so a click re-fetches with the
// clicked button's textContent as the PERIOD_MAP key.
const comparePicker = setupComparePicker({
    inputEl: document.getElementById("compare-input"),
    resultsEl: document.getElementById("compare-results"),
    chipsEl: document.getElementById("compare-chips"),
    onChange(symbols) {
        if (portfolioChartHandle) portfolioChartHandle.reload();

        // A normalized comparison has meaning only beside the TWR index.
        const performanceButton =
            document.querySelector('[data-chart-mode="performance"]');
        if (symbols.length && performanceButton
            && !performanceButton.classList.contains("active")) {
            performanceButton.click();
        }
    },
});

const portfolioChartHandle = setupTimeframeChart({
    canvas: portfolioCanvas,
    buttonBar: chartButtonsEl,
    // The Value/Performance view toggle — the portfolio endpoint answers
    // both series, so this tray (in index.html) flips between them. The
    // stock page passes nothing here and gets a plain value chart.
    modeBar: document.querySelector(".chart-mode-selectors"),
    getBenchmarks: () => (comparePicker ? comparePicker.getSymbols() : []),
    comparisonReadout: document.getElementById("portfolio-comparison-readout"),
    comparisonPrimaryLabel: "Portfolio",
    // The chart card's period return readout — the selected timeframe's TWR.
    onPeriodSummary: paintPeriodReturn,
    // The chart plots the CAD total in every mode — label it so the
    // currency is never guessed at.
    datasetLabel: "Portfolio Value (CAD)",
    endpoint: () => `/api/portfolio/history${portfolioQuery()}`,
    getScope: () => currentPortfolioId(),
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
// refresh time and need an explicit update). The donut's palette is also
// build-time state (see paintAllocation) and needs the same refresh.
document.addEventListener("themechange", () => {
    if (portfolioChartHandle) {
        portfolioChartHandle.repaintComparisonReadout();
    }
    // Re-read BOTH pieces of donut color from the new theme: the wedge
    // palette and the card-paper border between wedges. update("none")
    // repaints instantly — a theme flip is not the moment for a 600ms
    // spin. Empty portfolio → no chart yet; the next poll builds one with
    // fresh colors anyway.
    if (allocationChart) {
        const dataset = allocationChart.data.datasets[0];
        dataset.backgroundColor = getAllocationColors();
        dataset.borderColor = donutBorderColor();
        allocationChart.update("none");
    }
});

// ---------------------------------------------------------------------------
// ALLOCATION DONUT — the sidebar's doughnut of what the portfolio is made
// OF, cycled through 6 views with arrows and dots. Touching the chart
// shows a segment tooltip but never changes views. The "By Ticker" view
// reads the summary reply's `holdings` slice; the other 5 views fetch
// /api/portfolio/allocation?by=<key>.
// Data is backend-computed; this code paints, never re-derives the math.
// ---------------------------------------------------------------------------

// The canvas from the HTML, plus the box around it (found by walking UP
// from the canvas with closest() — the donut is where the canvas is, no
// matter how the card markup shifts).
const allocationCanvas = document.getElementById("allocationChart");
const donutBoxEl = allocationCanvas
    ? allocationCanvas.closest(".donut-box") : null;

// Carousel controls — the arrow buttons and label in the card header.
const allocPrevBtn = document.getElementById("alloc-prev");
const allocNextBtn = document.getElementById("alloc-next");
const allocLabelEl = document.getElementById("alloc-label");
const allocExcludedEl = document.getElementById("alloc-excluded");
const allocDotsEl = document.getElementById("alloc-dots");
const allocPositionEl = document.getElementById("alloc-position");
const allocStatusEl = document.getElementById("alloc-status");

// The holdings/slices array the donut currently plots. The tooltip
// callbacks need each wedge's CAD value, but Chart.js hands a tooltip
// only the parsed weight — this is the bridge from weight back to the
// value it came from. Kept in module state (not chart config) so a poll
// refresh can swap it in one place.
let currentHoldings = [];

// The chart object. Built LAZILY on the first non-empty payload — an
// empty portfolio has no wedges, and building a zero-wedge chart just to
// destroy it on the next poll is waste.
let allocationChart = null;
let animateNextAllocationPaint = false;

// The last payload THIS page successfully painted, keyed by dimension
// (null = the By Ticker view). A stale-while-revalidate cycle keeps the
// donut from the PREVIOUS fetch on screen while the next one loads, and a
// failed revalidation restores this payload instead of blanking the chart.
// A payload is reusable ONLY for its own dimension — restoring a "sector"
// donut under a "country" slide would lie about the data it shows.
let lastAllocPayload = null;

// Respect the OS "reduce motion" accessibility setting: users who opted
// out of animation get none — Chart.js accepts `false` to disable its
// build animation entirely (a bare duration object would still animate).
const REDUCED_MOTION = window.matchMedia(
    "(prefers-reduced-motion: reduce)"
).matches;

// The wedge border must match the card's paper so the 2px gaps read as
// cuts between wedges, not drawn lines. CSS variables can't live inside a
// canvas — read the live computed value instead (the same technique as
// CHART_COLORS in common.js), so both themes are covered.
function donutBorderColor() {
    return getComputedStyle(document.documentElement)
        .getPropertyValue("--card-bg").trim();
}

// Show the donut only when it has slices. A cached chart can stay visible
// with a status note during a refresh or after a failed refresh. The box
// ships `hidden` in the template and the global [hidden] rule hides it.
// Toggle the ATTRIBUTE, not
// style.display, so a reveal also lets CSS layout measure the canvas.
function setAllocState(state) {
    if (!allocStatusEl || !donutBoxEl) return;
    const messages = {
        loading: "Loading allocation\u2026",
        empty: "No open long holdings to allocate yet.",
        excluded: "No holdings could be priced or classified for this view.",
        unavailable: "Allocation unavailable right now.",
        stale: "Refreshing allocation with the latest prices\u2026",
        "stale-error": "Could not refresh allocation. Showing the last available result.",
        ready: "",
    };
    const message = messages[state] ?? "";
    donutBoxEl.hidden = !allocationChart ||
        !(state === "ready" || state === "stale" || state === "stale-error");
    allocStatusEl.textContent = message;
    allocStatusEl.hidden = !message;
    if (state === "ready") {
        // The box just became visible, so the canvas's real size changed —
        // Chart.js needs to re-measure AFTER the browser lays the new box
        // out, or the donut renders at the tiny size it had while hidden.
        requestAnimationFrame(() => {
            if (allocationChart) allocationChart.resize();
        });
    }
}

// ---------------------------------------------------------------------------
// ALLOCATION CAROUSEL — 6 views, cycled with arrows and dots.
//
// The "By Ticker" view reads from the summary poll's `holdings` slice
// (already fetched every 60s — zero extra network). The other 5 views
// fetch /api/portfolio/allocation?by=<key>, which reuses the quote
// cache warmed by the summary poll (steady-state: nearly free).
//
// Each dimension's payload is cached in a JS-side dict so arrow flips
// are instant. The 60s poll refreshes ONLY the active dimension. A
// flip paints the cached payload immediately and refetches in the
// background if stale.
// ---------------------------------------------------------------------------

// Source of truth for carousel order + labels. The null key signals
// "use the summary's holdings slice" — no allocation fetch needed.
// Order matches the template's arrow flow: prev at index 0 wraps
// to the last, next at the last index wraps to the first.
const ALLOCATION_VIEWS = [
    { key: null,     label: "By Ticker" },
    { key: "sector", label: "By Sector" },
    { key: "country", label: "By Country" },
    { key: "type",   label: "By Type" },
    { key: "cap",    label: "By Cap Bucket" },
    { key: "currency", label: "By Currency" },
];

// Carousel state. persisted in localStorage so the last-viewed
// dimension survives a reload. The index is bounds-checked below — a
// STALE saved index (e.g. a view cut from a previous build, or an
// index that now points at a different dimension after a reorder)
// simply opens whatever is at that position now; harmless, and we
// never change the persistence format over it.
let allocViewIndex = 0;
try {
    const saved = localStorage.getItem("allocationDimension");
    if (saved !== null) {
        const idx = parseInt(saved, 10);
        if (idx >= 0 && idx < ALLOCATION_VIEWS.length) allocViewIndex = idx;
    }
} catch { /* localStorage unavailable — use default */ }

// Per-dimension payload cache: {by_key: {data, fetchedAt}}.
// The ticker view (key null) uses the summary poll directly — no
// cache entry needed.
const allocCache = {};
// Per-dimension in-flight promise: {by_key: Promise}. One fetch per
// dimension at a time — the 60s poll, the boot restore, and an arrow flip
// can all fire within a single slow round-trip, and they all share that
// one request. The slot empties (identity-checked) when the fetch settles.
const allocInFlight = {};
const ALLOC_CACHE_TTL = REFRESH_MS; // refresh alongside the poll

function allocCacheStale(key) {
    const entry = allocCache[key];
    return !entry || (Date.now() - entry.fetchedAt) > ALLOC_CACHE_TTL;
}

function buildAllocDots() {
    if (!allocDotsEl) return;
    allocDotsEl.replaceChildren();
    ALLOCATION_VIEWS.forEach((view, index) => {
        const dot = document.createElement("button");
        dot.type = "button";
        dot.className = "alloc-dot";
        dot.setAttribute(
            "aria-label",
            `Show ${view.label} allocation, slide ${index + 1} of ${ALLOCATION_VIEWS.length}`
        );
        dot.addEventListener("click", () => switchAllocView(index));
        allocDotsEl.append(dot);
    });
}

function syncAllocCarousel() {
    const view = ALLOCATION_VIEWS[allocViewIndex];
    if (allocLabelEl) allocLabelEl.textContent = view.label;
    if (allocPositionEl) {
        allocPositionEl.textContent =
            `${allocViewIndex + 1} / ${ALLOCATION_VIEWS.length}`;
    }
    if (!allocDotsEl) return;
    allocDotsEl.querySelectorAll(".alloc-dot").forEach((dot, index) => {
        const active = index === allocViewIndex;
        dot.classList.toggle("active", active);
        dot.toggleAttribute("aria-current", active);
        if (active) dot.setAttribute("aria-current", "page");
    });
}

function isActiveAllocView(by) {
    return ALLOCATION_VIEWS[allocViewIndex].key === by;
}

function runAllocationCrossfade() {
    const shouldAnimate = animateNextAllocationPaint && !REDUCED_MOTION;
    animateNextAllocationPaint = false;
    if (!shouldAnimate || !donutBoxEl) return;
    donutBoxEl.classList.remove("alloc-crossfade");
    // Restart the one-shot animation even when navigation happens quickly.
    void donutBoxEl.offsetWidth;
    donutBoxEl.classList.add("alloc-crossfade");
}

// Navigate the carousel to a new index (with wrap-around) and fetch
// the new view's data.
function switchAllocView(newIndex) {
    // Wrap: prev on 0 → last; next on last → 0.
    const nextIndex =
        (newIndex + ALLOCATION_VIEWS.length) % ALLOCATION_VIEWS.length;
    animateNextAllocationPaint = nextIndex !== allocViewIndex;
    allocViewIndex = nextIndex;
    syncAllocCarousel();

    // Persist the choice.
    try { localStorage.setItem("allocationDimension", allocViewIndex); }
    catch { /* private browsing, ignore */ }

    const view = ALLOCATION_VIEWS[allocViewIndex];

    // Fetch the data for this view (ticker views use the summary's
    // holdings; others fetch the allocation endpoint).
    if (view.key === null) {
        // By Ticker: re-paint from the summary's holdings (already
        // in memory from the last poll). The next poll will refresh it.
        if (lastSummaryReady) {
            paintAllocation(lastSummaryHoldings, lastSummaryExcluded);
            if (lastSummaryFailed) setAllocState("stale-error");
        } else {
            updateAllocExcluded([]);
            setAllocState(lastSummaryFailed ? "unavailable" : "loading");
        }
    } else {
        fetchAllocDimension(view.key);
    }
}

// Fetch one allocation dimension, painting on arrival.
// SINGLE-FLIGHT: the 60s poll, the boot restore, and a carousel flip can
// all fire for the same dimension within one slow round-trip — the first
// caller owns the fetch; the rest join it (their paint arrives when its
// reply lands). STALE-WHILE-REVALIDATE: a request that finds a stale cache
// entry repaints that entry first (the CORRECT donut for this dimension
// stays visible while the network refreshes it) and shows a soft
// "refreshing" note instead of blanking to a skeleton; only a first-load
// paints "loading".
async function fetchAllocDimension(by) {
    if (!currentPortfolioId()) return;
    const epoch = portfolioEpoch();
    const key = `${currentPortfolioId()}|${by}`;
    const flightKey = `${key}|${epoch}`;
    // Navigation guard: never paint (or queue work) for a slide the user
    // already left — a late reply for an old view must not appear under
    // the current label.
    if (!isActiveAllocView(by)) return;

    // Paint this dimension's last-known payload NOW when we have one
    // (fresh, stale, or mid-revalidate): the flip must show ITS OWN donut
    // instantly. Without this, a flip to a dimension whose cache is stale
    // (or re-fetching) leaves the previous slide's donut on the canvas
    // under the new label until the network answers. Honest-empties carry
    // their own message via paintAllocation's states.
    if (allocCache[key]) {
        const entry = allocCache[key];
        paintAllocation(entry.data.slices, entry.data.excluded, by);
    } else {
        updateAllocExcluded([]);
        setAllocState("loading");
    }

    // Single-flight: join the request already in flight for this dimension
    // instead of starting a second one.
    if (allocInFlight[flightKey]) return allocInFlight[flightKey];

    // Fresh cache — just painted above, nothing to fetch this cycle.
    if (!allocCacheStale(key)) return;

    const flight = (async () => {
        // Stale or first visit: the cache TTL mirrors the 60s poll, so
        // every poll is a revalidate. A donut with real wedges shows a
        // soft "refreshing" note; an honest empty keeps its empty message
        // (the revalidate paints nothing new yet); a first load says
        // clearly that data is on the way.
        const cached = allocCache[key];
        if (cached && cached.data.slices &&
            cached.data.slices.length > 0) {
            setAllocState("stale");
        } else if (!cached) {
            setAllocState("loading");
        }

        const response = await fetch(
            `/api/portfolio/allocation${portfolioQuery()}&by=${encodeURIComponent(by)}`
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        if (epoch !== portfolioEpoch()) return;
        // Reply landed after the user moved on: cache it, but never paint
        // it over the current slide — their next flip reads the cache.
        allocCache[key] = { data, fetchedAt: Date.now() };
        if (isActiveAllocView(by)) {
            paintAllocation(data.slices, data.excluded, by);
        }
    })().catch((err) => {
        if (epoch !== portfolioEpoch()) return;
        if (!isActiveAllocView(by)) return;
        console.error(`allocation fetch (${by}) failed:`, err);
        // The prior payload is reusable ONLY when it belongs to THIS
        // dimension — restoring a "sector" donut under a "country" slide
        // would lie about the data it shows.
        const prior = lastAllocPayload && lastAllocPayload.by === by
            ? lastAllocPayload
            : null;
        if (prior && prior.slices && prior.slices.length > 0) {
            // A revalidation failed — this dimension's donut is still
            // painted: drop the "refreshing" note and keep the chart.
            // Failures are transient; blanking a valid donut over a blip
            // is not a kindness, and the next poll retries anyway.
            setAllocState("ready");
        } else if (prior) {
            // This dimension's last honest result was an empty portfolio —
            // keep its message instead of pretending it broke.
            setAllocState(allocationResultState(prior.slices, prior.excluded));
        } else {
            // Nothing for THIS dimension was ever painted. Hide whatever
            // other dimension's data is on the canvas and say so plainly.
            setAllocState("unavailable");
        }
    }).finally(() => {
        if (allocInFlight[flightKey] === flight) delete allocInFlight[flightKey];
    });

    allocInFlight[flightKey] = flight;
    return flight;
}

// Arrow button handlers.
if (allocPrevBtn) {
    allocPrevBtn.addEventListener("click", () => {
        switchAllocView(allocViewIndex - 1);
    });
}
if (allocNextBtn) {
    allocNextBtn.addEventListener("click", () => {
        switchAllocView(allocViewIndex + 1);
    });
}

// Touch cleanup on the donut box: Chart.js has no touchend event in its
// default list, so clear a tap's hover after the last finger lifts. The
// browser remains free to scroll; dragging the donut never changes views.
if (donutBoxEl) {
    function clearDonutTouchHover() {
        if (!allocationChart) return;
        allocationChart._touchHoverDormant = true;
        allocationChart._ghostEventsUntil = Date.now() + GHOST_EVENT_WINDOW_MS;
        if (allocationChart.tooltip) {
            allocationChart.tooltip.setActiveElements([], { x: 0, y: 0 });
        }
        allocationChart.setActiveElements([]);
        allocationChart.draw();
    }

    donutBoxEl.addEventListener("touchstart", (e) => {
        if (allocationChart) allocationChart._touchHoverDormant = false;
    }, { passive: true });
    donutBoxEl.addEventListener("touchend", (e) => {
        if (e.touches.length === 0) clearDonutTouchHover();
    }, { passive: true });
    donutBoxEl.addEventListener("touchcancel", () => {
        clearDonutTouchHover();
    }, { passive: true });
}

// The summary's holdings slice — the By Ticker view's data source.
// Set on every summary poll, consumed by switchAllocView when the
// ticker view is active.
let lastSummaryHoldings = [];
let lastSummaryExcluded = [];
let lastSummaryReady = false;
let lastSummaryFailed = false;

function initializeAllocCarousel() {
    buildAllocDots();
    syncAllocCarousel();
    const view = ALLOCATION_VIEWS[allocViewIndex];
    if (view.key !== null) fetchAllocDimension(view.key);
}

portfolioReady.then(initializeAllocCarousel);

// ---------------------------------------------------------------------------
// PAINT ALLOCATION — build or update the donut from one payload.
// Accepts an array of {label, value, weight} objects (the "slices"
// shape) plus an optional excluded list. The By Ticker view maps
// holdings (which have a `ticker` key) to this shape; the allocation
// endpoint's slices already match.
// ---------------------------------------------------------------------------

function allocationResultState(slices, excluded) {
    if (slices && slices.length > 0) return "ready";
    return excluded && excluded.length > 0 ? "excluded" : "empty";
}

function updateAllocExcluded(excluded) {
    if (!allocExcludedEl) return;
    if (excluded && excluded.length > 0) {
        const parts = excluded.map(
            (e) => `${e.ticker}\u2009\u2014\u2009${e.reason}`
        );
        allocExcludedEl.textContent = `Excludes ${parts.join("; ")}`;
        allocExcludedEl.style.display = "";
    } else {
        allocExcludedEl.textContent = "";
        allocExcludedEl.style.display = "none";
    }
}

function paintAllocation(slices, excluded, by = null) {
    // No canvas (defensive — index.html ships one) or no Chart.js (the
    // CDN script failed to load): degrade to the unavailable state rather
    // than throwing — same spirit as the chart handle's null guard.
    if (!allocationCanvas || typeof Chart === "undefined") {
        setAllocState("unavailable");
        return;
    }
    // Remember which dimension THIS donut shows and the payload it was
    // built from: a failed revalidation for the SAME dimension can safely
    // keep it (lastAllocPayload.by === by), but no other dimension may be
    // restored into its place.
    lastAllocPayload = { by: by ?? null, slices, excluded };
    currentHoldings = slices;
    runAllocationCrossfade();

    updateAllocExcluded(excluded);

    if (!slices || slices.length === 0) {
        // Empty reply: no wedges. DESTROY any chart a previous cycle
        // built — a stale donut beside an "empty" message would
        // contradict the data it claims to show.
        if (allocationChart) {
            allocationChart.destroy();
            allocationChart = null;
        }
        setAllocState(allocationResultState(slices, excluded));
        return;
    }
    const labels = slices.map((s) => s.key ?? s.ticker);
    const weights = slices.map((s) => s.weight);

    if (allocationChart) {
        // POLL REFRESH: swap the arrays in place and redraw WITHOUT
        // animation (update("none")) — a 600ms spin every 60s reads as
        // glitch, not life. Mutating chart.data + update() beats tearing
        // the Chart down and rebuilding it: no canvas flash, no dropped
        // hover state, no re-reading the theme on every cycle.
        allocationChart.data.labels = labels;
        allocationChart.data.datasets[0].data = weights;
        allocationChart.update("none");
        setAllocState("ready");
        return;
    }

    // FIRST BUILD: colors are read at build time (getAllocationColors is
    // common.js's theme-aware palette — a theme flip rebuilds the donut
    // through the themechange listener above, so no stale light-mode
    // wedge survives into dark mode).
    allocationChart = new Chart(allocationCanvas, {
        type: "doughnut",
        // Chart.js has no touchend event in its default event list. Block a
        // delayed touchstart or compatibility mouse event after our native
        // finger-lift cleanup, or the tooltip would reappear on an old slice.
        plugins: [{
            id: "donutTouchHoverEnd",
            beforeEvent(chart, args) {
                const type = args.event.native?.type;
                if (type === "touchstart" || type === "touchmove") {
                    if (chart._touchHoverDormant) return false;
                } else if (Date.now() < (chart._ghostEventsUntil || 0)) {
                    return false;
                }
            },
        }],
        data: {
            labels: labels,
            datasets: [{
                // The plotted values are the WEIGHTS (they sum to 1, so
                // the wedges close the circle by construction).
                data: weights,
                backgroundColor: getAllocationColors(),
                borderWidth: 2,
                borderColor: donutBorderColor(),
                hoverOffset: 4,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            // ~600ms on first build — enough to feel alive, short enough
            // not to delay the reading. Disabled entirely under
            // prefers-reduced-motion.
            animation: REDUCED_MOTION ? false : { duration: 600 },
            plugins: {
                legend: {
                    // Bottom: the sidebar is narrow — a right-side legend
                    // would squeeze the donut to a sliver.
                    position: "bottom",
                    labels: {
                        pointStyle: "circle",
                        usePointStyle: true,
                        boxWidth: 8,
                        boxHeight: 8,
                    },
                },
                tooltip: {
                    callbacks: {
                        label(item) {
                            const slice = currentHoldings[item.dataIndex];
                            // A view change can briefly leave Chart.js with a
                            // hover index from the old, longer slice list.
                            if (!slice) return "";
                            // PRIVACY: the CAD value masks while the eye
                            // is active, but the weight stays visible —
                            // the same rule as the ledger's privacy
                            // (percentages stay). Read LIVE at hover
                            // time, so toggling flips the very next
                            // tooltip with no rebuild.
                            const amount = portfolioMasked()
                                ? "****"
                                : `${formatNumber(slice.value)} CAD`;
                            // item.label comes from chart.data.labels NOW.
                            // Do not close over the first build's labels: the
                            // carousel replaces them in place on every view.
                            return `${item.label}: ${amount} ` +
                                `(${(item.parsed * 100).toFixed(1)}%)`;
                        },
                    },
                },
            },
            // Donut, not pie: the hollow center reads lighter on the
            // narrow sidebar than a full disc.
            cutout: "62%",
        },
    });
    // Chart.js may have measured the initially hidden box at zero size.
    // Reveal after construction, then resize on the next layout frame.
    setAllocState("ready");
}

// ---------------------------------------------------------------------------
// TABS — watchlist sidebar tab switcher (Watchlist / Volume Leaders).
// Clicking a tab shows its content and hides the other. The "+ Add" button
// is only visible on the Watchlist tab (volume leaders aren't user-managed).
// ---------------------------------------------------------------------------

const tabBar = document.querySelector(".tab-bar");
const tabBtns = document.querySelectorAll(".tab-btn");
const watchlistTab = document.querySelector("#watchlist-tab");
const volumeLeadersTab = document.querySelector("#volume-leaders-tab");
// addTickerBtn (grabbed with the watchlist section above) is reused here —
// the "+ Add" button belongs to the Watchlist tab, so the leaders tab hides it.

tabBar.addEventListener("click", (e) => {
    const btn = e.target.closest(".tab-btn");
    if (!btn) return;

    // Toggle active class on buttons
    tabBtns.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");

    // Show/hide the corresponding tab content
    const tab = btn.dataset.tab;
    if (tab === "watchlist") {
        watchlistTab.style.display = "";
        volumeLeadersTab.style.display = "none";
        addTickerBtn.style.display = "";
    } else {
        watchlistTab.style.display = "none";
        volumeLeadersTab.style.display = "";
        addTickerBtn.style.display = "none";
    }
});

// ---------------------------------------------------------------------------
// VOLUME LEADERS — top 10 highest-volume stocks today, top 1 per sector.
// Same refresh rhythm as the watchlist (60s polling). Rows use the same
// watchlist-item structure so the same CSS applies.
// ---------------------------------------------------------------------------

const volumeLeadersEl = document.querySelector("#volume-leaders");

// Volume is a share COUNT (whole units) — formatNumber's fixed two decimals
// would render "100,000,000.00 shares". Integer grouping instead, the same
// dedicated Intl formatter pattern stock.js uses for its stats grid.
const integerFormat = new Intl.NumberFormat("en-US",
    { maximumFractionDigits: 0 });

function setVolumeLeadersMessage(text) {
    volumeLeadersEl.textContent = "";
    const row = document.createElement("li");
    row.className = "empty-state";
    row.textContent = text;
    volumeLeadersEl.append(row);
}

function buildVolumeLeaderRow(leader) {
    const row = document.createElement("li");
    row.className = "watchlist-item";
    row.dataset.symbol = leader.symbol;

    // Left side: ticker and name (same structure as watchlist rows)
    const left = document.createElement("div");
    const tickerEl = document.createElement("strong");
    tickerEl.textContent = leader.symbol;
    const nameEl = document.createElement("div");
    nameEl.className = "sub-text";
    nameEl.textContent = leader.name || "";
    left.append(tickerEl, nameEl);

    // Right side: price and change (same structure as watchlist rows)
    const right = document.createElement("div");
    right.className = "text-right";
    const priceEl = document.createElement("div");
    priceEl.className = "watch-price";
    priceEl.textContent = `${formatPrice(leader.price)}`;
    const changeEl = document.createElement("span");
    changeEl.className = "change-tag";
    const positive = leader.change_pct >= 0;
    const sign = positive ? "+" : "";
    changeEl.textContent = `${sign}${leader.change_pct.toFixed(2)}%`;
    changeEl.classList.toggle("pos", positive);
    changeEl.classList.toggle("neg", !positive);
    right.append(priceEl, changeEl);

    // Volume badge — shows the volume in a readable format
    const volEl = document.createElement("div");
    volEl.className = "sub-text";
    volEl.textContent = `${integerFormat.format(leader.volume)} shares`;

    row.append(left, right, volEl);
    return row;
}

async function refreshVolumeLeaders() {
    try {
        const response = await fetch("/api/market/volume-leaders");
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        const leaders = data.leaders;

        volumeLeadersEl.textContent = "";
        if (leaders.length === 0) {
            setVolumeLeadersMessage("No volume data available");
            return;
        }

        for (const leader of leaders) {
            volumeLeadersEl.append(buildVolumeLeaderRow(leader));
        }
    } catch (err) {
        console.error("volume leaders refresh failed:", err);
        setVolumeLeadersMessage("Volume leaders unavailable");
    }
}

// Navigate: a volume leader ROW is a link to the detail page, same as the
// watchlist rows. Delegated listener on the <ul> — rows are rebuilt every
// cycle, so delegation is the only sane approach.
volumeLeadersEl.addEventListener("click", (event) => {
    const row = event.target.closest(".watchlist-item");
    if (!row) return;
    window.location.href = `/stock/${encodeURIComponent(row.dataset.symbol)}`;
});

// ---------------------------------------------------------------------------
// BOOT — the script's entry point. This block runs top-to-bottom the moment
// the browser reaches it, and only now are all the functions above defined.
// ---------------------------------------------------------------------------

// 1. Wire the market tabs (click + keyboard) and fetch every quote-driven
//    section immediately — no waiting for the first interval. (The ledger
//    lives on /ledger with its own timer.) The market overview ships EMPTY
//    from the template — the CSS :empty shimmer stands in until real data
//    lands — and preloadMarketOverview starts every category request
//    together. The watchlist starts empty and refreshWatchlist paints it.
setupMarketTabs();
preloadMarketOverview();
refreshWatchlist();
refreshVolumeLeaders();
portfolioReady.then(() => refreshPortfolioSummary());
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
const chartReady = portfolioReady.then(() => refreshPortfolioChart());

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

// 2. Poll. ONE timer drives all quote-driven cycles: the ACTIVE market
//    category, watchlist, volume leaders, portfolio summary, and the
//    active allocation dimension all change at the same rate.
//    setupAutoRefresh owns the interval and wires visibility/online events
//    so the page refreshes instantly when the user returns (see common.js).
//    Only the selected market category is polled; other tabs retain the
//    values fetched at startup or on their last visit.
setupAutoRefresh(() => {
    refreshMarketOverview(activeMarketCategory, { force: true });
    refreshWatchlist();
    refreshVolumeLeaders();
    refreshPortfolioSummary();
    // Refresh the active allocation dimension (skip the ticker view —
    // the summary poll already handles it above). The allocation
    // endpoint reuses the quote cache, so this is nearly free.
    const view = ALLOCATION_VIEWS[allocViewIndex];
    if (view.key !== null) {
        fetchAllocDimension(view.key);
    }
});

document.addEventListener("portfoliochange", () => {
    // A masked header keeps a snapshot for instant unmask. It belongs to the
    // old portfolio and must never be restored under the new name.
    lastPortfolioPaint = null;
    portfolioDayChangeEl.textContent = "";
    portfolioTotalReturnEl.textContent = "";
    if (!portfolioMasked()) portfolioCostBasisEl.textContent = "";
    lastSummaryHoldings = [];
    lastSummaryExcluded = [];
    lastSummaryReady = false;
    lastSummaryFailed = false;
    lastAllocPayload = null;
    setPortfolioUnavailable("Loading portfolio...");
    updateAllocExcluded([]);
    setAllocState("loading");
    if (portfolioChartHandle) portfolioChartHandle.invalidate();
    refreshPortfolioSummary();
    refreshPortfolioChart();
    const view = ALLOCATION_VIEWS[allocViewIndex];
    if (view.key !== null) fetchAllocDimension(view.key);
});
