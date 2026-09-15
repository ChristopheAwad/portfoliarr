# tests/test_web_refresh_wiring.py
# ====================================
# Meta-tests for the shared auto-refresh wiring in static/js/.
#
# WHY "META" TESTS?  The frontend JS has no pytest harness — we can't
# execute it here. What we CAN prove is that the source text contains
# the right wiring, so a future refactor can't silently drop the
# reconnect logic. Same approach test_docker.py uses for config files:
# read the artifact as text and assert on it.
#
# WHAT THESE TESTS CANNOT PROVE: that the JS actually executes correctly
# in a browser. That's the user's manual GUI gate.

from pathlib import Path

# Repo root = parent of tests/.
ROOT = Path(__file__).resolve().parent.parent


def _read_js(relpath: str) -> str:
    """Read a JS file from the repo, failing loudly if missing."""
    path = ROOT / relpath
    assert path.exists(), f"{relpath} is missing — create it at the repo root"
    return path.read_text()


# ---------------------------------------------------------------------------
# common.js — setupAutoRefresh definition
# ---------------------------------------------------------------------------

def test_common_defines_setupAutoRefresh():
    """common.js must export a setupAutoRefresh(refreshFn) helper.

    This is the single shared entry point for auto-refresh on all pages.
    It owns the setInterval, pauses while hidden, and fires refresh
    immediately on visibility change / network reconnect. Every page
    script must use it instead of its own raw setInterval.
    """
    src = _read_js("static/js/common.js")
    assert "function setupAutoRefresh" in src, (
        "common.js must define setupAutoRefresh"
    )


def test_common_wires_visibilitychange():
    """setupAutoRefresh must listen for the visibilitychange event.

    When the user switches tabs or returns to the app after
    backgrounding it, the page should refresh immediately instead of
    waiting for the next 60s tick. The visibilitychange event is the
    standard way to detect this in both browsers and Android WebView.
    """
    src = _read_js("static/js/common.js")
    assert "visibilitychange" in src, (
        "common.js must wire a visibilitychange listener for instant "
        "refresh on foreground"
    )


def test_common_wires_online_event():
    """setupAutoRefresh must listen for the window online event.

    When the device reconnects (Wi-Fi restored, airplane mode off, Doze
    ends), the page should refresh immediately and show a success toast.
    The 'online' event fires on the window when the browser regains
    network connectivity.
    """
    src = _read_js("static/js/common.js")
    assert '"online"' in src or "'online'" in src, (
        "common.js must wire an 'online' window event listener"
    )


def test_common_pauses_while_hidden():
    """setupAutoRefresh must stop the interval while document.hidden is true.

    Firing fetch requests while the app is backgrounded burns battery
    and generates the failure-toast storm in Android Doze. The interval
    must be cleared on hide and restarted on show.
    """
    src = _read_js("static/js/common.js")
    assert "document.hidden" in src, (
        "setupAutoRefresh must check document.hidden to pause polling "
        "while backgrounded"
    )


# ---------------------------------------------------------------------------
# Page scripts — must use setupAutoRefresh, not raw setInterval
# ---------------------------------------------------------------------------

def test_main_uses_setupAutoRefresh():
    """main.js must use setupAutoRefresh, not its own raw setInterval.

    Raw setInterval forgets to pause while hidden, fires the failure
    toast on every missed tick, and doesn't refresh instantly on
    foreground. The shared helper handles all three.
    """
    src = _read_js("static/js/main.js")
    assert "setupAutoRefresh" in src, (
        "main.js must call setupAutoRefresh instead of raw setInterval"
    )
    # Ensure no raw 60s poll remains — the interval reference is owned
    # by setupAutoRefresh, not by the page script.
    assert "setInterval" not in src, (
        "main.js must not contain a raw setInterval — use setupAutoRefresh"
    )


def test_ledger_uses_setupAutoRefresh():
    """ledger.js must use setupAutoRefresh, not its own raw setInterval.

    Same contract as main.js: the shared helper owns the interval and
    the visibility/online wiring.
    """
    src = _read_js("static/js/ledger.js")
    assert "setupAutoRefresh" in src, (
        "ledger.js must call setupAutoRefresh instead of raw setInterval"
    )
    assert "setInterval" not in src, (
        "ledger.js must not contain a raw setInterval — use setupAutoRefresh"
    )


def test_stock_uses_setupAutoRefresh():
    """stock.js must use setupAutoRefresh, not its own raw setInterval.

    Same contract as main.js and ledger.js.
    """
    src = _read_js("static/js/stock.js")
    assert "setupAutoRefresh" in src, (
        "stock.js must call setupAutoRefresh instead of raw setInterval"
    )
    assert "setInterval" not in src, (
        "stock.js must not contain a raw setInterval — use setupAutoRefresh"
    )
