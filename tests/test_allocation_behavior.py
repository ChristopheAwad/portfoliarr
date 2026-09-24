"""Run the donut's state and touch handlers in a small JavaScript engine.

These checks cover the transition logic that source-string assertions cannot
prove. No browser, live database, or Yahoo connection is needed.
"""

import json
from pathlib import Path

import pytest


MAIN = (Path(__file__).resolve().parents[1] / "static/js/main.js")


def _function(src, name):
    start = src.index(f"function {name}(")
    return src[start:src.index("\n}", start) + 2]


def _engine(*names, setup=""):
    MiniRacer = pytest.importorskip("py_mini_racer").MiniRacer
    js = MiniRacer()
    js.eval(setup)
    src = MAIN.read_text()
    for name in names:
        js.eval(_function(src, name))
    return js


@pytest.mark.parametrize("slices,excluded,expected", [
    ([], [], "empty"),
    ([], [{"ticker": "A", "reason": "no sector data"}], "excluded"),
    ([{"key": "Tech", "weight": 1}], [], "ready"),
    ([{"key": "Tech", "weight": 1}], [{"ticker": "B"}], "ready"),
])
def test_allocation_state_comes_from_current_reply(slices, excluded, expected):
    js = _engine("allocationResultState")
    assert js.eval(
        f"allocationResultState({json.dumps(slices)}, {json.dumps(excluded)})"
    ) == expected


def test_status_hides_canvas_without_slices_and_marks_failed_refresh():
    js = _engine("setAllocState", setup="""
        var allocStatusEl = {textContent: '', hidden: false};
        var donutBoxEl = {hidden: true};
        var allocationChart = null;
        function requestAnimationFrame(fn) { fn(); }
    """)
    js.eval('setAllocState("stale-error")')
    assert js.eval("donutBoxEl.hidden") is True
    assert "last" in js.eval("allocStatusEl.textContent").lower()
    js.eval("allocationChart = {resize: function () {}}")
    js.eval('setAllocState("stale-error")')
    assert js.eval("donutBoxEl.hidden") is False
    js.eval('setAllocState("excluded")')
    assert js.eval("donutBoxEl.hidden") is True
    assert "classif" in js.eval("allocStatusEl.textContent").lower() or (
        "pric" in js.eval("allocStatusEl.textContent").lower())
    js.eval('setAllocState("ready")')
    assert js.eval("allocStatusEl.hidden") is True


def test_excluded_note_updates_and_clears_on_portfolio_change():
    js = _engine("updateAllocExcluded", setup="""
        var allocExcludedEl = {textContent: '', style: {display: 'none'}};
    """)
    js.eval('updateAllocExcluded([{ticker:"AAA",reason:"no sector data"}])')
    assert "AAA" in js.eval("allocExcludedEl.textContent")
    assert "no sector data" in js.eval("allocExcludedEl.textContent")
    js.eval("updateAllocExcluded([])")
    assert js.eval("allocExcludedEl.textContent") == ""
    assert js.eval("allocExcludedEl.style.display") == "none"
    src = MAIN.read_text()
    switch = src.split('document.addEventListener("portfoliochange", () => {', 1)[1]
    assert "updateAllocExcluded([])" in switch
    assert 'setAllocState("loading")' in switch


def test_ticker_summary_handles_unpriced_and_failed_refresh():
    src = MAIN.read_text()
    summary = src.split("async function refreshPortfolioSummary()", 1)[1].split(
        "// PORTFOLIO CHART", 1)[0]
    assert "data.unpriced.map(" in summary
    assert "paintAllocation(tickerSlices" in summary
    assert "lastAllocPayload" in summary
    assert 'setAllocState("stale-error")' in summary
    assert 'setAllocState("unavailable")' in summary
    assert "if (epoch !== portfolioEpoch()) return;" in summary
    assert "paintAllocation([], [])" not in summary
    assert "lastSummaryFailed = true" in summary
    assert "lastSummaryFailed = false" in summary
    switch = src.split("function switchAllocView(newIndex)", 1)[1].split(
        "// Fetch one allocation dimension", 1)[0]
    assert 'if (lastSummaryFailed) setAllocState("stale-error")' in switch
    assert 'setAllocState(lastSummaryFailed ? "unavailable" : "loading")' in switch


def test_touch_cleanup_has_no_navigation_and_rearms_new_tap():
    src = MAIN.read_text()
    touch = src.split("// Touch cleanup on the donut box", 1)[1].split(
        "// The summary's holdings slice", 1)[0]
    assert "switchAllocView" not in touch
    assert "clientX" not in touch and "clientY" not in touch
    assert "_touchHoverDormant = false" in touch
    assert "_touchHoverDormant = true" in touch
    assert "_ghostEventsUntil" in touch
    assert "clearDonutTouchHover()" in touch

    MiniRacer = pytest.importorskip("py_mini_racer").MiniRacer
    js = MiniRacer()
    js.eval("""
        var GHOST_EVENT_WINDOW_MS = 500;
        var switches = 0, cleared = 0, drawn = 0;
        var donutBoxEl = {handlers: {}, addEventListener(name, fn) {
            this.handlers[name] = fn;
        }};
        var allocationChart = {
            tooltip: {setActiveElements() { cleared++; }},
            setActiveElements() { cleared++; },
            draw() { drawn++; }
        };
        function switchAllocView() { switches++; }
    """)
    js.eval("if (donutBoxEl) {" + touch.split("if (donutBoxEl) {", 1)[1])
    js.eval('donutBoxEl.handlers.touchstart({touches:[{clientX:200,clientY:50}]})')
    assert js.eval("allocationChart._touchHoverDormant") is False
    js.eval('donutBoxEl.handlers.touchend({touches:[],changedTouches:[{clientX:10,clientY:50}]})')
    assert js.eval("switches") == 0
    assert js.eval("cleared") == 2
    assert js.eval("drawn") == 1
    assert js.eval("allocationChart._touchHoverDormant") is True
    assert js.eval("allocationChart._ghostEventsUntil > Date.now()") is True
    js.eval('donutBoxEl.handlers.touchstart({touches:[{clientX:10,clientY:50}]})')
    assert js.eval("allocationChart._touchHoverDormant") is False
    js.eval('donutBoxEl.handlers.touchend({touches:[],changedTouches:[{clientX:10,clientY:170}]})')
    assert js.eval("switches") == 0
    js.eval('donutBoxEl.handlers.touchcancel({})')
    assert js.eval("allocationChart._touchHoverDormant") is True
    js.eval("allocationChart = null")
    js.eval('donutBoxEl.handlers.touchend({touches:[],changedTouches:[]})')
    js.eval('donutBoxEl.handlers.touchcancel({})')
    assert js.eval("switches") == 0
