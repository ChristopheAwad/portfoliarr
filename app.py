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
from market_data import get_quote, get_name, get_history, PERIOD_MAP
import db

# datetime's date class knows how to both VALIDATE and NORMALIZE dates:
# date.fromisoformat("2026-08-31") raises ValueError on garbage, and its
# .isoformat() hands back the same canonical "YYYY-MM-DD" text we store.
from datetime import date

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
    and at each day multiply that quantity by the ticker's close. Sum
    across tickers = portfolio value that day. Before a ticker's first
    buy its quantity is 0, so it contributes nothing until you own it.
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

        # Sum each ticker's held quantity × its close price at this label.
        total = 0.0
        for symbol, held in net_qty.items():
            if held != 0:
                # .get(label, 0): a day where Yahoo has no bar for this
                # ticker (holiday, delisted) counts as holding it at 0 —
                # a deliberate flat line rather than a gap.
                total += held * histories[symbol].get(label, 0)
        values.append(total)

    return jsonify({"labels": labels, "values": values})


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

    # All checks passed — write the immutable facts.
    tx_id = db.add_transaction(
        ticker=ticker,
        transaction_date=fields["transaction_date"],
        price=fields["price"],
        qty=fields["qty"],
        currency=currency,
        transaction_type=fields["transaction_type"],
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
        "transaction_type": fields["transaction_type"],
    }), 201


@app.route("/api/transactions")
def list_transactions():
    """Return every transaction, newest first: facts + live math.

    Each row's stored facts (date, price, qty, currency, type) come straight
    from the DB. On top, this route attaches the display numbers the ledger
    UI needs — price_now, value, total_gain, total_gain_pct, day_gain,
    day_gain_pct — computed HERE, per request, from live quotes. This is the
    facts-only rule working as designed: the numbers exist for exactly one
    response, then vanish. Nothing stale is ever persisted.

    Why decorate server-side? The ledger can hold tickers the user never
    added to the watchlist, so the browser has no other way to price them —
    and this keeps main.js a pure renderer (numbers in, text out), matching
    the architecture rule in AGENTS.md.
    """
    transactions = db.get_transactions()

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

    for tx in transactions:
        quote = quotes[tx["ticker"]]
        if quote is None:
            continue  # undecorated row; the frontend gap-fills with "—"

        live_price = quote["price"]
        bought_at = tx["price"]  # the stored fact, NOT the live price
        tx["price_now"] = live_price
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
        # scaled by the position size. Its % companion is the quote's own
        # change_pct UNCHANGED: a % move is a property of the price, not
        # the position — identical for 1 share or 1000.
        #
        # Fun edge case: a transaction dated TODAY shows total ≈ day gain
        # (bought today, so its whole lifetime IS today). Correct, not a bug.
        tx["day_gain"] = quote["change"] * tx["qty"]
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
    """
    # 404 BEFORE validation: when the id is the wrong part, "no transaction
    # with that id" is the useful answer — field-checking a nonexistent row
    # would just confuse. (Flask's <int:tx_id> converter 404s non-numeric
    # ids before this code even runs.)
    if db.get_transaction(tx_id) is None:
        return jsonify({"error": f"no transaction with id {tx_id}"}), 404

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "expected JSON body with date, price, qty, type"}), 400

    # Same validator as POST — one set of rules, no drift (see its docstring).
    fields, error = validate_tx_fields(body)
    if error:
        return error

    # update_transaction's SET list only names the four editable columns,
    # so ticker/currency physically cannot change here. A False return
    # means the row vanished between the existence check and the UPDATE
    # (deleted in another window) — same 404 as above.
    if not db.update_transaction(
        tx_id,
        transaction_date=fields["transaction_date"],
        price=fields["price"],
        qty=fields["qty"],
        transaction_type=fields["transaction_type"],
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


# This guard only runs the block when app.py is executed directly, not
# when it is imported by another module.
if __name__ == "__main__":
    # Start the built-in Flask development server, with debug mode enabled
    # (auto-reloads on code changes and shows detailed error pages).
    app.run(debug=True)
