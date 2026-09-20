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


def tooltip_title_callback_body() -> str:
    """Return the shared tooltip's title callback source."""
    text = common_js()
    title_at = text.find("title(items)", text.find("callbacks:"))
    assert title_at != -1, "shared tooltip lost its title callback"
    label_at = text.find("label(item)", title_at)
    assert label_at != -1, "shared tooltip title callback lost its boundary"
    return text[title_at:label_at]


def tooltip_callback_bodies() -> tuple:
    """Return (title, label, footer, footerColor) callback sources in order.

    The footerColor body is bounded by the next `scales:` block so negative
    assertions stay inside the callback and cannot match `chartNormalized`
    later in the file (e.g. in paint()).
    """
    text = common_js()
    callbacks_at = text.index("callbacks:")
    title_at = text.index("title(items)", callbacks_at)
    label_at = text.index("label(item)", title_at)
    footer_at = text.index("footer(items)", label_at)
    footer_color_at = text.index("footerColor(items)", footer_at)
    scales_at = text.index("scales: {", footer_color_at)
    return (
        text[title_at:label_at],
        text[label_at:footer_at],
        text[footer_at:footer_color_at],
        text[footer_color_at:scales_at],
    )


def tooltip_label_callback_body() -> str:
    return tooltip_callback_bodies()[1]


def tooltip_footer_callback_body() -> str:
    return tooltip_callback_bodies()[2]


def tooltip_footer_color_callback_body() -> str:
    return tooltip_callback_bodies()[3]


def test_opposite_positioner_latches_tooltip_to_far_edge():
    """The box must stay at its edge while the crosshair is near center."""
    js = common_js()
    assert "function oppositePositioner(items, eventPosition)" in js
    assert "chart._tooltipSide" in js
    assert "Math.abs(x - midX) > deadband" in js
    assert 'const targetSide = x <= midX ? "right" : "left";' in js
    assert 'x: side === "right" ? right : left' in js
    assert 'xAlign: side === "right" ? "right" : "left"' in js


def test_opposite_positioner_uses_continuous_pointer_y():
    """The tooltip must glide with the mouse instead of hopping by bar value."""
    js = common_js()
    assert "Math.max(top, Math.min(eventPosition.y, bottom))" in js


def test_opposite_positioner_is_registered():
    """The custom mode must be available before Chart.js builds the chart."""
    assert (
        "Chart.Tooltip.positioners.opposite = oppositePositioner;"
        in common_js()
    )


def test_shared_tooltip_uses_opposite_positioner_without_caret():
    """Both line charts opt in, hide the caret, and jump between edges.

    Chart.js otherwise animates numeric tooltip geometry for 400ms, which
    would sweep the card across the crosshair whenever its target edge flips.
    Opacity may still fade, but position and size must update immediately.
    """
    body = tooltip_options_body()
    assert 'position: "opposite"' in body
    assert "caretSize: 0" in body
    assert "animations:" in body
    assert "numbers:" in body
    assert "duration: 0" in body


def test_year_spanning_tooltip_keeps_exact_trading_date():
    """Crossing New Year must not reduce a hovered daily bar to month/year.

    The x-axis may use compact labels such as "Sep 2025", but the tooltip
    identifies one actual price point and must retain its day as well.
    """
    body = tooltip_title_callback_body()
    assert "monthYear(p)" not in body
    assert "`${monthDay(p)}, ${p.y}`" in body


def test_five_day_tooltip_keeps_the_exact_bar_time():
    """A 30-minute 5D bar needs its time, not only its trading date."""
    js = common_js()
    assert (
        "const DATETIME_RE = "
        "/^(\\d{4})-(\\d{2})-(\\d{2}) (\\d{2}):(\\d{2})$/;"
        in js
    )
    body = tooltip_title_callback_body()
    assert "`${monthDay(p)}, ${m[4]}:${m[5]}`" in body


def test_comparison_tooltip_body_and_footer_are_date_only():
    """In comparison mode the floating tooltip shows only the hovered date.

    The performance readout lives in the bottom comparison legend instead, so
    the label and footer callbacks must empty their payloads while the title
    callback keeps formatting the date.
    """
    title, label, footer, _ = tooltip_callback_bodies()
    assert "monthDay" in title
    assert "if (comparisonMode) return [];" in label
    assert "if (comparisonMode) return [];" in footer


def test_comparison_footer_color_is_neutral():
    """There is no visible footer to color while comparing."""
    body = tooltip_footer_color_callback_body()
    assert "comparisonMode" in body
    assert "chartNormalized" not in body


def test_normal_tooltip_return_footer_is_preserved():
    """Portfolio Performance WITHOUT overlays keeps its Return footer."""
    footer = tooltip_footer_callback_body()
    assert 'if (mode === "performance") {' in footer
