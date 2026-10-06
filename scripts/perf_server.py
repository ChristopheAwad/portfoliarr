"""Throwaway performance-measurement server: the whole Flask app on :5002
backed by a TEMP database in a fresh temp directory.

Same safety rule as capture_server.py: `db.DB_PATH` is redirected BEFORE
`app` is imported, so the import-time `db.init()` and every later write
land in the throwaway file — the real instance/ ledger is never touched.

Run with the VENV python (Flask lives there):
    .venv/bin/python scripts/perf_server.py

Environment:
    PERF_PORT            listen port (default 5002)
    PERF_STUB_YAHOO_MS   when set to a positive integer, replace every
                         market-data network call with a fixed-latency
                         deterministic fake. This removes Yahoo's network
                         variance so app-level changes (extra calls,
                         parallelism, caching) are what the numbers show.
                         Unset: live Yahoo, the real user experience.

The companion driver is scripts/measure_perf.py (SYSTEM python).
"""

import os
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

# Run from anywhere; the repo root is this file's grandparent.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TMP = Path(tempfile.mkdtemp(prefix="portfoliarr-perf-"))

os.environ.setdefault("TZ", "America/Toronto")

# Redirect FIRST: db._connect() reads DB_PATH at call time, and app.py
# runs db.init() at import — against the already-redirected path.
import db  # noqa: E402

db.DB_PATH = TMP / "perf.db"
db.init()

import app as app_module  # noqa: E402


def install_yahoo_stub(module, delay_ms):
    """Patch app.py's imported market functions with canned, delayed data.

    Shapes mirror conftest.py's fake_market, but generated for ANY symbol
    so the market overview's full category list resolves. Every call pays
    `delay_ms` — the simulator's stand-in for one Yahoo round trip.
    """
    delay = delay_ms / 1000.0

    def quote(symbol):
        time.sleep(delay)
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

    def name(symbol):
        time.sleep(delay)
        return f"{symbol} Holdings"

    def history(symbol, period_key):
        time.sleep(delay)
        if period_key == "1D":
            labels = [f"{9 + i // 12:02d}:{(i % 12) * 5:02d}"
                      for i in range(78)]
        elif period_key == "5D":
            labels = [f"day{i}" for i in range(65)]
        else:
            end = date.today()
            labels = [(end - timedelta(days=200 - i)).isoformat()
                      for i in range(201)]
        return {label: 100.0 + index * 0.1
                for index, label in enumerate(labels)}

    def stats(symbol):
        time.sleep(delay)
        return {"open": 100.0, "prev_close": 99.0, "volume": 1_000_000,
                "sector": "Technology", "quote_type": "EQUITY"}

    def financials(symbol):
        time.sleep(delay)
        keys = ["total_revenue", "cost_of_revenue", "gross_profit",
                "operating_expense", "operating_income", "total_expenses",
                "net_income", "diluted_eps"]
        return {"years": ["2022", "2023", "2024", "2025"],
                "rows": {key: [1.0, 2.0, 3.0, 4.0] for key in keys}}

    def events(symbol):
        time.sleep(delay)
        return {"earnings_date": "2026-11-01", "ex_dividend_date": None,
                "dividend_date": None, "ttm_total": 1.0, "recent": []}

    def profile(symbol):
        time.sleep(delay)
        return {"sector": "Technology", "country": "United States",
                "quote_type": "EQUITY", "market_cap": 1_000_000_000.0}

    def fx_rate(base, target):
        if base == target:
            return 1.0
        time.sleep(delay)
        return 1.35

    def fx_rate_on(base, target, date_iso):
        if base == target:
            return 1.0
        time.sleep(delay)
        return 1.35

    def price_on(symbol, date_iso):
        time.sleep(delay)
        return 100.0

    def search(query, limit=8):
        time.sleep(delay)
        return [{"symbol": (query.strip().upper() or "AAPL")[:6],
                 "name": "Search Hit", "exchange": "NASDAQ",
                 "type": "Equity"}]

    def volume_leaders():
        time.sleep(delay)
        return [{"symbol": f"VOL{i}", "name": f"Volume {i}", "price": 100.0,
                 "change": 1.0, "change_pct": 1.0, "volume": 10_000_000 - i}
                for i in range(10)]

    module.get_quote = quote
    module.get_name = name
    module.get_history = history
    module.get_stats = stats
    module.get_financials = financials
    module.get_events = events
    module.get_profile = profile
    module.get_fx_rate = fx_rate
    module.get_fx_rate_on = fx_rate_on
    module.get_price_on = price_on
    module.search_tickers = search
    module.get_volume_leaders = volume_leaders


STUB_MS = int(os.environ.get("PERF_STUB_YAHOO_MS", "0") or "0")
if STUB_MS > 0:
    install_yahoo_stub(app_module, STUB_MS)

PORT = int(os.environ.get("PERF_PORT", "5002"))

print("THROWAWAY-DATA:", TMP)
print("PERF-STUB-YAHOO-MS:", STUB_MS)

app_module.app.run(debug=False, port=PORT)
