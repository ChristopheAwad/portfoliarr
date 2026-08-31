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
