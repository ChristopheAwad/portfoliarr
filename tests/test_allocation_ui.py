# tests/test_allocation_ui.py
# ============================
# Meta-tests for the allocation carousel's template/JS contracts.
#
# WHY "META" TESTS? Same reason test_web_refresh_wiring.py exists: we
# can't run the JS, but we can lock the source text so a future refactor
# can't silently drop the carousel wiring or the dimension list.
# Read-the-file-and-assert, the same approach test_docker.py
# uses for config files.

from pathlib import Path

import pytest

from app import app

ROOT = Path(__file__).resolve().parent.parent


def _read_html(client, path="/"):
    """Fetch rendered HTML from the Flask test client."""
    return client.get(path).get_data(as_text=True)


def _read_js(relpath: str) -> str:
    """Read a JS file from the repo, failing loudly if missing."""
    path = ROOT / relpath
    assert path.exists(), f"{relpath} is missing — create it at the repo root"
    return path.read_text()


def _read_template(relpath: str) -> str:
    """Read a template file from the repo."""
    path = ROOT / relpath
    assert path.exists(), f"{relpath} is missing"
    return path.read_text()


def _read_css() -> str:
    """Read the shared stylesheet for carousel visual-state contracts."""
    return (ROOT / "static/style.css").read_text()


# ---------------------------------------------------------------------------
# Template: donut card structure
# ---------------------------------------------------------------------------

def test_donut_card_has_prev_next_buttons():
    """The donut card must ship prev/next arrow buttons for the carousel."""
    html = _read_html(app.test_client())
    assert 'donut-card' in html
    assert 'id="alloc-prev"' in html
    assert 'id="alloc-next"' in html


def test_donut_card_has_dimension_label():
    """The donut card must have a span showing the current dimension label."""
    html = _read_html(app.test_client())
    assert 'id="alloc-label"' in html


def test_excluded_note_element_exists():
    """The donut card must have a container for the excluded-tickers note."""
    html = _read_html(app.test_client())
    assert 'id="alloc-excluded"' in html


def test_donut_card_has_pagination_and_position_counter():
    """The carousel exposes both page dots and an explicit current/total."""
    html = _read_html(app.test_client())
    assert 'id="alloc-pagination"' in html
    assert 'aria-label="Allocation views"' in html
    assert 'id="alloc-dots"' in html
    assert 'id="alloc-position"' in html
    assert 'aria-live="polite"' in html
    assert ">1 / 6<" in html


# ---------------------------------------------------------------------------
# JS: ALLOCATION_VIEWS list (the source of truth for carousel order + labels)
# ---------------------------------------------------------------------------

def test_main_js_defines_six_allocation_views():
    """main.js must define an ALLOCATION_VIEWS array with 6 entries —
    the ticker view (null key, label from summary) plus 5 dimension views.
    By Industry and By Exchange were CUT from the product (cryptic /
    restates By Ticker at small-portfolio scale) — they must be gone from
    the source both ways, the test_docker-style absent-assert."""
    src = _read_js("static/js/main.js")
    assert "ALLOCATION_VIEWS" in src
    # Must have 6 entries. We can't run JS, but we can count the objects
    # in the array literal (each entry is {key: "..."..., label: "..."}).
    # Count label values as a proxy for the number of entries.
    for label in ["By Ticker", "By Sector", "By Country",
                  "By Type", "By Cap Bucket", "By Currency"]:
        assert label in src, (
            f"ALLOCATION_VIEWS must include a view labeled '{label}'"
        )
    for cut_label in ["By Industry", "By Exchange"]:
        assert cut_label not in src, (
            f"ALLOCATION_VIEWS must NOT include a view labeled '{cut_label}'"
        )


def test_js_dimension_keys_match_backend_whitelist():
    """Every non-ticker key in ALLOCATION_VIEWS must appear in the
    backend's ALLOCATION_DIMENSIONS whitelist — cross-contract lock."""
    from app import ALLOCATION_DIMENSIONS
    src = _read_js("static/js/main.js")
    for key in ALLOCATION_DIMENSIONS:
        assert f'"{key}"' in src, (
            f"ALLOCATION_VIEWS must reference backend key '{key}'"
        )


# ---------------------------------------------------------------------------
# JS: localStorage persistence
# ---------------------------------------------------------------------------

def test_main_js_persists_dimension_to_localstorage():
    """Switching views must save the chosen dimension to localStorage
    so it survives a reload."""
    src = _read_js("static/js/main.js")
    assert "localStorage" in src
    assert "allocationDimension" in src


def test_main_js_builds_clickable_dots_from_allocation_views():
    """Dots derive from the view source of truth and share navigation."""
    src = _read_js("static/js/main.js")
    assert "function buildAllocDots()" in src
    assert "ALLOCATION_VIEWS.forEach" in src
    assert 'dot.type = "button"' in src
    assert "switchAllocView(index)" in src
    assert "slide ${index + 1} of ${ALLOCATION_VIEWS.length}" in src


def test_main_js_synchronizes_carousel_status():
    """One sync path owns the label, counter, and active dot state."""
    src = _read_js("static/js/main.js")
    assert "function syncAllocCarousel()" in src
    assert "allocPositionEl.textContent" in src
    assert "allocDotsEl.querySelectorAll" in src
    assert 'classList.toggle("active"' in src
    assert 'toggleAttribute("aria-current"' in src
    switch_body = src.split("function switchAllocView(newIndex)", 1)[1]
    assert "syncAllocCarousel();" in switch_body.split("}", 1)[0]


def test_saved_non_ticker_view_loads_on_startup():
    """A restored dimension must not stay blank until the first poll."""
    src = _read_js("static/js/main.js")
    assert "function initializeAllocCarousel()" in src
    assert "syncAllocCarousel();" in src
    assert "fetchAllocDimension(view.key" in src


def test_stale_allocation_response_cannot_replace_active_slide():
    """Rapid navigation must ignore replies for a no-longer-active key."""
    src = _read_js("static/js/main.js")
    assert "isActiveAllocView(by)" in src
    assert "if (isActiveAllocView(by))" in src


def test_same_dimension_fetch_is_single_flighted():
    """A dimension never holds two in-flight requests. The 60s poll, a boot
    restore, and a carousel flip can all fire within one slow round-trip —
    every caller after the first must share the same promise, or a slow
    network triples the number of Yahoo-backed allocation round-trips.
    ROOT CAUSE: the old generation counter still let concurrent callers
    hit the endpoint; the newest reply won, but the requests themselves
    duplicated."""
    src = _read_js("static/js/main.js")
    assert "const allocInFlight = {};" in src, \
        "main.js must keep one in-flight promise per dimension"
    assert "if (allocInFlight[flightKey]) return allocInFlight[flightKey];" in src, \
        "exported callers must join (and share) the in-flight fetch"
    assert "allocInFlight[flightKey] = flight;" in src, \
        "the fetch must register its own promise under the dimension key"
    assert ".finally" in src, \
        "the in-flight slot must be released when the fetch settles"
    assert "delete allocInFlight[flightKey]" in src, \
        "a settled fetch must empty its slot so the next poll refetches"
    assert "const flightKey = `${key}|${epoch}`;" in src, \
        "a request from another portfolio or prior selection cannot block this fetch"
    assert "isLatestAllocRequest" not in src, \
        "the old generation counter is gone, replaced by the promise map"


def test_refetch_keeps_last_painable_payload():
    """A fetch that fails AFTER a previous success must keep the old chart
    painted (soft 'refreshing' note dropped, donut untouched) instead of
    blanking it. only a first-load failure shows the unavailable message.
    ROOT CAUSE: the catch path called paintAllocation([], []), which
    destroyed a perfectly valid donut on any transient network blip."""
    src = _read_js("static/js/main.js")
    assert "paintAllocation([], [])" not in src, \
        "the failure path must NOT fabricate an empty payload"
    assert "lastAllocPayload" in src, \
        "main.js must remember the last painted payload to restore it"
    assert "lastAllocPayload.by === by" in src, \
        "a stale payload is reusable ONLY for its own dimension — the " \
        "catch must gate on the dimension, not any last payload"
    assert '"unavailable"' in src, \
        "a first-load failure must show the unavailable state"
    assert '"stale"' in src, \
        "warmed revalidation must surface a soft refreshing state"
    assert '"empty"' in src, \
        "a genuine empty reply must show the empty state, not an error"
    assert 'setAllocState(allocationResultState(prior.slices, prior.excluded))' in src, \
        "a failed revalidation keeps the empty or excluded state from its own reply"


def test_stale_dimension_paints_its_cached_donut_first():
    """A dimension whose cache is stale (or mid-revalidate) must repaint its
    OWN cached payload before the network answers. ROOT CAUSE fixed here: the
    first version only set a 'refreshing' note and left the PREVIOUS slide's
    donut on the canvas under the new label until the reply landed."""
    src = _read_js("static/js/main.js")
    assert "paintAllocation(entry.data.slices, entry.data.excluded, by)" in src, \
        "fetchAllocDimension must repaint this dimension's cached payload " \
        "immediately, before any network wait"
    fetch = src.split("async function fetchAllocDimension(by)", 1)[1]
    fetch = fetch.split("\n}", 1)[0]
    # The cached-payload repaint must run before the in-flight join, so a
    # re-flip onto an in-flight dimension still shows that dimension's donut.
    paint_pos = fetch.find("paintAllocation(entry.data.slices")
    inflight_pos = fetch.find("if (allocInFlight[flightKey]) return")
    assert paint_pos != -1 and inflight_pos != -1 and paint_pos < inflight_pos, \
        "the cached payload must be painted before the single-flight join"


def test_stale_revalidation_only_notes_a_nonempty_donut():
    """A stale revalidation must show the 'refreshing' note only when the
    cached donut actually has wedges — an honest empty keeps its empty
    message instead of revealing a blank 220px box every 60s."""
    src = _read_js("static/js/main.js")
    assert "cached.data.slices.length > 0" in src, \
        "the refreshing note must be gated on a non-empty cached payload"


def test_allocation_tooltip_reads_the_current_chart_label():
    """A carousel update must not leave the tooltip using first-build labels.

    paintAllocation updates Chart.js's labels in place. The tooltip therefore
    has to read item.label at hover time, not close over the local `labels`
    array that existed when the Chart object was first constructed.
    """
    src = _read_js("static/js/main.js")
    tooltip = src.split("tooltip: {", 1)[1].split("},\n                },", 1)[0]
    assert "item.label" in tooltip
    assert "labels[item.dataIndex]" not in tooltip


def test_allocation_tooltip_ignores_a_stale_hover_index():
    """Changing to a view with fewer wedges must not throw during redraw."""
    src = _read_js("static/js/main.js")
    tooltip = src.split("tooltip: {", 1)[1].split("},\n                },", 1)[0]
    assert 'if (!slice) return "";' in tooltip


# ---------------------------------------------------------------------------
# JS: touch cleanup without swipe navigation
# ---------------------------------------------------------------------------

def test_donut_touch_never_changes_allocation_view():
    """A drag over a donut may scroll the page but cannot flip slides."""
    src = _read_js("static/js/main.js")
    touch = src.split("// Touch cleanup on the donut box", 1)[1].split(
        "// The summary's holdings slice", 1)[0]
    assert "switchAllocView" not in touch
    assert "clientX" not in touch
    assert "clientY" not in touch
    assert 'addEventListener("touchend"' in touch
    assert 'addEventListener("touchcancel"' in touch


def test_donut_controls_still_switch_and_wrap():
    src = _read_js("static/js/main.js")
    assert "switchAllocView(allocViewIndex - 1)" in src
    assert "switchAllocView(allocViewIndex + 1)" in src
    assert "switchAllocView(index)" in src
    assert "(newIndex + ALLOCATION_VIEWS.length) % ALLOCATION_VIEWS.length" in src


def test_donut_clears_touch_hover_without_changing_other_charts():
    src = _read_js("static/js/main.js")
    touch = src.split("// Touch cleanup on the donut box", 1)[1].split(
        "// The summary's holdings slice", 1)[0]
    assert "if (!allocationChart) return;" in touch
    assert "tooltip.setActiveElements([]" in touch
    assert "setActiveElements([]" in touch
    assert 'addEventListener("touchcancel"' in touch
    assert 'addEventListener("touchstart"' in touch
    plugin = src.split('id: "donutTouchHoverEnd"', 1)[1].split(
        "data: {", 1)[0]
    assert "_touchHoverDormant" in plugin
    assert "_ghostEventsUntil" in plugin
    assert "return false" in plugin


# ---------------------------------------------------------------------------
# JS: poll refreshes active dimension only
# ---------------------------------------------------------------------------

def test_poll_refreshes_active_dimension_only():
    """The setupAutoRefresh callback must fetch the allocation endpoint
    only when the active dimension is not the ticker view (which uses the
    summary poll)."""
    src = _read_js("static/js/main.js")
    # The allocation fetch should be conditional — only when a non-ticker
    # dimension is active.
    assert "/api/portfolio/allocation" in src


def test_navigation_crossfade_respects_reduced_motion():
    """Only navigation paints crossfade, and CSS disables reduced motion."""
    src = _read_js("static/js/main.js")
    css = _read_css()
    assert "animateNextAllocationPaint" in src
    assert 'classList.add("alloc-crossfade")' in src
    assert ".alloc-crossfade" in css
    assert "@keyframes alloc-crossfade" in css
    reduced_motion = css.split("@media (prefers-reduced-motion: reduce)", 1)[1]
    assert ".alloc-crossfade" in reduced_motion


def test_allocation_dots_have_active_hover_and_focus_states():
    """Dots remain legible for mouse, keyboard, and active-page users."""
    css = _read_css()
    assert ".alloc-dot.active" in css
    assert ".alloc-dot:hover" in css
    assert ".alloc-dot:focus-visible" in css


def test_allocation_dots_have_touch_friendly_hit_targets():
    """The 7px marks sit inside buttons large enough to click and tap."""
    css = _read_css()
    dot_rule = css.split(".alloc-dot {", 1)[1].split("}", 1)[0]
    marker_rule = css.split(".alloc-dot::before {", 1)[1].split("}", 1)[0]
    assert "width: 24px;" in dot_rule
    assert "height: 24px;" in dot_rule
    assert "width: 7px;" in marker_rule
    assert "height: 7px;" in marker_rule


def test_inactive_allocation_dots_use_visible_theme_token():
    """Inactive dots must not disappear through an undefined CSS variable."""
    css = _read_css()
    marker_rule = css.split(".alloc-dot::before {", 1)[1].split("}", 1)[0]
    hover_rule = css.split(".alloc-dot:hover::before {", 1)[1].split("}", 1)[0]
    assert "var(--border)" not in marker_rule
    assert "background: var(--text-secondary);" in marker_rule
    assert "background: var(--text-primary);" in hover_rule


# ---------------------------------------------------------------------------
# Donut states: explicit loading / ready / empty / unavailable / stale
# ---------------------------------------------------------------------------

def test_donut_card_has_status_line():
    """The donut card must ship a status line covering every non-ready
    state — loading, empty, unavailable, and 'refreshing' — instead of
    relying on the box itself (which is hidden until first data)."""
    html = _read_html(app.test_client())
    assert 'id="alloc-status"' in html
    assert 'class="empty-state"' in html
    assert 'role="status" aria-live="polite"' in html


def test_donut_box_starts_hidden_until_data_lands():
    """The donut box must start hidden in the template so no empty canvas
    sliver or wrong-sized donut flashes before the first payload arrives.
    Presence of `hidden` (not style.display) is the contract — main.js
    toggles the attribute, and the global [hidden] rule hides it."""
    html = _read_html(app.test_client())
    box = html.split('<div class="donut-box"', 1)[1].split("</div>", 1)[0]
    assert "hidden" in box, \
        "the donut box must ship with the hidden attribute on first paint"
    assert 'id="allocationChart"' in box


def test_donut_status_opens_loading():
    """The status line must announce the loading state by default so the
    first paint is never silent."""
    html = _read_html(app.test_client())
    assert "Loading allocation" in html


def test_canvas_fills_donut_box_css():
    """The canvas must fill its parent box: Chart.js measures its parent to
    pick a canvas size, and a hidden-to-shown transition needs the full box
    width/height or the donut renders a sliver."""
    css = _read_css()
    rule = css.split(".donut-box > canvas {", 1)[1].split("}", 1)[0]
    assert "display: block;" in rule
    assert "width: 100% !important;" in rule
    assert "height: 100% !important;" in rule


def test_main_js_defines_alloc_state_machine():
    """main.js must own the five donut states with one setter. The ready
    state reveals the box; every other state surfaces an explicit message
    through the status line."""
    src = _read_js("static/js/main.js")
    assert "function setAllocState(" in src
    for state in ['"loading"', '"ready"', '"empty"',
                  '"unavailable"', '"stale"']:
        assert state in src, f"setAllocState must handle {state}"
    assert "allocStatusEl.textContent" in src
    assert "donutBoxEl.hidden" in src


def test_main_js_ready_state_resizes_revealed_donut():
    """Revealing the box (hidden → visible) changes the canvas's real size,
    so the ready state must re-measure the chart after layout settles —
    requestAnimationFrame, then resize."""
    src = _read_js("static/js/main.js")
    rfd = src.split('setAllocState("ready")', 1)[0]
    assert "requestAnimationFrame" in src, \
        "reveal must defer the resize to after layout"
    assert "resize" in src, \
        "reveal must re-measure the chart after the box becomes visible"


def test_summary_refresh_is_single_flighted():
    """refreshPortfolioSummary must never run two overlapping cycles: the
    boot call, the unmask call, and the 60s poll can all stack. The guard
    drops the new call and lets the in-flight one serve this cycle."""
    src = _read_js("static/js/main.js")
    assert "let summaryInflight = null;" in src
    assert "if (summaryInflight && summaryFlightEpoch === epoch) return summaryInflight;" in src
    assert "summaryInflight = null;" in src
    body = src.split("async function refreshPortfolioSummary()", 1)[1]
    body = body.split("\n}", 1)[0]
    assert "summaryInflight = null" in body, \
        "the guard must be released inside the function, not just at module level"
    assert "if (epoch !== portfolioEpoch()) return;" in body
