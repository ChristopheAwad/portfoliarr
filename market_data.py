"""Market data access layer.

Fetches market data from Yahoo Finance via yfinance: live quotes (with a
short-lived in-memory cache so repeated requests don't hammer Yahoo),
company names, stats-grid numbers, price history, and free-text ticker
search.

This module knows nothing about Flask or HTTP — routes decide that.
"""

import time

import yfinance as yf

# date/timedelta build the lookup window for get_fx_rate_on: it fetches a
# small calendar range of daily bars around the transaction's date and
# picks the close on-or-before it.
from datetime import date, timedelta

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


def get_stats(symbol):
    """Return the stock detail page's stats-grid numbers for `symbol`.

    Shares the heavy `Ticker.info` endpoint with get_name (the full
    company profile — slower than fast_info but the only place Yahoo
    exposes these fields). Deliberately NOT cached: names never change,
    but these figures reset every trading day, so a process-lifetime
    cache would serve yesterday's numbers all week. The route fetches
    stats once per page load, so the cost is one call per visit.

    Returns snake_case keys for the grid — the route layer's convention
    of translating Yahoo's camelCase at this boundary:
        open / day_high / day_low   today's bar so far
        prev_close                  yesterday's last price
        volume                      shares traded today
        week52_low / week52_high    the 52-week range
        market_cap                  shares outstanding × price

    MISSING FIELDS → None, not an error: different security types
    legitimately lack different figures (an index has no marketCap, crypto
    has no volume on some venues). The frontend gap-fills those cells with
    "—", the same visual convention as a failed quote. Only TOTAL failure
    (Yahoo returns nothing at all) raises — the boundary rule: this layer
    reports, the route layer decides the HTTP response.
    """
    info = yf.Ticker(symbol).info

    # An empty profile means Yahoo knows nothing about this symbol —
    # fail loudly with a named error instead of returning eight Nones
    # that would masquerade as "real but empty" stats.
    if not info:
        raise ValueError(f"no stats data for {symbol}")

    # .get() everywhere: absent fields become None (see docstring). The
    # prev_close fallback covers Yahoo's two spellings of the same fact —
    # most tickers carry "regularMarketPreviousClose", a few only
    # "previousClose". (Same `or` fallback pattern as get_name.)
    return {
        "open": info.get("open"),
        "day_high": info.get("dayHigh"),
        "day_low": info.get("dayLow"),
        "prev_close": (
            info.get("regularMarketPreviousClose")
            or info.get("previousClose")
        ),
        "volume": info.get("volume"),
        "week52_low": info.get("fiftyTwoWeekLow"),
        "week52_high": info.get("fiftyTwoWeekHigh"),
        "market_cap": info.get("marketCap"),
    }


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


# ── FX rates — the CAD display layer's exchange rates ─────────────────
#
# Yahoo lists currency pairs as regular quotable symbols: "USDCAD=X" is
# "how many CAD one USD buys", and its live price / daily closes are
# fetched exactly like any stock's. That means the LIVE rate rides the
# existing quote cache for free (same symbol every 60s poll), while the
# HISTORICAL rate is a one-shot history fetch per lookup.
#
# Only base→target pairs in Yahoo's "<BASE><TARGET>=X" form are supported
# here — the app's display policy is USD↔CAD, nothing else.


def get_fx_rate(base, target):
    """Return the LIVE exchange rate: how many `target` units one `base`
    unit buys right now.

    Same-currency asks (CAD→CAD) answer 1.0 WITHOUT touching the network
    — a rate of one is arithmetic, not data. Anything else builds the
    Yahoo pair symbol and goes through get_quote, inheriting its 120s
    cache and its raise-on-failure boundary rule.
    """
    if base == target:
        return 1.0
    return get_quote(f"{base}{target}=X")["price"]


def get_fx_rate_on(base, target, date_iso):
    """Return the pair's daily CLOSE on-or-before `date_iso` — the
    historical fact a ledger row stores as its conversion rate.

    Why on-or-before: the ledger's dates are calendar days, markets close
    on weekends/holidays, and a Saturday buy's "rate at the time of
    buying" is the last close the market actually printed (Friday's).
    That's the same spirit as the portfolio chart's next-trading-day
    rule, applied to a cost fact instead of a value.

    The fetch is a small calendar WINDOW (ten days back covers every
    long weekend; one day forward so the date itself is included —
    yfinance's `end` is exclusive) rather than a PERIOD_MAP period,
    because the input here is a specific date, not a chart button.

    Raises ValueError when no bar covers the date (a Yahoo gap, a brand-
    new pair) — the route layer decides what an unavailable historical
    rate means (fall back to the live rate, store NULL, ...).
    """
    if base == target:
        return 1.0

    d = date.fromisoformat(date_iso)
    df = yf.Ticker(f"{base}{target}=X").history(
        start=(d - timedelta(days=10)).isoformat(),
        end=(d + timedelta(days=1)).isoformat(),
        interval="1d",
    )

    # Walk the (ascending) bars and keep the last close whose calendar
    # day is on-or-before the target date. A bar AFTER it means we've
    # walked past the answer — stop early.
    rate = None
    for ts, row in df.iterrows():
        if ts.date() <= d:
            rate = float(row["Close"])
        else:
            break

    if rate is None:
        raise ValueError(
            f"no {base}{target} close on or before {date_iso}"
        )
    return rate


def search_tickers(query, limit=8):
    """Search Yahoo's ticker universe for a free-text query.

    Powers the navbar's search suggestions. yf.Search is Yahoo's own
    search endpoint — the same one finance.yahoo.com's search box uses —
    so anything typed there finds here: stocks, ETFs, indices, crypto,
    international tickers (the brief's "anything Yahoo has is searchable").

    Returns a list of normalized hits, best match first (Yahoo ranks
    them), each shaped for the dropdown:
        symbol    "AAPL", "BTC-USD" — the navigation target
        name      "Apple Inc." — shortname, falling back to longname
                  (same `or` fallback as get_name)
        exchange  "NASDAQ" — the FRIENDLY display name (exchDisp) when
                  Yahoo offers it, the raw code ("NMS") otherwise
        type      "Equity", "ETF", "Index", "Cryptocurrency" — lets the
                  dropdown badge what kind of thing each hit is

    No cache, on purpose (decision recorded in feature.md): searches are
    user-typed and effectively unique, so a cache would almost never hit —
    unlike quotes (same symbol every 60s) or names (never change).

    Returns [] when nothing matches — a normal state, not an error.
    Raises on network failure — the boundary rule: this layer reports,
    the route layer decides the HTTP response.
    """
    results = []
    for hit in yf.Search(query, max_results=limit).quotes:
        symbol = hit.get("symbol")
        # A hit without a symbol can't be navigated to — skip it rather
        # than let the dropdown offer a link to /stock/None.
        if not symbol:
            continue
        results.append({
            "symbol": symbol,
            "name": hit.get("shortname") or hit.get("longname"),
            "exchange": hit.get("exchDisp") or hit.get("exchange"),
            "type": hit.get("typeDisp"),
        })
    return results
