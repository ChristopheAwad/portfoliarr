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
const positionCard = document.getElementById("position-card");
const positionNoteEl = document.getElementById("position-note");

// Once the symbol is known to be unquotable (404), later poll cycles have
// nothing to ask for — this flag silences them (the dashboard's sections
// poll forever because their data is a LIST that can change; here the
// symbol itself is fixed).
let symbolKnown = true;

// Which chart period is active — drives the change pill ownership: the
// chart's onPeriodData callback paints the pill for all periods; the quote
// poll only overwrites it on "1D" (the dollar-based daily move). Starts at
// "5D" to match the default button.
let activePeriod = "5D";

// Paint the stock header's change pill. The period leads so the timeframe
// reads first, then the dollar move and its percentage:
//   "5D: +$4.27 (+2.34%)"   "5D: -$4.27 (-2.34%)"   "5D: +$4.27"
// The amount uses the ABSOLUTE value behind an explicit sign, so a down
// move is "-$4.27", never the confusing "$-4.27". A null pct (zero first
// bar — no base to divide by) drops the parenthetical and keeps the dollar
// move. The display is native, so a plain "$" is correct for both USD and
// CAD; the big price above carries the currency code.
function paintPeriodChange(el, period, value, pct) {
    const sign = value >= 0 ? "+" : "-";
    const amount = `${sign}$${formatNumber(Math.abs(value))}`;
    el.textContent = pct === null
        ? `${period}: ${amount}`
        : `${period}: ${amount} (${sign}${Math.abs(pct).toFixed(2)}%)`;
    // Green for a gain, red for a loss — one call each, same as paintChange.
    el.classList.toggle("pos", value >= 0);
    el.classList.toggle("neg", value < 0);
}

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

        // The day-change pill: "Today: +$2.30 (+1.02%)". The quote's change
        // / change_pct are exactly the pill's inputs — the same stock-only
        // painter every other period uses, so the shape never changes.
        // Only paint on 1D: the chart's onPeriodData callback owns the
        // pill for every other period, showing the period return instead.
        // On 1D, the quote poll overwrites the callback's chart-derived
        // value with the more accurate dollar-based daily move.
        if (activePeriod === "1D") {
            paintPeriodChange(stockDayChangeEl, "Today",
                              quote.change, quote.change_pct);
        }

        // Feed the previous close into the chart handle so the 1D view
        // can draw a horizontal reference line at yesterday's close.
        if (stockChartHandle) stockChartHandle.updatePrevClose(quote.previous_close);
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
// POSITION — the signed-in person's holding in this security (native
// money, no FX). Facts come from the ledger replay; live numbers come
// from the quote. Hidden when not held; facts-only when the quote
// failed (live cells gap-fill to "—").
// ---------------------------------------------------------------------------

function setPos(id, text) {
    document.getElementById(id).textContent = text == null ? "—" : text;
}

function paintSignedMoney(el, value, currency, pct) {
    const sign = value >= 0 ? "+" : "-";
    const money = `${sign}${formatPrice(Math.abs(value))} ${currency}`;
    // The % keeps its OWN sign: for a short, the dollar move and the
    // market move point opposite ways (short −5, price up +2% →
    // day_gain −$10 but change_pct +4%), so borrowing the money sign
    // would misstate the market direction.
    const pctSign = pct >= 0 ? "+" : "-";
    el.textContent = pct == null || pct === undefined
        ? money
        : `${money} (${pctSign}${Math.abs(pct).toFixed(2)}%)`;
    el.classList.toggle("pos", value >= 0);
    el.classList.toggle("neg", value < 0);
}

async function refreshPosition() {
    if (!positionCard) return;
    try {
        await portfolioReady;
    } catch (err) {
        positionCard.hidden = true;
        return;
    }
    let pid;
    try {
        pid = currentPortfolioId();
    } catch (err) {
        positionCard.hidden = true;
        return;
    }
    if (!pid) {
        positionCard.hidden = true;
        return;
    }
    try {
        const response = await fetch(
            `/api/portfolio/position?symbol=${encodeURIComponent(symbol)}` +
            `&portfolio_id=${pid}`);
        if (!response.ok) {
            positionCard.hidden = true;
            return;
        }
        const pos = await response.json();
        if (!pos.held) {
            positionCard.hidden = true;
            return;
        }
        setPos("pos-qty", formatNumber(pos.qty, 4));
        setPos("pos-avg", pos.avg_cost == null
            ? null : `${formatPrice(pos.avg_cost)} ${pos.currency}`);
        setPos("pos-cost", pos.cost_basis == null
            ? null : `${formatPrice(pos.cost_basis)} ${pos.currency}`);
        if (pos.price === undefined || pos.value === undefined) {
            setPos("pos-value", null);
            setPos("pos-gain", null);
            setPos("pos-day", null);
            document.getElementById("pos-gain").classList.remove("pos", "neg");
            document.getElementById("pos-day").classList.remove("pos", "neg");
        } else {
            setPos("pos-value",
                `${formatPrice(pos.value)} ${pos.currency}`);
            const gainEl = document.getElementById("pos-gain");
            if (pos.gain == null || pos.gain === undefined) {
                setPos("pos-gain", null);
                gainEl.classList.remove("pos", "neg");
            } else {
                paintSignedMoney(gainEl, pos.gain, pos.currency, pos.gain_pct);
            }
            const dayEl = document.getElementById("pos-day");
            if (pos.day_gain == null || pos.day_gain === undefined) {
                setPos("pos-day", null);
                dayEl.classList.remove("pos", "neg");
            } else {
                paintSignedMoney(dayEl, pos.day_gain, pos.currency,
                    pos.day_gain_pct);
            }
        }
        positionNoteEl.textContent = "Native currency.";
        positionCard.hidden = false;
    } catch (err) {
        console.error("stock position refresh failed:", err);
        positionCard.hidden = true;
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

    // The fundamentals expansion (same already-fetched profile, many more
    // keys read out of it). Formatter per kind of number:
    //   ratios (forward P/E, P/B, PEG, rec. mean) → plain
    //   the percent fields arrive as backend ×100 numbers → "%" appended
    //   target low/high/median → price-shaped
    //   cash/debt/EBITDA/shares → compact ("107.72B")
    //   headcount → integer ("150,000")
    //   country/type → raw text
    setStat("stat-forward-pe",
        stats.forward_pe === null ? null : formatNumber(stats.forward_pe));
    setStat("stat-price-to-book",
        stats.price_to_book === null ? null : formatNumber(stats.price_to_book));
    setStat("stat-peg",
        stats.peg_ratio === null ? null : formatNumber(stats.peg_ratio));
    // The percent fields: null stays null (setStat renders "—"); otherwise
    // the backend already ×100'd the fraction, so this only appends "%".
    // debt_to_equity is in this list because the backend passes Yahoo's
    // already-scaled figure through — no ×100 here either.
    setStat("stat-payout-ratio",
        stats.payout_ratio === null ? null : `${formatNumber(stats.payout_ratio)}%`);
    setStat("stat-gross-margin",
        stats.gross_margin === null ? null : `${formatNumber(stats.gross_margin)}%`);
    setStat("stat-operating-margin",
        stats.operating_margin === null
            ? null : `${formatNumber(stats.operating_margin)}%`);
    setStat("stat-profit-margin",
        stats.profit_margin === null ? null : `${formatNumber(stats.profit_margin)}%`);
    setStat("stat-return-on-equity",
        stats.return_on_equity === null
            ? null : `${formatNumber(stats.return_on_equity)}%`);
    setStat("stat-revenue-growth",
        stats.revenue_growth === null ? null : `${formatNumber(stats.revenue_growth)}%`);
    setStat("stat-earnings-growth",
        stats.earnings_growth === null ? null : `${formatNumber(stats.earnings_growth)}%`);
    setStat("stat-debt-to-equity",
        stats.debt_to_equity === null
            ? null : `${formatNumber(stats.debt_to_equity)}%`);
    setStat("stat-target-low",
        stats.target_low === null ? null : formatPrice(stats.target_low));
    setStat("stat-target-high",
        stats.target_high === null ? null : formatPrice(stats.target_high));
    setStat("stat-target-median",
        stats.target_median === null ? null : formatPrice(stats.target_median));
    setStat("stat-num-analysts",
        stats.num_analyst_opinions === null
            ? null : integerFormat.format(stats.num_analyst_opinions));
    setStat("stat-recommendation-mean",
        stats.recommendation_mean === null
            ? null : formatNumber(stats.recommendation_mean));
    setStat("stat-total-cash",
        stats.total_cash === null ? null : compactFormat.format(stats.total_cash));
    setStat("stat-total-debt",
        stats.total_debt === null ? null : compactFormat.format(stats.total_debt));
    setStat("stat-free-cash-flow",
        stats.free_cashflow === null
            ? null : compactFormat.format(stats.free_cashflow));
    setStat("stat-ebitda",
        stats.ebitda === null ? null : compactFormat.format(stats.ebitda));
    setStat("stat-shares-out",
        stats.shares_outstanding === null
            ? null : compactFormat.format(stats.shares_outstanding));
    setStat("stat-float-shares",
        stats.float_shares === null
            ? null : compactFormat.format(stats.float_shares));
    setStat("stat-employees",
        stats.employees === null ? null : integerFormat.format(stats.employees));
    setStat("stat-country", stats.country === null ? null : stats.country);
    setStat("stat-quote-type",
        stats.quote_type === null ? null : stats.quote_type);

    // Website is a link, so setStat's text-only rule is not enough.
    if (stats.website == null) {
        setStat("stat-website", null);
        document.getElementById("stat-website").removeAttribute("href");
    } else {
        const link = document.getElementById("stat-website");
        const site = stats.website || "";
        link.textContent = site;
        if (site.startsWith("http://") || site.startsWith("https://")) {
            link.href = site;
        } else {
            link.removeAttribute("href");
        }
    }

    // About: the free-text company description. Prose, so the shared
    // setStat null rule renders "—" when Yahoo has no summary.
    setStat("stat-about", stats.business_summary);
}

// The grid's cell ids — used by the failure path to degrade the whole
// grid at once ("…" means waiting; "—" means this load couldn't price).
// Ordered to mirror the template's cluster order.
const STAT_IDS = ["stat-about",
                  "stat-open", "stat-day-high", "stat-day-low",
                  "stat-prev-close", "stat-volume",
                  "stat-avg-volume",
                  "stat-week52-range", "stat-50d-avg", "stat-200d-avg",
                  "stat-market-cap", "stat-pe", "stat-forward-pe",
                  "stat-peg", "stat-price-to-book", "stat-eps", "stat-beta",
                  "stat-dividend-yield", "stat-payout-ratio",
                  "stat-target-price", "stat-target-low", "stat-target-high",
                  "stat-target-median", "stat-rating", "stat-num-analysts",
                  "stat-recommendation-mean",
                  "stat-gross-margin", "stat-operating-margin",
                  "stat-profit-margin", "stat-return-on-equity",
                  "stat-revenue-growth", "stat-earnings-growth",
                  "stat-total-cash", "stat-total-debt", "stat-debt-to-equity",
                  "stat-free-cash-flow", "stat-ebitda", "stat-shares-out",
                  "stat-float-shares",
                  "stat-sector", "stat-industry", "stat-country",
                  "stat-quote-type", "stat-employees", "stat-website"];

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
// FINANCIALS — the annual income-statement table, fetched ONCE per page
// load (yearly figures from Yahoo's heaviest statement endpoint — same
// never-polled rhythm as the stats grid above).
// ---------------------------------------------------------------------------

// The eight body-row ids in income-statement order, each paired with its
// reply key: the first seven are MONEY (compact "107.72B"), the last is
// per-share (two-decimal, like EPS in the stats grid). Native currency
// throughout — the currency lives in the header's price, so repeating it
// per cell would just be noise.
const FIN_ROW_IDS = ["fin-row-total-revenue", "fin-row-cost-of-revenue",
    "fin-row-gross-profit", "fin-row-operating-expense",
    "fin-row-operating-income", "fin-row-total-expenses",
    "fin-row-net-income", "fin-row-diluted-eps"];
const FIN_ROW_KEYS = ["total_revenue", "cost_of_revenue", "gross_profit",
    "operating_expense", "operating_income", "total_expenses",
    "net_income", "diluted_eps"];

function paintFinancials(fin) {
    const card = document.getElementById("financials-card");
    const years = fin.years || [];
    // No years = no statement (an ETF, crypto, or index — normal, not
    // an error): stay hidden rather than show a table of "—".
    if (!years.length) {
        card.hidden = true;
        return;
    }
    // Clear any previous cells first so a retry never double-appends.
    const headRow = document.getElementById("fin-head-row");
    headRow.querySelectorAll("th:not(:first-child)").forEach((cell) => cell.remove());
    for (const year of years) {
        const th = document.createElement("th");
        th.scope = "col";
        th.textContent = year;
        headRow.append(th);
    }
    FIN_ROW_IDS.forEach((rowId, index) => {
        const row = document.getElementById(rowId);
        row.querySelectorAll("td").forEach((cell) => cell.remove());
        const key = FIN_ROW_KEYS[index];
        const values = (fin.rows && fin.rows[key]) || [];
        const isMoney = key !== "diluted_eps";
        years.forEach((_, yearIndex) => {
            const td = document.createElement("td");
            const value = values[yearIndex];
            td.textContent = value == null
                ? "—"
                : (isMoney ? compactFormat.format(value) : formatPrice(value));
            row.append(td);
        });
    });
    card.hidden = false;
    try {
        paintFinChart(fin);
    } catch (err) {
        // The table above is already painted and correct — a dead chart
        // (blocked CDN, hidden canvas) must never hide it.
        console.error("stock financials chart failed:", err);
    }
}

// The live financials chart instance (at most one). Destroyed before
// every rebuild so a retry never stacks two charts on one canvas.
let finChart = null;
// The last painted reply, kept so a theme flip can rebuild the chart
// with fresh palette colors without another network call.
let lastFin = null;

// Grouped bars above the table: one group per fiscal year, three bars —
// Total Revenue, Net Income (the profit), and Total Expenses drawn
// NEGATIVE (costs point down, profits point up, so the year reads as
// money in vs money out). The table below keeps all eight rows; the
// chart is the short story, not the full statement. The look follows
// the app's printed-ledger voice: slim ink bars with rounded outer
// ends, hairline grid, one ruled zero line, quiet captions. A null cell
// stays null (Chart.js skips it: a gap, never a fake zero bar). A chart
// failure must never kill the table, so callers wrap this in try/catch.
function paintFinChart(fin) {
    lastFin = fin;
    const canvas = document.getElementById("fin-chart");
    const years = fin.years || [];
    if (!years.length) return;
    const style = getComputedStyle(document.documentElement);
    const ink = (name) => style.getPropertyValue(name).trim();
    // Theme-aware inks, read live so a theme flip repaints correctly:
    // revenue wears the first allocation color, profit the app's
    // up-green, expenses the app's down-red.
    const revenueInk = getAllocationColors()[0];
    const profitInk = ink("--green-pos");
    const expenseInk = ink("--red-neg");
    // Quiet chart furniture, all theme tokens: hairline grid, a ruled
    // zero line (the ledger's hairline, so money-in vs money-out reads
    // at a glance), secondary-ink captions in the app's own typeface.
    const gridInk = ink("--border-subtle");
    const zeroInk = ink("--border-strong");
    const captionInk = ink("--text-secondary");
    const appFont = getComputedStyle(document.body).fontFamily;
    const series = [
        { key: "total_revenue", label: "Total Revenue", color: revenueInk },
        { key: "net_income", label: "Net Income", color: profitInk },
        // Expenses ship positive in the reply (the table prints them
        // that way); only the CHART negates them so the bars hang below
        // zero. Null stays null — never a fake zero bar.
        { key: "total_expenses", label: "Total Expenses",
          color: expenseInk, negative: true },
    ];
    const datasets = series.map((s) => {
        const values = (fin.rows && fin.rows[s.key]) || [];
        return {
            label: s.label,
            // Pad short arrays with null so every dataset aligns to years.
            data: years.map((_, i) => {
                const value = values[i];
                if (value == null) return null;
                return s.negative ? -value : value;
            }),
            // Soft ink fill with a solid 1px edge: engraved, not flat.
            backgroundColor: hexToRgba(s.color, 0.78),
            borderColor: s.color,
            borderWidth: 1.5,
            // Round the OUTER end only: 'start' is the bar's base (zero
            // for positives, zero for negatives too), so the rounded end
            // is always the tip — revenue rounds up, expenses round down.
            borderRadius: 6,
            borderSkipped: "start",
        };
    });
    // Drop rows that are entirely null (e.g. a ticker with no expense
    // line) so the legend never offers an empty series.
    const live = datasets.filter((ds) => ds.data.some((v) => v != null));
    if (!live.length) return;
    if (finChart) {
        finChart.destroy();
        finChart = null;
    }
    finChart = new Chart(canvas.getContext("2d"), {
        type: "bar",
        data: { labels: years, datasets: live },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            // Slim groups with air between them: three thin bars read as
            // figures in columns, not bricks in a wall.
            datasets: { bar: { categoryPercentage: 0.55, barPercentage: 0.72,
                               maxBarThickness: 30 } },
            layout: { padding: { top: 4 } },
            plugins: {
                legend: {
                    position: "bottom",
                    labels: {
                        // Small rounded keys, not default squares.
                        usePointStyle: true,
                        pointStyle: "rectRounded",
                        boxWidth: 8,
                        boxHeight: 8,
                        padding: 16,
                        color: captionInk,
                        font: { family: appFont },
                    },
                },
                tooltip: {
                    padding: 12,
                    cornerRadius: 10,
                    boxPadding: 6,
                    titleFont: { family: appFont },
                    bodyFont: { family: appFont },
                    callbacks: {
                        // Compact money in the hover box ("104B",
                        // "-96B") — raw floats would collide.
                        label: (ctx) =>
                            ` ${ctx.dataset.label}: ` +
                            `${compactFormat.format(ctx.parsed.y)}`,
                    },
                },
            },
            scales: {
                y: {
                    // Seven ticks at most: enough steps to read values off
                    // the axis without crowding the 220px box.
                    ticks: {
                        maxTicksLimit: 7,
                        color: captionInk,
                        font: { family: appFont },
                        // Compact money ("107.7B") — full figures would
                        // collide on a 220px axis.
                        callback: (v) => compactFormat.format(v),
                    },
                    grid: {
                        // The ruled zero line: money-in above, money-out
                        // below, split by the ledger's hairline.
                        color: (ctx) =>
                            (ctx.tick && ctx.tick.value === 0)
                                ? zeroInk : gridInk,
                    },
                    border: { display: false },
                },
                x: {
                    ticks: { color: captionInk, font: { family: appFont } },
                    grid: { display: false },
                    border: { display: false },
                },
            },
        },
    });
}

async function refreshStockFinancials() {
    const card = document.getElementById("financials-card");
    try {
        const response =
            await fetch(`/api/stock/${encodeURIComponent(symbol)}/financials`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        paintFinancials(await response.json());
    } catch (err) {
        console.error("stock financials refresh failed:", err);
        // Having no statement is normal for ETFs/crypto/indices — keep
        // the card hidden instead of showing a failure state.
        card.hidden = true;
    }
}

// ---------------------------------------------------------------------------
// EVENTS — earnings dates + dividend history, fetched ONCE per page load
// (event dates reset at most daily — same never-polled rhythm as the
// stats grid above).
// ---------------------------------------------------------------------------

// One date cell: an ISO string paints as-is (no reformatting — the
// reply is already YYYY-MM-DD), a null paints "—".
function setEventDate(id, value) {
    document.getElementById(id).textContent = value == null ? "—" : value;
}

function paintEvents(events) {
    const card = document.getElementById("events-card");
    const hasDate = events.earnings_date != null
        || events.ex_dividend_date != null
        || events.dividend_date != null;
    const recent = events.recent || [];
    // Nothing usable (the route 404s this case, but a stale cache or a
    // proxy should never paint an empty card): stay hidden.
    if (!hasDate && !recent.length && events.ttm_total == null) {
        card.hidden = true;
        return;
    }
    setEventDate("event-earnings", events.earnings_date);
    setEventDate("event-ex-div", events.ex_dividend_date);
    setEventDate("event-div-date", events.dividend_date);
    // TTM is native money without a currency suffix — the header price
    // owns that, same rule as the stats grid's money cells.
    setEventDate("event-ttm", events.ttm_total == null
        ? null : formatPrice(events.ttm_total));
    // Recent dividends: rebuild every row from JSON (the thead ships
    // static, the tbody ships empty — no static amount can ever
    // masquerade as a live fact). An empty recent hides the table but
    // keeps the dates grid above.
    const tbody = document.getElementById("events-tbody");
    tbody.querySelectorAll("tr").forEach((row) => row.remove());
    for (const entry of recent) {
        const tr = document.createElement("tr");
        const dateCell = document.createElement("td");
        dateCell.textContent = entry.date;
        const amountCell = document.createElement("td");
        amountCell.textContent = entry.amount == null
            ? "—" : formatPrice(entry.amount);
        tr.append(dateCell, amountCell);
        tbody.append(tr);
    }
    document.getElementById("events-table").style.display =
        recent.length ? "" : "none";
    // The body stays COLLAPSED on every paint (dates are a glance-able
    // extra, not the page's story): the card appears, the toggle keeps
    // its ▸ face, and the user opens it. A repaint must never flip a
    // body the user already opened — except this paint just rebuilt
    // every row, so collapsed is the honest state.
    document.getElementById("events-body").hidden = true;
    const toggle = document.getElementById("events-toggle");
    toggle.setAttribute("aria-expanded", "false");
    card.hidden = false;
}

// The Events header toggle: collapsed (▸, body hidden) ⇄ expanded
// (▾, body shown). Wired once at load — paintEvents above never
// touches the listener, only the collapsed state.
document.getElementById("events-toggle").addEventListener("click", () => {
    const body = document.getElementById("events-body");
    const toggle = document.getElementById("events-toggle");
    body.hidden = !body.hidden;
    toggle.setAttribute("aria-expanded", String(!body.hidden));
});

async function refreshStockEvents() {
    const card = document.getElementById("events-card");
    try {
        const response =
            await fetch(`/api/stock/${encodeURIComponent(symbol)}/events`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        paintEvents(await response.json());
    } catch (err) {
        console.error("stock events refresh failed:", err);
        // Having no calendar is normal for crypto/ETFs/indices — keep
        // the card hidden instead of showing a failure state.
        card.hidden = true;
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

// Log Transaction: the log form lives on the LEDGER page — ONE form, ONE
// submit handler, the same reuse rule the ledger's edit mode follows. The
// ?ticker= param is what ledger.js reads to prefill it, and the #tx-form
// anchor scrolls the browser straight to the form.
logTxBtn.addEventListener("click", () => {
    window.location.href = `/ledger?ticker=${encodeURIComponent(symbol)}#tx-form`;
});

// ---------------------------------------------------------------------------
// CHART — the security's close price over time. The shared factory builds
// it; this page's only input is WHERE the data comes from.
// ---------------------------------------------------------------------------

const comparePicker = setupComparePicker({
    inputEl: document.getElementById("compare-input"),
    resultsEl: document.getElementById("compare-results"),
    chipsEl: document.getElementById("compare-chips"),
    primarySymbol: symbol,
    onChange() {
        if (stockChartHandle) stockChartHandle.reload();
    },
});

const stockChartHandle = setupTimeframeChart({
    canvas: document.getElementById("stockChart"),
    buttonBar: document.querySelector(".chart-timeframe-selectors"),
    datasetLabel: symbol,
    endpoint: `/api/stock/${encodeURIComponent(symbol)}/history`,
    getBenchmarks: () => (comparePicker ? comparePicker.getSymbols() : []),
    comparisonReadout: document.getElementById("stock-comparison-readout"),
    defaultPeriod: "5D", // must match the `active` button in stock.html
    // When the chart loads new period data, compute the period return
    // and paint the change pill. Both units show in the stock pill's
    // "period: +$amount (+pct%)" shape, so every timeframe reads the
    // same way. A zero first bar has no percentage base — degrade to
    // the amount alone rather than dividing by zero. The quote poll
    // will overwrite the pill on 1D with the more accurate
    // dollar-based "Today" figure shortly after.
    onPeriodData({ firstValue, lastValue, period }) {
        activePeriod = period;
        const change = lastValue - firstValue;
        const pct = firstValue !== 0 ? (change / firstValue) * 100 : null;
        paintPeriodChange(stockDayChangeEl, period, change, pct);
    },
});

// When the theme toggles, repaint the chart so grid/line colors pick up
// the new CSS variable values.
document.addEventListener("themechange", () => {
    if (stockChartHandle) stockChartHandle.repaintComparisonReadout();
    // Rebuild the financials bars with the new palette (the reply is
    // cached, so this costs no network). A blocked CDN must not throw
    // out of a theme flip.
    if (lastFin && !document.getElementById("financials-card").hidden) {
        try {
            paintFinChart(lastFin);
        } catch (err) {
            console.error("stock financials chart failed:", err);
        }
    }
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
refreshPosition();
refreshStockStats();
refreshStockFinancials();
refreshStockEvents();
if (stockChartHandle) stockChartHandle.refresh();
// setupAutoRefresh owns the interval and wires visibility/online events
// so the page refreshes instantly when the user returns (see common.js).
// The position card rides the same heartbeat (facts + quote move together).
setupAutoRefresh(async () => {
    await refreshStockQuote();
    await refreshPosition();
});
document.addEventListener("portfoliochange", refreshPosition);
