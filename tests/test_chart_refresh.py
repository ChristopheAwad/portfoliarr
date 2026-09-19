"""Frontend request-order contracts for the shared timeframe chart.

Pytest does not execute the browser JavaScript, so these tests lock the
state transitions in setupTimeframeChart: background prefetches stay silent,
only the latest visible request can paint, and the selected button describes
the period that actually reached the canvas.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def common_js() -> str:
    return (ROOT / "static" / "js" / "common.js").read_text()


def refresh_body() -> str:
    text = common_js()
    start = text.index("async function refresh(period = defaultPeriod")
    end = text.index("// ── The render half", start)
    return text[start:end]


def timeframe_click_body() -> str:
    text = common_js()
    start = text.index('buttonBar.addEventListener("click"')
    end = text.index("// History is not part", start)
    return text[start:end]


def test_visible_request_becomes_the_recovery_target():
    """The latest user request remains retryable after an offline failure."""
    assert "if (!silent) requestedPeriod = period;" in refresh_body()


def test_silent_prefetch_never_changes_or_paints_the_selection():
    """Cache warming must return before latest-selection checks and painting."""
    body = refresh_body()
    silent_return = body.index("if (silent) return;")
    latest_guard = body.index("if (period !== requestedPeriod) return;")
    paint = body.index("paint(data, period);")
    assert silent_return < latest_guard < paint


def test_stale_visible_response_cannot_repaint_the_chart():
    """An older response may fill the cache but must not replace newer data."""
    body = refresh_body()
    cache_write = body.index("chartCache[period] = { data, fetchedAt: Date.now() };")
    latest_guard = body.index("if (period !== requestedPeriod) return;")
    paint = body.index("paint(data, period);")
    assert cache_write < latest_guard < paint


def test_successful_current_paint_updates_the_timeframe_button():
    """Selection changes only after the requested period successfully paints."""
    body = refresh_body()
    assert body.index("paint(data, period);") < body.index(
        "syncTimeframeButtons(period);"
    )


def test_click_does_not_claim_the_period_before_fetch_success():
    """A failed click must leave the old chart and old selected button paired."""
    body = timeframe_click_body()
    assert "refresh(period);" in body
    assert "classList.remove" not in body
    assert "classList.add" not in body
