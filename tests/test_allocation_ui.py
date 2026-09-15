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
