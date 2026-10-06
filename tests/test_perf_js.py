# tests/test_perf_js.py
# =====================
# Meta-tests for the browser performance instrumentation (perf.js and the
# render marks page scripts drop). The frontend has no pytest harness — we
# read the source text and assert the wiring exists, the same approach as
# test_web_refresh_wiring.py. What these CANNOT prove is execution in a
# browser; that is the GUI gate.

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(relpath: str) -> str:
    path = ROOT / relpath
    assert path.exists(), f"{relpath} is missing"
    return path.read_text()


# ---------------------------------------------------------------------------
# Wiring: perf.js must load before common.js, and the fetch wrapper must time
# every request while keeping its 401 redirect behavior.
# ---------------------------------------------------------------------------

def test_base_loads_perf_before_common():
    src = _read("templates/base.html")
    perf_index = src.index("js/perf.js")
    common_index = src.index("js/common.js")
    assert perf_index < common_index


def test_fetch_wrapper_times_requests_without_breaking_redirects():
    src = _read("static/js/common.js")
    assert "PortfoliarrPerf.recordFetch" in src
    assert "measurement is best-effort" in src
    assert 'window.perfMark = window.perfMark || function () {};' in src
    assert 'window.location.assign("/auth/login");' in src


def test_perf_mark_is_defined_in_perf_js():
    src = _read("static/js/perf.js")
    assert "window.perfMark = function (name)" in src
    assert "window.PortfoliarrPerf = {" in src


# ---------------------------------------------------------------------------
# perf.js collection and reporting contracts
# ---------------------------------------------------------------------------

def test_perf_js_collects_navigation_lcp_and_server_timing():
    src = _read("static/js/perf.js")
    assert 'getEntriesByType("navigation")' in src
    assert "largest-contentful-paint" in src
    assert "PerformanceObserver" in src
    assert "Server-Timing" in src


def test_perf_js_normalizes_dynamic_paths():
    src = _read("static/js/perf.js")
    for template in ("/api/stock/:symbol", "/api/stock/:symbol/stats",
                     "/api/stock/:symbol/history",
                     "/api/stock/:symbol/financials",
                     "/api/stock/:symbol/events", "/api/quote/:symbol",
                     "/api/transactions/:id",
                     "/api/transactions/ticker/:symbol",
                     "/api/watchlist/:symbol", "/api/portfolios/:id",
                     "/api/widget/tokens/:id", "/api/users/:id"):
        assert template in src


def test_perf_js_beacons_once_and_never_polls():
    src = _read("static/js/perf.js")
    assert "navigator.sendBeacon" in src
    assert '"pagehide"' in src
    assert '"visibilitychange"' in src
    assert "if (state.sent) return;" in src
    assert "setInterval" not in src


def test_overlay_is_opt_in():
    src = _read("static/js/perf.js")
    assert 'localStorage.getItem("perfDebug")' in src
    assert 'get("perf")' in src
    css = _read("static/style.css")
    assert "#perf-overlay" in css


# ---------------------------------------------------------------------------
# Render marks: each page's boot path must drop the agreed mark names.
# ---------------------------------------------------------------------------

def test_dashboard_marks():
    src = _read("static/js/main.js")
    for mark in ("dashboard:markets", "dashboard:watchlist",
                 "dashboard:volume", "dashboard:summary", "dashboard:chart"):
        assert f'perfMark("{mark}")' in src


def test_ledger_marks():
    src = _read("static/js/ledger.js")
    for mark in ("ledger:rows", "ledger:closed"):
        assert f'perfMark("{mark}")' in src


def test_stock_marks():
    src = _read("static/js/stock.js")
    for mark in ("stock:quote", "stock:stats", "stock:financials",
                 "stock:events", "stock:chart"):
        assert f'perfMark("{mark}")' in src


def test_shared_chart_paint_mark():
    assert 'perfMark("chart:paint")' in _read("static/js/common.js")


# ---------------------------------------------------------------------------
# Preferences Performance card
# ---------------------------------------------------------------------------

def test_preferences_card_reads_api_perf():
    html = _read("templates/preferences.html")
    assert 'id="perf-card"' in html
    assert 'id="perf-readout"' in html
    assert 'id="perf-reload"' in html
    src = _read("static/js/preferences.js")
    assert 'fetch("/api/perf")' in src
    assert 'perfMark("preferences:perf-card")' in src
    assert "setInterval" not in src
