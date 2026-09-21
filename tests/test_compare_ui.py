"""Source-level contracts for the shared comparison picker and chart."""

import re
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


def _picker_markup(html: str) -> str:
    """Return the complete compare-picker element, including nested divs."""
    start = html.index('<div class="compare-picker"')
    depth = 0
    for match in re.finditer(r"</?div\b[^>]*>", html[start:]):
        if match.group().startswith("</"):
            depth -= 1
            if depth == 0:
                return html[start:start + match.end()]
        else:
            depth += 1
    raise AssertionError("compare-picker closing div not found")


def _css_rule(selector: str, *, start: int = 0) -> str:
    """Return the first CSS rule for selector at or after start."""
    selector_at = STYLE_CSS.index(selector, start)
    body_start = STYLE_CSS.index("{", selector_at)
    body_end = STYLE_CSS.index("}", body_start)
    return STYLE_CSS[body_start:body_end + 1]


# ---------------------------------------------------------------------------
# Compact picker markup (Test A)
# ---------------------------------------------------------------------------

def test_picker_is_compact_labelled_control_on_both_pages():
    rejected = (
        "compare-selections",
        "compare-quick-picks",
        'class="compare-quick"',
        'data-symbol="^GSPC"',
        'data-symbol="^IXIC"',
        'data-symbol="^GSPTSE"',
    )
    for html in (INDEX_HTML, STOCK_HTML):
        picker = _picker_markup(html)
        opening_tag = picker[:picker.index(">") + 1]
        assert 'role="group"' in opening_tag
        assert 'aria-labelledby="compare-label"' in opening_tag
        assert re.search(
            r'<span\s+id="compare-label"\s+class="compare-label">'
            r'\s*Compare\s*</span>',
            picker,
        )

        label_at = picker.index('class="compare-label"')
        search_at = picker.index('class="compare-search"')
        chips_at = picker.index('id="compare-chips"')
        assert label_at < search_at < chips_at

        assert 'id="compare-results"' in picker
        assert 'class="search-results"' in picker

        input_at = picker.index('id="compare-input"')
        input_tag = picker[
            picker.rfind("<input", 0, input_at):picker.index(">", input_at)
        ]
        assert 'placeholder="Search ticker or benchmark..."' in input_tag
        assert 'aria-label="Search ticker or benchmark to compare"' in input_tag

        chips_tag = picker[
            picker.index('<div id="compare-chips"'):picker.index(">", chips_at)
        ]
        assert "hidden" in chips_tag

        for marker in rejected:
            assert marker not in picker


# ---------------------------------------------------------------------------
# Local benchmark recommendation definitions (Test B)
# ---------------------------------------------------------------------------

def test_benchmark_recommendations_match_supported_index_symbols():
    expected = {
        "^GSPC": "S&P 500",
        "^IXIC": "Nasdaq",
        "^GSPTSE": "TSX",
    }
    js = COMMON_JS
    assert "const COMPARE_RECOMMENDATIONS" in js
    start = js.index("const COMPARE_RECOMMENDATIONS")
    end = js.index("function setupComparePicker", start)
    block = js[start:end]
    for symbol, name in expected.items():
        assert symbol in app_module.INDEX_SYMBOLS
        assert f'symbol: "{symbol}"' in block
        assert f'name: "{name}"' in block


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


def test_picker_preserves_empty_invalid_duplicate_and_limit_guards():
    body = _picker_body()
    assert 'const symbol = String(raw || "").trim().toUpperCase();' in body
    assert "if (!symbol) return;" in body
    assert "if (symbol === primarySymbol)" in body
    assert 'showToast("That symbol is already the chart", "error")' in body
    assert "if (symbols.includes(symbol)) return;" in body
    assert "if (symbols.length >= COMPARE_MAX)" in body
    assert "showToast(`Up to ${COMPARE_MAX} comparisons`, \"error\")" in body
    assert "symbols.push(symbol);" in body


def test_picker_preserves_full_state_removal_and_clearing():
    body = _picker_body()
    assert "symbols.filter((item) => item !== symbol)" in body
    assert "if (next.length === symbols.length) return;" in body
    assert "symbols = next;" in body
    assert "symbols = [];" in body
    assert "renderChips();" in body
    assert "if (notifyChange && onChange) onChange(getSymbols());" in body
    assert 'window.addEventListener("pageshow"' in body
    assert "if (!event.persisted) return;" in body
    assert "clearSymbols();" in body


# ---------------------------------------------------------------------------
# Picker wires filtered defaults through the shared factory (Test E)
# ---------------------------------------------------------------------------

def test_picker_wires_filtered_benchmark_defaults():
    body = _picker_body()
    assert "COMPARE_RECOMMENDATIONS.filter" in body
    assert "item.symbol !== primarySymbol" in body
    assert 'defaultHeading: "Suggested"' in body
    assert "defaultResults:" in body
    assert "setupTickerSuggestions(" in body
    assert "addSymbol(symbol)" in body
    assert 'inputEl.value = ""' in body


# ---------------------------------------------------------------------------
# Every selection renders one removable chip (Test F)
# ---------------------------------------------------------------------------

def test_picker_renders_one_chip_per_selection():
    body = _picker_body()
    assert "quickPickBar" not in body
    assert "quickPickSymbols" not in body
    assert "aria-pressed" not in body
    assert "[data-symbol]" not in body
    render_start = body.index("function renderChips")
    render_end = body.index("function notify", render_start)
    render_body = body[render_start:render_end]
    assert 'chip.className = "compare-chip";' in render_body
    assert 'remove.className = "compare-chip-remove";' in render_body
    assert "chip.dataset.symbol = symbol;" in render_body
    assert "COMPARE_RECOMMENDATIONS.find" in render_body
    assert "rec.name : symbol" in render_body
    assert "removeSymbol(symbol)" in render_body
    assert "chipsEl.hidden = symbols.length === 0;" in render_body


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
        readout_tag = html[readout_at:html.index(">", readout_at)]
        assert "aria-live" not in readout_tag


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
    assert 'comparisonPrimaryLabel: "Portfolio"' in MAIN_JS
    assert "comparisonPrimaryLabel" in COMMON_JS


def test_theme_change_repaints_chart_and_readout_colors():
    assert "repaintComparisonReadout()" in COMMON_JS
    assert "portfolioChartHandle.repaintComparisonReadout();" in MAIN_JS
    assert "stockChartHandle.repaintComparisonReadout();" in STOCK_JS


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


def test_comparison_readout_identifies_failed_benchmarks():
    assert "dataset.compareError = overlays[i].error || null;" in COMMON_JS
    body = _comparison_readout_body()
    assert "dataset.compareError" in body
    assert " unavailable`" in body
    assert "name.title = dataset.compareError;" in body


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


# ---------------------------------------------------------------------------
# Compact desktop and mobile CSS (Test H)
# ---------------------------------------------------------------------------

def test_comparison_picker_has_compact_shared_styles():
    for selector in (
        ".compare-picker", ".compare-label", ".compare-search",
        ".compare-chips", ".compare-chip", ".compare-chip-remove",
        ".search-section-label",
    ):
        assert selector in STYLE_CSS
    for rejected in (
        ".compare-selections", ".compare-quick-picks", ".compare-quick",
    ):
        assert rejected not in STYLE_CSS
    picker_rule = _css_rule(".compare-picker")
    assert "display: grid" in picker_rule
    assert "grid-template-columns: auto minmax(0, 1fr)" in picker_rule
    chips_rule = _css_rule(".compare-chips")
    assert "grid-column: 2" in chips_rule
    assert "flex-wrap: wrap" in chips_rule
    search_rule = _css_rule(".compare-search")
    assert "position: relative" in search_rule
    assert "min-width: 0" in search_rule
    dropdown_rule = _css_rule(".compare-search .search-results")
    assert "min-width: min(280px, 100%)" in dropdown_rule


def test_comparison_picker_has_deliberate_mobile_layout():
    mobile_at = STYLE_CSS.rindex("@media (max-width: 600px)")
    mobile_css = STYLE_CSS[mobile_at:]
    picker_rule = _css_rule(".compare-picker", start=mobile_at)
    assert "grid-template-columns: 1fr" in picker_rule
    for rule in (
        picker_rule,
        _css_rule(".compare-chips", start=mobile_at),
        _css_rule(".compare-search", start=mobile_at),
    ):
        assert "overflow" not in rule
        assert "100vw" not in rule
        assert "scroll-snap" not in rule


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