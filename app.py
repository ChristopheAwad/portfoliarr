# time gives us perf_counter(), a monotonic high-resolution clock — used
# by the request-timing hook in the LOGGING section below.
import math
import sqlite3
import time

# ThreadPoolExecutor runs one callable across MANY OS threads and
# collects their results — the portfolio-history route uses it to fetch
# every ticker's Yahoo history at the same time instead of one after
# another (I/O waits overlap; CPU work wouldn't).
from concurrent.futures import ThreadPoolExecutor

# Import the Flask class (used to create the app), render_template (serves
# Jinja2 HTML templates to the browser), jsonify (converts Python
# dicts/lists into a proper JSON HTTP response, including the
# Content-Type: application/json header), request (gives access to the
# incoming HTTP request's data — we need its JSON body for the add route),
# and g (per-request scratch storage — the timing hook stashes its start
# time there).
from flask import Flask, g, jsonify, render_template, request

# HTTPException is the base class of Flask/werkzeug's OWN errors (404,
# 405...). The top-level error handler below must let these pass through
# untouched — it exists to catch genuine bugs, not Flask's normal replies.
from werkzeug.exceptions import HTTPException

# Import our data layers. This file is the "route layer": it decides WHICH
# symbols the page needs and HOW answers map to HTTP; market_data.py handles
# the HOW of fetching from Yahoo, db.py the HOW of persisting the watchlist
# and the transaction ledger.
from market_data import (
    get_quote, get_name, get_stats, get_profile, get_history,
    search_tickers,
    get_fx_rate, get_fx_rate_on, PERIOD_MAP, get_volume_leaders
)
import db

# datetime's date/datetime classes know how to both VALIDATE and NORMALIZE
# dates: date.fromisoformat("2026-08-31") raises ValueError on garbage, and
# its .isoformat() hands back the same canonical "YYYY-MM-DD" text we store.
# datetime.strptime is the importer's counterpart: it reads the paste's
# "16 Mar 2026" format into a real datetime object, raising ValueError on
# anything that isn't one.
from datetime import date, datetime

# Create the Flask application instance named "app". This object holds the
# routes, config, and is what runs our web server.
app = Flask(__name__)

# Make sure the database schema exists before the first request arrives.
# init() is idempotent (CREATE TABLE IF NOT EXISTS), so running it at import
# time is safe on every startup.
db.init()

# The symbols shown in the dashboard's indices bar. This is a product
# decision (which markets the bar tracks), so it lives in the route layer,
# not in the generic data module. Adding a chip = adding a string here AND
# a matching data-symbol attribute on the chip in templates/index.html.
INDEX_SYMBOLS = ["^GSPC", "^IXIC", "^GSPTSE", "BTC-USD"]

# Product decision: which allocation dimensions the donut carousel offers.
# Each key maps to a human-readable label (frontend reads, never re-derives)
# and the profile field it groups by. "ticker" is deliberately excluded —
# that view is served by the summary's holdings slice; two sources for one
# view would drift. By Industry and By Exchange were CUT from the product
# (Industry restates By Ticker with noisier labels at small-portfolio scale;
# Exchange shows raw Yahoo codes — cryptic and near-duplicates
# Currency/Country). Keys must match the frontend's ALLOCATION_VIEWS array
# (locked by test_allocation_ui.py::test_js_dimension_keys_match_backend_whitelist).
ALLOCATION_DIMENSIONS = {
    "sector":   {"label": "By Sector",   "field": "sector"},
    "country":  {"label": "By Country",  "field": "country"},
    "type":     {"label": "By Type",     "field": "quote_type"},
    "cap":      {"label": "By Cap Bucket", "field": "market_cap"},
    "currency": {"label": "By Currency", "field": None},  # special: from quote
}


# ---------------------------------------------------------------------------
# LOGGING — three tiers, console-only. Flask gives every app a pre-wired
# logger: `app.logger` writes to stderr, and with debug=True (our dev
# server) every level shows up with no configuration at all.
#
# WHY ALL LOGGING LIVES HERE, IN THE ROUTE LAYER: market_data.py and db.py
# are pure layers whose contract is "raise and let the route decide" — they
# know nothing about Flask, and app.logger IS Flask. Exceptions get caught
# in exactly one place (here), so they get logged in exactly one place.
#
# The level vocabulary used throughout this file:
#   debug   — too chatty to matter by default (timing lines, missing names)
#   info    — normal client behavior worth recording (a 404 a typo caused)
#   warning — degraded but recovered (one dead symbol; the rest still served)
#   error   — a real bug (unhandled exception, below)
# ---------------------------------------------------------------------------

# TIER 2 — the safety net. Any exception NO route caught lands here: we log
# the full traceback (exc_info=True) and answer JSON, matching the API's
# error convention instead of Flask's default HTML error page.
#
# Two subtleties worth knowing:
#  1. HTTP errors (404, 405...) are Exceptions too! Without the isinstance
#     guard, a typo'd URL would reach this handler and be mislabelled
#     "internal server error". We pass them through untouched — Flask
#     already has correct responses for those.
#  2. With debug=True, Werkzeug's interactive debugger re-raises the
#     exception BEFORE this handler runs — in dev you see the debugger
#     page instead. This handler is the PRODUCTION path; the tests
#     exercise it by pinning PROPAGATE_EXCEPTIONS = False.
@app.errorhandler(Exception)
def handle_unexpected_error(error):
    if isinstance(error, HTTPException):
        # Flask's own errors: the correct response already exists.
        return error
    app.logger.error(
        "unhandled error on %s %s", request.method, request.path,
        exc_info=True,
    )
    return jsonify({"error": "internal server error"}), 500


# TIER 3 — one timing line per request, at debug level. Werkzeug's dev
# server already prints each request's method/path/status; the one thing
# its line lacks is DURATION, so that's all we add.
#
# g is Flask's per-request scratch storage: every concurrent request gets
# its own `g`, so stashing the start time here needs no locks or shared
# dicts — requests can never see each other's values.
@app.before_request
def start_request_timer():
    # perf_counter() over time.time(): it is MONOTONIC (immune to the
    # system clock jumping around for NTP sync) and high-resolution —
    # the right tool for measuring durations.
    g.request_started_at = time.perf_counter()


@app.after_request
def log_request_duration(response):
    duration_ms = (time.perf_counter() - g.request_started_at) * 1000
    app.logger.debug(
        "%s %s -> %s (%.1f ms)",
        request.method, request.path, response.status_code, duration_ms,
    )
    # An after_request hook MUST return the response (modified or not) —
    # forgetting this breaks every route at once.
    return response


# The @app.route decorator registers this function as the handler for the
# root URL "/" (e.g. http://localhost:5000/).
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/preferences")
def preferences_page():
    """Render the preferences page. No server-side state — all settings
    are stored in the browser's localStorage by preferences.js."""
    return render_template("preferences.html")


@app.route("/ledger")
def ledger_page():
    """Render the ledger page — the transaction ledger (table, log/edit
    form, import panel, privacy eye) plus the Closed sales table. All
    three used to live on the dashboard; the ledger is a records/history
    surface, not a live-glance surface, so it moved here and the
    dashboard kept the live view. Rendering only: every number comes
    from /api/transactions and /api/portfolio/realized, fetched and
    painted by static/js/ledger.js (the same no-server-render rule as
    the dashboard)."""
    return render_template("ledger.html")


# JSON endpoint that powers the live indices bar. The browser's JavaScript
# fetches this URL. Returns a JSON *list* of quote dicts.
@app.route("/api/indices")
def index_quotes():
    # Per-symbol resilience: each chip is fetched independently, so one
    # dead symbol cannot blank the whole bar. Failures are skipped.
    # Fetch all index quotes in parallel — each is an independent
    # yfinance call, so threading cuts wall time from N×sequential to
    # ~1×slowest. Same pattern as portfolio_history's history fetch.
    def fetch_index_quote(symbol):
        try:
            return symbol, get_quote(symbol)
        except Exception:
            # Boundary rule: catch WIDE at the edge of the system (yfinance
            # can fail in many ways) and degrade gracefully, per symbol.
            # TIER 1: on screen the chip just shows "—" with no reason —
            # this log line IS the reason. exc_info=True attaches the full
            # traceback, which is exactly what a WIDE catch needs: the
            # actual cause is the thing we don't know.
            app.logger.warning(
                "index quote failed for %s — chip shows \"—\"", symbol,
                exc_info=True,
            )
            return symbol, None

    quotes_map = {}
    with ThreadPoolExecutor(
        max_workers=min(len(INDEX_SYMBOLS), 8)
    ) as pool:
        for symbol, quote in pool.map(fetch_index_quote, INDEX_SYMBOLS):
            if quote is not None:
                quotes_map[symbol] = quote

    # Only when EVERY symbol fails is the whole endpoint considered sick:
    # 503 = "Service Unavailable — it's me, not you, try again later."
    if len(quotes_map) == 0:
        # TIER 1: this is the endpoint's loudest cry for help — every
        # symbol failing at once usually means Yahoo is down or the
        # network is gone, not four unlucky symbols.
        app.logger.warning(
            "all %d index symbols failed — serving 503", len(INDEX_SYMBOLS)
        )
        return jsonify({"error": "quote service unavailable"}), 503

    # Successes only in original order: failed symbols are absent.
    # The frontend infers which chips to mark unavailable ("—").
    quotes = [quotes_map[s] for s in INDEX_SYMBOLS if s in quotes_map]
    return jsonify(quotes)


# ---------------------------------------------------------------------------
# PORTFOLIO VALUE CHART — the dashboard's line chart, computed from the
# transaction ledger + historical prices.
#
# This is the chart that started life as hardcoded placeholder data in
# main.js (a learning exercise). Now that the ledger exists, we can plot
# REAL numbers: for every point in the selected timeframe, the portfolio
# is worth the sum of each held quantity times that ticker's close price
# that day.
#
# The timeframe buttons (1D..MAX) each map to a Yahoo period/interval via
# PERIOD_MAP in market_data.py — this route validates the client's key
# against the same dict, keeping the label-to-fetch mapping in one place.
# ---------------------------------------------------------------------------

def _time_weighted_return(values, flows):
    """Chain per-bar returns into a growth-of-$100 TWR index.

    THE two portfolio questions, one line apart:
      * VALUE line (money-weighted cost basis) — "all the money I ever put
        in vs. what it's worth now". A deposit grows it; a deposit after a
        good run DILUTES the cost-basis % it headlines.
      * THIS index (time-weighted) — "how well did the picks do?" Cash
        flows are removed so deposits can neither fake nor dilute a gain.

    The method is the fund industry's "daily valuation" chaining: each
    bar's return is measured against the PREVIOUS bar's value, then the
    bars multiply together (compounding), the way real money grows.

        r_i    = (V_i − F_i − V_{i−1}) / V_{i−1}     (flows at bar close)
        index  = 100 × Π(1 + r_i);  twrr_pct = chained − 1, as a %.

    `flows` is the net cash CONTRIBUTION absorbed at each bar (buys minus
    sells) — portfoliarr has no separate cash account, so transactions ARE
    the cash movements. Bar 0's flow is DELIBERATELY ignored: it was
    already inside V_0 (the route trims the axis to the first logged
    investment, so the first buy IS bar 0), and removing it again would
    double-report the first bar's return.

    Honest degradation — never a confident-looking fake:
      * Fewer than two bars → (None, None): nothing to compare.
      * A bar whose BASE (the previous value) is ≤ 0 ends the chain:
        that is the ledger's oversell fold gone net-short, a fully
        withdrawn portfolio, or nothing priced. The index is TRUNCATED to
        the bars that had a real, positive base — performance is reported
        while the portfolio was worth measuring.
      * A bar whose value-minus-flow is ≤ 0 (the position turned short
        THAT bar) also ends it — 1 + r would flip the index's sign and
        report a gain as a loss.
      * If not one pair survives → (None, None), never a 0/0 NaN.
    """
    if len(values) < 2:
        return None, None
    index = [100.0]
    for i in range(1, len(values)):
        prev = values[i - 1]
        post_flow_value = values[i] - flows[i]
        if prev <= 0 or post_flow_value <= 0:
            break
        r = (post_flow_value - prev) / prev
        index.append(index[-1] * (1 + r))
    if len(index) < 2:
        return None, None
    return index, (index[-1] / 100.0 - 1.0) * 100.0


def _parse_compare_symbols(raw):
    """Normalize an ordered, comma-separated comparison list."""
    symbols = []
    for part in raw.split(","):
        symbol = part.strip().upper()
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    if len(symbols) > 3:
        raise ValueError("at most 3 benchmark symbols")
    return symbols


def _rebase_series(labels, closes):
    """Forward-fill closes onto labels and rebase the first close to 100."""
    values = []
    base = None
    last = None
    for label in labels:
        close = closes.get(label)
        if close is not None and math.isfinite(close) and close > 0:
            last = close
        if last is None:
            values.append(None)
            continue
        if base is None:
            base = last
        values.append(100.0 * last / base)
    return values


@app.route("/api/portfolio/history")
def portfolio_history():
    """Return the portfolio's value over time as
    {labels, values, costs, index_values, twrr_pct}.

    Query param `period` is a PERIOD_MAP key ("5D", "1M"...); defaults
    to "5D" (the chart's default view, matching the 5D button's `active`
    class in index.html). Anything else gets a 400.

    The first three keys: labels/values (the CAD value line) and costs
    (the netted cost basis) — see the section comment in this module.
    The last two power the TWR "Performance" chart view:
      index_values — a growth-of-$100 index (100 at bar 0), chained from
        per-bar returns with cash flows removed (see
        _time_weighted_return). May be SHORTER than labels (the chain
        truncates at a non-positive base) or null (nothing computable).
      twrr_pct     — the time-weighted % over the SAME span the index
        covers (= index end as a %). null when the index is null.

Algorithm: walk every trading day in the range forward, keeping a
    running "net quantity held" per ticker (buys add, sells subtract),
    and at each day multiply that quantity by the ticker's close price
    that day. Sum across tickers = portfolio value that day. The daily
    axis STARTS at the earliest logged transaction: Yahoo's "max" period
    reaches back to each ticker's IPO (an index to 1973...), and the flat
    zero before your first buy is pre-history — not your portfolio — so
    those labels are dropped. Before a ticker's first buy its quantity
    is 0, so it contributes nothing until you own it. A day where a held
    ticker printed no bar (a holiday on its market, Yahoo's unfinalized
    current-day bar) prices the position at its last KNOWN close —
    carried forward, never at zero, because a holding doesn't evaporate
    between closes.
    """
    # Validate the timeframe key BEFORE doing any work. get_history()
    # indexes PERIOD_MAP directly, so a bad key would KeyError mid-loop;
    # catching it here (and returning the valid options) is friendlier.
    period = request.args.get("period", "5D").upper()
    if period not in PERIOD_MAP:
        options = ", ".join(sorted(PERIOD_MAP))
        return jsonify({"error": f"period must be one of: {options}"}), 400

    try:
        benchmark_symbols = _parse_compare_symbols(
            request.args.get("benchmark", "")
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # The ledger's default sort is newest-first; we need the opposite to
    # walk history forward, so sort ascending here.
    transactions = sorted(
        db.get_transactions(),
        key=lambda tx: (tx["transaction_date"], tx["id"]),
    )

    # An empty ledger is a normal state, not an error — the frontend
    # shows "No transactions yet" and leaves the chart blank.
    if not transactions:
        return jsonify({"labels": [], "values": [], "costs": [],
                        "index_values": None, "twrr_pct": None})

    # Fetch each ticker's price history once — but IN PARALLEL. The
    # serial version paid "sum of every Yahoo call" before the chart
    # could draw (six tickers ≈ six seconds); a thread pool pays only
    # the SLOWEST single call, because fetching is network WAIT, not CPU
    # work — while a thread sits blocked on Yahoo's response it holds no
    # CPU, so eight threads overlap eight waits almost for free.
    #
    # UNIQUE symbols first (a dict-as-set would work, but a list keeps
    # the ledgers' first-appearance order): the old loop's `if symbol in
    # histories: continue` dedupe moves here, so two AAPL transactions
    # still cost ONE fetch.
    unique_symbols = []
    seen = set()
    for tx in transactions:
        if tx["ticker"] not in seen:
            seen.add(tx["ticker"])
            unique_symbols.append(tx["ticker"])

    def fetch_history(symbol):
        """One worker's job: fetch one ticker, or report it dead.

        Per-ticker resilience, the same rule as the indices bar: a
        dead/delisted ticker is skipped, its contribution is 0 for the
        whole period — never a 503 for the whole chart. The try/except
        lives INSIDE the worker (not around the pool) so one ticker's
        failure degrades only that ticker; returning a (symbol, {})
        pair instead of raising keeps the pool.map walk below uniform.
        Logging from a worker thread is safe — the logging module is
        thread-safe by design, and app.logger needs no request context.
        """
        try:
            return symbol, get_history(symbol, period)
        except Exception:
            # TIER 1: without a record, a dead ticker is indistinguishable
            # from "the user never traded it" — both contribute 0 and
            # flatten the line. The log separates the two.
            app.logger.warning(
                "history fetch failed for %s — contributes 0 to the chart",
                symbol,
                exc_info=True,
            )
            return symbol, {}  # can't be priced; treat as 0

    histories = {}
    with ThreadPoolExecutor(
        max_workers=min(len(unique_symbols), 8)
    ) as pool:
        # pool.map yields results in INPUT order (not completion order),
        # so `histories` ends up keyed in the same deterministic order
        # the serial loop produced — nothing downstream can tell the
        # difference except the clock.
        for symbol, history in pool.map(fetch_history, unique_symbols):
            histories[symbol] = history

    # Keep comparisons separate from the portfolio histories. Adding a
    # benchmark must not add labels and therefore change the portfolio line.
    benchmark_histories = {}
    benchmark_errors = {}
    missing_benchmarks = [
        symbol for symbol in benchmark_symbols if symbol not in histories
    ]

    def fetch_benchmark_history(symbol):
        try:
            return symbol, get_history(symbol, period)
        except Exception:
            app.logger.warning(
                "benchmark history failed for %s — comparison omitted",
                symbol,
                exc_info=True,
            )
            return symbol, None

    if missing_benchmarks:
        with ThreadPoolExecutor(
            max_workers=min(len(missing_benchmarks), 8)
        ) as pool:
            for symbol, history in pool.map(
                fetch_benchmark_history, missing_benchmarks
            ):
                if history is None:
                    benchmark_errors[symbol] = (
                        f"no history available for {symbol}"
                    )
                else:
                    benchmark_histories[symbol] = history
    for symbol in benchmark_symbols:
        if symbol in histories:
            benchmark_histories[symbol] = histories[symbol]

    # DISPLAY CURRENCY — the chart is ALWAYS CAD (the dashboard's ledger
    # toggle never touches it: this line IS the portfolio total). Each
    # ticker's currency comes from the LEDGER FACTS (stored at insert
    # time) — no quotes needed here, this route deliberately prices from
    # historical closes alone.
    currency_by_symbol = {}
    for tx in transactions:
        currency_by_symbol.setdefault(tx["ticker"], tx["currency"])

    # ONE live USDCAD rate per request, fetched only when a held ticker
    # actually trades in USD (a CAD-only portfolio makes no FX call). The
    # rate applies FLAT to every point — history is context, not a sell
    # price, so a per-point historical rate was deliberately skipped
    # (documented in project-brief.md). If the rate is unavailable, USD
    # tickers contribute 0: no honest CAD number, no fake 1:1 rate.
    usd_tickers = sorted(
        symbol for symbol, currency in currency_by_symbol.items()
        if currency == "USD"
    )
    live_rate = None
    if usd_tickers:
        try:
            live_rate = get_fx_rate("USD", "CAD")
        except Exception:
            app.logger.warning(
                "live USDCAD rate unavailable — USD tickers (%s) "
                "contribute 0 to the chart",
                ", ".join(usd_tickers),
                exc_info=True,
            )

    # The x-axis = the union of every ticker's trading days, ascending.
    # Build a set first (O(1) membership), then sort once.
    all_labels = set()
    for history in histories.values():
        all_labels.update(history)
    labels = sorted(all_labels)
    if not labels:
        return jsonify({"labels": [], "values": [], "costs": [],
                        "index_values": None, "twrr_pct": None})

    # Intraday (1D) labels are times ("09:30"), not dates ("2026-08-31") —
    # see get_history. So "which label applies which transaction" differs:
    #   Daily bars: a transaction dated that DAY applies at that day's bar.
    #   Intraday bars: the WHOLE current position — holdings carried in
    #     from past days plus today's trades — applies at today's FIRST
    #     bar. A date-only ledger can't know the exact minute of any
    #     trade, so pricing the walked-in position at the open is the
    #     honest, simple choice. (A portfolio bought last week is still
    #     held today — pricing only TODAY's transactions painted a flat
    #     zero line all day, which was a bug, not a statement.)
    # Detect the case by PERIOD_MAP's explicit "intraday" flag (same dict
    # that drove the fetch) — NO interval string-sniffing. This used to
    # test `interval == "5m"`, which worked only while 1D was the sole
    # intraday row; 5D's 30-minute bars span multiple days, so they keep
    # the DAILY branch on purpose: their labels are "YYYY-MM-DD HH:MM",
    # which still sorts correctly against "YYYY-MM-DD" transaction dates
    # (a buy dated 2026-09-03 applies at 2026-09-03 09:30, that day's
    # first bar — lexicographic compare is date compare here).
    # Grab today's date once (same local-day rule the frontend's date
    # input uses, so a "today" trade prices into today's intraday chart).
    is_intraday = PERIOD_MAP[period]["intraday"]
    label_date_today = date.today().isoformat()

    # START THE DAILY AXIS AT THE FIRST LOGGED INVESTMENT — not at the far
    # edge of the fetch. Yahoo's "max" period reaches back to each
    # ticker's IPO (an index bar to 1973...), and before the first buy
    # the portfolio is genuinely worth 0 — plotting that pre-history
    # stretched the MAX chart into decades of flat nothing before the
    # real story begins. Daily labels are ISO "YYYY-MM-DD" strings, so
    # lexicographic comparison IS date comparison, and the transaction
    # list is sorted ascending — its first element carries the earliest
    # date. Intraday labels are clock times and the 1D window is a single
    # day: nothing to trim, but a first buy dated in the FUTURE still
    # means there is nothing to price today (same "empty chart, 200"
    # shape as the empty ledger above).
    first_tx_date = transactions[0]["transaction_date"]
    if is_intraday:
        if first_tx_date > label_date_today:
            return jsonify({"labels": [], "values": [], "costs": [],
                            "index_values": None, "twrr_pct": None})
    else:
        labels = [label for label in labels if label >= first_tx_date]
        if not labels:
            # Every fetched bar predates the first logged investment —
            # the live case being a future-dated transaction vs. the
            # period's fixed window. Nothing plottable, not an error.
            return jsonify({"labels": [], "values": [], "costs": [],
                            "index_values": None, "twrr_pct": None})

    # Applying transactions is date-driven, and a transaction's date may
    # NOT be a trading-day label (it was a weekend/holiday — e.g. the
    # user logs a "Saturday" buy). So we use a POINTER into the
    # sorted-by-date transaction list: at each label we apply every
    # transaction whose date is on-or-before it that we haven't applied
    # yet. A Saturday buy therefore lands on the NEXT trading day's bar,
    # which is the honest approximation available to us.
    #
    # Walk each label forward, maintaining quantity per ticker. This is
    # the heart of the chart: buying shares must push the line up from
    # that point on; selling must pull it down. We only add/sell, never
    # average cost — that (more nuanced) math is a later feature.
    #
    # Alongside quantity we fold a COST accumulator — the chart's hover
    # shows what was PAID at each point (netted cost basis), not just
    # what it's worth. The rule mirrors /api/portfolio/summary (app.py):
    # a buy adds what was paid, a sell subtracts what was recouped, and
    # the per-transaction rate is the one true divergence from the value
    # side by design:
    #   VALUE side  → the FLAT LIVE rate (a potential sell today).
    #   COST side   → each transaction's STORED fx_rate (a frozen fact,
    #                 captured at its own date; USD rows with a NULL rate
    #                 — pre-feature rows — fall back to the live rate, 0
    #                 when even that is unavailable, never a fake 1:1).
    #   Dead/delisted tickers: their VALUE freezes at the last close or
    #   contributes 0 (above), but their COST stays a ledger fact — money
    #   genuinely paid is real regardless of pricing. The gap the tooltip
    #   shows is therefore the honest, blended gain-to-date.
    # The cost side needs no network — it is all stored facts, so it
    # rides this existing walk for free.
    def tx_cad_cost(tx):
        """This transaction's CAD cost contribution (negative for a sell
        = money recouped). CAD rows carry rate 1.0; unsupported
        currencies contribute 0, the same exclusion the value side
        applies, so the line never mints a currency that doesn't exist."""
        if tx["currency"] == "CAD":
            rate = 1.0
        elif tx["currency"] == "USD":
            rate = tx["fx_rate"] if tx["fx_rate"] is not None else live_rate
            if rate is None:
                return 0.0   # unconvertible — contributes 0 (see above)
        else:
            return 0.0       # unsupported currency — contributes 0
        sign = 1 if tx["transaction_type"] == "BUY" else -1
        return sign * tx["price"] * tx["qty"] * rate

    # THE TWR FLOW — the walk's third accumulator. The cost side answers
    # "what did I pay"; the flow side removes the CASH that moved in/out,
    # turning the value line into a PERFORMANCE line (see
    # _time_weighted_return). A BUY injects (positive flow), a SELL
    # withdraws (negative) — there is no separate cash account, so
    # transactions ARE the cash movements.
    #
    # THE MIRROR RULE: a transaction's flow is removed ONLY at a bar where
    # its symbol's value is actually measured. A dead ticker (get_history
    # raised → empty dict) contributes 0 to values, so removing its buy
    # would "return" money that never arrived — that would fake a LOSS.
    # Same for a USD row with no live rate, or an unsupported currency.
    #
    # The mirror is PER-BAR, not per-symbol (roadmap #14). A ticker's
    # first bar inside the window can land AFTER its transaction's
    # absorption label (a Yahoo data gap, or a MAX window whose history
    # starts later than a logged buy). On those gap bars the ticker still
    # contributes 0: removing its flow anyway would fake a one-bar loss
    # (and, when the flow is large, truncate the whole index). So each
    # symbol's flows wait in `pending_flows` and flush at the FIRST label
    # where that symbol has a measured price — the exact bar its value
    # enters the series. A symbol that never prices in the window keeps
    # its flows pending forever, so they are never removed (no value, no
    # flow). The set below gates CURRENCY only; the pending/flush walk
    # gates timing.
    flow_eligible_symbols = {
        symbol for symbol, currency in currency_by_symbol.items()
        if currency == "CAD"
        or (currency == "USD" and live_rate is not None)
    }

    def tx_flow(tx):
        """This transaction's cash contribution to TWR (BUY positive,
        SELL negative), in the series' OWN units — the flat live rate
        for USD, 1.0 for CAD. DELIBERATELY not the stored fx_rate: a
        flow must be measured in the same units as the value it's
        removed from, or a USD buy would leave a phantom FX gain on its
        own bar. (The COST side above keeps the stored rate — that's a
        frozen fact about the past; this is a removal amount in today's
        units, and the two must match or the books don't close.)"""
        if tx["ticker"] not in flow_eligible_symbols:
            return 0.0   # mirror rule — no value in the series, no flow
        if tx["currency"] == "USD":
            # The flowable gate already proves live_rate exists for a
            # USD-CLASSIFIED ticker — but a first-seen-CAD symbol can
            # still carry a stray USD row (classification is per first
            # tx, app-created data never mixes). Degrade to 0 like the
            # cost side above rather than multiply by None.
            rate = live_rate
            if rate is None:
                return 0.0   # unconvertible — contributes no flow
        else:
            rate = 1.0
        sign = 1 if tx["transaction_type"] == "BUY" else -1
        return sign * tx["price"] * tx["qty"] * rate

    net_qty = {}
    net_cost = {}  # symbol → netted CAD cost, folded with net_qty below
    last_closes = {}  # symbol → its most recent known close (forward-fill)
    values = []
    costs = []
    flows_by_label = {}  # label → net CAD cash contribution absorbed there
    pending_flows = {}   # symbol → flows absorbed BEFORE it first prices
    tx_index = 0        # next un-applied daily transaction (advances through
                        # the sorted list); unused in the intraday branch
    today_applied = False  # intraday: have today's transactions been applied?
    for label in labels:
        # Choose which transactions this label should absorb, then apply
        # them BEFORE pricing (a buy today prices at today's close).
        if is_intraday:
            # Intraday facts: see the comment above — every transaction
            # dated on-or-before today applies at the first bar of
            # today's session, once: the position carried in from past
            # days AND today's trades alike.
            if not today_applied:
                today_applied = True
                for tx in transactions:
                    if tx["transaction_date"] <= label_date_today:
                        net_qty[tx["ticker"]] = (
                            net_qty.get(tx["ticker"], 0)
                            + (tx["qty"]
                               if tx["transaction_type"] == "BUY" else -tx["qty"])
                        )
                        net_cost[tx["ticker"]] = (
                            net_cost.get(tx["ticker"], 0.0)
                            + tx_cad_cost(tx)
                        )
                        pending_flows[tx["ticker"]] = (
                            pending_flows.get(tx["ticker"], 0.0) + tx_flow(tx)
                        )
        else:
            # Daily: transactions are sorted by date, so as long as the
            # transaction's date is still on-or-before this label, it
            # belongs to the position from here on. Apply it now (once)
            # and advance.
            while tx_index < len(transactions) \
                    and transactions[tx_index]["transaction_date"] <= label:
                tx = transactions[tx_index]
                tx_index += 1
                net_qty[tx["ticker"]] = net_qty.get(tx["ticker"], 0) + (
                    tx["qty"] if tx["transaction_type"] == "BUY" else -tx["qty"]
                )
                net_cost[tx["ticker"]] = (
                    net_cost.get(tx["ticker"], 0.0) + tx_cad_cost(tx)
                )
                pending_flows[tx["ticker"]] = (
                    pending_flows.get(tx["ticker"], 0.0) + tx_flow(tx)
                )

        # Sum each ticker's held quantity × its close price at this label
        # (× the live rate for USD tickers — one CAD line). Non-USD/CAD
        # ledger currencies are treated like an unavailable rate: their
        # holdings contribute 0 rather than a wrong currency's number.
        total = 0.0
        for symbol, held in net_qty.items():
            if held == 0:
                continue
            # FORWARD-FILL for days the ticker printed no bar: a holiday
            # on its market, or the unfinalized current-day bar (whose
            # NaN close get_history already drops). A position you still
            # hold is worth its last known close — pricing the gap at 0
            # painted a cliff at the chart's end (and dipped every
            # one-market holiday), implying the holding lost its whole
            # value when the truth is "no fresh price printed yet".
            # Labels walk forward, so last_closes always holds THIS
            # label's most recent known close. A ticker with NO bar at
            # all (dead/delisted — get_history raised) has nothing to
            # carry and contributes 0 as before; one that delists
            # mid-period freezes at its last price — the ledger stays
            # the truth for what is held.
            close = histories[symbol].get(label)
            if close is not None:
                last_closes[symbol] = close
            else:
                close = last_closes.get(symbol)
                if close is None:
                    continue   # never traded in range → contributes 0
            currency = currency_by_symbol.get(symbol)
            if currency == "USD":
                if live_rate is None:
                    continue   # unconvertible — contributes 0 this period
                close *= live_rate
            elif currency != "CAD":
                continue       # unsupported currency — contributes 0
            total += held * close
        values.append(total)

        # Netted cost basis at this LABEL = the sum of every ticker's
        # fold so far. Flat between transactions, steps at each buy/sell
        # — a buy pushes it up, a sell pulls it down. A short's cost can
        # go negative (recouped more than paid); that's honest, matching
        # the summary strip's own negative-cost-basis semantics.
        costs.append(sum(net_cost.values()))

        # Flush every held symbol's pending flows at the first label where
        # that symbol has a measured price (a bar now, or a carried-forward
        # last close). `last_closes` is the same "this symbol's value is
        # real at this label" marker the value walk used just above, so a
        # flow is removed on exactly the bar its value enters — no earlier.
        # A symbol that never prices here stays in `pending_flows` forever,
        # so its flows are never removed (the mirror rule, now per-bar).
        for symbol in [s for s in pending_flows if s in last_closes]:
            flow = pending_flows.pop(symbol)
            if flow:
                flows_by_label[label] = (
                    flows_by_label.get(label, 0.0) + flow
                )

    # Time-weighted return: chain the value line with each bar's cash
    # flow removed. Label-keyed flows are aligned to the label order,
    # then the pure helper does the chaining — bar 0's flow is the
    # BASE and is ignored by design. index_values may be SHORTER than
    # labels (truncation) or null (nothing computable) — honest states,
    # never a 0/0 NaN.
    flows = [flows_by_label.get(label, 0.0) for label in labels]
    index_values, twrr_pct = _time_weighted_return(values, flows)

    payload = {
        "labels": labels, "values": values, "costs": costs,
        "index_values": index_values, "twrr_pct": twrr_pct,
    }
    if benchmark_symbols:
        payload["benchmarks"] = [
            {
                "symbol": symbol,
                "values": (
                    None if symbol in benchmark_errors
                    else _rebase_series(
                        labels, benchmark_histories.get(symbol, {})
                    )
                ),
                "error": benchmark_errors.get(symbol),
            }
            for symbol in benchmark_symbols
        ]
    return jsonify(payload)


# ---------------------------------------------------------------------------
# PORTFOLIO SUMMARY — the dashboard header's live numbers: total value,
# today's move, and total return, computed from the ledger + live quotes.
#
# The header's numbers used to be hardcoded mockup data ("$143.96" in the
# template, painted once and never updated). This route is their data
# source, and the first slice of the brief's full "value summary strip".
#
# Two portfolio views, two price sources — deliberately:
#   /api/portfolio/history  prices the portfolio at HISTORY closes
#   /api/portfolio/summary  prices it at LIVE quotes (right now)
# The answers are close but never identical by design: a quote is "the
# last traded price", a daily bar's close is "where that day ended".
#
# CURRENCY (permanent decision, documented in project-brief.md's Design
# Rules): the summary displays in CAD — ALWAYS, regardless of the
# dashboard's "Show USD in USD" ledger toggle (that toggle flips only the
# ledger; the portfolio total is deliberately untouched by it). USD
# amounts convert at the LIVE USDCAD rate (current value = a potential
# sell), while the cost basis converts each transaction at its OWN stored
# fx_rate (a past fact — see _derive_fx_rate). A CAD total gain therefore
# includes currency movement, which is the honest CAD picture.
# ---------------------------------------------------------------------------

@app.route("/api/portfolio/summary")
def portfolio_summary():
    """Return the portfolio header's headline numbers as raw floats, in
    CAD.

    No parameters: the ledger decides WHAT is held; live quotes decide
    what it's worth; the live USDCAD rate converts it. Shape of the reply:
        total_value     Σ net_qty × live price × rate (priced tickers)
        day_gain        Σ net_qty × quote.change × rate (today's move)
        day_gain_pct    day_gain ÷ yesterday's value (null if no base)
        total_gain      total_value − cost_basis (realized + unrealized)
        total_gain_pct  total_gain ÷ cost_basis (null if no base)
        cost_basis      Σ ±(price × qty × that tx's fx_rate) — buys paid
                        minus sells recouped, each at ITS day's rate
        unpriced        tickers excluded from ALL sums: quote failed, FX
                        unavailable for a USD holding, or a currency the
                        CAD display doesn't support
        currency        "CAD" — declared so the frontend can label it
        holdings        the allocation donut's per-ticker slice: one
                        {ticker, value, weight} per PRICED ticker with a
                        NET-LONG position, sorted value-DESCENDING; weight
                        is value ÷ (sum of the long values), so the wedges
                        close the circle; a short (net qty < 0) counts in
                        total_value but gets NO wedge (it's a bet against,
                        not an allocation); [] when nothing is priced,
                        held long, or held at all
    """
    # The ledger is the source of truth for what is held. Order doesn't
    # matter here — everything below is sums, not a forward walk.
    transactions = db.get_transactions()

    # Pass 1 — FACTS ONLY (no network): fold every transaction into per-
    # ticker figures.
    #   net_qty:    BUY adds shares, SELL subtracts — the same fold the
    #               history route does, but only the final state matters.
    #   cost_stored: Σ ±(price × qty × stored fx_rate) — the CAD cost of
    #               every transaction whose rate is a known fact. CAD rows
    #               carry fx_rate 1.0, so one formula serves both.
    #   cost_unrated: Σ ±(price × qty) for USD rows whose fx_rate is NULL
    #               (pre-feature rows, or Yahoo couldn't answer at insert
    #               time). Their rate is genuinely unknown — they convert
    #               at the LIVE rate as a documented per-request fallback.
    #   A buy adds what was PAID; a sell SUBTRACTS what was RECOUPED. The
    #   gap between today's value and this net figure is the position's
    #   whole lifetime gain (realized + unrealized) in ONE formula.
    net_qty = {}
    cost_stored = {}
    cost_unrated = {}
    has_unrated = False
    for tx in transactions:
        symbol = tx["ticker"]
        sign = 1 if tx["transaction_type"] == "BUY" else -1
        net_qty[symbol] = net_qty.get(symbol, 0) + sign * tx["qty"]
        if tx["currency"] == "USD" and tx["fx_rate"] is None:
            cost_unrated[symbol] = (
                cost_unrated.get(symbol, 0.0)
                + sign * tx["price"] * tx["qty"]
            )
            has_unrated = True
        else:
            # USD rows use their stored rate; every other currency uses 1
            # (CAD rows store exactly that; non-USD/CAD rows never reach a
            # cost that matters — they're excluded from all sums below).
            rate = tx["fx_rate"] if tx["currency"] == "USD" else 1.0
            cost_stored[symbol] = (
                cost_stored.get(symbol, 0.0)
                + sign * tx["price"] * tx["qty"] * rate
            )

    # (An empty ledger falls through this loop and returns all zeros +
    # null pcts below — a normal state, not an error, same rule as the
    # history route. No special case needed.)

    # One quote per UNIQUE ticker — the same dedup as list_transactions
    # (30 trades in one ticker pay for exactly one quote; the 120s cache
    # makes repeats free). Per-symbol resilience, the same rule as
    # everywhere quotes are fetched: a dead ticker goes into "unpriced"
    # and contributes to NOTHING — not value, not day move, not cost
    # basis. Excluding it from the cost basis too is what keeps every
    # number describing the SAME priced-only slice of the portfolio
    # (adding its cost but not its value would fake a loss that never
    # happened). The frontend surfaces the gap via a tooltip.
    # One quote per UNIQUE ticker, fetched in parallel — same pattern
    # as portfolio_history and the other quote endpoints.
    def fetch_summary_quote(symbol):
        try:
            return symbol, get_quote(symbol)
        except Exception:
            # Wide catch on purpose: yfinance fails in many ways, and
            # the ledger's facts still stand — degrade, never 500.
            # TIER 1: this log line is the only trace a dead ticker
            # leaves (on screen it's just absent from the totals).
            app.logger.warning(
                "summary quote failed for %s — excluded from all totals",
                symbol,
                exc_info=True,
            )
            return symbol, None

    quotes = {}
    if net_qty:
        with ThreadPoolExecutor(
            max_workers=min(len(net_qty), 8)
        ) as pool:
            for symbol, quote in pool.map(fetch_summary_quote, net_qty):
                quotes[symbol] = quote

    # ONE live USDCAD rate for the whole response — fetched only when
    # something actually needs converting (a USD-priced holding, or a
    # legacy NULL-fx row needing the fallback). A CAD-only portfolio
    # makes no FX call at all. If the rate is unavailable, USD holdings
    # join "unpriced": without it there is no honest CAD number, and a
    # fake 1:1 rate would quietly misstate the whole portfolio.
    needs_live_rate = has_unrated or any(
        quote is not None and quote["currency"] == "USD"
        for quote in quotes.values()
    )
    live_rate = None
    if needs_live_rate:
        try:
            live_rate = get_fx_rate("USD", "CAD")
        except Exception:
            app.logger.warning(
                "live USDCAD rate unavailable — USD holdings excluded "
                "from the summary",
                exc_info=True,
            )

    # Pass 2 — price the priced slice in CAD. held == 0 (fully-sold
    # ticker) contributes 0 to value and day move, but its net cost still
    # feeds cost_basis — which is exactly how a realized gain (bought
    # low, sold high, nothing left) shows up in total_gain.
    total_value = 0.0
    day_gain = 0.0
    cost_basis = 0.0
    unpriced = []
    holdings = []
    for symbol, held in net_qty.items():
        quote = quotes[symbol]
        if quote is None:
            unpriced.append(symbol)
            continue
        # The QUOTE's currency is the live truth (it's the same source the
        # ledger's currency was derived from at insert time). Only USD↔CAD
        # conversion is supported: anything else is excluded, not faked.
        currency = quote["currency"]
        if currency not in ("USD", "CAD"):
            app.logger.warning(
                "summary cannot convert %s (%s) — excluded from all totals",
                symbol, currency,
            )
            unpriced.append(symbol)
            continue
        if currency == "USD" and live_rate is None:
            unpriced.append(symbol)   # no FX → no honest CAD number
            continue
        value_rate = live_rate if currency == "USD" else 1.0
        # One value per ticker, computed ONCE: the headline total and the
        # donut's wedge must come from the same number, or a wedge could
        # disagree with the total it claims to be a fraction of.
        position_value = held * quote["price"] * value_rate
        total_value += position_value
        day_gain += held * quote["change"] * value_rate
        # The donut's per-ticker slice, accumulated in the SAME pass (same
        # quotes, same rate — no refetch). LONG positions only: the donut
        # plots what you HOLD, and a short (net qty < 0 — the ledger's
        # oversell fold opens one deliberately) is a bet AGAINST, not an
        # allocation. A fully-sold ticker (net qty 0) gets NO entry either:
        # a zero-value wedge is invisible clutter at best and a 0/0 weight
        # NaN at worst.
        if held > 0:
            holdings.append({"ticker": symbol, "value": position_value})
        # Cost: stored-rate amounts pass through; legacy unrated amounts
        # (USD rows with fx_rate NULL) convert at the live rate.
        cost_basis += (
            cost_stored.get(symbol, 0.0)
            + cost_unrated.get(symbol, 0.0)
              * (live_rate if currency == "USD" else 1.0)
        )

    unpriced.sort()  # stable, human-readable order for the tooltip

    # THE DONUT SLICE — weights over the PRICED, LONG-ONLY total. Two
    # exclusions already happened above, each for the same reason from
    # opposite directions:
    #   unpriced ticker → excluded from total_value AND holdings, so a
    #     dead ticker can never inflate the other wedges (a weight over a
    #     phantom denominator would misstate every holding that DID price);
    #   short position → its negative value still counts in total_value
    #     (that netting is the headline's existing, tested math) but gets
    #     NO wedge, so the weights divide by the sum of the LONG values
    #     only — the visible circle closes even when a short is quietly
    #     shrinking the headline.
    # Sorted value-DESCENDING so the donut's legend reads biggest-first —
    # the frontend reads, never re-derives. No zero-division guard is
    # needed past this point: every entry in holdings is a positive value,
    # so the sum is positive whenever the list is non-empty (empty ledger,
    # fully-sold, all-short, or nothing priced → no wedges at all — a
    # weight computed over an empty base is exactly how a NaN reaches
    # JSON, and the NaN contract forbids that).
    holdings.sort(key=lambda entry: entry["value"], reverse=True)
    long_total = sum(entry["value"] for entry in holdings)
    for entry in holdings:
        entry["weight"] = entry["value"] / long_total

    # Percentages need a meaningful BASE to divide by — otherwise the
    # math produces confident-looking nonsense:
    #   day_gain_pct divides by YESTERDAY'S value (today's minus the day
    #     move). With nothing held net, there is no base at all.
    #   total_gain_pct divides by cost basis, which drops to ≤ 0 once
    #     every position is sold (proceeds outweigh payments).
    # null tells the frontend to show the signed amount without a %.
    yesterdays_value = total_value - day_gain
    day_gain_pct = (
        day_gain / yesterdays_value * 100 if yesterdays_value > 0 else None
    )
    total_gain = total_value - cost_basis
    total_gain_pct = (
        total_gain / cost_basis * 100 if cost_basis > 0 else None
    )

    return jsonify({
        "total_value": total_value,
        "day_gain": day_gain,
        "day_gain_pct": day_gain_pct,
        "total_gain": total_gain,
        "total_gain_pct": total_gain_pct,
        "cost_basis": cost_basis,
        "unpriced": unpriced,
        "currency": "CAD",
        "holdings": holdings,
    })


# ---------------------------------------------------------------------------
# GET /api/portfolio/realized — the "Closed sales" table's data source.
#
# Every SELL transaction becomes one row carrying the REALIZED result of
# that sale in CAD: proceeds vs what the sold shares actually cost. This
# is the number the ledger's per-row gain can never give you — that gain
# compares the sell price to YESTERDAY'S close (market noise), while this
# compares it to the position's cost basis (performance).
#
# AVERAGE-COST REPLAY (the one formula that answers "what did I make?"):
#   The ledger is folded oldest-first (date, then id — db.get_transactions
#   returns newest-first, so it's reversed). Per ticker, three running
#   figures: qty, native cost pool, CAD cost pool.
#     BUY  → pool grows:  qty += q;  pools += q × price (+ × fx_rate)
#     SELL → cover min(q, qty) shares at the pool's AVERAGE:
#              realized = covered × (sell_price × fx − avg_cad_cost)
#            pools shrink by the covered shares' average — the leftover
#            shares keep the SAME average for the next sell.
#   Average cost (not FIFO) because it matches the ledger's Avg Cost
#   column and the Canadian ACB convention — one method, everywhere.
#
# NO QUOTE OR FX CALLS: every rate is a STORED FACT (fx_rate captured
# at log time; CAD rows store 1.0). A realized gain is history — it
# cannot go stale, so the money math never waits on Yahoo and never
# needs refreshing. (Names are the one courtesy fetch: get_name
# consults the process-lifetime name cache — one .info per sold ticker
# after a restart; a ticker Yahoo can't name retries each poll until it
# can. Only the name can degrade; the money never waits on it.)
#
# SHORTS ARE SYMMETRIC, not special-cased (nothing stops a SELL bigger
# than the position — the summary's net_qty already goes negative):
#   - The covered part realizes normally.
#   - The excess opens a SHORT whose basis is the sell price (the pools
#     go negative with the qty — one uniform "average = pool ÷ qty").
#   - A later BUY covering the short realizes (short basis − buy price).
#     That gain is earned on a BUY event, so NO row carries it — but
#     total_realized (the fold's full sum) must. Rows ⊂ total is the
#     documented divergence, locked by test_realized.py.
#
# RECOMPUTE-ON-READ (same philosophy as /api/portfolio/summary): nothing
# is stored, so editing an old BUY through the PUT route retroactively
# rewrites realized history — the honest consequence of an editable
# ledger. Replay cost is a few hundred in-memory operations.
#
# DEGRADATION, NEVER FABRICATION: a row's CAD math needs every leg of its
# position to carry a known rate. A NULL fx_rate (pre-feature rows, or
# Yahoo couldn't answer at log time) or an unsupported currency (only
# USD↔CAD is supported, permanent rule) makes the pool's CAD value
# unknowable: the row keeps its FACTS (native prices, qty, dates) but
# realized/pct go null with a reason, and one degraded row poisons
# total_realized to null — a partial sum that looks complete is a lie.
# The flag follows the POSITION LIFECYCLE: it clears when the pool
# returns to flat, so a fresh position after a degraded one computes
# normally. Native math (avg cost in the security's own currency) never
# degrades — currency purity means fx plays no part in it.
# ---------------------------------------------------------------------------

@app.route("/api/portfolio/realized")
def portfolio_realized():
    """Return one row per SELL with its realized CAD result, newest first.

    Shape of the reply:
        currency        "CAD" — declared so the frontend can label it
        total_realized  the fold's full realized sum in CAD — including
                        short-cover gains no row carries. null when ANY
                        row is degraded (never a partial sum).
        rows[]          newest-first, one per SELL transaction:
            id               the SELL transaction's id
            ticker / name    identity (name null when Yahoo can't say)
            transaction_date the SELL's date
            qty              shares sold (the FULL sell, even when only
                             part was covered)
            currency         the security's native currency
            price            native sell price
            avg_cost         native average cost of the covered shares
            avg_cost_fx      fx-weighted average CAD rate of those shares
            realized         CAD gain (proceeds − basis); null = degraded
            realized_pct     realized ÷ basis × 100; null when basis ≤ 0
            degraded         null, or a human-readable reason
    """
    transactions = db.get_transactions()
    transactions.reverse()  # the replay runs oldest-first

    def stored_rate(tx):
        """The transaction's STORED CAD conversion fact, or None when it
        is genuinely unknowable. CAD rows carry fx_rate 1.0 by convention;
        USD rows carry the USDCAD close of their day (or NULL for legacy
        rows); anything else was never supported — None, not a fake 1:1."""
        if tx["currency"] == "CAD":
            return 1.0
        if tx["currency"] == "USD":
            return tx["fx_rate"]
        return None

    def unrated_reason(tx):
        """Why a leg's CAD rate is unknowable — surfaced verbatim in the
        degraded row's tooltip, so the ledger can be fixed at the source."""
        if tx["currency"] == "USD":
            return (f"missing fx_rate on {tx['transaction_date']} "
                    f"{tx['transaction_type']}")
        return f"unsupported currency: {tx['currency']}"

    # Per-ticker replay state. rated/reason: whether the CAD pool's value
    # is exactly known (an unrated leg entering the pool flips it False
    # until the position goes flat — degradation follows the lifecycle).
    positions = {}
    rows = []
    fold_total = 0.0
    # An unrated leg whose gain is unknowable even in principle (an
    # unrated BUY covering a short) can't degrade any row — it books no
    # row at all — but it makes the TOTAL unverifiable. This flag nulls it.
    total_uncertain = False

    for tx in transactions:
        pos = positions.setdefault(tx["ticker"], {
            "qty": 0.0, "cost_native": 0.0, "cost_cad": 0.0,
            "rated": True, "reason": None,
        })
        q = tx["qty"]
        price = tx["price"]
        rate = stored_rate(tx)
        is_buy = tx["transaction_type"] == "BUY"
        qty_before = pos["qty"]

        if is_buy:
            # Covering an existing short first: the covered shares realize
            # (short basis − buy price). Buys emit no row, so this gain
            # lives only in fold_total — or, when the rate is unknown,
            # nowhere we can vouch for.
            if qty_before < 0:
                covered = min(q, -qty_before)
                if rate is not None and pos["rated"]:
                    fold_total += covered * (
                        pos["cost_cad"] / qty_before - price * rate
                    )
                elif rate is None:
                    total_uncertain = True
                if pos["rated"]:
                    # The CAD side of the short shrinks only when its
                    # basis is exactly known — an unrated pool's CAD
                    # value is garbage and stays untouched until the
                    # flat wipe.
                    pos["cost_cad"] += covered * (
                        pos["cost_cad"] / qty_before
                    )
                # The NATIVE side shrinks UNCONDITIONALLY: currency
                # purity makes it exact even when the CAD pool is not.
                # Gating it on rated let an unrated short's stale basis
                # leak into later rows' avg_cost — a corrupted "fact"
                # (regression locked by
                # test_covering_buy_shrinks_unrated_short_native_pool).
                ps_native = pos["cost_native"] / qty_before
                pos["cost_native"] += covered * ps_native
                pos["qty"] = qty_before + covered
                q -= covered
            # Any remainder (or the whole buy, when no short existed)
            # joins — or opens — the long pool.
            if q > 0:
                pos["qty"] += q
                pos["cost_native"] += q * price
                if rate is not None:
                    pos["cost_cad"] += q * price * rate
                else:
                    # Unrated cost entering the pool: the pool's CAD value
                    # is no longer exactly known until it goes flat.
                    pos["rated"] = False
                    pos["reason"] = unrated_reason(tx)
        else:
            # ---- SELL: emit one row (this IS the closed sale) ----
            row = {
                "id": tx["id"],
                "ticker": tx["ticker"],
                "name": None,          # attached after the fold
                "transaction_date": tx["transaction_date"],
                "qty": q,
                "currency": tx["currency"],
                "price": price,
                "avg_cost": price,     # short-opening fallback, replaced below
                "avg_cost_fx": rate,
                "realized": None,
                "realized_pct": None,
                "degraded": None,
            }
            if qty_before > 0:
                covered = min(q, qty_before)
                ps_native = pos["cost_native"] / qty_before
                ps_cad = (
                    pos["cost_cad"] / qty_before if pos["rated"] else None
                )
                row["avg_cost"] = ps_native
                row["avg_cost_fx"] = (
                    pos["cost_cad"] / pos["cost_native"]
                    if pos["rated"] else None
                )
                if pos["rated"] and rate is not None:
                    basis_cad = covered * ps_cad
                    realized = covered * price * rate - basis_cad
                    fold_total += realized
                    row["realized"] = realized
                    # A percentage needs a meaningful base to divide by
                    # (same rule as the summary route's gain pcts).
                    row["realized_pct"] = (
                        realized / basis_cad * 100 if basis_cad > 0 else None
                    )
                else:
                    row["degraded"] = (
                        pos["reason"] if not pos["rated"]
                        else unrated_reason(tx)
                    )
                # Pool bookkeeping is independent of the row's degradation:
                # the covered shares leave at their KNOWN average, so the
                # remaining pool stays exactly known (rated pools stay
                # rated even when THIS sell's proceeds were unrated).
                pos["qty"] = qty_before - covered
                pos["cost_native"] -= covered * ps_native
                if pos["rated"]:
                    pos["cost_cad"] -= covered * ps_cad
                q -= covered
            else:
                # Nothing held: the whole sell opens/extends a short. It
                # realizes NOTHING at this moment (the short's basis is
                # its own price) — zero is an exact answer, not a gap.
                if pos["rated"] and rate is not None:
                    row["realized"] = 0.0
                else:
                    row["degraded"] = (
                        pos["reason"] if not pos["rated"]
                        else unrated_reason(tx)
                    )
            # Everything beyond the held shares (or the whole sell, when
            # nothing was held) opens/extends a short: basis = sell price.
            # The pools go negative with the qty — the uniform
            # "average = pool ÷ qty" identity keeps working.
            if q > 0:
                pos["qty"] -= q
                pos["cost_native"] -= q * price
                if rate is not None:
                    pos["cost_cad"] -= q * price * rate
                else:
                    pos["rated"] = False
                    pos["reason"] = unrated_reason(tx)
            rows.append(row)

        # Going flat wipes the ancestry: a fresh position is judged fresh
        # (locked by test_degradation_follows_position_lifecycle). The
        # check is a TOLERANCE, not == 0: fractional qtys (the importer's
        # 6-decimal flagship input) leave binary residue — 0.1 + 0.2 − 0.3
        # is 5.55e-17 — and an exact check would glue an unrated ancestry
        # to the ticker forever, poisoning every later row and the total
        # (regression locked by test_fractional_positions_still_go_flat).
        if abs(pos["qty"]) < 1e-9:
            pos["cost_native"] = 0.0
            pos["cost_cad"] = 0.0
            pos["rated"] = True
            pos["reason"] = None

    # Names come from the process-lifetime name cache (market_data caches
    # successes; one .info per sold ticker after a restart, retried per
    # poll while Yahoo can't answer — the ONLY network this endpoint can
    # touch, and it never gates the money math). A ticker Yahoo can't
    # name keeps its full row: name null is cosmetic, not a gap in the
    # numbers.
    for ticker in {row["ticker"] for row in rows}:
        try:
            name = get_name(ticker)
        except Exception:
            name = None
        for row in rows:
            if row["ticker"] == ticker:
                row["name"] = name

    rows.reverse()  # replay was oldest-first; display newest-first

    return jsonify({
        "currency": "CAD",
        "total_realized": (
            None if total_uncertain
            or any(row["degraded"] for row in rows)
            else fold_total
        ),
        "rows": rows,
    })


# ---------------------------------------------------------------------------
# ALLOCATION DONUT — multi-dimension slicing of the portfolio value.
#
# The dashboard's donut card offers 6 views (By Ticker via the summary
# endpoint, plus 5 dimensions here), cycled with arrow buttons. Each
# dimension groups the same holdings math (net-qty × live quote × live
# FX rate) by a metadata field: sector, country, asset type, market-cap
# bucket, or currency. (By Industry and By Exchange were cut — see
# ALLOCATION_DIMENSIONS.)
#
# HOW THE MATH WORKS: identical to the summary's pass (fold → parallel
# quotes → live FX → long-only, priced-only), but instead of returning
# per-ticker entries, the per-ticker value is bucketed by the chosen
# dimension's key. Weights divide by the sum of CLASSIFIED slices only
# (an excluded ticker's value never inflates the denominator).
#
# DATA SOURCE: the "currency" dimension classifies off the quote's own
# currency (zero extra network). The other four consult get_profile()
# (market_data.py) — one Ticker.info call per ticker, process-lifetime
# cached (the name-cache pattern). Missing metadata fields → excluded
# with a human-readable reason, never fabricated into a category.
#
# CAP BUCKETS: USD market caps convert at the live rate so all buckets
# are CAD-consistent. Thresholds: Large ≥ $10B CAD, Mid $2–10B,
# Small < $2B. Missing market_cap → excluded.
#
# EXCLUDED LIST: every ticker that contributes to no slice lands in
# `excluded` with {ticker, reason}. Two exclusion paths:
#   - unpriced (quote failed or unsupported currency) — same excluded-
#     from-every-sum rule the summary already follows
#   - unclassified (profile missing the field, or profile fetch failed)
# The frontend surfaces this as a small note under the donut.
# ---------------------------------------------------------------------------

# Market-cap bucket thresholds (CAD). USD caps convert at the live rate
# before bucketing, so the thresholds are currency-agnostic.
_CAP_LARGE = 10_000_000_000   # ≥ $10B CAD
_CAP_MID = 2_000_000_000      # ≥ $2B CAD
# Small = everything below $2B CAD


def _cap_bucket(market_cap_cad):
    """Classify a CAD-converted market cap into a human-readable bucket.
    Returns the bucket label, or None if the cap is missing."""
    if market_cap_cad is None:
        return None
    if market_cap_cad >= _CAP_LARGE:
        return "Large"
    if market_cap_cad >= _CAP_MID:
        return "Mid"
    return "Small"


@app.route("/api/portfolio/allocation")
def portfolio_allocation():
    """Return per-dimension allocation slices for the donut carousel.

    Query param `by` is a key in ALLOCATION_DIMENSIONS; defaults to
    "sector". Invalid key → 400 with the valid options. Shape of reply:

        by          the dimension key ("sector", "currency", ...)
        currency    "CAD" — all values are CAD
        slices[]    value-desc, one per classified group:
            key     the dimension value ("Technology", "USD", ...)
            value   Σ net_qty × live price × rate for long positions
                    in this group (CAD)
            weight  value ÷ sum of all slice values
        excluded[]  tickers that contribute to no slice:
            ticker  the symbol
            reason  human-readable: "couldn't be priced", "no sector
                    data", "couldn't fetch profile", etc.

    Slices may be [] when every holding is excluded — that's honest, not
    an error. Empty ledger → both slices and excluded are [].
    """
    # Validate the dimension key BEFORE doing any work — the same
    # "fail early, fail friendly" pattern as portfolio_history's period
    # validation.
    by = request.args.get("by", "sector").lower()
    if by not in ALLOCATION_DIMENSIONS:
        options = ", ".join(sorted(ALLOCATION_DIMENSIONS))
        return jsonify({"error": f"by must be one of: {options}"}), 400

    dimension = ALLOCATION_DIMENSIONS[by]
    profile_field = dimension["field"]  # None for currency

    # ── PASS 1: fold transactions into per-ticker figures ────────────────
    # Same fold as portfolio_summary: net qty (BUY adds, SELL subtracts)
    # and cost. We need net_qty for the long-only check; value is priced
    # in pass 2 from live quotes.
    transactions = db.get_transactions()
    net_qty = {}
    currency_by_symbol = {}
    for tx in transactions:
        symbol = tx["ticker"]
        sign = 1 if tx["transaction_type"] == "BUY" else -1
        net_qty[symbol] = net_qty.get(symbol, 0) + sign * tx["qty"]
        currency_by_symbol.setdefault(symbol, tx["currency"])

    # Empty ledger → empty slices, empty excluded.
    if not net_qty:
        return jsonify({"by": by, "currency": "CAD",
                        "slices": [], "excluded": []})

    # ── PASS 2: price the priced slice in CAD ───────────────────────────
    # One quote per UNIQUE ticker, fetched in parallel — same pattern as
    # portfolio_summary. Unpriced tickers join the excluded list.
    def fetch_alloc_quote(symbol):
        try:
            return symbol, get_quote(symbol)
        except Exception:
            app.logger.warning(
                "allocation quote failed for %s — excluded from slices",
                symbol,
                exc_info=True,
            )
            return symbol, None

    quotes = {}
    with ThreadPoolExecutor(
        max_workers=min(len(net_qty), 8)
    ) as pool:
        for symbol, quote in pool.map(fetch_alloc_quote, net_qty):
            quotes[symbol] = quote

    # ONE live USDCAD rate — fetched only when a USD holding needs
    # converting. Same logic as portfolio_summary.
    usd_tickers = sorted(
        s for s, c in currency_by_symbol.items()
        if c == "USD" and net_qty.get(s, 0) > 0
    )
    live_rate = None
    if usd_tickers:
        try:
            live_rate = get_fx_rate("USD", "CAD")
        except Exception:
            app.logger.warning(
                "live USDCAD rate unavailable — USD holdings excluded "
                "from allocation",
                exc_info=True,
            )

    # ── PASS 3: classify + aggregate ────────────────────────────────────
    # Walk every held ticker. Priced + classified → slice; otherwise →
    # excluded with a reason. For profile dimensions, get_profile is
    # called once per unique ticker (process-lifetime cached, so only
    # the first request pays the cost).
    slices = {}    # {group_key: value}
    excluded = []  # [{ticker, reason}]

    for symbol, held in net_qty.items():
        quote = quotes[symbol]

        # Unpriced: same excluded-from-every-sum rule as the summary.
        if quote is None:
            excluded.append({"ticker": symbol,
                             "reason": "couldn't be priced"})
            continue

        # Currency check: only USD and CAD are supported — anything else
        # is excluded, same as the summary.
        currency = quote["currency"]
        if currency not in ("USD", "CAD"):
            excluded.append({"ticker": symbol,
                             "reason": f"unsupported currency: {currency}"})
            continue
        if currency == "USD" and live_rate is None:
            excluded.append({"ticker": symbol,
                             "reason": "USDCAD rate unavailable"})
            continue

        value_rate = live_rate if currency == "USD" else 1.0
        position_value = held * quote["price"] * value_rate

        # Long-only: a short is a bet against, not an allocation.
        if held <= 0:
            continue

        # Classify by the chosen dimension.
        if profile_field is None:
            # Currency dimension: group off the quote's currency directly.
            group_key = currency
        else:
            # Profile dimensions: consult get_profile (cached).
            try:
                profile = get_profile(symbol)
            except Exception:
                app.logger.warning(
                    "allocation profile failed for %s — excluded from "
                    "slices by %s",
                    symbol, by,
                    exc_info=True,
                )
                excluded.append({"ticker": symbol,
                                 "reason": "couldn't fetch profile"})
                continue

            field_value = profile.get(profile_field)

            # Missing metadata: excluded with a reason, never fabricated.
            if field_value is None:
                excluded.append({
                    "ticker": symbol,
                    "reason": f"no {dimension['label'].lower().removeprefix('by ')} data",
                })
                continue

            # Cap dimension: bucket the market cap (convert USD → CAD).
            if by == "cap":
                mc = profile.get("market_cap")
                if currency == "USD" and live_rate is not None and mc is not None:
                    mc = mc * live_rate
                field_value = _cap_bucket(mc)
                if field_value is None:
                    excluded.append({"ticker": symbol,
                                     "reason": "no market-cap data"})
                    continue

            group_key = field_value

        slices[group_key] = slices.get(group_key, 0.0) + position_value

    # ── PASS 4: build the response ──────────────────────────────────────
    # Sorted value-descending (biggest slice first — the donut's legend
    # reads biggest-first). Weights divide by the sum of classified
    # slices only: an excluded ticker's value never enters the denominator.
    total = sum(slices.values())
    result_slices = [
        {"key": key, "value": value,
         "weight": value / total if total > 0 else 0.0}
        for key, value in sorted(slices.items(),
                                 key=lambda item: item[1], reverse=True)
    ]

    excluded.sort(key=lambda e: e["ticker"])

    return jsonify({
        "by": by,
        "currency": "CAD",
        "slices": result_slices,
        "excluded": excluded,
    })


# JSON endpoint powering the live watchlist. One route, two payloads:
#   "symbols" — the full stored list (source of truth for which rows exist)
#   "quotes"  — per-symbol quote dicts, successes only
# Why send both? The indices bar's chips are fixed in HTML, so the browser
# already knows which symbols exist. Watchlist rows are dynamic, so the
# browser learns the list from THIS response — including rows whose quote
# failed this cycle (those render as "—", mirroring the chips' gap-fill).
@app.route("/api/watchlist")
def watchlist_quotes():
    # The DB read is the source of truth for what should be displayed.
    symbols = db.get_symbols()
    if not symbols:
        return jsonify({"symbols": [], "quotes": []})

    # Fetch all watchlist symbols in parallel — each needs a quote + name,
    # both independent yfinance calls. Threading cuts wall time from
    # N×(quote+name) sequential to ~1×slowest pair.
    def fetch_watchlist_symbol(symbol):
        try:
            # Keep route decoration local even though the market layer also
            # returns defensive copies; this makes ownership explicit here.
            quote = dict(get_quote(symbol))
        except Exception:
            # Same per-symbol resilience as the indices bar: a dead symbol
            # just won't appear in "quotes"; its row will gap-fill to "—".
            app.logger.warning(
                "watchlist quote failed for %s — row shows \"—\"", symbol,
                exc_info=True,
            )
            return symbol, None

        try:
            quote["name"] = get_name(symbol)
        except Exception:
            # A missing name shouldn't sink the whole row — the frontend
            # falls back to showing just the symbol. TIER 1 at DEBUG:
            # this fires often (Yahoo's heavier metadata endpoint is
            # flaky), so warning level would bury the interesting lines.
            app.logger.debug(
                "no name available for %s — row shows symbol only", symbol,
                exc_info=True,
            )
            quote["name"] = None

        return symbol, quote

    quotes_map = {}
    with ThreadPoolExecutor(
        max_workers=min(len(symbols), 8)
    ) as pool:
        for symbol, quote in pool.map(fetch_watchlist_symbol, symbols):
            if quote is not None:
                quotes_map[symbol] = quote

    # Preserve original symbol order for deterministic output.
    quotes = [quotes_map[s] for s in symbols if s in quotes_map]

    # An empty watchlist is a normal state, not an error — the frontend
    # shows a friendly "nothing here yet" message.
    return jsonify({"symbols": symbols, "quotes": quotes})


# Add a ticker to the watchlist. The browser POSTs JSON like {"symbol": "aapl"}.
@app.route("/api/watchlist", methods=["POST"])
def add_to_watchlist():
    # request.get_json parses the request body as JSON. silent=True makes it
    # return None on malformed JSON instead of raising — we handle that as
    # our own 400 instead of an ugly crash page.
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or "symbol" not in body:
        return jsonify({"error": "expected JSON body like {\"symbol\": \"AAPL\"}"}), 400

    # Normalize: trim stray spaces and uppercase ("aapl" and "AAPL" are the
    # same ticker to Yahoo — storing one canonical form keeps 409-duplicate
    # detection honest).
    symbol = str(body["symbol"]).strip().upper()
    if not symbol:
        return jsonify({"error": "symbol is required"}), 400

    # Validate BEFORE storing: is this a real, quotable ticker? get_quote
    # raises for unknown/dead symbols, and as a bonus the successful call
    # warms the price cache so the new row can render instantly.
    try:
        get_quote(symbol)
    except Exception:
        # 404 Not Found: the ticker doesn't exist (or Yahoo can't quote it).
        # TIER 1 at INFO — expected client behavior (typos happen), so no
        # traceback: the symbol string IS the story.
        app.logger.info("watchlist add rejected: unquotable symbol %s", symbol)
        return jsonify({"error": f"unknown or unquotable symbol: {symbol}"}), 404

    try:
        db.add_symbol(symbol)
    except sqlite3.IntegrityError:
        # The watchlist symbol is its primary key, so this specific database
        # error means the normalized ticker already exists. Operational
        # failures (locked/full/unwritable DB) must escape to the JSON 500
        # handler instead of being mislabeled as a harmless duplicate.
        return jsonify({"error": f"{symbol} is already on the watchlist"}), 409

    # 201 Created: standard status for "a new resource now exists".
    return jsonify({"symbol": symbol}), 201


# Remove a ticker. Flask passes the <symbol> part of the URL in as an argument.
@app.route("/api/watchlist/<symbol>", methods=["DELETE"])
def remove_from_watchlist(symbol):
    # Same normalization as add, so lookups match what we stored.
    symbol = symbol.strip().upper()
    if not db.remove_symbol(symbol):
        return jsonify({"error": f"{symbol} is not on the watchlist"}), 404
    # 204 No Content: success with nothing to say — the row is just gone.
    return "", 204


# ---------------------------------------------------------------------------
# TRANSACTION LEDGER — log, list, edit, and delete BUY/SELL events.
#
# The database stores immutable FACTS ONLY: nothing in the
# ledger table depends on a live market price. Total Value / Gain $ / Gain %
# are computed fresh on every GET request, from live quotes — never persisted.
#
# The edit boundary (why PUT can't touch two columns): ticker is the row's
# IDENTITY and currency is the yfinance fact DERIVED from it at insert
# time. Edits rewrite what the user typed — never what Yahoo supplied. A
# ticker sent in a PUT body is ignored outright.
#
# One naming subtlety: the JSON API uses short keys ("date", "type") because
# the browser writes them; the DB uses explicit columns ("transaction_date",
# "transaction_type") because schema is read by humans years later. The
# route is the translator between the two vocabularies.
# ---------------------------------------------------------------------------


def validate_tx_fields(body):
    """Validate the four ticker-independent fields of a transaction:
    date, price, qty, type.

    ONE validator for BOTH routes that write transactions — POST (log) and
    PUT (edit). If the two routes each had their own checks they could
    drift apart, and an edit could smuggle in a state that logging would
    have rejected (qty 0, a fake date...). Shared code = one set of rules.

    Returns (fields, None) on success — fields holds the NORMALIZED values
    under their DB-column names ("transaction_date", "transaction_type")
    because this function is the translator between the browser's short
    keys and the DB's explicit ones. Returns (None, (response, status)) on
    the first bad field, ready for the route to `return error` as-is.
    """
    # Date: fromisoformat is the whole validation — it raises ValueError for
    # anything that isn't a real calendar date in "YYYY-MM-DD" form (Feb 30,
    # "08/31/2026", "yesterday"...). .isoformat() then gives back canonical
    # text, so what we store is always uniform.
    try:
        transaction_date = date.fromisoformat(str(body.get("date", ""))).isoformat()
    except ValueError:
        return None, (jsonify({"error": "date must be YYYY-MM-DD (a real calendar date)"}), 400)

    # Numbers: price and qty must be JSON numbers > 0. The isinstance guard
    # rejects strings ("10") and None outright — being lenient here would
    # let half-validated data into the ledger. The bool check looks odd but
    # matters: in Python, True/False ARE ints (bool is a subclass of int),
    # so without it, True would sneak through isinstance(x, int).
    def positive_number(value, field):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return jsonify({"error": f"{field} must be a number"}), 400
        if not math.isfinite(value):
            return jsonify({"error": f"{field} must be finite"}), 400
        if value <= 0:
            return jsonify({"error": f"{field} must be greater than 0"}), 400
        return None

    for field in ("price", "qty"):
        error = positive_number(body.get(field), field)
        if error:
            return None, error

    # Type: normalize, then allow only the two verbs a ledger knows.
    transaction_type = str(body.get("type", "")).strip().upper()
    if transaction_type not in ("BUY", "SELL"):
        return None, (jsonify({"error": "type must be BUY or SELL"}), 400)

    return {
        "transaction_date": transaction_date,
        "price": body["price"],
        "qty": body["qty"],
        "transaction_type": transaction_type,
    }, None


def _derive_fx_rate(currency, transaction_date):
    """Derive a transaction's conversion FACT: how many CAD one unit of
    `currency` bought on `transaction_date`.

    THE LEDGER STORES THE HISTORICAL RATE, DELIBERATELY. The Price column
    and the cost basis describe the PAST — what the shares cost when they
    were bought — so they convert at the rate of the BUYING day (the
    USDCAD close on-or-before the transaction date) and freeze there
    forever. A rate change years later can never rewrite what a past
    trade cost. Current values (price_now, value, day gain) are a
    different story — they use the LIVE rate, because they answer "what
    would a sell bring in today?" (see list_transactions).

    Fallback ladder, best-effort like everything touching Yahoo:
      1. the date's historical close (the honest fact),
      2. the live rate (a visible approximation when the date's close is
         unavailable — the warning log is the audit trail),
      3. None ("rate unknown") — the ledger fact is still stored; the
         display layer falls back to the live rate per request, and
         editing the row later backfills the real date-based fact.
    """
    if currency == "CAD":
        return 1.0  # the true rate — CAD needs no conversion, ever
    if currency != "USD":
        # Only USD↔CAD is supported (the user's securities are CAD/USD).
        # Null is honest: display keeps such rows in their native currency.
        return None

    try:
        return get_fx_rate_on("USD", "CAD", transaction_date)
    except Exception:
        # TIER 1 at warning: degraded-but-recovered (a live-rate fallback
        # follows). exc_info carries the actual cause — the thing a WIDE
        # catch exists for.
        app.logger.warning(
            "no USDCAD close on or before %s — falling back to the live rate",
            transaction_date, exc_info=True,
        )

    try:
        return get_fx_rate("USD", "CAD")
    except Exception:
        app.logger.warning(
            "live USDCAD rate unavailable — fx_rate stored as NULL for %s",
            transaction_date, exc_info=True,
        )
        return None


def _derive_fx_rates_for_rows(rows, quotes):
    """Decorate every VALID import row with its fx_rate, memoized per
    (currency, date) — a batch of 30 rows spanning 3 dates pays for 3
    history lookups, not 30.

    Shared by BOTH import routes. Preview uses it to SHOW what would be
    stored; commit uses it to STORE them (each route derives from the
    same paste independently — commit never trusts preview's work, only
    the same paste). Rows with no quote are skipped: the caller marks
    them failed separately, and a row without a currency has no
    conversion fact to derive.
    """
    memo = {}
    for row in rows:
        if row["error"] is not None:
            continue
        quote = quotes[row["ticker"]]
        if quote is None:
            continue  # unquotable — the caller's verdict loop reports it
        key = (quote["currency"], row["transaction_date"])
        if key not in memo:
            memo[key] = _derive_fx_rate(
                quote["currency"], row["transaction_date"]
            )
        row["fx_rate"] = memo[key]


@app.route("/api/transactions", methods=["POST"])
def log_transaction():
    """Record one transaction. The browser POSTs JSON like:
        {"ticker": "AAPL", "date": "2026-08-31", "price": 229.50,
         "qty": 10, "type": "BUY"}
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "expected JSON body with ticker, date, price, qty, type"}), 400

    # --- Ticker: same trim + uppercase normalization as the watchlist add
    # route — one canonical form everywhere ("aapl" and "AAPL" must match).
    # (The other four fields share validate_tx_fields with the PUT route.)
    ticker = str(body.get("ticker", "")).strip().upper()
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400

    fields, error = validate_tx_fields(body)
    if error:
        return error

    # Prove the ticker is real BEFORE storing it (same rule as the watchlist
    # add route: unknown tickers get 404, never a row). The successful call
    # doubles as the currency source: the quote knows the security's trading
    # currency, so the user never types it — and the price cache gets warmed
    # for the ledger UI's later gain calculations.
    try:
        quote = get_quote(ticker)
    except Exception:
        # TIER 1 at INFO — same expected-client-behavior rule as the
        # watchlist add route: a bad ticker is a typo, not a malfunction.
        app.logger.info("transaction rejected: unquotable ticker %s", ticker)
        return jsonify({"error": f"unknown or unquotable symbol: {ticker}"}), 404
    currency = quote["currency"]

    # Derive the conversion FACT (see _derive_fx_rate): the USDCAD close
    # on the transaction's date, stored once and never recomputed.
    fx_rate = _derive_fx_rate(currency, fields["transaction_date"])

    # All checks passed — write the immutable facts.
    tx_id = db.add_transaction(
        ticker=ticker,
        transaction_date=fields["transaction_date"],
        price=fields["price"],
        qty=fields["qty"],
        currency=currency,
        transaction_type=fields["transaction_type"],
        fx_rate=fx_rate,
    )

    # 201 Created, echoing the stored row (note the DB's explicit column
    # names in the reply — the browser now learns the ledger's vocabulary).
    return jsonify({
        "id": tx_id,
        "ticker": ticker,
        "transaction_date": fields["transaction_date"],
        "price": fields["price"],
        "qty": fields["qty"],
        "currency": currency,
        "fx_rate": fx_rate,
        "transaction_type": fields["transaction_type"],
    }), 201


@app.route("/api/transactions")
def list_transactions():
    """Return every transaction, newest first: facts + display math.

    Each row's stored facts (date, price, qty, currency, fx_rate, type)
    come straight from the DB and NEVER change shape — the edit form
    prefills from them, so a converted number here could never be allowed
    to flow back into a PUT. On top, this route attaches the display
    numbers the ledger UI needs — computed HERE, per request. This is the
    facts-only rule working as designed: the numbers exist for exactly
    one response, then vanish. Nothing stale is ever persisted.

    DISPLAY CURRENCY (?currency=): "CAD" (the default) or "NATIVE" —
    this param is what the dashboard's "Show USD in USD" toggle flips.
    The dashboard's totals (summary, chart) are ALWAYS CAD; this is the
    only endpoint the toggle touches. The reply's display contract:
        display_currency  the currency the DISPLAY fields are in — "CAD"
                          when this row was converted, the stored code
                          otherwise (so an unconvertible row never lies)
        price_display     the price in display_currency — for a converted
                          USD row, price × its STORED fx_rate (a frozen
                          past fact, never the live rate)
        value/total_gain/day_gain (+ pcts) — the live math, in
                          display_currency

    THE TWO-RATE CONTRACT in CAD mode (why one row has two rates):
        price_display & cost side  → the row's STORED fx_rate (what the
                                     trade cost in CAD back then)
        value & day_gain side      → the LIVE rate (what a sell brings
                                     in TODAY)
        total_gain                 = CAD value − CAD cost, so its %
                                     includes currency movement — the
                                     honest CAD return for a Canadian.
    A row converts only when it CAN: a USD row needs its stored rate
    (or, for legacy NULL rows, the live rate) AND — when quoted — a live
    rate for the value side. Anything unconvertible displays native;
    nothing is ever faked with a 1:1 rate.

    Why decorate server-side? The ledger can hold tickers the user never
    added to the watchlist, so the browser has no other way to price them —
    and this keeps main.js a pure renderer (numbers in, text out), matching
    the architecture rule in AGENTS.md.
    """
    transactions = db.get_transactions()

    # Validate the display-currency key BEFORE doing any work — the same
    # contract as the chart's ?period= (a named 400 listing the options).
    display = request.args.get("currency", "CAD").strip().upper()
    if display not in ("CAD", "NATIVE"):
        return jsonify({"error": "currency must be one of: CAD, NATIVE"}), 400

    # One quote per UNIQUE ticker — the same dedup as before (30 trades in
    # one ticker pay for exactly one quote), but fetched in parallel.
    unique_symbols = []
    seen = set()
    for tx in transactions:
        if tx["ticker"] not in seen:
            seen.add(tx["ticker"])
            unique_symbols.append(tx["ticker"])

    def fetch_tx_quote(symbol):
        try:
            return symbol, get_quote(symbol)
        except Exception:
            # Same per-symbol resilience as everywhere else: a dead ticker
            # (delisted, Yahoo hiccup) must not sink the whole response.
            # None marks "couldn't quote" — its rows stay facts-only.
            return symbol, None

    quotes = {}
    if unique_symbols:
        with ThreadPoolExecutor(
            max_workers=min(len(unique_symbols), 8)
        ) as pool:
            for symbol, quote in pool.map(fetch_tx_quote, unique_symbols):
                quotes[symbol] = quote

    # ONE live USDCAD rate per response, fetched only in CAD mode AND only
    # when a quoted USD holding needs it (native mode and CAD-only
    # portfolios never pay for FX). If it fails, USD rows degrade to
    # native display below — converted-by-default is a convenience, never
    # a correctness requirement.
    live_rate = None
    if display == "CAD" and any(
        quote is not None and quote["currency"] == "USD"
        for quote in quotes.values()
    ):
        try:
            live_rate = get_fx_rate("USD", "CAD")
        except Exception:
            app.logger.warning(
                "live USDCAD rate unavailable — USD ledger rows degrade "
                "to native display",
                exc_info=True,
            )

    for tx in transactions:
        quote = quotes[tx["ticker"]]
        # The row's LIVE currency truth: the quote's, or (when the ticker
        # couldn't be quoted) the stored fact. They agree by construction;
        # the quote merely wins when both exist.
        row_currency = quote["currency"] if quote else tx["currency"]

        # CAN this row display in CAD?
        #   Native mode: never (that's the whole point of the toggle).
        #   Non-USD row: never needs to — native CAD display IS the CAD
        #     display, and other currencies aren't supported (honesty
        #     beats a fake 1:1 rate).
        #   USD row, quoted: needs the live rate (the value side).
        #   USD row, unquoted: needs only its STORED rate (the price is a
        #     past fact — it converts without any live data).
        if display == "CAD" and row_currency == "USD":
            converts = (live_rate is not None) if quote is not None \
                else (tx["fx_rate"] is not None)
        else:
            converts = False

        if converts:
            # The row's cost-side rate: its own stored fact, falling back
            # to the live rate for legacy NULL rows (a quoted row implies
            # live_rate is not None here, so the fallback always exists).
            row_rate = (
                tx["fx_rate"] if tx["fx_rate"] is not None else live_rate
            )
            tx["display_currency"] = "CAD"
            tx["price_display"] = tx["price"] * row_rate
        else:
            tx["display_currency"] = tx["currency"]
            tx["price_display"] = tx["price"]

        if quote is None:
            continue  # undecorated row; the frontend gap-fills with "—"

        live_price = quote["price"]
        bought_at = tx["price"]  # the stored fact, NOT the live price
        tx["price_now"] = live_price  # native — a fact, never displayed

        if converts:
            # CAD display: value and day move scale by the LIVE rate;
            # the gain compares today's CAD value against the CAD cost
            # AT THE STORED RATE (price_display × qty — the same number
            # the frontend's group-% math divides by).
            cad_cost = bought_at * row_rate * tx["qty"]
            tx["value"] = live_price * tx["qty"] * live_rate
            tx["total_gain"] = tx["value"] - cad_cost
            # cad_cost > 0: price, qty and rates are all validated > 0.
            tx["total_gain_pct"] = tx["total_gain"] / cad_cost * 100
            tx["day_gain"] = quote["change"] * tx["qty"] * live_rate
        else:
            # Native display: today's math, unchanged by this feature.
            tx["value"] = live_price * tx["qty"]

            # TOTAL gain — accumulated since the transaction date. For a BUY
            # row this is the position's unrealized gain: what it's worth now
            # vs what was paid. (Its % is this position's return since purchase
            # — qty matters, 100 shares "gained" more dollars than 1.)
            tx["total_gain"] = (live_price - bought_at) * tx["qty"]
            # bought_at > 0 is enforced at insert time, so this division is safe.
            tx["total_gain_pct"] = (live_price - bought_at) / bought_at * 100

            # DAILY gain — TODAY's market move applied to the position. The
            # quote already carries the move (change = live − previous close,
            # both validated inside get_quote), so this is just that move
            # scaled by the position size.
            tx["day_gain"] = quote["change"] * tx["qty"]

        # Day % companion — both branches: a % move is a property of the
        # PRICE, not the position or the currency — identical for 1 share
        # or 1000, in USD or CAD.
        #
        # Fun edge case: a transaction dated TODAY shows total ≈ day gain
        # (bought today, so its whole lifetime IS today). Correct, not a bug.
        tx["day_gain_pct"] = quote["change_pct"]

    # --- GROUP AGGREGATES — the numbers the ledger's collapsed summary
    # rows (and its sorter) display. Each row also carries its TICKER's
    # group-level fields, so the frontend renders aggregates instead of
    # re-deriving them: one holdings formula, one implementation.
    #
    # THE MATH MIRRORS /api/portfolio/summary exactly (app.py, Pass 1/2
    # there) — same netting, same two-rate contract, same guards:
    #   group_value          = net_qty × live price × value-rate
    #   group_cost_basis     = Σ ±(price_display × qty) — buys PAID minus
    #                          sells RECOUPED, each at its own display rate
    #   group_total_gain     = value − cost (realized + unrealized in ONE
    #                          formula, like the summary)
    #   group_total_gain_pct = gain ÷ cost, NULL when cost ≤ 0 (a ≤ 0
    #                          basis is no honest denominator)
    #   group_day_gain       = net_qty × quote.change × value-rate
    #   group_day_gain_pct   = the ticker's daily move (price-level)
    # A SELL therefore moves everything EXCEPT nothing: value, day move
    # and cost basis all shrink by the shares sold — which is what makes
    # the ledger's ticker rows agree with the portfolio header.
    #
    # Oversold positions (net qty < 0, e.g. a SELL-only group) display
    # honestly negative — the summary route does the same; no clamping.
    #
    # WHY EVERY ROW CARRIES THEM: the reply is a JSON array of
    # transactions (the frontend's render contract — see the tests in
    # tests/test_ledger_groups.py). All rows of one ticker share the same
    # quote and the same rate situation (quotes are fetched per UNIQUE
    # ticker above), so the group's fields are identical across its rows
    # and the frontend reads them off the group's first row.
    groups = {}
    for tx in transactions:
        groups.setdefault(tx["ticker"], []).append(tx)

    for ticker, rows in groups.items():
        quote = quotes[ticker]
        if quote is None:
            # Unquoted ticker: attach NOTHING. The rows stay facts-only,
            # and the frontend's existing hasLive / "—" gap-fill (which
            # keys on the fields' absence) renders the group degraded.
            continue

        # The group's conversion decision — the SAME expression the
        # per-row loop uses for quoted rows (display CAD + USD quote +
        # live rate available). All rows of a ticker share it because
        # they share the quote, so the group's numbers are internally
        # consistent: one currency, one value-side rate.
        converts = (
            display == "CAD"
            and quote["currency"] == "USD"
            and live_rate is not None
        )
        value_rate = live_rate if converts else 1.0

        # Pass A — facts: net shares and the net cost basis. price_display
        # is already in display currency (stored-rate CAD or native), so
        # the cost side needs no further conversion — buys paid, sells
        # recouped, each at ITS day's rate.
        net_qty = 0
        cost = 0.0
        for tx in rows:
            sign = 1 if tx["transaction_type"] == "BUY" else -1
            net_qty += sign * tx["qty"]
            cost += sign * tx["price_display"] * tx["qty"]

        # Pass B — live math: value and day move apply to the NET
        # position (sold shares no longer move with the market).
        value = net_qty * quote["price"] * value_rate
        day_gain = net_qty * quote["change"] * value_rate
        total_gain = value - cost
        # Same denominator guard as the summary: only a POSITIVE cost
        # basis backs a percentage. Fully-sold-at-profit and SELL-only
        # groups land here — their pct is None, which the frontend
        # renders as "—" (and sorts last).
        total_gain_pct = total_gain / cost * 100 if cost > 0 else None

        for tx in rows:
            tx["group_value"] = value
            tx["group_cost_basis"] = cost
            tx["group_total_gain"] = total_gain
            tx["group_total_gain_pct"] = total_gain_pct
            tx["group_day_gain"] = day_gain
            # The % is the price's move — position- and currency-
            # independent, identical to the per-row day_gain_pct.
            tx["group_day_gain_pct"] = quote["change_pct"]

    return jsonify(transactions)


@app.route("/api/transactions/<int:tx_id>", methods=["PUT"])
def edit_transaction(tx_id):
    """Correct the user-typed facts of ONE existing transaction. The
    browser PUTs JSON like:
        {"date": "2026-08-30", "price": 231.10, "qty": 12, "type": "BUY"}

    The body is exactly those four fields — nothing else. Ticker and
    currency are NOT editable (see the section banner above: identity and
    its yfinance-derived fact). If a client sends a "ticker" anyway it is
    ignored outright — the route never reads it.

    The ONE extra thing PUT does beyond POST: re-derive fx_rate from the
    (possibly corrected) date. The rate is a yfinance fact derived from
    the DATE, not the ticker — correcting the date while keeping the old
    rate would store a wrong fact.
    """
    # 404 BEFORE validation: when the id is the wrong part, "no transaction
    # with that id" is the useful answer — field-checking a nonexistent row
    # would just confuse. (Flask's <int:tx_id> converter 404s non-numeric
    # ids before this code even runs.) The row itself is kept: its
    # (non-editable) currency feeds the fx_rate re-derivation below.
    row = db.get_transaction(tx_id)
    if row is None:
        return jsonify({"error": f"no transaction with id {tx_id}"}), 404

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "expected JSON body with date, price, qty, type"}), 400

    # Same validator as POST — one set of rules, no drift (see its docstring).
    fields, error = validate_tx_fields(body)
    if error:
        return error

    # update_transaction's SET list names the four editable columns PLUS
    # the date-derived fx_rate, so ticker/currency physically cannot
    # change here. A False return means the row vanished between the
    # existence check and the UPDATE (deleted in another window) — same
    # 404 as above.
    if not db.update_transaction(
        tx_id,
        transaction_date=fields["transaction_date"],
        price=fields["price"],
        qty=fields["qty"],
        transaction_type=fields["transaction_type"],
        fx_rate=_derive_fx_rate(row["currency"], fields["transaction_date"]),
    ):
        return jsonify({"error": f"no transaction with id {tx_id}"}), 404

    # 200 with the truth, RE-READ from the DB: the reply shows exactly what
    # is now on disk (including the untouched ticker/currency), not what we
    # think we wrote.
    return jsonify(db.get_transaction(tx_id))


@app.route("/api/transactions/<int:tx_id>", methods=["DELETE"])
def remove_transaction(tx_id):
    """Delete one transaction permanently. 204 = gone. 404 = it never
    existed or was already deleted (double click, or another tab got there
    first) — the frontend refreshes either way and shows the stored truth,
    same rule as watchlist removal.
    """
    if not db.delete_transaction(tx_id):
        return jsonify({"error": f"no transaction with id {tx_id}"}), 404
    # 204 No Content: success with nothing to say — the row is just gone.
    return "", 204


@app.route("/api/transactions/ticker/<symbol>", methods=["DELETE"])
def remove_ticker_transactions(symbol):
    """Delete EVERY transaction of one ticker — the ledger's BULK verb,
    what the frontend's group row (one summary row per ticker) deletes.

    No collision with the per-row route above: its <int:tx_id> converter
    only matches digits, so the literal "ticker" path segment can never
    be mistaken for an id (and this route needs TWO segments after
    /api/transactions anyway).

    The reply shape mirrors the per-row verb exactly: 204 = gone,
    404 = nothing matched (unknown ticker, empty ledger, or another
    window already got there first). Watchlist membership is deliberately
    NOT touched — the watchlist is a separate list; watching a ticker and
    holding it are independent decisions.

    Deliberately no market data here: this route acts purely on stored
    facts, so it works even for a delisted ticker Yahoo can no longer
    quote — often exactly the ledger you WANT to wipe.
    """
    # Same trim + uppercase normalization as every route that takes a
    # symbol from a URL: "aapl" in the path must hit the stored "AAPL".
    ticker = symbol.strip().upper()

    deleted = db.delete_transactions_for_ticker(ticker)
    if deleted == 0:
        # TIER 1 at INFO: expected client behavior (stale UI, typo, double
        # click) — no traceback; the ticker string IS the story.
        app.logger.info(
            "ticker delete rejected: no transactions for %s", ticker
        )
        return jsonify(
            {"error": f"no transactions for ticker {ticker}"}
        ), 404

    # TIER 1 at INFO: an audit trail for a bulk destructive action — the
    # one line that says how many immutable facts this request erased.
    app.logger.info(
        "deleted %d transaction(s) for ticker %s", deleted, ticker
    )
    return "", 204


# ---------------------------------------------------------------------------
# TRANSACTION IMPORTER — bulk-load a pasted batch of transactions.
#
# The source format (feature.md): tab-separated rows, four columns each —
#     CM<TAB>16 Mar 2026<TAB>132.55<TAB>1.296383
# No side column (every row is a BUY) and no currency (derived from
# yfinance, exactly as POST /api/transactions does for hand-logged rows).
#
# Two routes, one parse function:
#   preview — parse + quote-check, return the report, write NOTHING. The
#             user sees exactly what commit would store before agreeing.
#   commit  — re-parse the SAME text (the server trusts nothing the client
#             could have edited between the two calls), then write.
# Best-effort per row, matching this codebase's resilience philosophy
# (indices bar, portfolio history): 50 rows shouldn't die because row 17
# has a typo — valid rows import, broken rows come back with reasons.
# ---------------------------------------------------------------------------


def parse_import_text(text):
    """Parse a paste of tab-separated transaction rows into report dicts.

    Returns a list where every item describes ONE line of the paste:
      * a valid row: the normalized fields (ticker, transaction_date,
        price, qty, transaction_type) with error=None
      * a broken row: error="<human-readable reason>" — whichever fields
        parsed before the failure are filled in, the rest stay None
    Both shapes carry "line" (1-based position in the paste) and "raw"
    (the original text) so a report can point at the exact spot. Broken
    rows are DATA, not exceptions: one bad line must never abort the
    whole batch — the report needs the good rows AND the bad reasons.

    Deliberately STRICT: exactly four tab-separated columns, no "$"
    stripping, no whitespace-split fallback. Parsing exactly the known
    format keeps every failure loud (a named error the user can fix)
    instead of silently storing a mis-parsed fact.
    """
    rows = []
    # splitlines() handles both Unix (\n) and Windows (\r\n) endings, and
    # a trailing newline simply produces no extra element. Blank lines are
    # paste noise — skipped, but they still COUNT for line numbering, so
    # the report's line numbers match what the user sees in their editor.
    for line_no, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        # Every line gets a row dict up front — even one that fails at the
        # first check must appear in the report (with its reason).
        row = {
            "line": line_no,
            "raw": line,
            "ticker": None,
            "transaction_date": None,
            "price": None,
            "qty": None,
            "transaction_type": None,
            "error": None,
        }
        rows.append(row)

        fields = line.split("\t")
        if len(fields) != 4:
            row["error"] = (
                f"expected 4 tab-separated columns, got {len(fields)}"
            )
            continue

        # .strip() per field: padded columns ("CM ␣␣\t16 Mar 2026 ␣") are
        # paste cosmetics, not a different format.
        ticker, date_text, price_text, qty_text = (
            field.strip() for field in fields
        )

        # Ticker: same trim + uppercase normalization as log_transaction —
        # "cm" and "CM" must land as the same ledger identity.
        row["ticker"] = ticker.upper()
        if not ticker:
            row["error"] = "ticker is required"
            continue

        # Date: strptime both VALIDATES ("16 Mar 2026" — day, abbreviated
        # English month, year) and PARSES it. The .date() matters: strptime
        # returns a DATETIME, and its isoformat() would smuggle a
        # "T00:00:00" tail into the ledger's date column. (A non-padded
        # day like "1 May 2026" parses fine.)
        try:
            row["transaction_date"] = datetime.strptime(
                date_text, "%d %b %Y"
            ).date().isoformat()
        except ValueError:
            row["error"] = f"date must be like '16 Mar 2026', got '{date_text}'"
            continue

        # Numbers: float() accepts everything the format promises, and a
        # fractional qty like 1.296383 is exactly why the qty column is
        # REAL. Strings like "10" never reach here as strings — the paste
        # is text, so EVERY value arrives as a string and gets converted.
        try:
            row["price"] = float(price_text)
        except ValueError:
            row["error"] = f"price must be a number, got '{price_text}'"
            continue
        try:
            row["qty"] = float(qty_text)
        except ValueError:
            row["error"] = f"qty must be a number, got '{qty_text}'"
            continue

        if not math.isfinite(row["price"]):
            row["error"] = f"price must be finite, got '{price_text}'"
            continue
        if not math.isfinite(row["qty"]):
            row["error"] = f"qty must be finite, got '{qty_text}'"
            continue

        # Same > 0 rule as validate_tx_fields: however well "0" or "-3"
        # parses, it's nonsense in a ledger.
        if row["price"] <= 0:
            row["error"] = f"price must be greater than 0, got '{price_text}'"
            continue
        if row["qty"] <= 0:
            row["error"] = f"qty must be greater than 0, got '{qty_text}'"
            continue

        # The format has no side column: every imported row is a BUY.
        # (Rework trigger documented in feature.md: the day the source
        # includes sells, this fixed assignment becomes a column read.)
        row["transaction_type"] = "BUY"

    return rows


def _import_text_or_error():
    """Shared body check for both import routes: unwrap {"text": "..."}.

    Returns (text, None) on success, (None, (response, status)) when the
    body is missing, not JSON, not a dict, or carries blank text — the
    same (value, error) convention as validate_tx_fields.
    """
    body = request.get_json(silent=True)
    text = body.get("text") if isinstance(body, dict) else None
    if not isinstance(text, str) or not text.strip():
        return None, (
            jsonify({"error": "expected JSON body like {\"text\": \"<pasted rows>\"}"}),
            400,
        )
    return text, None


def _quote_unique_tickers(rows):
    """One get_quote per UNIQUE ticker among the parseable rows.

    Same dedup idea as list_transactions: a batch of 30 CM trades pays for
    exactly ONE quote. Unquotable tickers map to None rather than raising —
    the caller decides what "can't be priced" means for its row (here: the
    row can't be stored, because currency comes FROM the quote).
    """
    quotes = {}
    for row in rows:
        if row["error"] is not None or row["ticker"] in quotes:
            continue
        try:
            quotes[row["ticker"]] = get_quote(row["ticker"])
        except Exception:
            # Wide catch on purpose: yfinance fails in many ways, and a
            # dead ticker is data (a report line), not a crash.
            quotes[row["ticker"]] = None
    return quotes


@app.route("/api/transactions/import/preview", methods=["POST"])
def import_preview():
    """Parse the paste and quote-check its tickers. Writes NOTHING.

    Returns {"rows": [...], "valid_count": n, "invalid_count": m}, where
    valid rows are decorated with their yfinance-derived "currency" AND
    the date-derived "fx_rate" (the USDCAD close on that row's own date)
    — so the user sees exactly what commit will store, conversion fact
    included. The zero-writes rule is what makes the preview trustworthy:
    the ledger is untouched, so previewing is always safe.
    """
    text, error = _import_text_or_error()
    if error:
        return error

    rows = parse_import_text(text)
    quotes = _quote_unique_tickers(rows)

    for row in rows:
        if row["error"] is not None:
            continue  # already broken at parse time — leave that reason
        quote = quotes[row["ticker"]]
        if quote is None:
            # Same rule as log_transaction's 404: the ticker isn't proven
            # real, and with no quote there is no currency — no row.
            row["error"] = "unknown or unquotable ticker"
        else:
            row["currency"] = quote["currency"]

    # Same decoration as the currency, one fact deeper: each valid row
    # shows the conversion rate of ITS OWN date (memoized per date).
    _derive_fx_rates_for_rows(rows, quotes)

    valid_count = sum(1 for row in rows if row["error"] is None)
    return jsonify({
        "rows": rows,
        "valid_count": valid_count,
        "invalid_count": len(rows) - valid_count,
    })


@app.route("/api/transactions/import/commit", methods=["POST"])
def import_commit():
    """Write the paste's valid rows into the ledger. Best-effort per row.

    Body {"text": ...} AGAIN — the same text preview saw. Re-parsing
    server-side (instead of trusting a client-sent row list) means the
    ledger only ever stores what THIS parse says; the browser had no
    opportunity to edit anything in between.

    Returns {"imported": n, "failed": [...]} at 200 even when imported
    is 0 — the request succeeded; the report IS the answer. A 400 would
    claim the request was malformed, when the honest story is "nothing
    qualified".
    """
    text, error = _import_text_or_error()
    if error:
        return error

    rows = parse_import_text(text)
    quotes = _quote_unique_tickers(rows)

    # Derive every valid row's conversion fact up front (memoized per
    # currency+date) — the commit-side twin of preview's decoration.
    _derive_fx_rates_for_rows(rows, quotes)

    imported_count = 0
    failed = []
    for row in rows:
        if row["error"] is not None:
            failed.append(row)  # parse-stage failure: report it, skip it
            continue

        quote = quotes[row["ticker"]]
        if quote is None:
            # Quotable at preview but dead by commit (Yahoo hiccup) is the
            # same verdict as any other bad ticker: skip, report, never
            # fatal to the rest of the batch.
            row["error"] = "unknown or unquotable ticker"
            failed.append(row)
            continue

        # All checks passed — write the immutable facts (BUY forced by the
        # parser; currency from the quote; fx_rate from the row's OWN
        # date — commit trusts the re-parse, never the preview).
        row["currency"] = quote["currency"]
        try:
            row["id"] = db.add_transaction(
                ticker=row["ticker"],
                transaction_date=row["transaction_date"],
                price=row["price"],
                qty=row["qty"],
                currency=quote["currency"],
                transaction_type=row["transaction_type"],
                fx_rate=row["fx_rate"],
            )
        except Exception:
            app.logger.warning(
                "import database write failed for line %s", row["line"],
                exc_info=True,
            )
            row["error"] = "database write failed"
            failed.append(row)
            continue
        imported_count += 1

    # TIER 1 at INFO: a batch with failures is normal client behavior (a
    # paste with typos), fully visible in the response — this line is the
    # audit trail, not a cry for help.
    app.logger.info(
        "import committed: %d imported, %d failed", imported_count, len(failed)
    )
    return jsonify({"imported": imported_count, "failed": failed})


# ---------------------------------------------------------------------------
# STOCK DETAIL PAGE — /stock/<symbol> plus the JSON endpoints that feed it.
#
# The dashboard prices a PORTFOLIO (ledger facts + live quotes); this page
# prices ONE SECURITY. Same visual shell, simpler math: a stock has no
# ledger behind it, so there is no cost basis — and therefore no total
# return, the one dashboard number this page deliberately lacks.
#
# Three endpoints, sized to their data's weight and refresh rhythm:
#   /api/stock/<symbol>           light  (fast_info)  — polled every 60s
#   /api/stock/<symbol>/stats     heavy  (Ticker.info) — once per page load
#   /api/stock/<symbol>/history   medium (bar closes)  — per button click
#
# ERROR CONVENTION (differs from the dashboard's multi-symbol endpoints on
# purpose): an unquotable symbol here is 404, not graceful degradation —
# when ONE symbol is the entire request there is nothing left to degrade
# to. Same verdict as watchlist-add and transaction-log.
#
# /api/search lives in this section too: it exists to feed the navbar's
# suggestion dropdown, whose whole job is navigating to this page.
# ---------------------------------------------------------------------------


@app.route("/stock/<symbol>")
def stock_page(symbol):
    """Render the detail-page shell. Rendering NEVER touches the network:
    the template ships blank placeholders and stock.js fills them from the
    JSON endpoints below — the same "browser does all rendering" rule as
    the dashboard. The uppercased symbol rides into the template so it can
    stamp <body data-symbol> (stock.js's identity hook) and <title>.

    One DB read rides along (never Yahoo): whether this symbol is already
    on the watchlist. Stamping the answer into the HTML (data-watched)
    lets stock.js paint the button's check mark at load — the alternative,
    a fetch on boot, would flicker and put a network call on the critical
    path. The symbol is uppercased FIRST so the lookup matches what the
    watchlist routes stored."""
    symbol = symbol.strip().upper()
    return render_template(
        "stock.html", symbol=symbol, watched=db.is_watched(symbol)
    )


@app.route("/api/search")
def ticker_search():
    """Turn a free-text query into ticker suggestions for the navbar.

    ?q=apple  ->  {"results": [{symbol, name, exchange, type}, ...]}

    An empty/missing q is a 400 BEFORE any network call (nothing to
    search). Empty results are a normal 200 with an empty list — the
    dropdown shows "No matches". A failed Yahoo search is a 503: the
    SEARCH service is unavailable and the dropdown says so, but the page
    keeps working — search is an entry point, not the page's data.
    """
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "query parameter q is required"}), 400

    try:
        results = search_tickers(query)
    except Exception:
        # Wide catch on purpose: yfinance fails in many ways. TIER 1 at
        # warning WITH the traceback — a dead search is a degraded app
        # (everything else still works), and the cause is not knowable
        # from the outside.
        app.logger.warning(
            "ticker search failed for %r — serving 503", query, exc_info=True,
        )
        return jsonify({"error": "search service unavailable"}), 503

    return jsonify({"results": results})


@app.route("/api/market/volume-leaders")
def volume_leaders():
    """Top 10 highest-volume stocks today, top 1 per market sector.

    Scans hardcoded sector leaders (2-3 liquid tickers per sector) and
    picks the highest-volume stock per sector, then returns the top 10
    overall by volume. Cached server-side for 5 minutes.

    Reply shape: {"leaders": [{symbol, name, price, change, change_pct,
                                volume}, ...]}

    Never a 500 — partial data is fine. If everything fails, the list
    is empty and the frontend shows a graceful empty state.
    """
    try:
        leaders = get_volume_leaders()
    except Exception:
        # Wide catch on purpose: volume leaders are a convenience feature,
        # not core data. A total failure degrades to an empty list — the
        # tab shows "No data available" rather than breaking the page.
        app.logger.warning("volume leaders fetch failed", exc_info=True)
        leaders = []

    return jsonify({"leaders": leaders})


@app.route("/api/quote/<symbol>")
def quote(symbol):
    """One security's live price — the LIGHTWEIGHT slice of
    /api/stock/<symbol> that the ledger's Ticker field calls to prefill the
    Price input when a symbol is picked (from the suggestion dropdown or the
    stock page's deep-link).

    Why a separate endpoint instead of reusing /api/stock/<symbol>: that
    route also fetches the display NAME via get_name (the heavy `Ticker.info`
    endpoint — process-lifetime cached, but slow on a cold process). The form
    only needs the number, so this route ships the get_quote dict alone and
    never touches get_name — picking a symbol on the ledger must feel instant,
    not like a company-profile lookup.

    Reply shape: exactly the get_quote dict (symbol, price, previous_close,
    currency, change, change_pct). Same contract as the other single-symbol
    routes: case-normalized, and an unquotable symbol is a plain 404 — the
    prefill silently leaves the price empty and the user types it (the POST
    route re-validates the ticker anyway).
    """
    # Same normalize-to-canonical-form rule as every symbol route.
    symbol = symbol.strip().upper()

    try:
        # Keep the route's response object independent from the data-layer
        # result, matching the decoration pattern used by stock_quote.
        return jsonify(dict(get_quote(symbol)))
    except Exception:
        # TIER 1 at INFO — same expected-client-behavior rule as stock_quote:
        # an unquotable symbol is usually a typo, not a malfunction.
        app.logger.info("quote failed for %s — serving 404", symbol)
        return jsonify({"error": f"unknown or unquotable symbol: {symbol}"}), 404


@app.route("/api/stock/<symbol>")
def stock_quote(symbol):
    """One security's live quote + display name — the detail page's polled
    endpoint (every 60s, like the dashboard's sections).

    Reply shape: the get_quote dict (symbol, price, previous_close,
    currency, change, change_pct) plus "name" — None when Yahoo's heavier
    name endpoint flakes, so the header falls back to the bare symbol
    (same degrade rule as the watchlist rows).
    """
    # Same normalize-to-canonical-form rule as every route that takes a
    # symbol from the URL: "aapl" and "AAPL" must hit the same cache slot.
    symbol = symbol.strip().upper()

    try:
        # Decorate a route-owned object. The market layer already returns a
        # defensive copy, and this keeps that ownership boundary explicit.
        quote = dict(get_quote(symbol))
    except Exception:
        # TIER 1 at INFO, no traceback: an unquotable symbol on a page the
        # user navigated to is usually a typo or a delisted ticker —
        # expected client behavior; the symbol string IS the story.
        app.logger.info("stock quote failed for %s — serving 404", symbol)
        return jsonify({"error": f"unknown or unquotable symbol: {symbol}"}), 404

    try:
        quote["name"] = get_name(symbol)
    except Exception:
        # A missing name must not sink the quote — TIER 1 at DEBUG, same
        # rule as the watchlist route (this endpoint is the flaky one).
        app.logger.debug(
            "no name available for %s — header shows symbol only", symbol,
            exc_info=True,
        )
        quote["name"] = None

    return jsonify(quote)


@app.route("/api/stock/<symbol>/stats")
def stock_stats(symbol):
    """The detail page's stats grid, fetched ONCE per page load (not
    polled): these numbers reset daily, and the endpoint behind them
    (Ticker.info) is the heaviest one yfinance offers."""
    symbol = symbol.strip().upper()

    try:
        return jsonify(get_stats(symbol))
    except Exception:
        # The quote worked (the page rendered) but stats didn't — degraded,
        # not dead. TIER 1 at warning with traceback: on screen the grid
        # just gap-fills to "—" and this log line is the reason.
        app.logger.warning(
            "stats fetch failed for %s — serving 404", symbol, exc_info=True,
        )
        return jsonify({"error": f"no stats available for {symbol}"}), 404


@app.route("/api/stock/<symbol>/history")
def stock_history(symbol):
    """One security's close prices over a timeframe — the raw line the
    chart plots. Same ?period= contract as /api/portfolio/history
    (validated against the same PERIOD_MAP), but no ledger math: the
    values ARE the closes.

    Without comparisons, get_history returns {label: close} and this route
    preserves the original raw-price reply. With `benchmark`, the primary
    symbol and every benchmark are rebased to growth-of-$100 on their union
    axis; failed benchmarks degrade independently while a failed primary
    remains a 404.
    """
    symbol = symbol.strip().upper()

    period = request.args.get("period", "5D").upper()
    if period not in PERIOD_MAP:
        # Identical validation to the portfolio route — same dict, same
        # "here are the valid options" reply.
        options = ", ".join(sorted(PERIOD_MAP))
        return jsonify({"error": f"period must be one of: {options}"}), 400

    try:
        benchmark_symbols = _parse_compare_symbols(
            request.args.get("benchmark", "")
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # The primary cannot be its own comparison. Keep this defensive rule at
    # the route boundary even though the picker also blocks it.
    benchmark_symbols = [
        benchmark for benchmark in benchmark_symbols if benchmark != symbol
    ]
    symbols = [symbol] + benchmark_symbols
    results = {}
    errors = {}

    def fetch_one(history_symbol):
        try:
            return history_symbol, get_history(history_symbol, period)
        except Exception:
            app.logger.warning(
                "stock comparison history failed for %s",
                history_symbol,
                exc_info=True,
            )
            return history_symbol, None

    with ThreadPoolExecutor(max_workers=min(len(symbols), 8)) as pool:
        for history_symbol, history in pool.map(fetch_one, symbols):
            if history is None:
                errors[history_symbol] = (
                    f"no history available for {history_symbol}"
                )
            else:
                results[history_symbol] = history

    if symbol in errors:
        return jsonify({"error": f"no history available for {symbol}"}), 404

    primary = results[symbol]
    if not benchmark_symbols:
        labels = sorted(primary)
        return jsonify({
            "labels": labels,
            "values": [primary[label] for label in labels],
        })

    all_labels = set(primary)
    for benchmark in benchmark_symbols:
        if benchmark in results:
            all_labels.update(results[benchmark])
    labels = sorted(all_labels)

    return jsonify({
        "labels": labels,
        "values": _rebase_series(labels, primary),
        "normalized": True,
        "benchmarks": [
            {
                "symbol": benchmark,
                "values": (
                    None if benchmark in errors
                    else _rebase_series(labels, results[benchmark])
                ),
                "error": errors.get(benchmark),
            }
            for benchmark in benchmark_symbols
        ],
    })


# This guard only runs the block when app.py is executed directly, not
# when it is imported by another module.
if __name__ == "__main__":
    # Start the built-in Flask development server, with debug mode enabled
    # (auto-reloads on code changes and shows detailed error pages).
    # host="0.0.0.0" means "listen on ALL network interfaces", so the server
    # is reachable from other machines on the LAN via this machine's IP
    # (e.g. http://<machine-ip>:5000), not just from this machine itself.
    app.run(debug=True, host="0.0.0.0")
