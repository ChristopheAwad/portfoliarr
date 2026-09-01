"""Market data access layer.

Fetches quotes from Yahoo Finance via yfinance, with a short-lived
in-memory cache so repeated requests don't hammer Yahoo (rate limits).

This module knows nothing about Flask or HTTP — routes decide that.
"""

import time

import yfinance as yf

# How long a cached quote stays trustworthy, in seconds.
TTL_SECONDS = 120

# Module-level cache: {symbol: {"data": <quote dict>, "fetched_at": <epoch seconds>}}
# Lives as long as the Flask process does; starts empty on every restart.
_cache = {}

# Company-name cache: {symbol: "Apple Inc"}. Different data, different
# policy: a company's name never changes, so entries stay valid forever —
# no TTL, no timestamps. One Yahoo call per symbol per process lifetime.
_name_cache = {}

# The page's timeframe buttons map to a Yahoo "period" + "interval" pair.
# This dict is the single source of truth for that mapping, shared by
# get_history (the HOW of fetching) and the portfolio-history route (also
# uses its keys to validate a client-supplied timeframe string).
#
#   period   — how far back Yahoo goes ("1d", "5d", "3mo", "max"...)
#   interval — the spacing of data points within that range:
#              "5m" for 1D (intraday every 5 minutes),
#              "1d" for everything else (one close per trading day).
PERIOD_MAP = {
    "1D":  {"period": "1d",  "interval": "5m"},
    "5D":  {"period": "5d",  "interval": "1d"},
    "1M":  {"period": "1mo", "interval": "1d"},
    "3M":  {"period": "3mo", "interval": "1d"},
    "6M":  {"period": "6mo", "interval": "1d"},
    "YTD": {"period": "ytd", "interval": "1d"},
    "1Y":  {"period": "1y",  "interval": "1d"},
    "5Y":  {"period": "5y",  "interval": "1d"},
    "MAX": {"period": "max", "interval": "1d"},
}


def get_quote(symbol):
    """Return a quote dict for `symbol`, serving from cache when fresh.

    Raises on network failure or bad data — the caller (route layer)
    decides how to translate that into an HTTP response.
    """
    # 1. Cache check — is our copy young enough to trust?
    now = time.time()
    entry = _cache.get(symbol)
    if entry and (now - entry["fetched_at"]) < TTL_SECONDS:
        return entry["data"]  # cache hit: no network involved

    # 2. Cache miss — pay the network cost, exactly as in the scratch script
    fi = yf.Ticker(symbol).fast_info
    price = fi["lastPrice"]
    previous_close = fi["previousClose"]

    # 3. Defensive guard: turn a would-be ZeroDivisionError (or None price)
    #    into a deliberate, named error with a useful message.
    if not price or not previous_close:
        raise ValueError(f"incomplete quote data for {symbol}")

    # 4. Build the payload — raw floats only; formatting is the frontend's job
    data = {
        "symbol": symbol,
        "price": price,
        "previous_close": previous_close,
        "currency": fi["currency"],
    }
    data["change"] = price - previous_close
    data["change_pct"] = data["change"] / previous_close * 100

    # 5. Remember it (with its timestamp), then hand it back
    _cache[symbol] = {"data": data, "fetched_at": now}
    return data


def get_name(symbol):
    """Return the human-readable company name for `symbol` (e.g. "Apple Inc").

    Uses Ticker.info — a heavier Yahoo endpoint than fast_info (it fetches
    the full company profile), which is exactly why we cache its result for
    the process lifetime.

    Raises on failure or missing name — same boundary rule as get_quote:
    this layer reports problems, the route layer decides the HTTP response.
    """
    # Cache check: after the first success this is a pure dict lookup.
    if symbol in _name_cache:
        return _name_cache[symbol]

    # Cache miss: pay the (slow) network cost once.
    info = yf.Ticker(symbol).info
    # shortName is Yahoo's display name; longName is the fuller legal one.
    # `or` falls back when shortName is missing or empty — either is fine
    # to show, so we take whichever exists.
    name = info.get("shortName") or info.get("longName")

    if not name:
        raise ValueError(f"no name available for {symbol}")

    _name_cache[symbol] = name
    return name


def get_history(symbol, period_key):
    """Return a {label: close_price} dict for `symbol` over a timeframe.

    Used by the portfolio-value chart, which multiplies each ticker's
    close price by its held quantity on every date (or intraday tick)
    to plot portfolio value over time.

    `period_key` is one of the PERIOD_MAP keys ("5D", "1M"...); it is
    looked up here so both the validation keys and the fetch go through
    the same dict.

    The returned dict maps a plain-string label to that point's CLOSE
    price (the standard "price at end of that bar"):
      - Daily ranges ("5D"...): label is "YYYY-MM-DD" ("2026-08-31").
      - Intraday (1D):         label is "HH:MM" ("09:30").

    These plain strings are exactly what the frontend wants for
    Chart.js x-axis labels — no timezone math leaked to the browser.

    Raises on failure — same boundary rule as get_quote: this layer
    reports problems, the route layer decides the HTTP response.
    """
    # Unpack the chosen timeframe into the two args yfinance wants.
    timeframe = PERIOD_MAP[period_key]
    df = yf.Ticker(symbol).history(
        period=timeframe["period"],
        interval=timeframe["interval"],
    )

    # df is a pandas DataFrame indexed by timezone-aware timestamps
    # (e.g. 2026-08-31 00:00:00-04:00). We want a plain {label: price}
    # dict, so walk each (timestamp, row) pair and key it by a clean
    # string: the date part for daily bars, the time part for intraday.
    result = {}
    for ts, row in df.iterrows():
        # Daily bars: "YYYY-MM-DD" (the first 10 chars of the ISO text).
        # Intraday bars: keep just the "HH:MM" time to keep labels short.
        label = ts.strftime("%Y-%m-%d") if timeframe["interval"] == "1d" \
            else ts.strftime("%H:%M")
        result[label] = float(row["Close"])
    return result
