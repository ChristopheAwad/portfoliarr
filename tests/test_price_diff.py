"""Chart price-difference tool contract tests.

These are string checks, not rendering tests — pytest can't run a browser
or JavaScript. What they lock is the CONTRACT that the price-difference
ruler (click-and-drag on desktop, two-finger touch on mobile) is wired
end-to-end:

  1. common.js defines a priceDiffPlugin with the right hooks;
  2. the plugin uses formatPrice and CSS tokens for colors;
  3. the factory exposes a clearMeasurement method;
  4. refresh() clears the measurement state;
  5. the crosshair is suppressed while measuring;
  6. native touch listeners are attached for mobile two-finger gestures.

The visual output (dashed line, label, circles) is out of scope — that's
a browser concern.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def common_js() -> str:
    return (ROOT / "static" / "js" / "common.js").read_text()


def style_css() -> str:
    return (ROOT / "static" / "style.css").read_text()


# ── Plugin existence ─────────────────────────────────────────────────────────


def test_price_diff_plugin_exists():
    """setupTimeframeChart must register a chart-local plugin with id
    'priceDiff' that draws the measurement overlay."""
    js = common_js()
    assert "priceDiff" in js, (
        "common.js must define a priceDiff chart plugin"
    )


def test_price_diff_plugin_has_after_datasets_draw():
    """The plugin must have an afterDatasetsDraw hook to paint the dashed
    line, endpoint circles, and price-diff label after the dataset is
    drawn (so the overlay sits on top of the line)."""
    js = common_js()
    assert "afterDatasetsDraw" in js, (
        "priceDiff plugin must have an afterDatasetsDraw hook"
    )


# ── Measurement state ────────────────────────────────────────────────────────


def test_clear_measurement_exposed():
    """The chart factory must expose a clearMeasurement method on its
    return handle so callers can programmatically dismiss the overlay."""
    js = common_js()
    assert "clearMeasurement" in js, (
        "setupTimeframeChart must expose a clearMeasurement method"
    )


def test_measurement_cleared_on_refresh():
    """refresh() must reset the measurement state so switching timeframes
    drops the overlay — stale points on a new series would be confusing."""
    js = common_js()
    # The refresh function should reference the measurement state variables
    # to clear them. Look for reset logic near the top of refresh.
    assert "measureStart" in js, (
        "refresh() must reference measureStart to clear measurement state"
    )


# ── Crosshair suppression ────────────────────────────────────────────────────


def test_crosshair_suppressed_during_measure():
    """The crosshair plugin must check the measuring flag and skip drawing
    when a measurement is active — two overlapping vertical lines would be
    visual noise."""
    js = common_js()
    # The crosshairPlugin should reference the measuring flag
    assert "measuring" in js, (
        "crosshairPlugin must reference the measuring flag to suppress "
        "it during a price-diff measurement"
    )


# ── Mobile touch handling ────────────────────────────────────────────────────


def test_touch_listeners_attached():
    """setupTimeframeChart must attach native touchstart/touchmove/touchend
    listeners on the canvas for two-finger gesture detection. Chart.js
    only passes one touch point in its event system, so we need the raw
    TouchEvent.touches array."""
    js = common_js()
    assert "touchstart" in js, (
        "setupTimeframeChart must attach a touchstart listener on the canvas"
    )
    assert "touchmove" in js, (
        "setupTimeframeChart must attach a touchmove listener on the canvas"
    )
    assert "touchend" in js, (
        "setupTimeframeChart must attach a touchend listener on the canvas"
    )


def test_two_finger_detection():
    """The touch handler must check e.touches.length >= 2 to detect the
    two-finger gesture — a single finger is a normal tap, not a measure."""
    js = common_js()
    assert "touches.length" in js or "touches[" in js, (
        "touch handler must check touches.length for two-finger detection"
    )


# ── Drawing and formatting ───────────────────────────────────────────────────


def test_price_diff_uses_format_price():
    """The price-diff label must use formatPrice to display values,
    keeping formatting consistent with the rest of the app."""
    js = common_js()
    # formatPrice must appear in the priceDiff plugin context — since it's
    # in the same file, just check it's present (same pattern as
    # test_prev_close_label_shows_format_price).
    assert "formatPrice" in js, (
        "priceDiff label must call formatPrice for the value"
    )


def test_price_diff_uses_dashed_line():
    """The measurement line must use ctx.setLineDash for a dashed style,
    matching the prevCloseLine pattern."""
    js = common_js()
    assert "setLineDash" in js, (
        "priceDiff plugin must use setLineDash for a dashed measurement line"
    )


def test_price_diff_vertical_lines_use_chart_bottom():
    """The dashed guide lines must be VERTICAL — each runs from the chart
    area bottom up to the data point, not a diagonal between the two points.
    This makes it clear which date each endpoint corresponds to."""
    js = common_js()
    # The old diagonal line did: moveTo(x1, y1) → lineTo(x2, y2) — a single
    # stroke connecting two points at different heights.  Vertical lines
    # instead start from bottom: moveTo(x, bottom) → lineTo(x, y).  So the
    # old diagonal start pattern must be gone.
    assert "moveTo(x1, y1)" not in js, (
        "priceDiff plugin must NOT start a diagonal from point 1 (y1) — "
        "vertical lines must start from chartArea.bottom"
    )


def test_price_diff_reads_direction_color_tokens():
    """The overlay must read --green-pos and --red-neg from CSS for the
    price-diff label color, not hardcoded values."""
    css = style_css()
    assert "--green-pos" in css, (
        ":root must define --green-pos token"
    )
    assert "--red-neg" in css, (
        ":root must define --red-neg token"
    )
    js = common_js()
    assert "--green-pos" in js or "green-pos" in js, (
        "priceDiff plugin must read --green-pos CSS token"
    )
    assert "--red-neg" in js or "red-neg" in js, (
        "priceDiff plugin must read --red-neg CSS token"
    )


# ── Pixel-to-data mapping ────────────────────────────────────────────────────


def test_get_relative_position_used():
    """Pixel coordinates must be converted to chart-relative coordinates.
    Either Chart.helpers.getRelativePosition or manual getBoundingClientRect
    offset calculation is fine — the key contract is that the page position
    is accounted for so the overlay isn't offset."""
    js = common_js()
    assert "getRelativePosition" in js or "getBoundingClientRect" in js, (
        "priceDiff plugin must convert page pixels to chart-relative "
        "coordinates (via getRelativePosition or getBoundingClientRect)"
    )


def test_get_value_for_pixel_used():
    """Chart-relative pixel positions must be mapped back to data values
    using the scale's getValueForPixel method — this is how we know the
    PRICE at each endpoint."""
    js = common_js()
    assert "getValueForPixel" in js, (
        "priceDiff plugin must use getValueForPixel to map pixels to data "
        "values"
    )


def test_tooltip_suppressed_during_measure():
    """The priceDiff plugin must have a beforeTooltipDraw hook that cancels
    the tooltip when measuring is active — the date/price readout would
    flicker over the measurement label."""
    js = common_js()
    assert "beforeTooltipDraw" in js, (
        "priceDiff plugin must have a beforeTooltipDraw hook"
    )


# ── Data-point snapping (the fix) ────────────────────────────────────────────


def test_pixel_to_data_uses_x_scale():
    """pixelToData must find the nearest data point by X position using
    chart.scales.x.getValueForPixel — this is how we resolve which date
    the finger/cursor is closest to, matching Chart.js hover behavior."""
    js = common_js()
    assert "scales.x" in js and "getValueForPixel" in js, (
        "pixelToData must call chart.scales.x.getValueForPixel to find "
        "the nearest data point index by X position"
    )


def test_pixel_to_data_reads_dataset_values():
    """pixelToData must read the actual price from chart.data.datasets[0].data
    at the resolved index — not from the Y-axis scale. The Y scale gives an
    arbitrary value at that pixel height; the dataset has the real price at
    that date."""
    js = common_js()
    assert "datasets[0].data" in js, (
        "pixelToData must read from chart.data.datasets[0].data to get "
        "the actual price at the snapped data point"
    )


def test_pixel_to_data_snaps_y():
    """pixelToData must use chart.scales.y.getPixelForValue to convert the
    actual data value back to a pixel Y position. This snaps the dot to the
    data point instead of drawing it at the raw finger position."""
    js = common_js()
    assert "getPixelForValue" in js, (
        "pixelToData must use y.getPixelForValue to compute the snapped "
        "Y pixel position from the actual data value"
    )


def test_pixel_to_data_clamps_index():
    """The data index resolved from pixelToData must be clamped to
    [0, values.length - 1] so a finger at the chart edge doesn't read
    beyond the data array bounds."""
    js = common_js()
    # Look for clamping logic near getValueForPixel — Math.max/Math.min
    # guarding the index.
    assert "Math.max" in js and "Math.min" in js, (
        "pixelToData must clamp the resolved index with Math.max/Math.min "
        "to prevent out-of-bounds reads"
    )


def test_pixel_to_data_returns_label():
    """pixelToData must return the date label for the snapped data point
    (from chart.data.labels[index]) so the measurement overlay can display
    the dates being compared."""
    js = common_js()
    assert "labels[index]" in js or "labels[" in js, (
        "pixelToData must return the date label from chart.data.labels "
        "for the snapped data point"
    )
