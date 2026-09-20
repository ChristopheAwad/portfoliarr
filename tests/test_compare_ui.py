"""Source-level contracts for the shared comparison picker and chart."""

from pathlib import Path

import app as app_module


ROOT = Path(__file__).resolve().parent.parent
COMMON_JS = (ROOT / "static/js/common.js").read_text()
MAIN_JS = (ROOT / "static/js/main.js").read_text()
STOCK_JS = (ROOT / "static/js/stock.js").read_text()
INDEX_HTML = (ROOT / "templates/index.html").read_text()
STOCK_HTML = (ROOT / "templates/stock.html").read_text()
STYLE_CSS = (ROOT / "static/style.css").read_text()


def _picker_body() -> str:
    """Return only the setupComparePicker function source."""
    start = COMMON_JS.index("function setupComparePicker")
    end = COMMON_JS.index("// The navbar's search box is the original call site")
    return COMMON_JS[start:end]


def _comparison_readout_body() -> str:
    """Return the renderComparisonReadout function source."""
    start = COMMON_JS.index("function renderComparisonReadout")
    end = COMMON_JS.index("function paint(data, period)")
    return COMMON_JS[start:end]


def test_picker_markup_is_present_on_both_pages():
    required = (
        'id="compare-input"',
        'id="compare-results"',
        'id="compare-chips"',
        'class="compare-picker"',
        'class="compare-quick-picks"',
    )
    for html in (INDEX_HTML, STOCK_HTML):
        for marker in required:
            assert marker in html


def test_quick_pick_symbols_match_supported_index_symbols():
    for symbol in ("^GSPC", "^IXIC", "^GSPTSE"):
        assert symbol in app_module.INDEX_SYMBOLS
        marker = f'data-symbol="{symbol}"'
        assert marker in INDEX_HTML
        assert marker in STOCK_HTML


def test_common_js_defines_picker_palette_and_limit():
    assert "function setupComparePicker" in COMMON_JS
    assert "function getCompareColors" in COMMON_JS
    assert "const COMPARE_MAX = 3" in COMMON_JS


def test_picker_does_not_persist_symbols():
    body = _picker_body()
    assert "localStorage.getItem" not in body
    assert "localStorage.setItem" not in body
    assert "compareSymbols" not in body
    assert "sessionStorage" not in body
    assert "storageKey" not in body


def test_picker_clears_bfcache_restoration():
    body = _picker_body()
    assert '"pageshow"' in body
    assert "event.persisted" in body
    assert "clearSymbols" in body


def test_chart_factory_reads_and_paints_comparisons():
    for marker in (
        "getBenchmarks",
        "data.benchmarks",
        "data.normalized === true",
        "chartNormalized",
        "syncOverlayDatasets",
    ):
        assert marker in COMMON_JS


def test_built_in_legend_stays_disabled_in_favor_of_bottom_readout():
    js = COMMON_JS
    legend_at = js.index("legend: {")
    assert "display: false" in js[legend_at:legend_at + 120]
    assert "showOverlays" not in js
    assert "comparisonReadout" in js


def test_comparison_readout_markup_is_below_each_canvas():
    for html, canvas_id, readout_id in (
        (INDEX_HTML, 'id="portfolioChart"', 'id="portfolio-comparison-readout"'),
        (STOCK_HTML, 'id="stockChart"', 'id="stock-comparison-readout"'),
    ):
        canvas_at = html.index(canvas_id)
        readout_at = html.index(readout_id)
        assert readout_at > canvas_at
        assert 'class="comparison-readout"' in html
        assert 'aria-live="polite"' in html


def test_chart_factory_receives_comparison_readout():
    assert "comparisonReadout" in COMMON_JS
    assert (
        'comparisonReadout: document.getElementById("portfolio-comparison-readout")'
        in MAIN_JS
    )
    assert (
        'comparisonReadout: document.getElementById("stock-comparison-readout")'
        in STOCK_JS
    )


def test_comparison_readout_renders_marker_value_then_name():
    body = _comparison_readout_body()
    order = [
        body.index("comparison-readout-marker"),
        body.index("comparison-readout-value"),
        body.index("comparison-readout-name"),
    ]
    assert order == sorted(order)


def test_comparison_readout_uses_growth_return_math():
    body = _comparison_readout_body()
    assert "(value / 100 - 1) * 100" in body
    assert "pct.toFixed(2)" in body
    assert 'pct >= 0 ? "+" : ""' in body
    assert '"—"' in body


def test_comparison_readout_tracks_hover_and_falls_back_to_latest():
    js = COMMON_JS
    assert "onHover:" in js
    assert "renderComparisonReadout(index)" in js
    assert "renderComparisonReadout()" in js


def test_comparison_readout_does_not_fall_forward_on_hover():
    body = _comparison_readout_body()
    assert "const hasHoverIndex = index !== null && index !== undefined;" in body
    assert "const value = hasHoverIndex" in body
    assert "Number.isFinite(values[index]) ? values[index] : null" in body


def test_chart_period_summary_uses_finite_primary_endpoints():
    start = COMMON_JS.index("function paint(data, period)")
    end = COMMON_JS.index("function syncTimeframeButtons(period)", start)
    body = COMMON_JS[start:end]
    assert "const finitePlotValues" in body
    assert "plotValues.filter(Number.isFinite)" in body
    assert "firstValue: finitePlotValues[0]" in body
    assert "lastValue: finitePlotValues.at(-1)" in body


def test_dashboard_wires_picker_to_performance_chart():
    assert "setupComparePicker" in MAIN_JS
    assert "getBenchmarks" in MAIN_JS
    assert 'data-chart-mode="performance"' in MAIN_JS


def test_stock_page_excludes_primary_from_picker():
    assert "setupComparePicker" in STOCK_JS
    assert "primarySymbol: symbol" in STOCK_JS
    assert "getBenchmarks" in STOCK_JS


def test_comparison_picker_has_shared_styles():
    for selector in (
        ".compare-picker", ".compare-chip", ".compare-chip-remove",
        ".compare-search",
    ):
        assert selector in STYLE_CSS


def test_comparison_readout_has_styles():
    for selector in (
        ".comparison-readout",
        ".comparison-readout-item",
        ".comparison-readout-marker",
        ".comparison-readout-value",
        ".comparison-readout-name",
    ):
        assert selector in STYLE_CSS
    media_at = STYLE_CSS.rindex("@media")
    assert "comparison-readout" in STYLE_CSS[media_at:]
