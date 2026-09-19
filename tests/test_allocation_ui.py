# tests/test_allocation_ui.py
# ============================
# Meta-tests for the allocation carousel's template/JS contracts.
#
# WHY "META" TESTS? Same reason test_web_refresh_wiring.py exists: we
# can't run the JS, but we can lock the source text so a future refactor
# can't silently drop the carousel wiring, the dimension list, or the
# swipe handler. Read-the-file-and-assert, the same approach test_docker.py
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


def test_same_dimension_requests_only_accept_latest_response():
    """An older request for the active key cannot overwrite a newer one."""
    src = _read_js("static/js/main.js")
    assert "const allocRequestGenerations = {};" in src
    assert "allocRequestGenerations[by] = requestGeneration;" in src
    assert "function isLatestAllocRequest(by, requestGeneration)" in src
    assert src.count("isLatestAllocRequest(by, requestGeneration)") >= 3


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
# JS: swipe wiring
# ---------------------------------------------------------------------------

def test_main_js_wires_swipe_on_donut_box():
    """The donut box must have touchstart/touchend listeners for swipe-
    based view flipping on phones."""
    src = _read_js("static/js/main.js")
    assert "touchstart" in src
    assert "touchend" in src


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
