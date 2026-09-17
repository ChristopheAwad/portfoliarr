"""Tooltip-positioning contracts for the shared Chart.js line charts.

These are source checks rather than rendering tests: pytest cannot run the
browser, but it can ensure the dashboard and stock-detail charts keep the
custom positioner that parks their tooltip at the plot edge opposite the
active crosshair.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def common_js() -> str:
    return (ROOT / "static" / "js" / "common.js").read_text()


def tooltip_options_body() -> str:
    """Return the shared line chart's tooltip options before its callbacks."""
    text = common_js()
    tooltip_at = text.find("tooltip: {", text.find("interaction:"))
    assert tooltip_at != -1, "shared chart factory lost its tooltip options"
    callbacks_at = text.find("callbacks:", tooltip_at)
    assert callbacks_at != -1, "tooltip options lost their callbacks block"
    return text[tooltip_at:callbacks_at]


def test_opposite_positioner_pins_tooltip_to_far_edge():
    """The box must use the plot edge opposite the active crosshair."""
    js = common_js()
    assert "function oppositePositioner(items)" in js
    assert "x: crosshairLeft ? right : left" in js
    assert 'xAlign: crosshairLeft ? "right" : "left"' in js


def test_opposite_positioner_is_registered():
    """The custom mode must be available before Chart.js builds the chart."""
    assert (
        "Chart.Tooltip.positioners.opposite = oppositePositioner;"
        in common_js()
    )


def test_shared_tooltip_uses_opposite_positioner_without_caret():
    """Both shared line charts opt in and hide the disconnected caret."""
    body = tooltip_options_body()
    assert 'position: "opposite"' in body
    assert "caretSize: 0" in body
