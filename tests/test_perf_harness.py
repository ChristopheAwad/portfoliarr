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


def test_expected_seed_counts_cover_small_and_large_ledgers():
    assert perf_stub.expected_seed_counts(0) == (2, 2)
    assert perf_stub.expected_seed_counts(1) == (3, 3)
    assert perf_stub.expected_seed_counts(3) == (5, 5)
    assert perf_stub.expected_seed_counts(7) == (9, 9)
    assert perf_stub.expected_seed_counts(8) == (10, 10)
    assert perf_stub.expected_seed_counts(1000) == (1002, 10)


def test_perf_server_redirects_the_database_before_importing_app():
    source = (ROOT / "scripts" / "perf_server.py").read_text()
    redirect = source.index("db.DB_PATH = DB_PATH")
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
    out_base = tmp_path / "smoke"
    result = subprocess.run(
        [str(playwright_python), str(ROOT / "scripts" / "measure_perf.py"),
         "--runs", "1", "--stub-ms", "1", "--settle", "0.2",
         "--out", str(out_base),
         "--offline-assets", "--python", sys.executable, *extra],
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
    assert report["chart_required"] is True
    assert report["external_requests"] == []
    assert all(row["summary"] for row in report["measurements"])
    charts = {row["page"]: row["chart"] for row in report["measurements"]}
    assert charts["dashboard"]["portfolio_chart"] is True
    assert charts["stock"]["stock_chart"] is True
    assert charts["dashboard"]["finite_points"] > 0
    assert charts["stock"]["finite_points"] > 0
    marks = {row["page"]: row["summary"]["marks"]
             for row in report["measurements"]}
    assert "dashboard:chart" in marks["dashboard"]
    assert "stock:chart" in marks["stock"]
    assert charts["ledger"]["chart_loaded"] is False
    assert charts["preferences"]["chart_loaded"] is False

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


def test_missing_chart_assets_stay_a_separate_expected_failure(tmp_path):
    """A missing local chart library is a real degradation, not a clean run.
    The report must say charts were not required and not rendered."""
    result, report = _run_measure(
        tmp_path, "--missing-chart", "--allow-console-errors")
    assert result.returncode == 0, result.stdout + result.stderr
    assert report is not None
    assert report["missing_chart"] is True
    assert report["chart_required"] is False
    assert report["page_errors"] == []
    assert all(row["chart"]["chart_loaded"] is False
               for row in report["measurements"])


def test_chart_readiness_rejects_empty_stale_or_missing_data():
    """Use a browser to distinguish a completed finite draw from an empty one.

    The success harness seeds real holdings, so an empty canvas is not ready.
    Missing-chart mode can still measure the non-chart part of the page.
    """
    playwright_python = _playwright_python()
    if playwright_python is None:
        pytest.skip("Playwright is unavailable for the readiness check")
    probe = r'''
from playwright.sync_api import sync_playwright, TimeoutError
from scripts.measure_perf import wait_for_page_ready

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.set_content('<canvas id="portfolioChart"></canvas><canvas id="stockChart"></canvas>')
    page.evaluate("""() => {
        window.marks = {'dashboard:summary': 1, 'stock:quote': 1};
        window.PortfoliarrPerf = {summary: () => ({marks: window.marks})};
        window.chart = {data: {datasets: [{data: []}]}};
        window.Chart = {getChart: () => window.chart};
    }""")
    for name, mark in [('dashboard', 'dashboard:chart'), ('stock', 'stock:chart')]:
        page.evaluate("(mark) => { window.marks[mark] = 1; }", mark)
        # A chart object and a stale mark still cannot make an empty or
        # non-finite series a seeded-run success.
        for values in ([], [None, '5']):
            page.evaluate("(values) => { window.chart.data.datasets[0].data = values; }", values)
            try:
                wait_for_page_ready(page, name, True, timeout_ms=250)
            except TimeoutError:
                pass
            else:
                raise AssertionError(f'{name}: accepted empty/non-finite chart')
        page.evaluate("() => { window.chart.data.datasets[0].data = [null, 42]; }")
        page.evaluate("(mark) => { delete window.marks[mark]; }", mark)
        try:
            wait_for_page_ready(page, name, True, timeout_ms=250)
        except TimeoutError:
            pass
        else:
            raise AssertionError(f'{name}: accepted a chart without a draw mark')
        page.evaluate("(mark) => { window.marks[mark] = 1; }", mark)
        wait_for_page_ready(page, name, True, timeout_ms=2500)
    page.evaluate("() => { delete window.Chart; }")
    wait_for_page_ready(page, 'dashboard', False, timeout_ms=2500)
    browser.close()
'''
    result = subprocess.run(
        [str(playwright_python), "-c", probe], cwd=str(ROOT),
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_slow_local_fonts_do_not_block_authenticated_startup():
    """Hold the font responses while a real browser starts the dashboard."""
    playwright_python = _playwright_python()
    if playwright_python is None:
        pytest.skip("Playwright is unavailable for the font-delay check")
    probe = r'''
import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright
from scripts.measure_perf import PerfServer

async def run(server):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        seed_context = await browser.new_context()
        seed_page = await seed_context.new_page()
        await seed_page.goto(server.base + '/auth/setup')
        await seed_page.fill('#setup-username', 'fontcheck')
        await seed_page.fill('#setup-password', 'font-pass-1234')
        await seed_page.fill('#setup-confirm', 'font-pass-1234')
        await seed_page.click('.auth-form button[type=submit]')
        await seed_page.wait_for_url(server.base + '/')
        cookies = await seed_context.cookies()
        await seed_context.close()

        context = await browser.new_context(viewport={'width': 390, 'height': 844})
        await context.add_cookies(cookies)
        await context.add_init_script("localStorage.setItem('theme', 'dark')")
        font_started = asyncio.Event()
        release_fonts = asyncio.Event()
        portfolios_requested = asyncio.Event()
        external = []
        font_paths = set()
        errors = []
        async def route_request(route):
            parts = urlsplit(route.request.url)
            origin = f'{parts.scheme}://{parts.netloc}'
            if origin != server.base:
                external.append(origin)
                await route.abort()
            elif parts.path.endswith('.woff2'):
                font_paths.add(parts.path)
                font_started.set()
                await release_fonts.wait()
                await route.continue_()
            else:
                await route.continue_()
        await context.route(re.compile(r'^https?://'), route_request)
        page = await context.new_page()
        page.on('request', lambda req: portfolios_requested.set()
                if urlsplit(req.url).path == '/api/portfolios' else None)
        page.on('pageerror', lambda exc: errors.append(str(exc)))
        try:
            await page.goto(server.base + '/', wait_until='commit')
            await asyncio.wait_for(font_started.wait(), timeout=10)
            await asyncio.wait_for(portfolios_requested.wait(), timeout=10)
            await page.locator('.navbar').wait_for(state='visible', timeout=10000)
            assert await page.evaluate("document.documentElement.classList.contains('dark')")
            assert await page.evaluate("document.fonts.status === 'loading'")
            assert not release_fonts.is_set()
        finally:
            release_fonts.set()
        await page.wait_for_load_state('load', timeout=20000)
        await page.wait_for_function("""() => {
            const loaded = new Set(Array.from(document.fonts)
                .filter(face => face.status === 'loaded')
                .map(face => face.family.replaceAll('"', '')));
            return loaded.has('Instrument Sans') && loaded.has('Fraunces');
        }""", timeout=10000)
        loaded_subsets = await page.evaluate("""async () => {
            const samples = [
                ['600 20px "Fraunces"', 'A'],
                ['600 20px "Fraunces"', 'Ž'],
                ['600 20px "Fraunces"', 'ậ'],
                ['400 20px "Instrument Sans"', 'A'],
                ['400 20px "Instrument Sans"', 'Ž'],
            ];
            const faces = await Promise.all(samples.map(([font, text]) =>
                document.fonts.load(font, text)));
            return faces.every(group => group.length > 0 &&
                group.every(face => face.status === 'loaded'));
        }""")
        assert loaded_subsets
        assert font_paths == {
            '/static/fonts/fraunces-v38-latin.woff2',
            '/static/fonts/fraunces-v38-latin-ext.woff2',
            '/static/fonts/fraunces-v38-vietnamese.woff2',
            '/static/fonts/instrument-sans-v4-latin.woff2',
            '/static/fonts/instrument-sans-v4-latin-ext.woff2',
        }, font_paths
        assert not external, external
        assert not errors, errors
        await context.close()
        await browser.close()

with tempfile.TemporaryDirectory(prefix='font-delay-', dir='/tmp/opencode') as temp:
    server = PerfServer(Path(sys.argv[1]), dict(os.environ), Path(temp) / 'perf.db', stub_ms=1)
    try:
        asyncio.run(run(server))
    finally:
        server.stop()
'''
    result = subprocess.run(
        [str(playwright_python), "-c", probe, sys.executable], cwd=str(ROOT),
        capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr


def test_cold_mode_restarts_the_server_per_page(tmp_path):
    result, report = _run_measure(tmp_path, "--cold", "--settle", "0.1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert report is not None
    assert report["cold"] is True
    assert [row["page"] for row in report["measurements"]] == [
        "dashboard", "ledger", "stock", "preferences"]
    assert report["page_errors"] == []


def test_missing_chart_in_cold_mode_uses_each_new_server_port(tmp_path):
    result, report = _run_measure(
        tmp_path, "--cold", "--missing-chart", "--allow-console-errors",
        "--settle", "0.1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert report is not None
    assert report["cold"] is True
    assert report["missing_chart"] is True
    assert report["chart_required"] is False
    assert report["external_requests"] == []
    assert report["page_errors"] == []
    assert all(row["chart"]["chart_loaded"] is False
               for row in report["measurements"])
