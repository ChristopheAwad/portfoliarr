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


# ── Tooltip dismissal on touch (the fix) ─────────────────────────────────────


def _hook_bodies(js: str, signature: str) -> list[str]:
    """Extract the body of every JS function whose header contains
    `signature`, matching braces so a hook that never resolves can't let
    the NEXT hook's code satisfy an assertion."""
    bodies = []
    start = 0
    while True:
        idx = js.find(signature, start)
        if idx == -1:
            break
        brace = js.find("{", idx)
        depth = 1
        i = brace + 1
        while i < len(js) and depth:
            if js[i] == "{":
                depth += 1
            elif js[i] == "}":
                depth -= 1
            i += 1
        bodies.append(js[brace + 1:i - 1])
        start = i
    return bodies


def test_touch_ghost_guard_plugin_exists():
    """common.js must register a chart-local 'touchGhostGuard' plugin that
    swallows the platform's post-touch ghost events (synthetic mouse
    events, and any rAF-replayed touchstart) which would otherwise
    resurrect a tooltip the user just dismissed."""
    js = common_js()
    assert 'id: "touchGhostGuard"' in js, (
        "common.js must define a touchGhostGuard chart plugin"
    )


def test_before_event_hooks_cancel_with_return_false():
    """Both beforeEvent hooks (priceDiff measurement suppression and
    touchGhostGuard) must cancel by RETURNING false. Chart.js's
    core.plugins.js `_notify` aborts the hook chain only on a false
    return; `args.cancel = true` is never read, so it silently fails to
    cancel and the tooltip re-activates."""
    js = common_js()
    bodies = _hook_bodies(js, "beforeEvent(chart, args)")
    assert len(bodies) == 2, (
        "expected both beforeEvent hooks (priceDiff + touchGhostGuard)"
    )
    for body in bodies:
        assert "return false" in body, (
            "every beforeEvent hook must cancel by returning false"
        )


def test_args_cancel_is_not_used_in_code():
    """Guards against reintroducing the dead `args.cancel = true` API —
    comments may mention it, executable code must not."""
    js = common_js()
    code = "\n".join(
        line for line in js.splitlines()
        if not line.lstrip().startswith("//")
    )
    assert "args.cancel" not in code, (
        "args.cancel is dead API — cancel a beforeEvent hook by returning "
        "false instead"
    )


def test_touch_cancel_listener_attached():
    """An interrupted gesture (scroll takeover, Android back, incoming
    call) fires touchcancel, not touchend — a listener must exist so the
    hover still ends and the tooltip can't stay pinned."""
    js = common_js()
    assert '"touchcancel"' in js, (
        "setupTimeframeChart must attach a touchcancel listener"
    )


def test_touch_cancel_finalizes_measurement():
    """touchcancel must also reset the measuring flag: a cancelled
    two-finger gesture never gets its touchend, so leaving it set would
    strand a phantom ruler and keep the tooltip/crosshair suppressed."""
    js = common_js()
    bodies = _hook_bodies(js, 'addEventListener("touchcancel"')
    assert bodies, "touchcancel listener must exist"
    assert "_priceDiffMeasuring = false" in bodies[0], (
        "touchcancel must reset _priceDiffMeasuring when measuring"
    )


def test_last_finger_lift_marks_hover_dormant():
    """touchend on the last finger must clear the tooltip and mark the
    hover dormant, arming touchGhostGuard to swallow the ghost events the
    platform fires right after."""
    js = common_js()
    assert "_hoverDormant = true" in js, (
        "touchend/touchcancel must set _hoverDormant to true"
    )
    assert "_ghostEventsUntil" in js, (
        "the ghost-event window must be armed on last-finger lift"
    )


# Interaction regressions: inspect the actual gesture branches, rather than
# accepting an unrelated comment or another chart's handler as evidence.
def _gesture_body(signature: str) -> str:
    bodies = _hook_bodies(common_js(), signature)
    assert len(bodies) == 1, f"expected one gesture handler: {signature}"
    return bodies[0]


def test_ruler_requires_raw_values_for_mouse_and_touch():
    js = common_js()
    assert "function canMeasurePrice()" in js
    for signature in ('addEventListener("mousedown"',
                      'addEventListener("touchstart"'):
        assert "canMeasurePrice()" in _gesture_body(signature)
    guard = _gesture_body("function canMeasurePrice()")
    assert 'mode === "value"' in guard
    assert "!chartNormalized" in guard


def test_ruler_snaps_all_coordinates_to_a_finite_primary_bar():
    body = _gesture_body("function pixelToData(")
    assert "Number.isFinite(dataValue)" in body
    assert "getPixelForValue(index)" in body
    assert "x: px" not in body
    assert "getPixelForValue(dataValue)" in body


def test_mouse_click_and_drag_have_separate_states():
    down = _gesture_body('addEventListener("mousedown"')
    move = _gesture_body('addEventListener("mousemove"')
    up = _gesture_body('canvas.addEventListener("mouseup"')
    assert "_ghostEventsUntil" in down
    assert "mousePress" in down and "measureStart = pixelToData" not in down
    assert "MOUSE_DRAG_THRESHOLD" in move and "mousePress" in move
    assert "measureStart = pixelToData" in move
    assert "finishMouseGesture" in up
    assert "mousePress = null" in _gesture_body("function finishMouseGesture()")
    assert "finishMouseGesture" in _gesture_body('document.addEventListener("mouseup"')


def test_finished_ruler_suppresses_hover_and_new_touch_can_dismiss_it():
    js = common_js()
    assert "_priceDiffMeasuring || chart._priceDiffPinned" in js
    before_events = _hook_bodies(js, "beforeEvent(chart, args)")
    assert "_priceDiffPinned" in before_events[0]
    assert "_priceDiffPinned" in _hook_bodies(js, "beforeTooltipDraw(chart)")[0]
    assert "_priceDiffPinned" in js.split('id: "costLine"', 1)[1].split(
        "data: {", 1)[0]
    assert "_priceDiffPinned" in _gesture_body('addEventListener("touchstart"')
    assert "_priceDiffPinned" in _gesture_body('addEventListener("mousedown"')


def test_staggered_touch_release_does_not_restart_hover():
    end = _gesture_body('addEventListener("touchend"')
    move = _gesture_body('addEventListener("touchmove"')
    assert "e.touches.length === 0" in end
    assert "_priceDiffMeasuring = false" in end
    assert "_priceDiffMeasuring = false" not in move
    assert move.index("e.preventDefault()") < move.index("e.touches.length < 2")
    assert "_priceDiffPinned" in end


def test_mode_switch_and_empty_chart_drop_old_ruler():
    mode_body = _gesture_body('modeBar.addEventListener("click"')
    assert "clearMeasurement" in mode_body
    assert "if (values.length === 0) return null;" in _gesture_body(
        "function pixelToData(")
