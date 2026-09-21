# tests/test_period_return_ui.py
# ==============================
# Contracts for the dashboard's period return readout.
#
# WHY SOURCE/TEMPLATE CHECKS? pytest cannot execute the browser JavaScript
# or lay out CSS. What it CAN lock is the wiring that makes the feature
# work:
#
#   1. index.html ships the readout above the chart with stable hooks and
#      an honest explanation of the metric.
#   2. common.js's setupTimeframeChart reports the selected period's
#      twrr_pct on every successful visible paint, and reports an
#      unavailable result on an initial-load failure only.
#   3. main.js paints the percentage and the label without deriving its own
#      value or touching privacy/summary/chart-mode state.
#   4. style.css gives the readout a quiet, overflow-safe layout.
#
# The metric choice matters: twrr_pct removes cash flows, so a deposit can
# neither fake nor dilute a return. A first-to-last value delta would.

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

COMMON_JS = (ROOT / "static/js/common.js").read_text()
MAIN_JS = (ROOT / "static/js/main.js").read_text()
INDEX_HTML = (ROOT / "templates/index.html").read_text()
STYLE_CSS = (ROOT / "static/style.css").read_text()


# ── Source-slice helpers ──────────────────────────────────────────────

def _paint_body() -> str:
    """The paint(data, period) function body (ends at syncTimeframeButtons)."""
    start = COMMON_JS.index("function paint(data, period)")
    end = COMMON_JS.index("function syncTimeframeButtons(period)", start)
    return COMMON_JS[start:end]


def _refresh_body() -> str:
    """The refresh() function body, up to the render-half comment."""
    start = COMMON_JS.index("async function refresh(period = defaultPeriod")
    end = COMMON_JS.index("// ── The render half", start)
    return COMMON_JS[start:end]


def _refresh_catch_body() -> str:
    """The refresh() catch block."""
    start = _refresh_body().index("} catch (err) {")
    return _refresh_body()[start:]


def _timeframe_click_body() -> str:
    start = COMMON_JS.index('buttonBar.addEventListener("click"')
    end = COMMON_JS.index("// History is not part", start)
    return COMMON_JS[start:end]


def _function_body(js: str, signature: str) -> str:
    """Extract a top-level function's text: signature to the first '\n}'."""
    start = js.find(signature)
    assert start != -1, f"{signature} not found"
    end = js.find("\n}", start)
    assert end != -1, f"{signature} has no closing brace"
    return js[start:end]


def _emit_info() -> dict:
    """The emitPeriodSummary call-site details, checked as one contract."""
    paint = _paint_body()
    helper_start = COMMON_JS.index("function emitPeriodSummary")
    helper_end = COMMON_JS.index("\n    }", helper_start)
    return {"paint": paint, "helper": COMMON_JS[helper_start:helper_end]}


def _css_rule(selector: str, *, start: int = 0) -> str:
    selector_at = STYLE_CSS.index(selector, start)
    body_start = STYLE_CSS.index("{", selector_at)
    body_end = STYLE_CSS.index("}", body_start)
    return STYLE_CSS[body_start:body_end + 1]


# ---------------------------------------------------------------------------
# A. Template structure and copy
# ---------------------------------------------------------------------------

def test_dashboard_ships_period_return_readout(client):
    html = client.get("/").get_data(as_text=True)
    assert 'id="period-return"' in html, "dashboard missing period return container"


def test_period_return_has_label_and_value_hooks(client):
    html = client.get("/").get_data(as_text=True)
    assert 'id="period-return-label"' in html, "period return label hook missing"
    assert 'id="period-return-value"' in html, "period return value hook missing"


def test_initial_label_matches_the_chart_default():
    default = re.search(
        r'const DEFAULT_CHART_PERIOD = "([^"]+)";', MAIN_JS
    )
    assert default, "main.js must declare DEFAULT_CHART_PERIOD"
    label = re.search(
        r'id="period-return-label">([^<]+)</span>', INDEX_HTML
    )
    assert label, "index.html must ship the initial period return label"
    assert label.group(1) == f"{default.group(1)} return"


def test_period_return_sits_above_the_chart():
    """The readout describes the chart, so it must render before the canvas."""
    container = INDEX_HTML.index('id="period-return"')
    chart_box = INDEX_HTML.index('class="chart-box"')
    canvas = INDEX_HTML.index('id="portfolioChart"')
    assert container < chart_box < canvas


def test_period_return_explains_excluded_cash_flows(client):
    html = client.get("/").get_data(as_text=True)
    assert "Deposits and withdrawals excluded" in html


def test_period_return_is_announced_politely(client):
    """Async updates must be announced without stealing focus."""
    html = client.get("/").get_data(as_text=True)
    start = html.index('id="period-return"')
    tag = html[html.rindex("<", 0, start):html.index(">", start) + 1]
    assert 'aria-live="polite"' in tag


def test_period_return_is_dashboard_only(client):
    for path in ("/stock/AAPL", "/ledger"):
        html = client.get(path).get_data(as_text=True)
        assert 'id="period-return"' not in html, f"{path} must not ship the readout"


def test_dashboard_hero_facts_are_unchanged(client):
    """The live summary pills must survive; the readout is an addition."""
    html = client.get("/").get_data(as_text=True)
    assert 'id="portfolio-day-change"' in html
    assert 'id="portfolio-total-return"' in html
    assert 'id="portfolio-cost-basis"' in html


# ---------------------------------------------------------------------------
# B. Shared chart factory wiring
# ---------------------------------------------------------------------------

def test_factory_accepts_period_summary_callback():
    signature = COMMON_JS.index("function setupTimeframeChart(")
    span = COMMON_JS[signature:COMMON_JS.index(") {", signature)]
    assert "onPeriodSummary" in span, (
        "setupTimeframeChart must accept an optional onPeriodSummary callback"
    )


def test_successful_paint_emits_summary_from_twrr():
    info = _emit_info()
    assert "emitPeriodSummary(period, data);" in info["paint"], (
        "paint() must report the painted period's return"
    )
    assert "reply.twrr_pct" in info["helper"], (
        "the summary must come from the reply's twrr_pct"
    )


def test_summary_emit_normalizes_non_finite_to_null():
    """Empty, one-point, or null results become null — never a fake 0."""
    helper = _emit_info()["helper"]
    assert "Number.isFinite(raw) ? raw : null" in helper


def test_timeframe_click_does_not_emit_summary():
    """A click only fetches; only a successful paint may update the readout."""
    body = _timeframe_click_body()
    assert "emitPeriodSummary" not in body
    assert "onPeriodSummary" not in body


def test_silent_prefetch_cannot_emit_summary():
    body = _refresh_body()
    assert body.index("if (silent) return;") < body.index(
        "emitPeriodSummary(period, null)"
    ), "a silent prefetch must return before any summary report"


def test_summary_never_derives_from_plot_series_or_mode():
    """The metric is the backend's TWR, not a first-to-last value delta."""
    info = _emit_info()
    assert "finitePlotValues" not in info["helper"]
    assert "firstValue" not in info["helper"]
    assert "lastValue" not in info["helper"]
    assert "mode" not in info["helper"]
    assert "data.values" not in info["helper"]
    assert "data.index_values" not in info["helper"]


def test_stock_detail_period_callback_unchanged():
    """The stock page's own onPeriodData contract must remain intact."""
    paint = _paint_body()
    assert "finitePlotValues[0]" in paint
    assert "finitePlotValues.at(-1)" in paint
    assert "onPeriodData" in paint


# ---------------------------------------------------------------------------
# C. Failure and recovery
# ---------------------------------------------------------------------------

def test_initial_failure_emits_unavailable():
    catch = _refresh_catch_body()
    assert "lastReply === null" in catch, (
        "an initial-load failure must be distinguished from a later failure"
    )
    assert "emitPeriodSummary(period, null)" in catch


def test_later_failure_preserves_previous_summary():
    """After a reply painted, a later failure must not overwrite the readout."""
    catch = _refresh_catch_body()
    assert "lastReply === null" in catch
    emit_at = catch.index("emitPeriodSummary(period, null)")
    guard_at = catch.index("lastReply === null")
    assert guard_at < emit_at


def test_failed_request_is_generation_guarded():
    catch = _refresh_catch_body()
    emit_at = catch.index("emitPeriodSummary(period, null)")
    guard_at = catch.index("visibleGeneration === visibleRequestGeneration")
    assert guard_at < emit_at, "a stale failed request must not report unavailable"


def test_silent_prefetch_failure_does_not_emit():
    catch = _refresh_catch_body()
    assert "!silent" in catch


# ---------------------------------------------------------------------------
# D. Dashboard painter
# ---------------------------------------------------------------------------

def _painter_body() -> str:
    return _function_body(MAIN_JS, "function paintPeriodReturn(")


def test_dashboard_wires_period_summary_callback():
    setup = MAIN_JS.index("setupTimeframeChart({", MAIN_JS.index("const portfolioChartHandle"))
    span = MAIN_JS[setup:MAIN_JS.index("});", setup)]
    assert "onPeriodSummary: paintPeriodReturn" in span


def test_painter_uses_period_return_label():
    body = _painter_body()
    assert "`${period} return`" in body


def test_painter_formats_finite_positive():
    body = _painter_body()
    assert 'returnPct >= 0 ? "+"' in body
    assert "toFixed(2)" in body
    assert 'classList.toggle("pos", nextClass === "pos")' in body


def test_painter_formats_finite_negative():
    body = _painter_body()
    assert 'const nextClass = returnPct >= 0 ? "pos" : "neg"' in body
    assert 'classList.toggle("neg", nextClass === "neg")' in body


def test_painter_handles_unavailable():
    body = _painter_body()
    assert "Number.isFinite(returnPct)" in body
    assert '"Return unavailable"' in body
    assert 'classList.remove("pos", "neg")' in body


def test_painter_avoids_reannouncing_unchanged_values():
    body = _painter_body()
    assert "periodReturnLabelEl.textContent !== nextLabel" in body
    assert "periodReturnValueEl.textContent !== nextValue" in body


def test_painter_does_not_compute_value_delta():
    body = _painter_body()
    assert "(lastValue - firstValue)" not in body
    assert "firstValue" not in body


def test_painter_ignores_chart_mode_and_comparisons():
    body = _painter_body()
    assert "benchmark" not in body
    assert "comparisonMode" not in body
    assert "dataset" not in body


def test_period_readout_not_in_privacy_lock_list():
    for signature in ("function applyPortfolioPrivacy()",
                      "function clearPortfolioGeometryLocks()"):
        body = _function_body(MAIN_JS, signature)
        assert "periodReturnValueEl" not in body
        assert "periodReturnLabelEl" not in body


def test_period_readout_not_painted_by_summary_poll():
    body = _function_body(MAIN_JS, "async function refreshPortfolioSummary()")
    assert "periodReturnValueEl" not in body


# ---------------------------------------------------------------------------
# E. Styling and responsive behavior
# ---------------------------------------------------------------------------

def test_period_return_has_styles():
    rule = _css_rule(".period-return {")
    assert "display" in rule
    assert "justify-content: flex-start" in rule


def test_period_return_value_uses_tabular_numbers():
    rule = _css_rule(".period-return-value {")
    assert "font-variant-numeric" in rule and "tabular-nums" in rule


def test_period_return_sign_colors():
    assert "var(--green-pos)" in _css_rule(".period-return-value.pos")
    assert "var(--red-neg)" in _css_rule(".period-return-value.neg")


def test_period_return_note_is_secondary():
    rule = _css_rule(".period-return-note {")
    assert "var(--text-secondary)" in rule


def test_period_return_has_no_box_chrome():
    rule = _css_rule(".period-return {")
    for banned in ("background", "border", "box-shadow", "border-radius"):
        assert banned not in rule, f"base readout must stay unboxed ({banned})"


def test_period_return_has_deliberate_mobile_layout():
    mobile_at = STYLE_CSS.rindex("@media (max-width: 600px)")
    rule = _css_rule(".period-return {", start=mobile_at)
    assert "gap" in rule


def test_mobile_rule_avoids_viewport_width():
    mobile_at = STYLE_CSS.rindex("@media (max-width: 600px)")
    block = STYLE_CSS[mobile_at:]
    assert "100vw" not in block
