# Import the Flask class (used to create the app), render_template (serves
# Jinja2 HTML templates to the browser), jsonify (converts Python
# dicts/lists into a proper JSON HTTP response, including the
# Content-Type: application/json header), and request (gives access to the
# incoming HTTP request's data — we need its JSON body for the add route).
from flask import Flask, jsonify, render_template, request

# Import our data layers. This file is the "route layer": it decides WHICH
# symbols the page needs and HOW answers map to HTTP; market_data.py handles
# the HOW of fetching from Yahoo, db.py the HOW of persisting the watchlist
# and the transaction ledger.
from market_data import get_quote, get_name
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
            failures += 1

    # Only when EVERY symbol fails is the whole endpoint considered sick:
    # 503 = "Service Unavailable — it's me, not you, try again later."
    if failures == len(INDEX_SYMBOLS):
        return jsonify({"error": "quote service unavailable"}), 503

    # Successes only: failed symbols are simply absent from the list.
    # The frontend infers which chips to mark unavailable ("—").
    return jsonify(quotes)


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
            continue

        try:
            quote["name"] = get_name(symbol)
        except Exception:
            # A missing name shouldn't sink the whole row — the frontend
            # falls back to showing just the symbol.
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
        return jsonify({"error": f"unknown or unquotable symbol: {symbol}"}), 404

    try:
        db.add_symbol(symbol)
    except Exception:
        # The most likely DB failure here is the PRIMARY KEY violation from
        # adding a duplicate — report it as 409 Conflict ("it's already
        # there"), which is more precise than a generic 500.
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
# TRANSACTION LEDGER — log and list BUY/SELL events.
#
# The database stores immutable FACTS ONLY: nothing in the
# ledger table depends on a live market price. Total Value / Gain $ / Gain %
# are computed fresh on every GET request, from live quotes — never persisted.
#
# One naming subtlety: the JSON API uses short keys ("date", "type") because
# the browser writes them; the DB uses explicit columns ("transaction_date",
# "transaction_type") because schema is read by humans years later. The
# route is the translator between the two vocabularies.
# ---------------------------------------------------------------------------

@app.route("/api/transactions", methods=["POST"])
def log_transaction():
    """Record one transaction. The browser POSTs JSON like:
        {"ticker": "AAPL", "date": "2026-08-31", "price": 229.50,
         "qty": 10, "type": "BUY"}
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "expected JSON body with ticker, date, price, qty, type"}), 400

    # --- Validate every field BEFORE touching the DB (fail fast, fail clear).
    # Each check returns its own 400 with a message naming the bad field, so
    # a caller always knows exactly what to fix.

    # Ticker: same trim + uppercase normalization as the watchlist add route
    # — one canonical form everywhere ("aapl" and "AAPL" must match).
    ticker = str(body.get("ticker", "")).strip().upper()
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400

    # Date: fromisoformat is the whole validation — it raises ValueError for
    # anything that isn't a real calendar date in "YYYY-MM-DD" form (Feb 30,
    # "08/31/2026", "yesterday"...). .isoformat() then gives back canonical
    # text, so what we store is always uniform.
    try:
        transaction_date = date.fromisoformat(str(body.get("date", ""))).isoformat()
    except ValueError:
        return jsonify({"error": "date must be YYYY-MM-DD (a real calendar date)"}), 400

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
            return error

    # Type: normalize, then allow only the two verbs a ledger knows.
    transaction_type = str(body.get("type", "")).strip().upper()
    if transaction_type not in ("BUY", "SELL"):
        return jsonify({"error": "type must be BUY or SELL"}), 400

    # Prove the ticker is real BEFORE storing it (same rule as the watchlist
    # add route: unknown tickers get 404, never a row). The successful call
    # doubles as the currency source: the quote knows the security's trading
    # currency, so the user never types it — and the price cache gets warmed
    # for the ledger UI's later gain calculations.
    try:
        quote = get_quote(ticker)
    except Exception:
        return jsonify({"error": f"unknown or unquotable symbol: {ticker}"}), 404
    currency = quote["currency"]

    # All checks passed — write the immutable facts.
    tx_id = db.add_transaction(
        ticker=ticker,
        transaction_date=transaction_date,
        price=body["price"],
        qty=body["qty"],
        currency=currency,
        transaction_type=transaction_type,
    )

    # 201 Created, echoing the stored row (note the DB's explicit column
    # names in the reply — the browser now learns the ledger's vocabulary).
    return jsonify({
        "id": tx_id,
        "ticker": ticker,
        "transaction_date": transaction_date,
        "price": body["price"],
        "qty": body["qty"],
        "currency": currency,
        "transaction_type": transaction_type,
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


# This guard only runs the block when app.py is executed directly, not
# when it is imported by another module.
if __name__ == "__main__":
    # Start the built-in Flask development server, with debug mode enabled
    # (auto-reloads on code changes and shows detailed error pages).
    app.run(debug=True)
