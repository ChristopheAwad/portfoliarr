"""Behavior contracts for a degraded chart reply.

Server contract: ``/api/portfolio/history`` keeps healthy payloads
unchanged, but may add ``valuation_status: "partial" | "unavailable"``
when some or none of the held positions can be priced.  A degraded reply
is a 200, so it must never be cached or painted as if it were complete.

The Node harness below runs the real shared chart factory with a fake
network and animation-frame queue.  It deliberately keeps its own copy of
the patterns used by other chart tests so no other PR's fixture is shared.
"""

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def run_node(harness, case):
    if not NODE:
        pytest.skip("Node is required for chart behavior tests")
    if "})().catch(" in case:
        case = ("const testDeadline = setTimeout(() => { "
                "console.error('degraded chart test did not complete'); "
                "process.exitCode = 1; }, 3000);\n" +
                case.replace("})().catch(",
                             "})().finally(() => clearTimeout(testDeadline)).catch("))
    result = subprocess.run(
        [NODE, "-e", harness + "\n" + case, str(ROOT)],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


CHART_HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1] + '/static/js/common.js', 'utf8');
const start = source.indexOf('function historyRequestUrl(');
const end = source.indexOf('// PROFILE DROPDOWN', start);
assert(start >= 0 && end > start);

const marks = [], frames = [], requests = [], summaries = [], completions = [];
let scope = 1, benchmarks = [], now = 0;
Date.now = () => now;
globalThis.perfMark = name => marks.push(name);
globalThis.requestAnimationFrame = callback => frames.push(callback);
globalThis.fetch = url => new Promise((resolve, reject) => requests.push({url, resolve, reject}));
globalThis.window = {handlers:{}, addEventListener(name, fn) {
    (this.handlers[name] ||= []).push(fn);
}, dispatch(name) {for (const fn of this.handlers[name] || []) fn();}};
globalThis.document = {documentElement: {}, hidden: false, addEventListener() {},
    createElement() { return element(); }};
globalThis.localStorage = {getItem() {return null;}, setItem() {}};
globalThis.getComputedStyle = () => ({getPropertyValue: () => '#123456'});
globalThis.hexToRgba = () => 'rgba(1,2,3,.75)';
globalThis.tickTargetForWidth = () => 6;
globalThis.buildXTickLabels = labels => labels;
globalThis.crosshairPlugin = {};
globalThis.oppositePositioner = () => ({});
globalThis.CHART_COLORS = {up: {line: 'green'}, down: {line: 'red'}};
globalThis.getCompareColors = () => ['blue', 'purple', 'orange'];
globalThis.GHOST_EVENT_WINDOW_MS = 500;

function classes() {
    const set = new Set();
    return {toggle(name, on) { on ? set.add(name) : set.delete(name); },
            add(name) {set.add(name);}, remove(name) {set.delete(name);},
            contains(name) {return set.has(name);}};
}
function element() {
    let text = '';
    return {children: [], hidden: false, style: {}, classList: classes(),
        handlers: {},
        get textContent() {return text;},
        set textContent(value) {text = value; this.children = [];},
        addEventListener(name, fn) {this.handlers[name] = fn;},
        click() {this.handlers.click?.({target: this});},
        append(...nodes) {this.children.push(...nodes);},
        replaceChildren(...nodes) {this.children = nodes;}};
}
function statusNode() {
    const node = element();
    node.hidden = true;
    return node;
}
function button(text, mode) {
    return {textContent: text, dataset: mode ? {chartMode: mode} : {},
            classList: classes(), closest() {return this;}};
}
const buttons = ['1D', '5D', '1M', '3M', '6M', 'YTD', '1Y', '5Y', 'MAX'].map(x => button(x));
buttons[1].classList.add('active');
const buttonBar = {handlers: {}, querySelectorAll() {return buttons;},
    addEventListener(name, fn) {this.handlers[name] = fn;}};
const modes = [button('Value', 'value'), button('Performance', 'performance')];
const modeBar = {handlers: {}, querySelectorAll() {return modes;},
    addEventListener(name, fn) {this.handlers[name] = fn;}};
const canvas = {parentElement: {clientWidth: 600}, getContext() {return {};},
    addEventListener() {}, getBoundingClientRect() {return {left: 0, top: 0};}};
const comparisonReadout = element();
const chartStatus = statusNode();
const chartRetry = statusNode();
class FakeChart {
    static Tooltip = {positioners: {}};
    constructor(ctx, config) {
        this.data = config.data; this.options = config.options; this.plugins = config.plugins;
        this.updates = []; this.resizes = 0; this.tooltip = {setActiveElements() {}};
        this.scales = {x: {}, y: {}};
        this.width = 600; this.height = 300;
        this.chartArea = {left:0, right:600, top:0, bottom:300};
    }
    resize() {
        this.resizes++; this.width = canvas.parentElement.clientWidth;
        this.chartArea.right = this.width;
    }
    update(mode) {
        const scale = {id: 'y', min: 100, max: 200};
        this.plugins.find(p => p.id === 'prevCloseLine').afterDataLimits(this, {scale});
        this.updates.push({mode: mode ?? 'default', min: scale.min,
            values: [...this.data.datasets[0].data]});
    }
    draw() {}
    setActiveElements() {}
}
globalThis.Chart = FakeChart;
vm.runInThisContext(source.slice(start, end));
const handle = setupTimeframeChart({canvas, buttonBar, modeBar, datasetLabel: 'Value',
    endpoint: () => `/history?scope=${scope}`, defaultPeriod: '5D',
    getScope: () => scope, getBenchmarks: () => benchmarks, comparisonReadout,
    chartStatus, chartRetry,
    onPeriodSummary: value => summaries.push(value),
    onPaintComplete: value => {
        completions.push(value);
        if (globalThis.completeHook) globalThis.completeHook(value);
    }});
const data = (a, b, extra = {}) => ({labels: ['2026-01-01', '2026-01-02'],
    values: [a, b], index_values: [100, 105], costs: [a, a], twrr_pct: 5,
    ...extra});
const degraded = (a, b, valuationStatus = 'unavailable') =>
    data(a, b, {valuation_status: valuationStatus});
async function flush() {for (let i = 0; i < 12; i++) await Promise.resolve();}
async function frame() {const pending = frames.splice(0); pending.forEach(fn => fn()); await flush();}
async function succeed(index, value) {
    requests[index].resolve({ok: true, json: async () => value}); await flush();
}
async function fail(index) {requests[index].resolve({ok: false, status: 503}); await flush();}
function selected() {return buttons.find(b => b.classList.contains('active'))?.textContent;}
function statusText() {return chartStatus.hidden ? null : chartStatus.textContent;}
function retryVisible() {return chartRetry.hidden === false;}
async function initial(value = data(100, 110)) {
    handle.refresh('5D'); await succeed(0, value); await frame(); await frame();
}
"""


def test_dashboard_ships_an_accessible_chart_status_and_retry(client):
    html = client.get("/").get_data(as_text=True)
    status_at = html.index('id="portfolio-chart-status"')
    tag = html[html.rindex("<", 0, status_at):html.index(">", status_at) + 1]
    assert 'role="status"' in tag
    assert 'aria-live="polite"' in tag
    assert 'id="portfolio-chart-retry"' in html
    assert html.index('id="period-return"') < status_at


def test_stock_and_ledger_pages_do_not_ship_the_status(client):
    for path in ("/stock/AAPL", "/ledger"):
        html = client.get(path).get_data(as_text=True)
        assert 'id="portfolio-chart-status"' not in html
        assert 'id="portfolio-chart-retry"' not in html


def test_dashboard_wires_the_status_elements_into_the_factory():
    main = (ROOT / "static/js/main.js").read_text()
    setup = main.index("setupTimeframeChart({", main.index("const portfolioChartHandle"))
    span = main[setup:main.index("});", setup)]
    assert ('chartStatus: document.getElementById("portfolio-chart-status")'
            in span)
    assert ('chartRetry: document.getElementById("portfolio-chart-retry")'
            in span)


def test_partial_reply_keeps_previous_chart_and_names_both_timeframes():
    run_node(CHART_HARNESS, r"""
    (async () => {
        await initial();
        handle.refresh('1D');
        await succeed(1, degraded(150, 160, 'partial'));
        await flush(); await frame();
        assert.deepEqual(handle.chart.data.datasets[0].data, [100, 110]);
        assert.equal(selected(), '5D');
        assert.equal(statusText(), 'Showing 5D data — 1D unavailable.');
        assert.equal(retryVisible(), true);
        assert.equal(summaries.at(-1).period, '5D');
    })().catch(e => {console.error(e); process.exitCode = 1;});
    """)


def test_partial_reply_then_retry_recovers_to_requested_period():
    run_node(CHART_HARNESS, r"""
    (async () => {
        await initial();
        handle.refresh('1D');
        await succeed(1, degraded(150, 160, 'partial'));
        await flush(); await frame();
        chartRetry.click();
        assert.equal(requests.length, 3, 'retry must issue a new request');
        await succeed(2, data(150, 160)); await frame(); await frame();
        assert.deepEqual(handle.chart.data.datasets[0].data, [150, 160]);
        assert.equal(selected(), '1D');
        assert.equal(statusText(), null);
        assert.equal(retryVisible(), false);
    })().catch(e => {console.error(e); process.exitCode = 1;});
    """)


def test_unavailable_reply_with_no_prior_chart_reports_return_unavailable():
    run_node(CHART_HARNESS, r"""
    (async () => {
        handle.refresh('5D');
        await succeed(0, degraded(150, 160, 'unavailable'));
        await flush(); await frame();
        assert.deepEqual(handle.chart.data.datasets[0].data, []);
        assert.deepEqual(summaries.at(-1), {period: '5D', returnPct: null});
        assert.equal(statusText(), '5D unavailable.');
        assert.equal(retryVisible(), true);
        modes[1].classList.add('active');
        handle.refresh('5D'); // cached? degraded must not be cached
        assert.equal(requests.length, 2, 'degraded reply must not be cached');
    })().catch(e => {console.error(e); process.exitCode = 1;});
    """)


def test_degraded_reply_is_never_written_to_the_cache():
    run_node(CHART_HARNESS, r"""
    (async () => {
        handle.refresh('5D');
        await succeed(0, degraded(150, 160, 'unavailable'));
        await flush(); await frame();
        const count = requests.length;
        handle.refresh('5D');
        await flush();
        assert.equal(requests.length, count + 1,
            'a degraded reply must not be served from the cache');
    })().catch(e => {console.error(e); process.exitCode = 1;});
    """)


def test_retry_bypasses_a_cached_entry():
    run_node(CHART_HARNESS, r"""
    (async () => {
        handle.refresh('1D');
        await succeed(0, data(150, 160)); await frame(); await frame();
        now = 200000; // past the 1D cache TTL
        handle.refresh('1D');
        await succeed(1, degraded(150, 160, 'unavailable'));
        await flush(); await frame();
        assert.equal(retryVisible(), true);

        // If the degraded request had kept or rewritten the old entry, going
        // back inside its TTL would make retry paint without a fetch.
        now = 1000;
        const count = requests.length;
        chartRetry.click();
        await flush();
        assert.equal(requests.length, count + 1,
            'retry must delete or bypass the cached entry');
        await succeed(2, data(170, 180)); await frame(); await frame();
        assert.equal(statusText(), null);
    })().catch(e => {console.error(e); process.exitCode = 1;});
    """)


def test_late_degraded_reply_after_newer_success_is_ignored():
    run_node(CHART_HARNESS, r"""
    (async () => {
        handle.refresh('1D');
        handle.refresh('5D');
        await succeed(1, data(100, 110)); await frame(); await frame();
        await succeed(0, degraded(150, 160, 'unavailable'));
        await flush(); await frame();
        assert.equal(statusText(), null);
        assert.deepEqual(handle.chart.data.datasets[0].data, [100, 110]);
        assert.equal(selected(), '5D');
        const count = requests.length;
        handle.refresh('1D');
        await flush();
        assert.equal(requests.length, count + 1,
            'a stale degraded reply must not be cached');
    })().catch(e => {console.error(e); process.exitCode = 1;});
    """)


def test_hidden_preload_degraded_reply_is_silent():
    run_node(CHART_HARNESS, r"""
    (async () => {
        await initial();
        handle.refresh('1D', {silent: true});
        await succeed(1, degraded(150, 160, 'unavailable'));
        await flush(); await frame();
        assert.equal(statusText(), null);
        assert.deepEqual(handle.chart.data.datasets[0].data, [100, 110]);
        assert.equal(selected(), '5D');
        assert.equal(summaries.at(-1).period, '5D');
        const count = requests.length;
        handle.refresh('1D');
        await flush();
        assert.equal(requests.length, count + 1,
            'a silent degraded reply must not be cached');
    })().catch(e => {console.error(e); process.exitCode = 1;});
    """)


def test_mode_repaint_does_not_clear_the_degraded_notice():
    run_node(CHART_HARNESS, r"""
    (async () => {
        await initial();
        handle.refresh('1D');
        await succeed(1, degraded(150, 160, 'unavailable'));
        await flush(); await frame();
        assert.equal(statusText(), 'Showing 5D data — 1D unavailable.');
        modeBar.handlers.click({target: modes[1]});
        await frame(); await frame();
        assert.equal(statusText(), 'Showing 5D data — 1D unavailable.');
        assert.equal(retryVisible(), true);
        assert.deepEqual(handle.chart.data.datasets[0].data, [100, 105]);
        assert.equal(requests.length, 2, 'a view repaint must not fetch');
    })().catch(e => {console.error(e); process.exitCode = 1;});
    """)


def test_successful_healthy_empty_paint_clears_the_notice():
    run_node(CHART_HARNESS, r"""
    (async () => {
        await initial();
        handle.refresh('1D');
        await succeed(1, degraded(150, 160, 'unavailable'));
        await flush(); await frame();
        assert.equal(retryVisible(), true);
        handle.refresh('1M');
        await succeed(2, {labels: [], values: [], index_values: [], twrr_pct: null});
        await frame(); await frame();
        assert.equal(statusText(), null);
        assert.equal(retryVisible(), false);
        assert.deepEqual(handle.chart.data.datasets[0].data, []);
    })().catch(e => {console.error(e); process.exitCode = 1;});
    """)


def test_scope_invalidation_clears_previous_close_before_update():
    run_node(CHART_HARNESS, r"""
    (async () => {
        scope = 1;
        handle.refresh('1D');
        await succeed(0, data(150, 160)); await frame(); await frame();
        handle.updatePrevClose(50);
        assert(handle.chart.updates.at(-1).min < 100,
            'the first scope must draw its previous-close line');

        scope = 2;
        handle.invalidate();
        handle.refresh('1D');
        await succeed(1, data(150, 160)); await frame(); await frame();
        assert.equal(handle.chart.updates.at(-1).min, 100,
            'the new scope must not inherit the old previous-close line');
    })().catch(e => {console.error(e); process.exitCode = 1;});
    """)


SUMMARY_HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1] + '/static/js/main.js', 'utf8');
const start = source.indexOf('let summaryInflight = null;');
const end = source.indexOf('// PORTFOLIO CHART', start);
assert(start >= 0 && end > start);

const calls = [];
function element() {
    let text = '';
    return {style: {}, className: '', classList: {add() {}, remove() {}, toggle() {}},
        title: '', get textContent() {return text;},
        set textContent(value) {text = value;}, parentElement: {style: {}}};
}
globalThis.currentPortfolioId = () => 1;
globalThis.portfolioEpoch = () => 1;
globalThis.portfolioQuery = () => '?portfolio_id=1';
globalThis.portfolioMasked = () => false;
globalThis.window = {};
globalThis.portfolioChartHandle = {
    updatePrevClose(value) {calls.push(['prevClose', value]);}
};
globalThis.portfolioValueEl = element();
globalThis.portfolioDayChangeEl = element();
globalThis.portfolioTotalReturnEl = element();
globalThis.portfolioCostBasisEl = element();
globalThis.allocViewIndex = 0;
globalThis.lastSummaryHoldings = null;
globalThis.lastSummaryExcluded = null;
globalThis.lastSummaryReady = false;
globalThis.lastSummaryFailed = false;
globalThis.paintAllocation = () => {};
globalThis.setPortfolioUnavailable = message => calls.push(['unavailable', message]);
globalThis.clearPortfolioGeometryLocks = () => {};
globalThis.paintChange = () => {};
globalThis.formatNumber = value => String(value);
vm.runInThisContext(source.slice(start, end));
"""


def run_summary_node(case):
    if not NODE:
        pytest.skip("Node is required for summary behavior tests")
    result = subprocess.run(
        [NODE, "-e", SUMMARY_HARNESS + "\n" + case, str(ROOT)],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_summary_with_unpriced_clears_previous_close_before_early_return():
    run_summary_node(r"""
    (async () => {
        globalThis.fetch = async () => ({
            ok: true,
            json: async () => ({
                unpriced: ['AAPL'], total_value: 0, day_gain: 0,
                total_gain: 0, holdings: [], currency: 'CAD',
            }),
        });
        await refreshPortfolioSummary();
        assert.deepEqual(calls[0], ['prevClose', null],
            'an unpriced summary must clear the previous close first');
        assert(calls.some(call => call[0] === 'unavailable'),
            'the all-unpriced path must still report the header as unavailable');
        const prevAt = calls.findIndex(call => call[0] === 'prevClose');
        const unavailableAt = calls.findIndex(call => call[0] === 'unavailable');
        assert(prevAt < unavailableAt,
            'the previous close must clear before the early return');
    })().catch(e => {console.error(e); process.exitCode = 1;});
    """)
