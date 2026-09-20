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
    body = refresh_body()
    visible_branch = body.index("if (!silent) {")
    recovery_target = body.index("requestedPeriod = period;")
    visible_generation = body.index(
        "visibleGeneration = ++visibleRequestGeneration;"
    )
    assert visible_branch < recovery_target < visible_generation


def test_silent_prefetch_never_changes_or_paints_the_selection():
    """Cache warming must return before latest-selection checks and painting."""
    body = refresh_body()
    silent_return = body.index("if (silent) return;")
    latest_guard = body.index(
        "if (visibleGeneration !== visibleRequestGeneration) return;"
    )
    paint = body.index("paint(data, period);")
    assert silent_return < latest_guard < paint


def test_stale_same_period_response_cannot_replace_newer_cache_data():
    """Only the latest request for one page+comparison state may write its cache.

    The key combines the period with the ordered comparison list so a plain
    chart and an overlay chart share nothing (see test_compare.test_portfolio_
    one_benchmark_rebases_against_axis for the two-reply behavior).
    """
    body = refresh_body()
    cache_write = body.index(
        "chartCache[cacheKey] = { data, fetchedAt: Date.now() };"
    )
    cache_guard = body.index(
        "if (isLatestChartRequest(period, requestGeneration))"
    )
    assert "const cacheKey = `" in body
    assert "${benchmarks.join(",")}" in body
    assert cache_guard < cache_write


def test_a_b_a_response_order_uses_request_generation_not_period_name():
    """The first A response must stay stale after the user returns to A."""
    text = common_js()
    body = refresh_body()
    assert "let visibleRequestGeneration = 0;" in text
    assert "visibleGeneration = ++visibleRequestGeneration;" in body
    assert "if (visibleGeneration !== visibleRequestGeneration) return;" in body
    assert "if (period !== requestedPeriod) return;" not in body


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
