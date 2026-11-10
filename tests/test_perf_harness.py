"""Contracts for the performance harness and its deterministic stub.

These tests guard the pieces that made the old report misleading: labels
that did not match PERIOD_MAP, payloads the pages could not paint, and a
stock-page console error that the report still called a clean run.
"""

import importlib.util
import json
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

import market_data

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_PYTHON = Path("/usr/bin/python3")


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


perf_stub = _load("perf_stub", "scripts/perf_stub.py")


@pytest.mark.parametrize("period_key", list(market_data.PERIOD_MAP))
def test_history_labels_follow_period_map(period_key):
    now = datetime(2026, 11, 10, 14, 37)
    labels = perf_stub.history_labels(period_key, now=now)
    fmt = market_data.PERIOD_MAP[period_key]["label"]

    assert labels == sorted(labels)
    assert len(labels) == len(set(labels))
    for label in labels:
        datetime.strptime(label, fmt)  # raises on a shape drift
    # Today's transaction must land on a bar: the last label carries today
    # for every period, including the date-only long ranges.
    assert labels[-1].startswith("2026-11-10")


def test_stub_stats_matches_the_real_getter_keys(monkeypatch):
    info = {
        "open": 1, "dayHigh": 2, "dayLow": 0.5,
        "regularMarketPreviousClose": 1.5, "volume": 10,
        "fiftyTwoWeekLow": 0.1, "fiftyTwoWeekHigh": 3,
        "marketCap": 100, "trailingPE": 20, "forwardPE": 18,
        "priceToBook": 2, "pegRatio": 1.1, "trailingEps": 1.2,
        "dividendYield": 2.5, "payoutRatio": 0.3, "beta": 1.1,
        "fiftyDayAverage": 1.4, "twoHundredDayAverage": 1.3,
        "avgVolume10days": 11, "grossMargins": 0.4,
        "operatingMargins": 0.2, "profitMargins": 0.1,
        "returnOnEquity": 0.2, "revenueGrowth": 0.05,
        "earningsGrowth": 0.07, "totalCash": 50, "totalDebt": 40,
        "debtToEquity": 70, "freeCashflow": 30, "ebitda": 60,
        "sharesOutstanding": 1000, "floatShares": 900,
        "targetMeanPrice": 2.2, "targetLowPrice": 1.8,
        "targetHighPrice": 2.6, "targetMedianPrice": 2.2,
        "recommendationKey": "buy", "recommendationMean": 1.8,
        "numberOfAnalystOpinions": 20, "fullTimeEmployees": 100,
        "sector": "Technology", "industry": "Software",
        "country": "United States", "quoteType": "EQUITY",
        "website": "https://example.com", "longBusinessSummary": "Text",
    }

    class FakeTicker:
        def __init__(self, symbol):
            self.info = info

    monkeypatch.setattr(market_data.yf, "Ticker", FakeTicker)
    real = market_data.get_stats("TEST")
    stub = perf_stub.stats_payload("TEST")

    assert set(stub) == set(real)
    assert isinstance(stub["recommendation"], str)
    json.dumps(stub)


def test_stub_financials_matches_the_real_getter_shape(monkeypatch):
    columns = [pd.Timestamp(f"{year}-12-31") for year in (2022, 2023, 2024, 2025)]
    labels = ["Total Revenue", "Cost Of Revenue", "Gross Profit",
              "Operating Expense", "Operating Income", "Total Expenses",
              "Net Income", "Diluted EPS"]
    frame = pd.DataFrame(
        {column: [100.0, 40.0, 60.0, 20.0, 40.0, 60.0, 30.0, 1.5]
         for column in columns},
        index=labels)

    class FakeTicker:
        def __init__(self, symbol):
            self.income_stmt = frame

    monkeypatch.setattr(market_data.yf, "Ticker", FakeTicker)
    market_data.clear_market_caches()
    real = market_data.get_financials("TEST")
    stub = perf_stub.financials_payload("TEST")

    assert set(stub["rows"]) == set(real["rows"])
    assert stub["years"] == real["years"]
    for key, values in stub["rows"].items():
        assert len(values) == len(stub["years"])
    json.dumps(stub)


def test_stub_events_has_the_reply_shape():
    payload = perf_stub.events_payload("TEST")
    assert set(payload) == {
        "earnings_date", "ex_dividend_date", "dividend_date", "ttm_total",
        "recent"}
    assert all(set(entry) == {"date", "amount"} for entry in payload["recent"])
    json.dumps(payload)


def test_stub_profile_carries_the_classification_keys():
    payload = perf_stub.profile_payload("TEST")
    assert {"sector", "country", "quote_type", "market_cap"} <= set(payload)
    json.dumps(payload)


def test_stub_installs_every_market_boundary():
    class Namespace:
        pass

    module = Namespace()
    perf_stub.install_yahoo_stub(module, 0)
    for name in ("get_quote", "get_name", "get_history", "get_stats",
                 "get_financials", "get_events", "get_profile",
                 "get_fx_rate", "get_fx_rate_on", "get_price_on",
                 "search_tickers", "get_volume_leaders"):
        assert callable(getattr(module, name))
    assert module.get_quote("AAPL")["price"] > 0
    assert module.get_history("AAPL", "1D")
    assert module.get_fx_rate_on("USD", "CAD", "2026-08-28") == 1.35


def test_perf_server_redirects_the_database_before_importing_app():
    source = (ROOT / "scripts" / "perf_server.py").read_text()
    redirect = source.index("db.DB_PATH = TMP")
    app_import = source.index("import app as app_module")
    assert redirect < app_import
    assert "db.init()" in source[:app_import]


def _playwright_python():
    """The interpreter that owns Playwright, or None to skip the smoke."""
    candidates = [SYSTEM_PYTHON, Path(sys.executable)]
    for candidate in candidates:
        if not candidate.exists():
            continue
        probe = subprocess.run(
            [str(candidate), "-c", "import playwright.sync_api"],
            capture_output=True, text=True)
        if probe.returncode == 0:
            return candidate
    return None


def _run_measure(tmp_path, *extra):
    playwright_python = _playwright_python()
    if playwright_python is None:
        pytest.skip("Playwright is unavailable for the smoke run")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    out_base = tmp_path / "smoke"
    result = subprocess.run(
        [str(playwright_python), str(ROOT / "scripts" / "measure_perf.py"),
         "--runs", "1", "--stub-ms", "1", "--settle", "0.2",
         "--port", str(port), "--out", str(out_base),
         "--block-external", "--python", sys.executable, *extra],
        cwd=str(ROOT), capture_output=True, text=True, timeout=180)
    report = None
    if out_base.with_suffix(".json").exists():
        report = json.loads(out_base.with_suffix(".json").read_text())
    return result, report


def test_measure_perf_smoke_writes_only_the_requested_output(tmp_path):
    docs = ROOT / "docs" / "perf"
    before = {path.name: path.read_bytes()
              for path in docs.iterdir() if path.is_file()}
    instance_db = ROOT / "instance" / "portfolio.db"
    instance_before = instance_db.read_bytes() if instance_db.exists() else None

    result, report = _run_measure(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert report is not None
    assert [row["page"] for row in report["measurements"]] == [
        "dashboard", "ledger", "stock", "preferences"]
    assert report["page_errors"] == []
    assert report["console_errors"] == []
    assert all(row["summary"] for row in report["measurements"])

    after = {path.name: path.read_bytes()
             for path in docs.iterdir() if path.is_file()}
    assert after == before
    instance_after = instance_db.read_bytes() if instance_db.exists() else None
    assert instance_after == instance_before


def test_empty_stock_degrades_without_uncaught_page_errors(tmp_path):
    # Financials/events answer their normal 404 and the stats grid is all
    # nulls. The page hides the cards; the fetch layer logs a handled
    # console error, so only uncaught page errors are forbidden.
    result, report = _run_measure(
        tmp_path, "--empty-stock", "--allow-console-errors")
    assert result.returncode == 0, result.stdout + result.stderr
    assert report is not None
    assert report["empty_stock"] is True
    assert report["page_errors"] == []
    statuses = {}
    for row in report["measurements"]:
        if row["page"] != "stock":
            continue
        for fetch in row["summary"]["fetches"]:
            statuses.setdefault(fetch["endpoint"], set()).add(fetch["status"])
    assert statuses["/api/stock/:symbol/financials"] == {404}
    assert statuses["/api/stock/:symbol/events"] == {404}
    assert 200 in statuses["/api/stock/:symbol/stats"]
