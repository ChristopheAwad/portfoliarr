"""The browser must send an explicit destination and discard stale portfolio data."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def source(path):
    return (ROOT / path).read_text()


def test_selector_and_management_controls():
    for page in ("templates/index.html", "templates/ledger.html"):
        assert 'id="portfolio-select"' in source(page)
    prefs = source("templates/preferences.html")
    for hook in ("portfolio-create", "portfolio-list", "portfolio-error"):
        assert hook in prefs


def test_shared_selection_and_chart_cache_scope():
    common = source("static/js/common.js")
    assert "portfoliochange" in common
    assert 'addEventListener("storage"' in common
    assert "portfolio_id" in common
    assert "getScope" in common
    assert "invalidate" in common


def test_ledger_writes_and_import_use_selected_portfolio():
    ledger = source("static/js/ledger.js")
    assert "portfolioQuery" in ledger
    assert "portfoliochange" in ledger
    assert "importCommitBtn.hidden = true" in ledger
    assert "previewPortfolioId !== currentPortfolioId()" in ledger


def test_dashboard_scopes_reads_but_not_global_watchlist():
    dashboard = source("static/js/main.js")
    assert "portfolioQuery" in dashboard
    assert "portfoliochange" in dashboard
    assert 'fetch("/api/watchlist")' in dashboard


def test_changed_page_scripts_parse_in_javascript_engine():
    MiniRacer = pytest.importorskip("py_mini_racer").MiniRacer
    engine = MiniRacer()
    for path in ("static/js/common.js", "static/js/main.js",
                 "static/js/ledger.js", "static/js/preferences.js"):
        engine.eval("new Function(" + json.dumps(source(path)) + ")")


def test_chart_url_uses_one_query_delimiter_for_both_page_types():
    """A scoped endpoint already has '?'; the chart must append '&period'."""
    common = source("static/js/common.js")
    start = common.index("function historyRequestUrl(")
    end = common.index("\n}", start) + 2
    MiniRacer = pytest.importorskip("py_mini_racer").MiniRacer
    engine = MiniRacer()
    engine.eval(common[start:end])
    assert engine.eval('historyRequestUrl("/api/portfolio/history?portfolio_id=2", "5D", "")') == (
        "/api/portfolio/history?portfolio_id=2&period=5D")
    assert engine.eval('historyRequestUrl("/api/stock/AAPL/history", "1M", "&benchmark=SPY")') == (
        "/api/stock/AAPL/history?period=1M&benchmark=SPY")


def test_dashboard_selector_width_does_not_depend_on_loaded_name():
    """Reserve a narrow slot before the async portfolio list fills the select."""
    css = source("static/style.css")
    picker = css.split(".portfolio-picker select {", 1)[1].split("}", 1)[0]
    assert "width: min(" in picker
    assert "max-width: 100%" in picker
    assert "grid-template-columns: minmax(0, 1fr)" in css
