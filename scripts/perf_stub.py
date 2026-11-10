"""Deterministic market-data payloads for the performance harness.

Pure builders only: no Flask, no network, no database, no side effects.
`perf_server.py` wraps them with its fixed latency and patches them onto
`app.py`'s imported market functions; `tests/test_perf_harness.py` checks
that their shapes keep matching the real getters and the page scripts.

Every label and field comes from the same contracts the app uses:

- History labels follow `market_data.PERIOD_MAP`'s `label` format. The
  intraday formats ("%Y-%m-%d %H:%M") always carry a date, so a label is
  never a bare "09:30" that two sessions could collide under.
- The stats payload carries every key `get_stats` returns, including the
  analyst `recommendation` string the stock page title-cases. A missing
  string there used to crash `stock.js` and made the report look clean.
- Financials and events use the reply shapes their routes serve, with a
  real dividend row so the collapsed table is exercised.
"""

from datetime import date, datetime, timedelta
import time

from market_data import PERIOD_MAP


# (step, bar count) per PERIOD_MAP key. The step only shapes the fake axis;
# no route reads it. Each count keeps labels unique and the last bar on
# today, so a transaction dated today still prices.
_BARS = {
    "1D": (timedelta(minutes=5), 78),
    "5D": (timedelta(minutes=30), 65),
    "1M": (timedelta(hours=1), 140),
    "3M": (timedelta(days=1), 92),
    "6M": (timedelta(days=1), 183),
    "YTD": (timedelta(days=1), 200),
    "1Y": (timedelta(days=1), 365),
    "5Y": (timedelta(weeks=1), 260),
    "MAX": (timedelta(days=30), 300),
}


def history_labels(period_key, now=None):
    """Ascending, unique labels in PERIOD_MAP's format for `period_key`."""
    period = PERIOD_MAP[period_key]
    step, count = _BARS[period_key]
    anchor = (now or datetime.now()).replace(second=0, microsecond=0)
    if step >= timedelta(days=1):
        # Pin the time so DST cannot shift a date label across a day.
        anchor = anchor.replace(hour=12, minute=0)
    labels = []
    moment = anchor
    for _ in range(count):
        labels.append(moment.strftime(period["label"]))
        moment -= step
    labels.reverse()
    # A wall-clock step can repeat a label across a DST fall-back; the
    # dict reply would silently collapse the duplicate. Keep first-seen
    # (still ascending) so the contract "unique labels" holds.
    seen = set()
    unique = []
    for label in labels:
        if label not in seen:
            seen.add(label)
            unique.append(label)
    return unique


def history_payload(symbol, period_key):
    """The {label: close} shape `get_history` returns, deterministic."""
    seed = sum(ord(ch) for ch in symbol)
    return {
        label: round(100 + (seed % 17) + index * 0.1, 2)
        for index, label in enumerate(history_labels(period_key))
    }


def quote_payload(symbol):
    seed = sum(ord(ch) for ch in symbol)
    price = round(50 + seed % 950 + 0.25, 2)
    previous = round(price - 1.5, 2)
    return {
        "symbol": symbol,
        "price": price,
        "previous_close": previous,
        "currency": "CAD" if symbol.endswith(".TO") else "USD",
        "change": round(price - previous, 2),
        "change_pct": round((price - previous) / previous * 100, 4),
    }


def name_payload(symbol):
    return f"{symbol} Holdings"


def stats_payload(symbol):
    """Every key the real getter returns; plausible values, no None traps."""
    seed = sum(ord(ch) for ch in symbol)
    price = 50 + seed % 950
    return {
        "open": price - 0.5,
        "day_high": price + 1.25,
        "day_low": price - 1.75,
        "prev_close": price - 1.5,
        "volume": 1_000_000 + seed * 1_000,
        "week52_low": price * 0.7,
        "week52_high": price * 1.3,
        "market_cap": price * 1_000_000_000,
        "pe_ratio": 21.4,
        "forward_pe": 18.2,
        "price_to_book": 4.1,
        "peg_ratio": 1.8,
        "eps": 6.32,
        "dividend_yield": 2.63,
        "payout_ratio": 34.5,
        "beta": 1.12,
        "fifty_day_average": price * 0.97,
        "two_hundred_day_average": price * 0.93,
        "avg_volume": 12_500_000,
        "gross_margin": 48.6,
        "operating_margin": 31.2,
        "profit_margin": 24.8,
        "return_on_equity": 42.1,
        "revenue_growth": 8.4,
        "earnings_growth": 11.2,
        "total_cash": 62_000_000_000,
        "total_debt": 98_000_000_000,
        "debt_to_equity": 78.4,
        "free_cashflow": 55_000_000_000,
        "ebitda": 130_000_000_000,
        "shares_outstanding": 15_000_000_000,
        "float_shares": 14_900_000_000,
        "target_price": price * 1.08,
        "target_low": price * 0.9,
        "target_high": price * 1.3,
        "target_median": price * 1.07,
        "recommendation": "buy",
        "recommendation_mean": 1.9,
        "num_analyst_opinions": 38,
        "employees": 164_000,
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "country": "United States",
        "quote_type": "EQUITY",
        "website": "https://example.com",
        "business_summary": (
            "Synthetic company profile used only by the performance harness."
        ),
    }


def financials_payload(symbol):
    years = ["2022", "2023", "2024", "2025"]
    rows = {
        "total_revenue": [394_328.0, 383_285.0, 391_035.0, 400_000.0],
        "cost_of_revenue": [223_546.0, 214_137.0, 210_352.0, 215_000.0],
        "gross_profit": [170_782.0, 169_148.0, 180_683.0, 185_000.0],
        "operating_expense": [51_345.0, 54_847.0, 57_467.0, 58_000.0],
        "operating_income": [119_437.0, 114_301.0, 123_216.0, 127_000.0],
        "total_expenses": [274_891.0, 268_984.0, 267_819.0, 273_000.0],
        "net_income": [99_803.0, 96_995.0, 93_736.0, 100_000.0],
        "diluted_eps": [6.11, 6.13, 6.08, 6.50],
    }
    return {"years": years, "rows": rows}


def events_payload(symbol):
    today = date.today()
    return {
        "earnings_date": (today + timedelta(days=30)).isoformat(),
        "ex_dividend_date": (today + timedelta(days=10)).isoformat(),
        "dividend_date": (today + timedelta(days=12)).isoformat(),
        "ttm_total": 1.0,
        "recent": [
            {"date": (today - timedelta(days=90)).isoformat(),
             "amount": 0.25},
            {"date": (today - timedelta(days=180)).isoformat(),
             "amount": 0.24},
        ],
    }


def profile_payload(symbol):
    return {
        "sector": "Technology",
        "country": "United States",
        "quote_type": "EQUITY",
        "market_cap": 1_000_000_000.0,
        "asset_mix": None,
        "sector_mix": None,
        "fund_degraded": False,
    }


def fx_rate_payload(base, target, date_iso=None):
    # `get_fx_rate` calls with two args; `get_fx_rate_on` adds the date.
    return 1.0 if base == target else 1.35


def price_on_payload(symbol, date_iso):
    return 100.0


def search_payload(query, limit=8):
    return [{
        "symbol": (query.strip().upper() or "AAPL")[:6],
        "name": "Search Hit",
        "exchange": "NASDAQ",
        "type": "Equity",
    }]


def volume_leaders_payload():
    return [
        {
            "symbol": f"VOL{i}",
            "name": f"Volume {i}",
            "price": 100.0,
            "change": 1.0,
            "change_pct": 1.0,
            "volume": 10_000_000 - i,
        }
        for i in range(10)
    ]


def install_yahoo_stub(module, delay_ms, empty_stock=False):
    """Patch a module's imported market functions with latched builders.

    The target is `app.py` (whose route layer imported the names), NOT
    `market_data.yf`, so the real process caches are bypassed. That is
    deliberate: it makes app-level call counts and parallelism visible,
    but stub mode must never be read as real cache performance.

    Each patched call sleeps `delay_ms` first — the stand-in for one Yahoo
    round trip — so parallel work still shows up as overlapping waits.
    """
    delay = delay_ms / 1000.0

    def paced(builder):
        def call(*args, **kwargs):
            time.sleep(delay)
            return builder(*args, **kwargs)
        return call

    if empty_stock:
        def no_financials(symbol):
            raise ValueError(f"no financials data for {symbol}")

        def no_events(symbol):
            raise ValueError(f"no events data for {symbol}")

        def empty_stats(symbol):
            return {key: None for key in stats_payload(symbol)}

        module.get_stats = paced(empty_stats)
        module.get_financials = paced(no_financials)
        module.get_events = paced(no_events)
    else:
        module.get_stats = paced(stats_payload)
        module.get_financials = paced(financials_payload)
        module.get_events = paced(events_payload)

    module.get_quote = paced(quote_payload)
    module.get_name = paced(name_payload)
    module.get_history = paced(history_payload)
    module.get_profile = paced(profile_payload)
    module.get_fx_rate = paced(fx_rate_payload)
    module.get_fx_rate_on = paced(fx_rate_payload)
    module.get_price_on = paced(price_on_payload)
    module.search_tickers = paced(search_payload)
    module.get_volume_leaders = paced(volume_leaders_payload)

