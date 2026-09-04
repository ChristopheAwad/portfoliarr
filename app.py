# time gives us perf_counter(), a monotonic high-resolution clock — used
# by the request-timing hook in the LOGGING section below.
import time

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
    get_quote, get_name, get_stats, get_history, search_tickers,
    get_fx_rate, get_fx_rate_on, PERIOD_MAP
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
# Define the "index" view function. Flask calls it whenever the root URL
# is requested, and its return value becomes the HTTP response.
def index():
    # Render "index.html". The watchlist used to be passed in here as a
    # Jinja variable, but its rows are now built by JavaScript from
    # /api/watchlist (they're dynamic — add/remove — so static server
    # rendering doesn't fit them).
    return render_template("index.html")


# JSON endpoint that powers the live indices bar. The browser's JavaScript
# fetches this URL. Returns a JSON *list* of quote dicts.
@app.route("/api/indices")
def index_quotes():
    # Per-symbol resilience: each chip is fetched independently, so one
    # dead symbol cannot blank the whole bar. Failures are skipped.
    quotes = []
    failures = 0
    for symbol in INDEX_SYMBOLS:
        try:
            quotes.append(get_quote(symbol))
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
            failures += 1

    # Only when EVERY symbol fails is the whole endpoint considered sick:
    # 503 = "Service Unavailable — it's me, not you, try again later."
    if failures == len(INDEX_SYMBOLS):
        # TIER 1: this is the endpoint's loudest cry for help — every
        # symbol failing at once usually means Yahoo is down or the
        # network is gone, not four unlucky symbols.
        app.logger.warning(
            "all %d index symbols failed — serving 503", len(INDEX_SYMBOLS)
        )
        return jsonify({"error": "quote service unavailable"}), 503

    # Successes only: failed symbols are simply absent from the list.
    # The frontend infers which chips to mark unavailable ("—").
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

@app.route("/api/portfolio/history")
def portfolio_history():
    """Return the portfolio's value over time as {labels, values}.

    Query param `period` is a PERIOD_MAP key ("5D", "1M"...); defaults
    to "5D" (the chart's default view, matching the 5D button's `active`
    class in index.html). Anything else gets a 400.

Algorithm: walk every trading day in the range forward, keeping a
    running "net quantity held" per ticker (buys add, sells subtract),
    and at each day multiply that quantity by the ticker's close price
    that day. Sum across tickers = portfolio value that day. Before a
    ticker's first buy its quantity is 0, so it contributes nothing
    until you own it. A day where a held ticker printed no bar (a
    holiday on its market, Yahoo's unfinalized current-day bar) prices
    the position at its last KNOWN close — carried forward, never at
    zero, because a holding doesn't evaporate between closes.
    """
    # Validate the timeframe key BEFORE doing any work. get_history()
    # indexes PERIOD_MAP directly, so a bad key would KeyError mid-loop;
    # catching it here (and returning the valid options) is friendlier.
    period = request.args.get("period", "5D").upper()
    if period not in PERIOD_MAP:
        options = ", ".join(sorted(PERIOD_MAP))
        return jsonify({"error": f"period must be one of: {options}"}), 400

    # The ledger's default sort is newest-first; we need the opposite to
    # walk history forward, so sort ascending here.
    transactions = sorted(
        db.get_transactions(),
        key=lambda tx: (tx["transaction_date"], tx["id"]),
    )

    # An empty ledger is a normal state, not an error — the frontend
    # shows "No transactions yet" and leaves the chart blank.
    if not transactions:
        return jsonify({"labels": [], "values": []})

    # Fetch each ticker's price history once. Per-ticker resilience, the
    # same rule as the indices bar: a dead/delisted ticker is skipped,
    # its contribution is 0 for the whole period — never a 503 for the
    # whole chart.
    histories = {}
    for tx in transactions:
        symbol = tx["ticker"]
        if symbol in histories:
            continue
        try:
            histories[symbol] = get_history(symbol, period)
        except Exception:
            # TIER 1: without a record, a dead ticker is indistinguishable
            # from "the user never traded it" — both contribute 0 and
            # flatten the line. The log separates the two.
            app.logger.warning(
                "history fetch failed for %s — contributes 0 to the chart",
                symbol,
                exc_info=True,
            )
            histories[symbol] = {}  # he can't be priced; treat as 0

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

    # Intraday (1D) labels are times ("09:30"), not dates ("2026-08-31") —
    # see get_history. So "which label applies which transaction" differs:
    #   Daily bars: a transaction dated that DAY applies at that day's bar.
    #   Intraday bars: every transaction dated TODAY applies at today's
    #     FIRST bar (they all happened during today's session, and we can't
    #     know the exact minute from a date-only ledger — applying at the
    #     open is the honest, simple choice).
    # Detect the case by the interval (same dict that drove the fetch), and
    # grab today's date once (same local-day rule the frontend's date input
    # uses, so a "today" trade prices into today's intraday chart).
    is_intraday = PERIOD_MAP[period]["interval"] != "1d"
    label_date_today = date.today().isoformat()

    # Walk each label forward, maintaining quantity per ticker. This is
    # the heart of the chart: buying shares must push the line up from
    # that point on; selling must pull it down. We only add/sell, never
    # average cost — that (more nuanced) math is a later feature.
    #
    # Applying transactions is date-driven, and a transaction's date may
    # NOT be a trading-day label (it was a weekend/holiday — e.g. the
    # user logs a "Saturday" buy). So we use a POINTER into the
    # sorted-by-date transaction list: at each label we apply every
    # transaction whose date is on-or-before it that we haven't applied
    # yet. A Saturday buy therefore lands on the NEXT trading day's bar,
    # which is the honest approximation available to us.
    net_qty = {}
    last_closes = {}  # symbol → its most recent known close (forward-fill)
    values = []
    tx_index = 0        # next un-applied daily transaction (advances through
                        # the sorted list); unused in the intraday branch
    today_applied = False  # intraday: have today's transactions been applied?
    for label in labels:
        # Choose which transactions this label should absorb, then apply
        # them BEFORE pricing (a buy today prices at today's close).
        if is_intraday:
            # Intraday facts: see the comment above — today's txs apply at
            # the first bar of today's session, once.
            if not today_applied:
                today_applied = True
                for tx in transactions:
                    if tx["transaction_date"] == label_date_today:
                        net_qty[tx["ticker"]] = (
                            net_qty.get(tx["ticker"], 0)
                            + (tx["qty"]
                               if tx["transaction_type"] == "BUY" else -tx["qty"])
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

    return jsonify({"labels": labels, "values": values})


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
    quotes = {}
    for symbol in net_qty:
        try:
            quotes[symbol] = get_quote(symbol)
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
            quotes[symbol] = None

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
        total_value += held * quote["price"] * value_rate
        day_gain += held * quote["change"] * value_rate
        # Cost: stored-rate amounts pass through; legacy unrated amounts
        # (USD rows with fx_rate NULL) convert at the live rate.
        cost_basis += (
            cost_stored.get(symbol, 0.0)
            + cost_unrated.get(symbol, 0.0)
              * (live_rate if currency == "USD" else 1.0)
        )

    unpriced.sort()  # stable, human-readable order for the tooltip

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

    quotes = []
    for symbol in symbols:
        try:
            # get_quote returns the object SHARED with the cache — mutating
            # it here would leak our edits into every future cache hit. So
            # copy it first, then decorate the copy with the name.
            quote = dict(get_quote(symbol))
        except Exception:
            # Same per-symbol resilience as the indices bar: a dead symbol
            # just won't appear in "quotes"; its row will gap-fill to "—".
            app.logger.warning(
                "watchlist quote failed for %s — row shows \"—\"", symbol,
                exc_info=True,
            )
            continue

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

        quotes.append(quote)

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
    except Exception:
        # The most likely DB failure here is the PRIMARY KEY violation from
        # adding a duplicate — report it as 409 Conflict ("it's already
        # there"), which is more precise than a generic 500. TIER 1: the
        # 409 reply can't tell a harmless duplicate from a REAL database
        # problem (locked file, full disk) — the traceback in the log can,
        # which is why a wide catch here logs at warning with exc_info.
        app.logger.warning(
            "watchlist insert failed for %s — serving 409", symbol,
            exc_info=True,
        )
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

    # One quote per UNIQUE ticker: a ledger with 30 AAPL trades pays for
    # exactly ONE quote (the 120s cache makes repeats free, and the dict
    # deduplicates within this request).
    quotes = {}
    for tx in transactions:
        symbol = tx["ticker"]
        if symbol in quotes:
            continue
        try:
            quotes[symbol] = get_quote(symbol)
        except Exception:
            # Same per-symbol resilience as everywhere else: a dead ticker
            # (delisted, Yahoo hiccup) must not sink the whole response.
            # None marks "couldn't quote" — its rows stay facts-only.
            quotes[symbol] = None

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
        row["id"] = db.add_transaction(
            ticker=row["ticker"],
            transaction_date=row["transaction_date"],
            price=row["price"],
            qty=row["qty"],
            currency=quote["currency"],
            transaction_type=row["transaction_type"],
            fx_rate=row["fx_rate"],
        )
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
    stamp <body data-symbol> (stock.js's identity hook) and <title>."""
    return render_template("stock.html", symbol=symbol.strip().upper())


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
        # COPY before decorating: get_quote hands back the object SHARED
        # with the cache — mutating it (adding "name") would leak our edit
        # into every future cache hit (the watchlist route learned this
        # first; same rule, new caller).
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

    get_history returns {label: close}; Chart.js wants parallel arrays, so
    sort the labels once and walk them. Plain-string labels sort
    chronologically in both shapes: "YYYY-MM-DD" dates, and (for the 1D
    intraday view) "HH:MM" times within their single day.
    """
    symbol = symbol.strip().upper()

    period = request.args.get("period", "5D").upper()
    if period not in PERIOD_MAP:
        # Identical validation to the portfolio route — same dict, same
        # "here are the valid options" reply.
        options = ", ".join(sorted(PERIOD_MAP))
        return jsonify({"error": f"period must be one of: {options}"}), 400

    try:
        closes = get_history(symbol, period)
    except Exception:
        # TIER 1 at warning: a chart that can't load is degraded page state
        # (the header/stats may still be fine) — the traceback says why.
        app.logger.warning(
            "history fetch failed for %s — serving 404", symbol,
            exc_info=True,
        )
        return jsonify({"error": f"no history available for {symbol}"}), 404

    labels = sorted(closes)
    return jsonify({
        "labels": labels,
        "values": [closes[label] for label in labels],
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
