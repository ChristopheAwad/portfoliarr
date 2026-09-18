"""Recovery contracts for charts restored in stale mobile browser tabs.

The frontend has no JavaScript browser harness, so these tests lock the source
contracts that prevent a recovered Chart.js canvas from keeping the tiny size
it measured while its tab was hidden or its page was unavailable.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def common_js() -> str:
    return (ROOT / "static" / "js" / "common.js").read_text()


def style_css() -> str:
    return (ROOT / "static" / "style.css").read_text()


def rule_body(selector: str) -> str:
    """Return the first CSS declaration block after ``selector``."""
    text = style_css()
    selector_at = text.find(selector)
    assert selector_at != -1, f"missing CSS selector: {selector}"
    start = text.find("{", selector_at)
    end = text.find("}", start)
    assert start != -1 and end != -1, f"malformed CSS rule: {selector}"
    return text[start : end + 1]


def test_successful_chart_paint_remeasures_on_a_layout_frame():
    """Recovered data must not reuse geometry measured in a hidden tab."""
    text = common_js()
    assert "function resizeAndUpdateChart" in text
    helper_at = text.find("function resizeAndUpdateChart")
    helper_end = text.find("\n    }", helper_at)
    helper = text[helper_at:helper_end]
    assert "requestAnimationFrame" in helper
    assert "chart.resize()" in helper
    assert "chart.update()" in helper
    assert "resizeAndUpdateChart();" in text[text.find("function paint"):]


def test_chart_retries_active_period_on_reconnect_and_foreground():
    """A failed initial history request must recover without a page reload."""
    text = common_js()
    assert 'window.addEventListener("online", recoverActiveChart)' in text
    assert 'document.addEventListener("visibilitychange", () =>' in text
    assert "if (!document.hidden) recoverActiveChart();" in text
    assert "refresh(requestedPeriod);" in text


def test_chart_box_releases_width_and_canvas_fills_it():
    """The canvas must not fall back to its intrinsic 300x150 corner size."""
    box = rule_body(".chart-box {")
    assert "width: 100%" in box
    assert "min-width: 0" in box

    canvas = rule_body(".chart-box > canvas")
    assert "width: 100% !important" in canvas
    assert "height: 100% !important" in canvas
    assert "display: block" in canvas
