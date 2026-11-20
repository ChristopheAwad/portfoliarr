"""Run the donut's state, coverage, and touch handlers in small JS engines.

These checks cover the transition logic that source-string assertions cannot
prove. No browser, live database, or Yahoo connection is needed.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "static/js/main.js"
NODE = shutil.which("node")


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


def _json(value):
    return json.dumps(value)


# ---------------------------------------------------------------------------
# State machine: classified value decides whether a pie may be drawn.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("slices,excluded,coverage,expected", [
    ([], [], None, "empty"),
    ([], [{"ticker": "A", "reason": "no sector data"}], None, "excluded"),
    ([{"key": "Tech", "weight": 1, "status": "classified"}], [], None,
     "ready"),
    ([{"key": "Tech", "weight": 1}], [{"ticker": "B"}], None, "ready"),
    # A positive priced base with no classified wedge: coverage must show,
    # but a pie would imply data that does not exist.
    ([{"key": "Unknown", "weight": 0.6, "status": "unknown"},
      {"key": "n/a", "weight": 0.4, "status": "not_applicable"}],
     [], {"priced_value": 100000, "classified_weight": 0.0,
          "unknown_weight": 0.6, "not_applicable_weight": 0.4},
     "no-classified"),
    # One real wedge is enough to draw the pie, synthetic wedges included.
    ([{"key": "US", "weight": 0.4, "status": "classified"},
      {"key": "Unknown", "weight": 0.6, "status": "unknown"}],
     [], {"priced_value": 100000, "classified_weight": 0.4,
          "unknown_weight": 0.6, "not_applicable_weight": 0.0},
     "ready"),
    # A backend without status/coverage still paints its ticker slices.
    ([{"key": "AAPL", "weight": 1}], [], None, "ready"),
])
def test_allocation_state_comes_from_current_reply(
        slices, excluded, coverage, expected):
    js = _engine("allocationResultState", "allocationClassifiedWeight",
                 "allocationSliceStatus")
    assert js.eval(
        f"allocationResultState({_json(slices)}, {_json(excluded)}, "
        f"{_json(coverage)})"
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
    js.eval('setAllocState("no-classified")')
    assert js.eval("donutBoxEl.hidden") is True
    assert "classif" in js.eval("allocStatusEl.textContent").lower()
    js.eval('setAllocState("ready")')
    assert js.eval("allocStatusEl.hidden") is True


# ---------------------------------------------------------------------------
# Coverage line: percentages only, never a new CAD amount.
# ---------------------------------------------------------------------------

def test_coverage_text_reports_percentages_without_cad():
    js = _engine("updateAllocCoverage", "allocationPercent", setup="""
        var allocCoverageEl = {
            textContent: '', title: '', style: {display: 'none'}
        };
    """)
    js.eval("""updateAllocCoverage({
        priced_value: 100000,
        classified_weight: 0.40,
        unknown_weight: 0.40,
        not_applicable_weight: 0.20
    })""")
    text = js.eval("allocCoverageEl.textContent")
    assert "40% classified" in text
    assert "40% unknown" in text
    assert "20% N/A" in text
    assert "priced long holdings" in text
    assert "CAD" not in text and "$" not in text and "100,000" not in text
    assert js.eval("allocCoverageEl.style.display") == "block"

    # Relevant categories only: 96% classified / 4% unknown hides N/A.
    js.eval("""updateAllocCoverage({
        priced_value: 100000,
        classified_weight: 0.96,
        unknown_weight: 0.04,
        not_applicable_weight: 0
    })""")
    text = js.eval("allocCoverageEl.textContent")
    assert "96% classified" in text
    assert "4% unknown" in text
    assert "N/A" not in text

    for empty in ("null", "{priced_value: 0, classified_weight: 0, "
                         "unknown_weight: 0, not_applicable_weight: 0}"):
        js.eval(f"updateAllocCoverage({empty})")
        assert js.eval("allocCoverageEl.textContent") == ""
        assert js.eval("allocCoverageEl.style.display") == "none"


# ---------------------------------------------------------------------------
# Synthetic wedge labels + per-row colors.
# ---------------------------------------------------------------------------

def test_wedge_colors_follow_status_and_theme():
    js = _engine("allocationSliceStatus", "allocationSliceLabel",
                 "allocationWedgeColors", "getSyntheticAllocationColors",
                 setup="""
        var theme = "light";
        var document = {documentElement: {}};
        function getAllocationColors() {
            return theme === "dark"
                ? ["#dark1", "#dark2", "#dark3"]
                : ["#real1", "#real2", "#real3"];
        }
        function getComputedStyle() {
            return {getPropertyValue: function (name) {
                if (name === "--alloc-unknown")
                    return theme === "dark" ? "#unknown-dark" : "#unknown-light";
                if (name === "--alloc-na")
                    return theme === "dark" ? "#na-dark" : "#na-light";
                return "";
            }};
        }
        var slices = [
            {key: "US", weight: 0.4, status: "classified"},
            {key: "Unknown", weight: 0.3, status: "unknown"},
            {key: "CA", weight: 0.2, status: "classified"},
            {key: "n/a", weight: 0.1, status: "not_applicable"}
        ];
    """)
    assert js.eval('allocationSliceLabel({key: "n/a"})') == "Not applicable"
    assert js.eval('allocationSliceLabel({key: "Unknown"})') == "Unknown"
    assert json.loads(js.eval(
        "JSON.stringify(allocationWedgeColors(slices))"
    )) == ["#real1", "#unknown-light", "#real2", "#na-light"]

    js.eval('theme = "dark"')
    assert json.loads(js.eval(
        "JSON.stringify(allocationWedgeColors(slices))"
    )) == ["#dark1", "#unknown-dark", "#dark2", "#na-dark"]


def test_paint_no_pie_for_unknown_only_but_keeps_coverage_and_reasons():
    js = _engine(
        "setAllocState", "paintAllocation", "allocationResultState",
        "allocationClassifiedWeight", "allocationSliceStatus",
        "allocationSliceLabel", "allocationWedgeColors",
        "getSyntheticAllocationColors", "allocationPercent",
        "allocationLegendLabelColor", "updateAllocCoverage",
        "appendAllocationNoteEntry", "appendAllocationMoreDetails",
        "updateAllocExcluded", "updateAllocUnclassified",
        "donutBorderColor", setup="""
        var allocCoverageEl = {textContent: '', title: '', style: {display: 'none'}};
        var allocExcludedEl = {
            children: [], textContent: '', title: '', style: {display: 'none'},
            replaceChildren: function () { this.children = []; this.textContent = ''; },
            append: function (n) {
                this.children.push(n);
                this.textContent += (n.textContent || '');
            }
        };
        var allocUnclassifiedEl = {
            children: [], textContent: '', style: {display: 'none'},
            replaceChildren: function () { this.children = []; this.textContent = ''; },
            append: function (n) {
                this.children.push(n);
                this.textContent += (n.textContent || '');
            }
        };
        var allocStatusEl = {textContent: '', hidden: false};
        var donutBoxEl = {hidden: true};
        var allocationCanvas = {};
        var allocationChart = null;
        var currentHoldings = [];
        var lastAllocPayload = null;
        var MANUAL_CLASSIFICATION_DIMS =
            new Set(['country', 'sector', 'asset_class']);
        var MAX_ALLOC_NOTE_ITEMS = 3;
        var REDUCED_MOTION = false;
        var chartBuilds = 0;
        var chartUpdates = 0;
        var document = {
            createTextNode: function (t) {
                return {kind: 'text', textContent: t, title: ''};
            },
            createElement: function (tag) {
                return {kind: tag, href: '', textContent: '', title: '',
                        className: ''};
            }
        };
        function getComputedStyle() {
            return {getPropertyValue: function (name) {
                if (name === '--alloc-unknown') return '#aaaaaa';
                if (name === '--alloc-na') return '#bbbbbb';
                if (name === '--card-bg') return '#ffffff';
                if (name === '--text-primary') return '#171a20';
                if (name === '--text-secondary') return '#5c6370';
                return '';
            }};
        }
        function getAllocationColors() { return ['#real1', '#real2', '#real3']; }
        function requestAnimationFrame(fn) { fn(); }
        function runAllocationCrossfade() {}
        function Chart(canvas, config) {
            chartBuilds += 1;
            this.config = config;
            this.data = config.data;
            this.options = config.options;
            this.destroyed = false;
            this.resize = function () {};
            this.update = function () { chartUpdates += 1; };
            this.destroy = function () { this.destroyed = true; };
            allocationChart = this;
        }
    """)

    js.eval("""
        var mixed = [
            {key: 'US', value: 40000, weight: 0.4, status: 'classified'},
            {key: 'Unknown', value: 40000, weight: 0.4, status: 'unknown'},
            {key: 'n/a', value: 20000, weight: 0.2, status: 'not_applicable'}
        ];
        paintAllocation(mixed, [], 'country',
            [{ticker: 'BTC-USD', reason: 'no country data'}],
            {priced_value: 100000, classified_weight: 0.4,
             unknown_weight: 0.4, not_applicable_weight: 0.2});
    """)
    assert json.loads(js.eval(
        "JSON.stringify(allocationChart.data.labels)"
    )) == ["US", "Unknown", "Not applicable"]
    assert json.loads(js.eval(
        "JSON.stringify(allocationChart.data.datasets[0].backgroundColor)"
    )) == ["#real1", "#aaaaaa", "#bbbbbb"]
    assert js.eval(
        "allocationChart.options.plugins.legend.labels.color"
    ) == "#171a20"
    assert "40% classified" in js.eval("allocCoverageEl.textContent")

    # Refresh swaps per-row colors instead of keeping the first build's flat
    # palette order.
    js.eval("""
        var reordered = [
            {key: 'Unknown', value: 40000, weight: 0.4, status: 'unknown'},
            {key: 'CA', value: 40000, weight: 0.4, status: 'classified'},
            {key: 'n/a', value: 20000, weight: 0.2, status: 'not_applicable'}
        ];
        paintAllocation(reordered, [], 'country', [],
            {priced_value: 100000, classified_weight: 0.4,
             unknown_weight: 0.4, not_applicable_weight: 0.2});
    """)
    assert json.loads(js.eval(
        "JSON.stringify(allocationChart.data.datasets[0].backgroundColor)"
    )) == ["#aaaaaa", "#real1", "#bbbbbb"]
    assert js.eval("chartUpdates") >= 1

    # Only Unknown/N/A on a priced base: destroy the pie, keep the coverage
    # text and the unclassified reasons.
    js.eval("""
        paintAllocation([
            {key: 'Unknown', value: 60000, weight: 0.6, status: 'unknown'},
            {key: 'n/a', value: 40000, weight: 0.4, status: 'not_applicable'}
        ], [], 'country', [
            {ticker: 'ETH-USD', reason: 'no country data'},
            {ticker: 'BTC-USD', reason: 'country not applicable'}
        ], {priced_value: 100000, classified_weight: 0,
            unknown_weight: 0.6, not_applicable_weight: 0.4});
    """)
    assert js.eval("allocationChart") is None
    assert js.eval("donutBoxEl.hidden") is True
    assert "0% classified" in js.eval("allocCoverageEl.textContent")
    assert "ETH-USD" in js.eval("allocUnclassifiedEl.textContent")
    assert "no country data" in js.eval("allocUnclassifiedEl.textContent")
    assert "classif" in js.eval("allocStatusEl.textContent").lower()

    # No usable price: no pie, no weights, but ticker + reason listed.
    js.eval("""
        paintAllocation([], [{ticker: 'SOL', reason: "couldn't be priced"}],
            'country', [], null);
    """)
    assert js.eval("allocationChart") is None
    assert js.eval("donutBoxEl.hidden") is True
    assert "SOL" in js.eval("allocExcludedEl.textContent")
    assert "couldn't be priced" in js.eval("allocExcludedEl.textContent")
    assert js.eval("allocCoverageEl.style.display") == "none"


# ---------------------------------------------------------------------------
# Notes: manual links only where they help, long lists collapse.
# ---------------------------------------------------------------------------

def test_excluded_note_updates_clears_and_expands_long_lists():
    js = _engine("updateAllocExcluded", "appendAllocationExcludedDetails", setup="""
        function makeNoteNode(kind) {
            return {
                kind: kind, href: '', textContent: '', title: '',
                className: '', children: [],
                replaceChildren: function () {
                    this.children = [];
                    this.textContent = '';
                },
                append: function (n) {
                    this.children.push(n);
                    this.textContent += (n.textContent || '');
                }
            };
        }
        var allocExcludedEl = makeNoteNode('p');
        allocExcludedEl.style = {display: 'none'};
        var document = {
            createTextNode: function (t) {
                return {kind: 'text', textContent: t, title: '',
                        className: '', children: []};
            },
            createElement: makeNoteNode
        };
        var MAX_ALLOC_NOTE_ITEMS = 3;
    """)
    js.eval('updateAllocExcluded([{ticker:"AAA",reason:"no sector data"}])')
    assert "AAA" in js.eval("allocExcludedEl.textContent")
    assert "no sector data" in js.eval("allocExcludedEl.textContent")
    assert js.eval("allocExcludedEl.style.display") == "block"
    js.eval("updateAllocExcluded([])")
    assert js.eval("allocExcludedEl.textContent") == ""
    assert js.eval("allocExcludedEl.style.display") == "none"

    # The hidden tail is reachable on touch: native <details> content holds
    # the complete ticker/reason list, not a title-only tooltip.
    js.eval("""updateAllocExcluded([
        {ticker:'A',reason:'no quote'},
        {ticker:'B',reason:'no quote'},
        {ticker:'C',reason:'no quote'},
        {ticker:'D',reason:'no quote'},
        {ticker:'E',reason:'unsupported currency'}
    ])""")
    assert "+2 more" in js.eval("allocExcludedEl.textContent")
    details = ("allocExcludedEl.children.filter(function (n) { "
               "return n.className === 'alloc-note-details'; })[0]")
    assert js.eval(details + ".kind") == "details"
    details_text = js.eval(details + ".textContent")
    assert "+2 more" in details_text
    assert "D" in details_text and "E" in details_text
    assert "unsupported currency" in details_text

    src = MAIN.read_text()
    switch = src.split('document.addEventListener("portfoliochange", () => {', 1)[1]
    assert "updateAllocExcluded([])" in switch
    assert "updateAllocUnclassified([])" in switch
    assert "updateAllocCoverage(null)" in switch
    assert 'setAllocState(hasPortfolio ? "loading" : "unavailable")' in switch


def test_unclassified_note_links_only_for_manual_dimensions():
    setup = """
        function makeNoteNode(kind) {
            return {
                kind: kind, href: '', textContent: '', title: '',
                className: '', children: [],
                replaceChildren: function () {
                    this.children = [];
                    this.textContent = '';
                },
                append: function (n) {
                    this.children.push(n);
                    this.textContent += (n.textContent || '');
                }
            };
        }
        var allocUnclassifiedEl = makeNoteNode('p');
        allocUnclassifiedEl.style = {display: 'none'};
        var document = {
            createTextNode: function (t) {
                return {kind: 'text', textContent: t, title: '',
                        className: '', children: []};
            },
            createElement: makeNoteNode
        };
        var MANUAL_CLASSIFICATION_DIMS =
            new Set(['country', 'sector', 'asset_class']);
        var MAX_ALLOC_NOTE_ITEMS = 3;
    """
    js = _engine("updateAllocUnclassified", "appendAllocationNoteEntry",
                 "appendAllocationMoreDetails", setup=setup)
    js.eval('updateAllocUnclassified([{ticker:"VEQT.TO",reason:"no country data"}], "country")')
    assert js.eval("allocUnclassifiedEl.style.display") == "block"
    assert js.eval("allocUnclassifiedEl.children.some(function (n) { return n.kind === 'a'; })") is True
    assert "VEQT.TO" in js.eval("allocUnclassifiedEl.textContent")
    assert "no country data" in js.eval("allocUnclassifiedEl.textContent")
    assert "open the stock page" in js.eval(
        "allocUnclassifiedEl.children.filter(function (n) { return n.kind === 'a'; })[0].title"
    )

    js.eval('updateAllocUnclassified([{ticker:"NOCAP",reason:"no market-cap data"}], "cap")')
    assert js.eval("allocUnclassifiedEl.children.some(function (n) { return n.kind === 'a'; })") is False
    assert "NOCAP" in js.eval("allocUnclassifiedEl.textContent")
    assert "no market-cap data" in js.eval("allocUnclassifiedEl.textContent")

    # Many positions collapse to native details. Both links and reasons are
    # inside the expandable body, so touch users can read the hidden tail.
    js.eval("""updateAllocUnclassified([
        {ticker:'A',reason:'no country data'},
        {ticker:'B',reason:'no country data'},
        {ticker:'C',reason:'no country data'},
        {ticker:'D',reason:'no country data'},
        {ticker:'E',reason:'country not applicable'}
    ], 'country')""")
    details = ("allocUnclassifiedEl.children.filter(function (n) { "
               "return n.className === 'alloc-note-details'; })[0]")
    assert js.eval(details + ".kind") == "details"
    details_text = js.eval(details + ".textContent")
    assert "+2 more" in details_text
    assert "D" in details_text and "E" in details_text
    assert "country not applicable" in details_text
    assert js.eval(
        details + ".children.some(function (n) { return n.kind === 'a'; })"
    ) is True
    js.eval("updateAllocUnclassified([], 'country')")
    assert js.eval("allocUnclassifiedEl.style.display") == "none"
    assert js.eval("allocUnclassifiedEl.children.length") == 0


def test_unclassified_heading_is_neutral_when_not_applicable_is_included():
    """A reason saying "not applicable" is a coverage gap, not a failed
    classification; use the neutral heading for that note."""
    setup = """
        function makeNoteNode(kind) {
            return {
                kind: kind, href: '', textContent: '', title: '',
                className: '', children: [],
                replaceChildren: function () {
                    this.children = [];
                    this.textContent = '';
                },
                append: function (n) {
                    this.children.push(n);
                    this.textContent += (n.textContent || '');
                }
            };
        }
        var allocUnclassifiedEl = makeNoteNode('p');
        allocUnclassifiedEl.style = {display: 'none'};
        var document = {
            createTextNode: function (t) {
                return {kind: 'text', textContent: t, title: '',
                        className: '', children: []};
            },
            createElement: makeNoteNode
        };
        var MANUAL_CLASSIFICATION_DIMS =
            new Set(['country', 'sector', 'asset_class']);
        var MAX_ALLOC_NOTE_ITEMS = 3;
    """
    js = _engine("updateAllocUnclassified", "appendAllocationNoteEntry",
                 "appendAllocationMoreDetails", setup=setup)
    js.eval('updateAllocUnclassified([{ticker:"BTC-USD",reason:"country not applicable"}], "country")')
    text = js.eval("allocUnclassifiedEl.textContent")
    assert text.startswith("Coverage details: ")
    assert "Not classified:" not in text

    js.eval('updateAllocUnclassified([{ticker:"ETH-USD",reason:"no country data"}], "country")')
    text = js.eval("allocUnclassifiedEl.textContent")
    assert text.startswith("Not classified: ")
    assert "Coverage details:" not in text


def test_legend_color_tracks_theme_and_refresh_is_static():
    js = _engine(
        "allocationLegendLabelColor", "refreshAllocationThemeColors",
        "allocationWedgeColors", "allocationSliceStatus",
        "getSyntheticAllocationColors", "donutBorderColor", setup="""
        var theme = "light";
        var document = {documentElement: {classList: {contains: function () {
            return theme === "dark";
        }}}};
        var updates = [];
        var currentHoldings = [
            {key: "US", weight: 1, status: "classified"}
        ];
        var allocationChart = {
            data: {datasets: [{}]},
            options: {plugins: {legend: {labels: {color: ""}}}},
            update: function (mode) { updates.push(mode); }
        };
        function getAllocationColors() {
            return theme === "dark" ? ["#dark-real"] : ["#light-real"];
        }
        function getComputedStyle() {
            return {getPropertyValue: function (name) {
                if (name === "--text-primary")
                    return theme === "dark" ? "#e7e8ea" : "#171a20";
                if (name === "--text-secondary")
                    return theme === "dark" ? "#9aa1ad" : "#5c6370";
                if (name === "--alloc-unknown")
                    return theme === "dark" ? "#unknown-dark" : "#unknown-light";
                if (name === "--alloc-na")
                    return theme === "dark" ? "#na-dark" : "#na-light";
                if (name === "--card-bg")
                    return theme === "dark" ? "#181c24" : "#ffffff";
                return "";
            }};
        }
    """)
    assert js.eval("allocationLegendLabelColor()") == "#171a20"
    js.eval("theme = 'dark'")
    assert js.eval("allocationLegendLabelColor()") == "#e7e8ea"
    js.eval("refreshAllocationThemeColors()")
    assert js.eval("allocationChart.options.plugins.legend.labels.color") == "#e7e8ea"
    assert js.eval("allocationChart.data.datasets[0].backgroundColor[0]") == "#dark-real"
    assert js.eval("updates.length") == 1
    assert js.eval("updates[0]") == "none"


# ---------------------------------------------------------------------------
# Summary integration and mocked API races.
# ---------------------------------------------------------------------------

def test_ticker_summary_handles_coverage_unpriced_and_failed_refresh():
    src = MAIN.read_text()
    summary = src.split("async function refreshPortfolioSummary()", 1)[1].split(
        "// PORTFOLIO CHART", 1)[0]
    assert "data.allocation_excluded" in summary
    assert "data.allocation_coverage" in summary
    assert "lastSummaryCoverage" in summary
    assert "data.unpriced.map(" in summary
    assert "paintAllocation(tickerSlices, tickerExcluded, null, []," in summary
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
    assert "lastSummaryCoverage" in switch


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


FETCH_HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1] + '/static/js/main.js', 'utf8');
function fn(name) {
    const start = source.indexOf('function ' + name + '(');
    assert(start >= 0, 'missing function ' + name);
    return source.slice(start, source.indexOf('\n}', start) + 2);
}
const sandbox = {
    console,
    ALLOCATION_VIEWS: [{key: null}, {key: 'country'}, {key: 'sector'}],
    allocViewIndex: 1,
    allocCache: {},
    allocInFlight: {},
    ALLOC_CACHE_TTL: 0,
    lastAllocPayload: null,
    epoch: 1,
    paints: [],
    states: [],
    coveragePaints: [],
    currentPortfolioId: () => 1,
    portfolioEpoch: () => sandbox.epoch,
    portfolioQuery: () => '?portfolio_id=1',
    isActiveAllocView: (by) =>
        sandbox.ALLOCATION_VIEWS[sandbox.allocViewIndex].key === by,
    paintAllocation: (...args) => {
        sandbox.paints.push(args);
        sandbox.lastAllocPayload = {
            by: args[2] ?? null, slices: args[0], excluded: args[1],
            unclassified: args[3] || [], coverage: args[4] || null
        };
    },
    updateAllocExcluded: () => {},
    updateAllocUnclassified: () => {},
    updateAllocCoverage: (coverage) => sandbox.coveragePaints.push(coverage),
    setAllocState: (state) => sandbox.states.push(state),
    allocCacheStale: (key) => !sandbox.allocCache[key] ||
        (Date.now() - sandbox.allocCache[key].fetchedAt) > sandbox.ALLOC_CACHE_TTL,
    fetch: null,
    nextResponse: null,
    fetchedUrls: []
};
vm.createContext(sandbox);
for (const name of ['fetchAllocDimension', 'allocationResultState',
                    'allocationClassifiedWeight', 'allocationSliceStatus']) {
    vm.runInContext(fn(name), sandbox);
}
sandbox.fetch = async (url) => {
    sandbox.fetchedUrls.push(url);
    return sandbox.nextResponse;
};
(async () => {
"""


def _run_node(body):
    if not NODE:
        pytest.skip("Node is required for mocked allocation API tests")
    script = FETCH_HARNESS + body + r"""
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(
        [NODE, "-e", script, str(ROOT)], capture_output=True, text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_mocked_api_paints_coverage_and_statuses():
    _run_node(r"""
        sandbox.nextResponse = {ok: true, json: async () => ({
            slices: [
                {key: 'US', value: 40000, weight: 0.4, status: 'classified'},
                {key: 'Unknown', value: 40000, weight: 0.4, status: 'unknown'},
                {key: 'n/a', value: 20000, weight: 0.2, status: 'not_applicable'}
            ],
            excluded: [],
            unclassified: [{ticker: 'VEQT.TO', reason: 'no country data'}],
            coverage: {priced_value: 100000, classified_weight: 0.4,
                       unknown_weight: 0.4, not_applicable_weight: 0.2}
        })};
        await sandbox.fetchAllocDimension('country');
        assert.equal(sandbox.paints.length, 1);
        const [slices, excluded, by, unclassified, coverage] = sandbox.paints[0];
        assert.equal(by, 'country');
        assert.equal(slices[2].status, 'not_applicable');
        assert.equal(unclassified[0].ticker, 'VEQT.TO');
        assert.equal(coverage.classified_weight, 0.4);
        assert.equal(sandbox.states.includes('loading'), true);
        assert.equal(sandbox.allocationResultState(slices, excluded, coverage),
                     'ready');
        assert.equal(sandbox.allocCache['1|country'].data.coverage
            .not_applicable_weight, 0.2);
    """)


def test_mocked_api_no_classified_payload_keeps_reason():
    _run_node(r"""
        sandbox.nextResponse = {ok: true, json: async () => ({
            slices: [
                {key: 'Unknown', value: 60000, weight: 0.6, status: 'unknown'},
                {key: 'n/a', value: 40000, weight: 0.4, status: 'not_applicable'}
            ],
            excluded: [],
            unclassified: [
                {ticker: 'ETH-USD', reason: 'no country data'},
                {ticker: 'BTC-USD', reason: 'country not applicable'}
            ],
            coverage: {priced_value: 100000, classified_weight: 0,
                       unknown_weight: 0.6, not_applicable_weight: 0.4}
        })};
        await sandbox.fetchAllocDimension('country');
        const [slices, , , unclassified, coverage] = sandbox.paints[0];
        assert.equal(sandbox.allocationResultState(slices, [], coverage),
                     'no-classified');
        assert.equal(unclassified.length, 2);
        assert.equal(coverage.priced_value, 100000);
    """)


def test_mocked_api_unpriced_payload_lists_excluded_without_weights():
    _run_node(r"""
        sandbox.allocViewIndex = 2;
        sandbox.nextResponse = {ok: true, json: async () => ({
            slices: [], excluded: [{ticker: 'SOL', reason: "couldn't be priced"}],
            unclassified: [], coverage: null
        })};
        await sandbox.fetchAllocDimension('sector');
        const [slices, excluded, , , coverage] = sandbox.paints[0];
        assert.deepEqual(slices, []);
        assert.equal(excluded[0].ticker, 'SOL');
        assert.equal('weight' in excluded[0], false);
        assert.equal(coverage, null);
        assert.equal(sandbox.allocationResultState(slices, excluded, coverage),
                     'excluded');
    """)


def test_mocked_api_view_race_caches_but_never_paints_stale_reply():
    _run_node(r"""
        let release;
        sandbox.fetch = async (url) => {
            sandbox.fetchedUrls.push(url);
            return new Promise(resolve => { release = resolve; });
        };
        const flight = sandbox.fetchAllocDimension('country');
        sandbox.allocViewIndex = 2;  // user moved to sector before reply
        release({ok: true, json: async () => ({
            slices: [{key: 'US', value: 100, weight: 1, status: 'classified'}],
            excluded: [], unclassified: [],
            coverage: {priced_value: 100, classified_weight: 1,
                       unknown_weight: 0, not_applicable_weight: 0}
        })});
        await flight;
        assert.equal(sandbox.paints.length, 0);
        assert.equal(sandbox.allocCache['1|country'].data.slices[0].key, 'US');

        // A flip back paints that cached payload immediately, with coverage.
        sandbox.ALLOC_CACHE_TTL = 10 * 60 * 1000;
        sandbox.allocViewIndex = 1;
        await sandbox.fetchAllocDimension('country');
        assert.equal(sandbox.paints.length, 1);
        assert.equal(sandbox.paints[0][4].classified_weight, 1);
        assert.equal(sandbox.fetchedUrls.length, 1);
    """)


def test_mocked_api_portfolio_race_cannot_paint_old_scope():
    _run_node(r"""
        let release;
        sandbox.fetch = async (url) => {
            sandbox.fetchedUrls.push(url);
            return new Promise(resolve => { release = resolve; });
        };
        const flight = sandbox.fetchAllocDimension('country');
        sandbox.epoch = 2;  // portfolio changed mid-flight
        release({ok: true, json: async () => ({
            slices: [{key: 'US', value: 100, weight: 1, status: 'classified'}],
            excluded: [], unclassified: [],
            coverage: {priced_value: 100, classified_weight: 1,
                       unknown_weight: 0, not_applicable_weight: 0}
        })});
        await flight;
        assert.equal(sandbox.paints.length, 0);
    """)


def test_mocked_api_failure_keeps_last_same_dimension_cache():
    _run_node(r"""
        sandbox.lastAllocPayload = {
            by: 'country',
            slices: [{key: 'US', value: 100, weight: 1, status: 'classified'}],
            excluded: [], unclassified: [],
            coverage: {priced_value: 100, classified_weight: 1,
                       unknown_weight: 0, not_applicable_weight: 0}
        };
        sandbox.fetch = async () => { throw new Error('offline'); };
        await sandbox.fetchAllocDimension('country');
        assert.equal(sandbox.states[sandbox.states.length - 1], 'ready');
        assert.equal(sandbox.states.includes('unavailable'), false);
        assert.equal(sandbox.lastAllocPayload.by, 'country');
        assert.equal(sandbox.lastAllocPayload.coverage.classified_weight, 1);
    """)


def test_coverage_and_tooltip_keep_privacy():
    src = MAIN.read_text()
    coverage = src.split("function updateAllocCoverage(coverage)", 1)[1].split(
        "\n}", 1)[0]
    assert "formatNumber" not in coverage and "CAD" not in coverage
    tooltip = src.split("tooltip: {", 1)[1].split("},\n                },", 1)[0]
    assert "portfolioMasked()" in tooltip
    assert '"****"' in tooltip
    assert "item.label" in tooltip
