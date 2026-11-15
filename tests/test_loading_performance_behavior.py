"""Exercise chart and portfolio startup behavior in a controlled JS runtime.

Node runs the actual shared chart factory and portfolio selection code.  The
fake network and animation frames make response ordering deterministic without
requiring a browser or changing the application's dependencies.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def run_node(harness, case):
    if not NODE:
        pytest.skip("Node is required for JavaScript behavior tests")
    # An unresolved Promise alone does not keep Node running. Fail instead of
    # silently passing when a drawing or network completion never arrives.
    if "})().catch(" in case:
        case = ("const testDeadline = setTimeout(() => { "
                "console.error('behavior test did not complete'); "
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
let scope = 1, benchmarks = [];
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
        get textContent() {return text;},
        set textContent(value) {text = value; this.children = [];},
        append(...nodes) {this.children.push(...nodes);},
        replaceChildren(...nodes) {this.children = nodes;}};
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
    onPeriodSummary: value => summaries.push(value),
    onPaintComplete: value => {
        completions.push(value);
        if (globalThis.completeHook) globalThis.completeHook(value);
    }});
const data = (a, b) => ({labels: ['2026-01-01', '2026-01-02'], values: [a, b],
    index_values: [100, 105], costs: [a, a], twrr_pct: 5});
async function flush() {for (let i = 0; i < 12; i++) await Promise.resolve();}
async function frame() {const pending = frames.splice(0); pending.forEach(fn => fn()); await flush();}
async function succeed(index, value) {
    requests[index].resolve({ok: true, json: async () => value}); await flush();
}
async function fail(index) {requests[index].resolve({ok: false, status: 503}); await flush();}
function selected() {return buttons.find(b => b.classList.contains('active'))?.textContent;}
async function initial(value = data(100, 110)) {
    handle.refresh('5D'); await succeed(0, value); await frame(); await frame();
}
"""


@pytest.mark.parametrize("case", [
    r"""
    (async () => {
        const ready = handle.refresh('5D');
        let settled = false; ready.then(() => settled = true);
        await succeed(0, data(100, 110));
        assert.equal(settled, false);
        assert.deepEqual(handle.chart.data.datasets[0].data, []);
        assert.equal(marks.includes('chart:paint'), false);
        await frame();
        assert.deepEqual(handle.chart.data.datasets[0].data, [100, 110]);
        assert.equal(handle.chart.resizes, 1);
        assert.equal(handle.chart.updates.at(-1).mode, 'default',
            'the first paint runs the draw animation');
        assert.equal(settled, false);
        await frame();
        assert.equal(settled, true);
        assert.equal((await ready).hasData, true);
        assert(marks.includes('chart:paint'));
    })().catch(e => {console.error(e); process.exitCode = 1;});
    """,
    r"""
    (async () => {
        await initial();
        handle.refresh('1M'); await succeed(1, data(200, 220));
        handle.refresh('3M');
        await frame();
        assert.deepEqual(handle.chart.data.datasets[0].data, [100, 110]);
        assert.equal(selected(), '5D');
        assert.equal(summaries.at(-1).period, '5D');
        await fail(2); await frame();
        assert.deepEqual(handle.chart.data.datasets[0].data, [100, 110]);
        assert.equal(selected(), '5D');
        assert.equal(summaries.at(-1).period, '5D');
    })().catch(e => {console.error(e); process.exitCode = 1;});
    """,
    r"""
    (async () => {
        await initial();
        handle.refresh('1M', {silent:true});
        handle.refresh('1M');
        assert.equal(requests.length, 2, 'visible selection must join its pending preload');
        await succeed(1, data(200, 220)); await frame(); await frame();
        assert.deepEqual(handle.chart.data.datasets[0].data, [200, 220]);
        assert.equal(selected(), '1M');
        const count = requests.length;
        handle.refresh('5D'); await frame(); await frame();
        assert.equal(requests.length, count, 'cached switch must not fetch');
        assert.equal(handle.chart.updates.at(-1).mode, 'default',
            'a cached switch still runs the draw animation');
    })().catch(e => {console.error(e); process.exitCode = 1;});
    """,
    r"""
    (async () => {
        await initial();
        handle.refresh('1M');
        handle.invalidate();
        handle.refresh('1M');
        assert.equal(requests.length, 3, 'invalidation must start a new flight');
        await succeed(2, data(300, 330)); await frame(); await frame();
        await succeed(1, data(200, 220)); await frame(); await frame();
        assert.deepEqual(handle.chart.data.datasets[0].data, [300, 330]);
        benchmarks = ['SPY']; handle.refresh('3M');
        benchmarks = ['QQQ']; handle.refresh('3M');
        assert.equal(requests.length, 5, 'different benchmarks cannot share');
        await fail(4); handle.refresh('3M');
        assert.equal(requests.length, 6, 'failed requests must be retryable');
    })().catch(e => {console.error(e); process.exitCode = 1;});
    """,
    r"""
    (async () => {
        await initial();
        const before = handle.chart.updates.length;
        handle.updatePrevClose(42); handle.updatePrevClose(44); handle.updatePrevClose(44);
        assert.equal(handle.chart.updates.length, before, '5D does not draw a previous-close line');
        handle.refresh('1D'); await succeed(1, data(150, 160)); await frame(); await frame();
        assert(handle.chart.updates.at(-1).min < 44, 'the latest stored close must reach 1D');
        const after = handle.chart.updates.length;
        handle.updatePrevClose(44);
        assert.equal(handle.chart.updates.length, after, 'unchanged close must not redraw');
        handle.updatePrevClose(43);
        assert.equal(handle.chart.updates.at(-1).mode, 'none');
    })().catch(e => {console.error(e); process.exitCode = 1;});
    """,
    r"""
    (async () => {
        const ready = handle.refresh('5D');
        await succeed(0, {labels: [], values: [], index_values: [], twrr_pct: null});
        await frame(); await frame();
        assert.equal((await ready).hasData, false);
        assert.equal(marks.includes('chart:paint'), false);
        assert.equal(completions.length, 1, 'an empty successful draw still completes');
    })().catch(e => {console.error(e); process.exitCode = 1;});
    """,
    r"""
    (async () => {
        await initial();
        modeBar.handlers.click({target:modes[1]});
        assert.deepEqual(handle.chart.data.datasets[0].data, [100, 110]);
        await frame(); await frame();
        assert.deepEqual(handle.chart.data.datasets[0].data, [100, 105]);
        assert.equal(modes[1].classList.contains('active'), true);
        assert.equal(handle.chart.updates.at(-1).mode, 'default',
            'a view switch still runs the draw animation');
        assert.equal(requests.length, 1, 'mode switch must not fetch');
    })().catch(e => {console.error(e); process.exitCode = 1;});
    """,
    r"""
    (async () => {
        const first = handle.refresh('5D');
        await succeed(0, data(100, 110)); await frame();
        handle.refresh('1M');
        await frame();
        assert.equal(await first, null, 'a superseded draw cannot report readiness');
        assert.equal(marks.includes('chart:paint'), false);
        assert.equal(completions.length, 0);
    })().catch(e => {console.error(e); process.exitCode = 1;});
    """,
    r"""
    (async () => {
        await initial();
        handle.refresh('1M');
        handle.invalidate();
        handle.refresh('1M');
        await succeed(1, data(200, 220));
        handle.refresh('1M');
        assert.equal(requests.length, 3, 'old completion must not clear the new flight');
        await succeed(2, data(300, 330)); await frame(); await frame();
        assert.deepEqual(handle.chart.data.datasets[0].data, [300, 330]);
        scope = 2; handle.invalidate(); handle.refresh('1M');
        assert.equal(requests.length, 4, 'another portfolio needs its own history');
        assert.match(requests[3].url, /scope=2/);
        requests[3].reject(new Error('offline')); await flush();
        handle.refresh('1M');
        assert.equal(requests.length, 5, 'network failures release the pending slot');
    })().catch(e => {console.error(e); process.exitCode = 1;});
    """,
    r"""
    (async () => {
        canvas.parentElement.clientWidth = 0;
        const first = handle.refresh('5D'); await succeed(0, data(100, 110));
        await frame(); await frame();
        assert.equal(await first, null, 'zero geometry cannot claim a completed draw');
        assert.equal(marks.includes('chart:paint'), false);
        assert.equal(completions.length, 0);
        canvas.parentElement.clientWidth = 600;
        const recovered = handle.refresh('5D'); await frame(); await frame();
        assert.equal((await recovered).hasData, true);
        assert.equal(requests.length, 1, 'geometry recovery uses the cached reply');
    })().catch(e => {console.error(e); process.exitCode = 1;});
    """,
    r"""
    (async () => {
        await initial();
        handle.refresh('1M');
        scope = null; handle.invalidate();
        const count = requests.length;
        await succeed(1, data(500, 550)); await frame();
        handle.reload(); window.dispatch('online'); await flush();
        scope = undefined; handle.reload(); await flush();
        assert.equal(requests.length, count, 'a missing scope cannot request a default portfolio');
        assert.deepEqual(handle.chart.data.datasets[0].data, []);
    })().catch(e => {console.error(e); process.exitCode = 1;});
    """,
], ids=["draw-completion", "superseded-frame", "pending-and-cache",
         "invalidation-and-failure", "previous-close", "empty-draw",
         "mode-switch", "superseded-after-draw", "old-flight-first", "zero-geometry",
         "missing-scope"])
def test_chart_behavior(case):
    run_node(CHART_HARNESS, case)


def test_pending_new_timeframe_does_not_block_requested_mode():
    run_node(CHART_HARNESS, r"""
        (async () => {
            await initial();
            handle.refresh('1M'); await succeed(1, data(200, 220));
            modeBar.handlers.click({target:modes[1]});
            handle.refresh('3M');
            await frame(); await frame();
            assert.equal(requests.length, 3, 'the new timeframe is still pending');
            assert.equal(selected(), '5D');
            assert.equal(modes[1].classList.contains('active'), true);
            assert.deepEqual(handle.chart.data.datasets[0].data, [100, 105]);
            assert.equal(summaries.at(-1).period, '5D');
            modeBar.handlers.click({target:modes[1]});
            await frame();
            assert.deepEqual(handle.chart.data.datasets[0].data, [100, 105]);
            await succeed(2, data(300, 330)); await frame(); await frame();
            assert.equal(selected(), '3M');
            assert.deepEqual(handle.chart.data.datasets[0].data, [100, 105]);
        })().catch(e => {console.error(e); process.exitCode = 1;});
    """)


def test_pending_new_timeframe_keeps_requested_mode_before_first_draw():
    run_node(CHART_HARNESS, r"""
        (async () => {
            handle.refresh('5D'); await succeed(0, data(100, 110));
            modeBar.handlers.click({target:modes[1]});
            handle.refresh('1M');
            await frame(); await frame();
            assert.equal(requests.length, 2, 'the new timeframe is still pending');
            assert.equal(modes[1].classList.contains('active'), true);
            assert.deepEqual(handle.chart.data.datasets[0].data, []);
            assert.equal(marks.includes('chart:paint'), false);
            await succeed(1, data(200, 220)); await frame(); await frame();
            assert.equal(selected(), '1M');
            assert.deepEqual(handle.chart.data.datasets[0].data, [100, 105]);
        })().catch(e => {console.error(e); process.exitCode = 1;});
    """)


def test_scope_invalidation_keeps_requested_mode_without_old_data():
    run_node(CHART_HARNESS, r"""
        (async () => {
            await initial();
            handle.refresh('1M'); await succeed(1, data(200, 220));
            modeBar.handlers.click({target:modes[1]});
            scope = 2; handle.invalidate();
            handle.refresh('3M');
            await frame(); await frame();
            assert.equal(modes[1].classList.contains('active'), true);
            assert.deepEqual(handle.chart.data.datasets[0].data, []);
            await succeed(2, data(300, 330)); await frame(); await frame();
            assert.equal(selected(), '3M');
            assert.deepEqual(handle.chart.data.datasets[0].data, [100, 105]);
        })().catch(e => {console.error(e); process.exitCode = 1;});
    """)


@pytest.mark.parametrize("after_fallback", [False, True], ids=["before-fallback", "after-fallback"])
def test_mode_fallback_never_supersedes_newer_draw_or_repaints_old_scope(after_fallback):
    run_node(CHART_HARNESS, f"const afterFallback = {str(after_fallback).lower()};\n" + r"""
        (async () => {
            await initial();
            handle.refresh('1M'); await succeed(1, data(200, 220));
            modeBar.handlers.click({target:modes[1]});
            handle.refresh('3M');
            if (afterFallback) await frame();
            await succeed(2, data(300, 330));
            await frame(); await frame();
            assert.equal(selected(), '3M');
            assert.deepEqual(handle.chart.data.datasets[0].data, [100, 105]);

            modeBar.handlers.click({target:modes[0]}); await frame(); await frame();
            handle.refresh('6M'); await succeed(3, data(400, 440));
            modeBar.handlers.click({target:modes[1]});
            const updates = handle.chart.updates.length;
            scope = 2; await frame(); await frame();
            assert.equal(handle.chart.updates.length, updates, 'a changed scope must not repaint old data');
            assert.deepEqual(handle.chart.data.datasets[0].data, [300, 330]);
        })().catch(e => {console.error(e); process.exitCode = 1;});
    """)


@pytest.mark.parametrize("failure_before_frame", [True, False], ids=["fast", "after-frame"])
def test_failed_new_timeframe_keeps_requested_mode_on_last_valid_data(failure_before_frame):
    run_node(CHART_HARNESS, f"const fastFailure = {str(failure_before_frame).lower()};\n" + r"""
        (async () => {
            await initial();
            handle.refresh('1M'); await succeed(1, data(200, 220));
            modeBar.handlers.click({target:modes[1]});
            handle.refresh('3M');
            if (!fastFailure) await frame();
            await fail(2);
            await frame(); await frame();
            modeBar.handlers.click({target:modes[1]});
            await frame(); await frame();
            assert.equal(selected(), '5D');
            assert.equal(modes[1].classList.contains('active'), true);
            assert.deepEqual(handle.chart.data.datasets[0].data, [100, 105]);
        })().catch(e => {console.error(e); process.exitCode = 1;});
    """)


def test_failed_new_timeframe_keeps_requested_mode_before_any_chart_draw():
    run_node(CHART_HARNESS, r"""
        (async () => {
            handle.refresh('5D'); await succeed(0, data(100, 110));
            modeBar.handlers.click({target:modes[1]});
            handle.refresh('1M'); await fail(1);
            await frame(); await frame();
            modeBar.handlers.click({target:modes[1]}); await frame();
            assert.equal(modes[1].classList.contains('active'), true);
            assert.deepEqual(handle.chart.data.datasets[0].data, []);
            assert.equal(marks.includes('chart:paint'), false);
            handle.refresh('1M'); await succeed(2, data(200, 220));
            await frame(); await frame();
            assert.deepEqual(handle.chart.data.datasets[0].data, [100, 105]);
        })().catch(e => {console.error(e); process.exitCode = 1;});
    """)


def test_fast_comparison_failure_survives_pending_mode_draw_and_recovers():
    run_node(CHART_HARNESS, r"""
        (async () => {
            await initial();
            benchmarks = ['SPY']; handle.refresh('5D');
            modeBar.handlers.click({target:modes[1]});
            await fail(1); await frame(); await frame();
            assert.equal(modes[1].classList.contains('active'), true);
            let spy = handle.chart.data.datasets.find(d => d.label === 'SPY');
            assert.equal(spy?.compareError, 'refresh failed');
            assert.equal(comparisonReadout.hidden, false);
            assert.equal(comparisonReadout.children[1].children[2].textContent, 'SPY unavailable');

            benchmarks = ['QQQ']; handle.reload(); await fail(2);
            assert.equal(handle.chart.data.datasets.some(d => d.label === 'SPY'), false);
            assert.equal(handle.chart.data.datasets.find(d => d.label === 'QQQ')?.compareError, 'refresh failed');
            modeBar.handlers.click({target:modes[0]}); await frame(); await frame();
            modeBar.handlers.click({target:modes[1]}); await frame(); await frame();
            assert.equal(handle.chart.data.datasets.find(d => d.label === 'QQQ')?.compareError, 'refresh failed');

            handle.reload();
            await succeed(3, {...data(100,110), benchmarks:[{symbol:'QQQ', values:[100,110], error:null}]});
            await frame(); await frame();
            const qqq = handle.chart.data.datasets.find(d => d.label === 'QQQ');
            assert.equal(qqq.compareError, null);
            assert.deepEqual(qqq.data, [100,110]);
            assert.equal(comparisonReadout.children[1].children[2].textContent, 'QQQ');
        })().catch(e => {console.error(e); process.exitCode = 1;});
    """)


def test_partial_benchmark_errors_survive_repaint_without_mutating_reply():
    run_node(CHART_HARNESS, r"""
        (async () => {
            const reply = {...data(100,110), benchmarks:[
                {symbol:'SPY', values:null, error:'provider unavailable'}]};
            const before = JSON.stringify(reply);
            benchmarks = ['SPY']; await initial(reply);
            modeBar.handlers.click({target:modes[1]}); await frame(); await frame();
            benchmarks = ['SPY','QQQ']; handle.reload(); await fail(1);
            assert.equal(handle.chart.data.datasets.find(d => d.label === 'SPY').compareError, 'provider unavailable');
            assert.equal(handle.chart.data.datasets.find(d => d.label === 'QQQ').compareError, 'refresh failed');
            modeBar.handlers.click({target:modes[0]}); await frame(); await frame();
            modeBar.handlers.click({target:modes[1]}); await frame(); await frame();
            assert.equal(handle.chart.data.datasets.find(d => d.label === 'SPY').compareError, 'provider unavailable');
            assert.equal(handle.chart.data.datasets.find(d => d.label === 'QQQ').compareError, 'refresh failed');
            assert.equal(JSON.stringify(reply), before);
        })().catch(e => {console.error(e); process.exitCode = 1;});
    """)


PORTFOLIO_HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1] + '/static/js/common.js', 'utf8');
const start = source.indexOf('// A selection belongs to this browser');
const end = source.indexOf('// How long after a finger LIFTS', start);
assert(start >= 0 && end > start);
const requests = [], events = [], saved = new Map();
function target(extra={}) {
    return Object.assign({handlers:{}, addEventListener(name, fn) {
        (this.handlers[name] ||= []).push(fn);
    }, dispatch(name, event={}) {for (const fn of this.handlers[name] || []) fn(event);}}, extra);
}
const status = {hidden:true}, message = {textContent:''}, retry = target({disabled:false});
const select = target({disabled:true, value:'', replaceChildren(...nodes) {this.children=nodes;}});
const elements = {'portfolio-load-status':status, 'portfolio-load-message':message,
    'portfolio-load-retry':retry, 'portfolio-select':select};
globalThis.document = target({hidden:false, getElementById(id) {return elements[id] || null;},
    createElement() {return {};}, dispatchEvent(event) {events.push(event); this.dispatch(event.type, event);}});
globalThis.window = target();
globalThis.CustomEvent = class {constructor(type, init={}) {this.type=type; this.detail=init.detail;}};
globalThis.localStorage = {getItem(k) {return saved.get(k) || null;}, setItem(k,v) {saved.set(k,v);}};
globalThis.fetch = url => new Promise((resolve, reject) => requests.push({url, resolve, reject}));
vm.runInThisContext(source.slice(start, end));
async function flush() {for (let i=0; i<15; i++) await Promise.resolve();}
async function succeed(index, list) {requests[index].resolve({ok:true,json:async()=>list}); await flush();}
async function fail(index) {requests[index].resolve({ok:false,status:503}); await flush();}
function changes(type) {return events.filter(e => e.type === type);}
"""


@pytest.mark.parametrize("case", [
    r"""
    (async () => {
        saved.set('activePortfolioId', '2');
        await succeed(0, [{id:1,name:'Main'}, {id:2,name:'Other'}]);
        assert.equal(currentPortfolioId(), 2);
        assert.equal(changes('portfoliochange').length, 0);
        assert.equal(changes('portfoliolistchange').length, 1);
        assert.equal(requests.length, 1);
        assert.equal(status.hidden, true);
    })().catch(e => {console.error(e); process.exitCode=1;});
    """,
    r"""
    (async () => {
        await fail(0);
        assert.equal(status.hidden, false);
        assert(message.textContent.length > 0);
        window.dispatch('online');
        document.dispatch('visibilitychange');
        retry.dispatch('click');
        assert.equal(requests.length, 2, 'retries must share one pending read');
        assert.equal(retry.disabled, true);
        await succeed(1, [{id:7,name:'Recovered'}]);
        assert.equal(currentPortfolioId(), 7);
        assert.equal(status.hidden, true);
        assert.deepEqual(changes('portfoliochange').map(e=>e.detail), [{id:7, previous:null}]);
        assert.equal(changes('portfoliolistchange').length, 1);
    })().catch(e => {console.error(e); process.exitCode=1;});
    """,
    r"""
    (async () => {
        await succeed(0, []);
        assert.equal(currentPortfolioId(), null);
        assert.equal(status.hidden, false);
        assert.match(message.textContent, /no portfolios available/i);
        assert.equal(changes('portfoliochange').length, 0);
        retry.dispatch('click'); await fail(1);
        assert.equal(status.hidden, false);
        retry.dispatch('click'); await succeed(2, [{id:3,name:'Main'}]);
        assert.equal(currentPortfolioId(), 3);
        assert.equal(changes('portfoliochange').length, 1);
    })().catch(e => {console.error(e); process.exitCode=1;});
    """,
    r"""
    (async () => {
        await fail(0);
        retry.dispatch('click');
        const fresh = refreshPortfolioList();
        assert.equal(requests.length, 3, 'post-write refresh must be fresh');
        await succeed(2, [{id:2,name:'New'}]); await fresh;
        await succeed(1, [{id:1,name:'Old'}]);
        assert.equal(currentPortfolioId(), 2, 'older list must not replace newer list');
        assert.equal(changes('portfoliochange').length, 1);
    })().catch(e => {console.error(e); process.exitCode=1;});
    """,
    r"""
    (async () => {
        let ready = false;
        portfolioReady.then(() => ready = true);
        window.dispatch('storage', {key:'portfolioRevision'});
        assert.equal(requests.length, 2);
        await succeed(0, [{id:1,name:'Old'}]);
        assert.equal(ready, false, 'initial readiness must wait for the newer list');
        await succeed(1, [{id:2,name:'New'}]);
        assert.equal(ready, true);
        assert.equal(currentPortfolioId(), 2);
        assert.equal(changes('portfoliochange').length, 0);
        assert.equal(changes('portfoliolistchange').length, 1);
    })().catch(e => {console.error(e); process.exitCode=1;});
    """,
    r"""
    (async () => {
        await succeed(0, [{id:7,name:'Main'}]);
        const empty = refreshPortfolioList();
        await succeed(1, []); await empty;
        assert.equal(currentPortfolioId(), null);
        assert.equal(status.hidden, false);
        assert.deepEqual(changes('portfoliochange').map(e=>e.detail), [{id:null, previous:7}]);
        retry.dispatch('click'); await succeed(2, [{id:7,name:'Main'}]);
        assert.equal(currentPortfolioId(), 7);
        assert.deepEqual(changes('portfoliochange').map(e=>e.detail), [
            {id:null, previous:7}, {id:7, previous:null}]);
        assert.equal(changes('portfoliolistchange').length, 3);
    })().catch(e => {console.error(e); process.exitCode=1;});
    """,
], ids=["normal-start", "online-coalescing", "empty-and-repeated-failure",
         "fresh-after-write", "startup-superseded", "valid-empty-recovery"])
def test_portfolio_startup_behavior(case):
    run_node(PORTFOLIO_HARNESS, case)


@pytest.mark.parametrize("outcome", ["success", "http", "empty"])
def test_newer_startup_list_can_finish_while_the_original_read_hangs(outcome):
    run_node(PORTFOLIO_HARNESS, f"const outcome = {outcome!r};\n" + r"""
        (async () => {
            let ready = false;
            portfolioReady.then(() => ready = true);
            window.dispatch('storage', {key:'portfolioRevision'});
            assert.equal(requests.length, 2);
            if (outcome === 'success') await succeed(1, [{id:2,name:'New'}]);
            else if (outcome === 'http') await fail(1);
            else await succeed(1, []);
            assert.equal(ready, true, 'newest settled list must unblock startup');
            if (outcome !== 'success') {
                assert.equal(currentPortfolioId(), null);
                assert.equal(status.hidden, false);
                retry.dispatch('click');
                assert.equal(requests.length, 3);
                await succeed(2, [{id:2,name:'New'}]);
            }
            assert.equal(currentPortfolioId(), 2);
            assert.equal(changes('portfoliochange').length, outcome === 'success' ? 0 : 1);
            const lists = changes('portfoliolistchange').length;
            await succeed(0, [{id:1,name:'Old'}]);
            assert.equal(currentPortfolioId(), 2);
            assert.equal(changes('portfoliolistchange').length, lists);
        })().catch(e => {console.error(e); process.exitCode=1;});
    """)


@pytest.mark.parametrize("keys", [
    ["portfolioRevision"], ["activePortfolioId"],
    ["portfolioRevision", "activePortfolioId"],
], ids=["revision", "selection", "both"])
def test_cross_tab_revision_starts_fresh_read_during_recovery(keys):
    run_node(PORTFOLIO_HARNESS, f"const keys = {json.dumps(keys)};\n" + r"""
        (async () => {
            await fail(0); retry.dispatch('click');
            saved.set('activePortfolioId', '2');
            for (const key of keys) window.dispatch('storage', {key});
            assert.equal(requests.length, 2 + keys.length, 'storage changes must not join a pre-write read');
            const newest = requests.length - 1;
            await succeed(newest, [{id:1,name:'Old'}, {id:2,name:'New'}]);
            for (let i = 1; i < newest; i++) await succeed(i, [{id:1,name:'Old'}]);
            assert.equal(currentPortfolioId(), 2);
            assert.equal(saved.get('activePortfolioId'), '2');
            assert.deepEqual(changes('portfoliochange').map(e=>e.detail), [{id:2, previous:null}]);
        })().catch(e => {console.error(e); process.exitCode=1;});
    """)


@pytest.mark.parametrize("initial", ["http", "empty"])
@pytest.mark.parametrize("key", ["portfolioRevision", "activePortfolioId"])
def test_storage_recovery_is_shared_with_retry_events(initial, key):
    run_node(PORTFOLIO_HARNESS, f"const initial = {initial!r}, key = {key!r};\n" + r"""
        (async () => {
            if (initial === 'http') await fail(0);
            else await succeed(0, []);
            window.dispatch('storage', {key});
            assert.equal(requests.length, 2);
            assert.equal(retry.disabled, true);
            window.dispatch('online');
            document.dispatch('visibilitychange');
            retry.dispatch('click');
            assert.equal(requests.length, 2, 'retry events must join the storage recovery');
            await succeed(1, [{id:2,name:'Recovered'}]);
            assert.equal(currentPortfolioId(), 2);
            assert.equal(retry.disabled, false);
            assert.equal(status.hidden, true);
            assert.deepEqual(changes('portfoliochange').map(e=>e.detail), [{id:2,previous:null}]);
        })().catch(e => {console.error(e); process.exitCode=1;});
    """)


@pytest.mark.parametrize("outcome", ["http", "network", "empty"])
def test_storage_recovery_failure_releases_retry(outcome):
    run_node(PORTFOLIO_HARNESS, f"const outcome = {outcome!r};\n" + r"""
        (async () => {
            await fail(0);
            window.dispatch('storage', {key:'portfolioRevision'});
            window.dispatch('online');
            assert.equal(requests.length, 2);
            if (outcome === 'http') await fail(1);
            else if (outcome === 'network') {requests[1].reject(new Error('offline')); await flush();}
            else await succeed(1, []);
            assert.equal(retry.disabled, false);
            assert.equal(status.hidden, false);
            retry.dispatch('click');
            assert.equal(requests.length, 3);
            await succeed(2, [{id:2,name:'Recovered'}]);
            assert.equal(currentPortfolioId(), 2);
            assert.equal(changes('portfoliochange').length, 1);
        })().catch(e => {console.error(e); process.exitCode=1;});
    """)


def test_later_storage_event_supersedes_storage_recovery():
    run_node(PORTFOLIO_HARNESS, r"""
        (async () => {
            await fail(0);
            saved.set('activePortfolioId', '2');
            window.dispatch('storage', {key:'portfolioRevision'});
            window.dispatch('online');
            assert.equal(requests.length, 2);
            window.dispatch('storage', {key:'activePortfolioId'});
            document.dispatch('visibilitychange');
            retry.dispatch('click');
            assert.equal(requests.length, 3, 'later storage event must force a fresh read');
            await succeed(1, [{id:1,name:'Old'}]);
            assert.equal(currentPortfolioId(), null);
            assert.equal(retry.disabled, true, 'old completion cannot release the newest read');
            await succeed(2, [{id:1,name:'Old'}, {id:2,name:'New'}]);
            assert.equal(currentPortfolioId(), 2);
            assert.equal(saved.get('activePortfolioId'), '2');
            assert.equal(retry.disabled, false);
            assert.deepEqual(changes('portfoliochange').map(e=>e.detail), [{id:2,previous:null}]);
        })().catch(e => {console.error(e); process.exitCode=1;});
    """)


@pytest.mark.parametrize("outcome", ["http", "empty"])
def test_superseded_storage_failure_retries_before_old_read_settles(outcome):
    run_node(PORTFOLIO_HARNESS, f"const outcome = {outcome!r};\n" + r"""
        (async () => {
            await fail(0);
            window.dispatch('storage', {key:'portfolioRevision'});
            window.dispatch('storage', {key:'activePortfolioId'});
            assert.equal(requests.length, 3);
            if (outcome === 'http') await fail(2);
            else await succeed(2, []);
            assert.equal(retry.disabled, false);
            retry.dispatch('click');
            assert.equal(requests.length, 4);
            await succeed(1, [{id:1,name:'Old'}]);
            assert.equal(currentPortfolioId(), null);
            assert.equal(retry.disabled, true);
            await succeed(3, [{id:2,name:'Recovered'}]);
            assert.equal(currentPortfolioId(), 2);
            assert.equal(retry.disabled, false);
            assert.equal(changes('portfoliochange').length, 1);
        })().catch(e => {console.error(e); process.exitCode=1;});
    """)


@pytest.mark.parametrize("outcome", ["http", "network", "empty"], ids=["http", "network", "empty"])
@pytest.mark.parametrize("trigger", ["manual", "online"])
@pytest.mark.parametrize("old_first", [True, False], ids=["old-first", "new-first"])
def test_superseded_hung_recovery_does_not_block_new_retry(outcome, trigger, old_first):
    run_node(PORTFOLIO_HARNESS, f"const outcome = {outcome!r}, trigger = {trigger!r}, oldFirst = {str(old_first).lower()};\n" + r"""
        (async () => {
            await fail(0); retry.dispatch('click');
            const fresh = refreshPortfolioList().catch(() => null);
            assert.equal(requests.length, 3);
            if (outcome === 'http') await fail(2);
            else if (outcome === 'network') { requests[2].reject(new Error('offline')); await flush(); }
            else await succeed(2, []);
            await fresh; await flush();
            assert.equal(retry.disabled, false, 'a newer finished read must release Retry');
            if (trigger === 'manual') retry.dispatch('click');
            else window.dispatch('online');
            assert.equal(requests.length, 4, 'retry must not join the older hung read');
            if (oldFirst) {
                await succeed(1, [{id:1,name:'Old'}]);
                assert.equal(retry.disabled, true, 'an old completion must not release the new retry');
                window.dispatch('online');
                assert.equal(requests.length, 4);
            }
            await succeed(3, [{id:2,name:'Recovered'}]);
            assert.equal(currentPortfolioId(), 2);
            if (!oldFirst) await succeed(1, [{id:1,name:'Old'}]);
            assert.equal(currentPortfolioId(), 2);
            assert.equal(retry.disabled, false);
        })().catch(e => {console.error(e); process.exitCode=1;});
    """)


def test_reused_formatters_preserve_values_and_errors():
    run_node(r"""
        const assert = require('node:assert/strict');
        const fs = require('node:fs'); const vm = require('node:vm');
        const src = fs.readFileSync(process.argv[1] + '/static/js/common.js', 'utf8');
        const start = src.indexOf('// FORMATTERS');
        const end = src.indexOf('// Signed money text', start);
        const Original = Intl.NumberFormat; let made = 0;
        Intl.NumberFormat = function(...args) {made++; return new Original(...args);};
        vm.runInThisContext(src.slice(start, end));
        assert.equal(formatPrice(1234.5), '1,234.50');
        assert.equal(formatNumber(1.23456, 4), '1.2346');
        assert.equal(formatNumber(-2), '-2.00');
        for (let i=0; i<20; i++) {formatPrice(i); formatNumber(i, 4);}
        assert(made <= 3, `created ${made} formatters`);
        assert.throws(() => formatNumber(1, 1), RangeError);
    """, "")


@pytest.mark.parametrize("has_data", [True, False], ids=["finite", "empty"])
def test_first_completed_draw_starts_the_other_eight_preloads(has_data):
    run_node(r"""
        const assert = require('node:assert/strict');
        const fs = require('node:fs'); const vm = require('node:vm');
        const src = fs.readFileSync(process.argv[1] + '/static/js/main.js', 'utf8');
        const start = src.indexOf('const ALL_PERIODS =');
        const end = src.indexOf('const portfolioChartHandle =', start);
        assert(start >= 0 && end > start);
        const calls = [], marks = [];
        globalThis.refreshPortfolioChart = (period, opts) => calls.push({period, opts});
        globalThis.perfMark = mark => marks.push(mark);
        vm.runInThisContext(src.slice(start, end));
    """, f"""
        portfolioChartPainted({{period:'1D', hasData:{str(has_data).lower()}}});
        assert.deepEqual(calls.map(c => c.period), ['5D','1M','3M','6M','YTD','1Y','5Y','MAX']);
        assert(calls.every(c => c.opts.silent === true));
        assert.equal(marks.includes('dashboard:chart'), {str(has_data).lower()});
        portfolioChartPainted({{period:'5D', hasData:true}});
        assert.equal(calls.length, 8, 'preloads start only once');
    """)


def test_failed_default_then_selected_draw_starts_eight_other_periods():
    run_node(CHART_HARNESS, r"""
        const main = fs.readFileSync(process.argv[1] + '/static/js/main.js', 'utf8');
        const from = main.indexOf('const ALL_PERIODS =');
        const to = main.indexOf('const portfolioChartHandle =', from);
        globalThis.refreshPortfolioChart = (period, opts) => handle.refresh(period, opts);
        vm.runInThisContext(main.slice(from, to));
        globalThis.completeHook = portfolioChartPainted;
        (async () => {
            handle.refresh('5D'); await fail(0);
            assert.equal(requests.length, 1);
            handle.refresh('1D'); await succeed(1, data(100, 110));
            await frame();
            assert.equal(requests.length, 2, 'preloads wait for the next frame');
            await frame();
            assert.equal(requests.length, 10, 'all eight preloads start without awaiting replies');
            const periods = requests.slice(2).map(r => new URL(r.url, 'http://test').searchParams.get('period'));
            assert.deepEqual(periods, ['5D','1M','3M','6M','YTD','1Y','5Y','MAX']);
        })().catch(e => {console.error(e); process.exitCode = 1;});
    """)


@pytest.mark.parametrize("completion", ["response", "json", "rejected-after-recovery"])
def test_old_stock_position_reply_cannot_restore_an_empty_scope(completion):
    run_node(r"""
        const assert = require('node:assert/strict');
        const fs = require('node:fs'); const vm = require('node:vm');
        const src = fs.readFileSync(process.argv[1] + '/static/js/stock.js', 'utf8');
        const start = src.indexOf('function setPos(');
        const end = src.indexOf('// STATS', start);
        let scope = 7, epoch = 1; const positionRequests = [];
        globalThis.positionCard = {hidden:false};
        globalThis.positionNoteEl = {textContent:''};
        globalThis.symbol = 'AAPL';
        globalThis.portfolioReady = Promise.resolve();
        globalThis.currentPortfolioId = () => scope;
        globalThis.portfolioEpoch = () => epoch;
        globalThis.formatNumber = value => String(value);
        globalThis.formatPrice = value => String(value);
        const elements = {};
        globalThis.document = {getElementById(id) {
            return elements[id] ||= {textContent:'',classList:{remove(){},toggle(){}}};
        }};
        globalThis.fetch = () => new Promise((resolve, reject) => {
            positionRequests.push({resolve, reject});
        });
        vm.runInThisContext(src.slice(start, end));
    """, f"const completion = {completion!r};\n" + r"""
        (async () => {
            const old = refreshPosition(); await Promise.resolve();
            let resolveJson;
            const pos = {held:true,qty:123,avg_cost:1, cost_basis:123,price:1,
                value:123,gain:0,gain_pct:0,day_gain:0,day_gain_pct:0,currency:'USD'};
            if (completion === 'json') {
                positionRequests[0].resolve({ok:true,json:() => new Promise(resolve => {resolveJson = resolve;})});
                for (let i = 0; i < 5; i++) await Promise.resolve();
            }
            scope = null; epoch++;
            await refreshPosition();
            assert.equal(positionCard.hidden, true);
            if (completion === 'rejected-after-recovery') {
                scope = 8; epoch++;
                const fresh = refreshPosition(); await Promise.resolve();
                positionRequests[1].resolve({ok:true,json:async()=>({...pos,qty:8})});
                await fresh;
                assert.equal(positionCard.hidden, false);
                positionRequests[0].reject(new Error('late network failure'));
                await old;
                assert.equal(positionCard.hidden, false, 'an old failure cannot hide the recovered position');
                assert.equal(elements['pos-qty'].textContent, '8');
                return;
            }
            if (completion === 'json') resolveJson(pos);
            else positionRequests[0].resolve({ok:true,json:async()=>pos});
            await old;
            assert.equal(positionCard.hidden, true, 'a stale position cannot return after selection clears');
        })().catch(e => {console.error(e); process.exitCode=1;});
    """)


def test_real_pages_recover_after_initial_portfolio_failure():
    """Check the existing page listeners against a disposable stub server."""
    candidates = [Path("/usr/bin/python3"), Path(sys.executable)]
    browser_python = next((str(p) for p in candidates if p.exists() and
        subprocess.run([str(p), "-c", "import playwright.sync_api"],
                       capture_output=True).returncode == 0), None)
    if not browser_python:
        pytest.skip("Playwright is unavailable for the real-page recovery test")
    script = r"""
import os, re, sys, tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(sys.argv[1]); python = Path(sys.argv[2])
sys.path.insert(0, str(root / 'scripts'))
import measure_perf

with tempfile.TemporaryDirectory(prefix='portfolio-recovery-') as tmp:
    server = measure_perf.PerfServer(python, dict(os.environ), Path(tmp) / 'test.db', stub_ms=1)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            setup = browser.new_context()
            setup.route(re.compile(r'^https://'), lambda route: route.abort())
            page = setup.new_page()
            page.goto(server.base + '/auth/setup')
            page.fill('#setup-username', 'recovery-user')
            page.fill('#setup-password', 'recovery-pass-1234')
            page.fill('#setup-confirm', 'recovery-pass-1234')
            page.click('.auth-form button[type=submit]')
            page.wait_for_url(server.base + '/')
            created = page.evaluate('''async () => {
                const list = await fetch('/api/portfolios').then(r => r.json());
                return fetch('/api/transactions', {method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({ticker:'AAPL', date:'2026-01-01', price:100,
                        qty:2, type:'BUY', portfolio_id:list[0].id})}).then(r=>r.status);
            }''')
            assert created == 201, created
            real_portfolios = setup.request.get(server.base + '/api/portfolios').json()
            cookies = setup.cookies(); setup.close()

            cases = [('/', 'http', 'manual'), ('/ledger', 'http', 'online'),
                     ('/stock/AAPL', 'network', 'foreground'),
                     ('/preferences', 'empty', 'manual')]
            for path, failure, trigger in cases:
                context = browser.new_context()
                context.add_cookies(cookies)
                context.route(re.compile(r'^https://'), lambda route: route.abort())
                reads = []
                force_empty = {'enabled': False}
                def portfolios(route):
                    reads.append(route.request.url)
                    if force_empty['enabled']:
                        route.fulfill(status=200, content_type='application/json', body='[]')
                    elif len(reads) != 1:
                        route.continue_()
                    elif failure == 'network':
                        route.abort()
                    else:
                        route.fulfill(status=200 if failure == 'empty' else 503,
                                      content_type='application/json',
                                      body='[]' if failure == 'empty' else '{}')
                context.route('**/api/portfolios', portfolios)
                context.add_init_script('''window.recoveryChanges=[];
                    document.addEventListener('portfoliochange', e => recoveryChanges.push(e.detail));''')
                page = context.new_page(); errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(server.base + path, wait_until='domcontentloaded')
                page.locator('#portfolio-load-status').wait_for(state='visible')
                if failure == 'empty':
                    assert 'No portfolios available' in page.locator('#portfolio-load-message').inner_text()
                if trigger == 'manual':
                    page.locator('#portfolio-load-retry').focus()
                    page.keyboard.press('Enter')
                elif trigger == 'online':
                    page.evaluate("window.dispatchEvent(new Event('online'))")
                else:
                    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
                page.locator('#portfolio-load-status').wait_for(state='hidden')
                if path == '/':
                    page.wait_for_function("window.PortfoliarrPerf.summary().marks['dashboard:summary']")
                    page.wait_for_function("window.PortfoliarrPerf.summary().marks['dashboard:chart']")
                    assert page.locator('#portfolio-value').inner_text() not in ('', '—')
                elif path == '/ledger':
                    page.wait_for_function("document.querySelector('#ledger-body').textContent.includes('AAPL')")
                elif path.startswith('/stock/'):
                    page.locator('#position-card').wait_for(state='visible')
                    assert page.locator('#pos-qty').inner_text() == '2.00'
                else:
                    page.wait_for_function("document.querySelector('#portfolio-list').textContent.includes('Main')")
                changes = page.evaluate('window.recoveryChanges')
                assert len(changes) == 1 and changes[0]['previous'] is None, (path, changes)
                assert len(reads) == 2, (path, reads)
                assert not errors, (path, errors)

                # Normal startup must not emit a recovery event or launch the
                # scoped loaders twice. Preloads use other history periods.
                normal = context.new_page(); seen = []
                normal.on('request', lambda request: seen.append(request.url))
                normal.goto(server.base + path, wait_until='networkidle')
                if path == '/':
                    normal.wait_for_function("window.PortfoliarrPerf.summary().marks['dashboard:chart']")
                    assert sum('/api/portfolio/summary?' in url for url in seen) == 1, seen
                    assert sum('/api/portfolio/history?' in url and 'period=5D' in url for url in seen) == 1, seen
                elif path == '/ledger':
                    normal.wait_for_function("document.querySelector('#ledger-body').textContent.includes('AAPL')")
                    assert sum('/api/transactions?' in url for url in seen) == 1, seen
                    assert sum('/api/portfolio/realized?' in url for url in seen) == 1, seen
                elif path.startswith('/stock/'):
                    normal.locator('#position-card').wait_for(state='visible')
                    assert sum('/api/portfolio/position?' in url for url in seen) == 1, seen
                else:
                    normal.wait_for_function("document.querySelector('#portfolio-list').textContent.includes('Main')")
                assert sum(url.endswith('/api/portfolios') for url in seen) == 1, seen
                assert normal.evaluate('window.recoveryChanges') == []

                # A later empty list must clear every old scoped view. Online
                # and foreground retries still returning [] must not make any
                # scoped request while there is no active portfolio.
                old_id = normal.evaluate('currentPortfolioId()')
                force_empty['enabled'] = True
                normal.evaluate('() => refreshPortfolioList()')
                normal.locator('#portfolio-load-status').wait_for(state='visible')
                assert normal.evaluate('currentPortfolioId()') is None
                assert normal.evaluate('window.recoveryChanges') == [{'id':None,'previous':old_id}]
                def check_cleared():
                    if path == '/':
                        assert normal.locator('#portfolio-value').inner_text() in ('', '—')
                        assert normal.locator('#portfolio-cost-basis').inner_text() == ''
                        assert normal.evaluate("Chart.getChart(document.getElementById('portfolioChart')).data.labels.length") == 0
                    elif path == '/ledger':
                        assert 'AAPL' not in normal.locator('#ledger-body').inner_text()
                        assert 'AAPL' not in normal.locator('#closed-sales-body').inner_text()
                    elif path.startswith('/stock/'):
                        assert normal.locator('#position-card').is_hidden()
                    else:
                        assert normal.locator('#portfolio-list li').count() == 0
                check_cleared()
                scoped = lambda: [url for url in seen if '/api/portfolio/' in url or '/api/transactions?' in url]
                before = len(scoped())
                normal.evaluate("() => { window.dispatchEvent(new Event('online')); "
                                "document.dispatchEvent(new Event('visibilitychange')); }")
                normal.wait_for_load_state('networkidle')
                assert len(scoped()) == before, (path, scoped())
                check_cleared()
                assert normal.evaluate('window.recoveryChanges') == [{'id':None,'previous':old_id}]
                force_empty['enabled'] = False
                normal.locator('#portfolio-load-retry').click()
                normal.locator('#portfolio-load-status').wait_for(state='hidden')
                if path == '/':
                    normal.wait_for_function("Chart.getChart(document.getElementById('portfolioChart')).data.labels.length > 0")
                    normal.wait_for_function("document.querySelector('#portfolio-value').textContent.includes('CAD')")
                elif path == '/ledger':
                    normal.wait_for_function("document.querySelector('#ledger-body').textContent.includes('AAPL')")
                elif path.startswith('/stock/'):
                    normal.locator('#position-card').wait_for(state='visible')
                else:
                    normal.wait_for_function("document.querySelector('#portfolio-list').textContent.includes('Main')")
                assert normal.evaluate('window.recoveryChanges') == [
                    {'id':None,'previous':old_id}, {'id':old_id,'previous':None}]
                assert not errors, (path, errors)
                if path == '/':
                    # A slow newer timeframe must not block the actual
                    # Chart.js Performance view of the last valid reply.
                    pending_mode = normal.evaluate('''async () => {
                        const oldRAF = window.requestAnimationFrame, oldFetch = window.fetch;
                        const oldNow = Date.now, frames = [], requests = [];
                        const chart = Chart.getChart(document.getElementById('portfolioChart'));
                        const originalLabels = chart.data.labels.length;
                        window.requestAnimationFrame = callback => {frames.push(callback); return frames.length;};
                        window.fetch = (url, ...args) => String(url).startsWith('/api/portfolio/history')
                            ? new Promise(resolve => requests.push({url, resolve})) : oldFetch(url, ...args);
                        Date.now = () => oldNow() + 700000;
                        const flush = async () => {for (let i = 0; i < 25; i++) await Promise.resolve();};
                        const frame = async () => {
                            frames.splice(0).forEach(callback => callback(performance.now()));
                            await flush();
                        };
                        try {
                            portfolioChartHandle.refresh('1M'); await flush();
                            if (requests.length !== 1) throw new Error('Expected 1M request');
                            requests[0].resolve(new Response(JSON.stringify({labels:['2026-01-01','2026-01-02'],
                                values:[200,220], index_values:[100,105], costs:[200,200], twrr_pct:5}),
                                {status:200, headers:{'Content-Type':'application/json'}}));
                            await flush();
                            document.querySelector('[data-chart-mode="performance"]').click();
                            portfolioChartHandle.refresh('3M'); await flush();
                            if (requests.length !== 2) throw new Error('Expected pending 3M request');
                            await frame(); await frame();
                            const state = {
                                performance:document.querySelector('[data-chart-mode="performance"]').classList.contains('active'),
                                period:document.querySelector('.chart-timeframe-selectors .time-btn.active').textContent.trim(),
                                label:chart.data.datasets[0].label,
                                labels:chart.data.labels.length, originalLabels,
                                first:chart.data.datasets[0].data[0]
                            };
                            document.querySelector('[data-chart-mode="value"]').click();
                            await frame(); await frame();
                            return state;
                        } finally {
                            window.requestAnimationFrame = oldRAF; window.fetch = oldFetch; Date.now = oldNow;
                        }
                    }''')
                    assert pending_mode['performance'] is True, pending_mode
                    assert pending_mode['period'] == '5D', pending_mode
                    assert pending_mode['label'] == 'Growth of $100 (TWR)', pending_mode
                    assert pending_mode['labels'] == pending_mode['originalLabels'], pending_mode
                    assert pending_mode['first'] == 100, pending_mode
                    # Real Chart.js and the real picker: fail the comparison
                    # before its automatically queued Performance draw.
                    result = normal.evaluate('''async () => {
                        const oldRAF = window.requestAnimationFrame;
                        const oldFetch = window.fetch;
                        const frames = [], requests = [];
                        window.requestAnimationFrame = callback => {frames.push(callback); return frames.length;};
                        window.fetch = (url, ...args) => String(url).startsWith('/api/portfolio/history')
                            ? new Promise(resolve => requests.push({url, resolve})) : oldFetch(url, ...args);
                        const flush = async () => {for (let i = 0; i < 20; i++) await Promise.resolve();};
                        const frame = async () => {
                            const callbacks = frames.splice(0);
                            callbacks.forEach(callback => callback(performance.now()));
                            await flush();
                        };
                        try {
                            comparePicker.addSymbol('SPY'); await flush();
                            if (requests.length !== 1) throw new Error('Expected one comparison request');
                            requests[0].resolve(new Response('{}', {status:503}));
                            await flush(); await frame(); await frame();
                            const chart = Chart.getChart(document.getElementById('portfolioChart'));
                            const spy = chart.data.datasets.find(dataset => dataset.label === 'SPY');
                            return {mode:document.querySelector('[data-chart-mode="performance"]').classList.contains('active'),
                                error:spy && spy.compareError,
                                readout:document.querySelector('#portfolio-comparison-readout').textContent};
                        } finally {window.requestAnimationFrame = oldRAF; window.fetch = oldFetch;}
                    }''')
                    assert result['mode'] is True, result
                    assert result['error'] == 'refresh failed', result
                    assert 'SPY unavailable' in result['readout'], result
                context.close()

            # Exercise the storage/reconnect race on a real dashboard. The
            # pending list response is controlled in-page, not served twice.
            context = browser.new_context(); context.add_cookies(cookies)
            context.route(re.compile(r'^https://'), lambda route: route.abort())
            context.route('**/api/portfolios', lambda route: route.fulfill(
                status=503, content_type='application/json', body='{}'))
            context.add_init_script('''window.recoveryChanges=[];
                document.addEventListener('portfoliochange', e => recoveryChanges.push(e.detail));''')
            page = context.new_page()
            page.goto(server.base + '/', wait_until='domcontentloaded')
            page.locator('#portfolio-load-status').wait_for(state='visible')
            race = page.evaluate('''async portfolios => {
                const previous = window.fetch, pending = [];
                window.fetch = (url, ...args) => String(url) === '/api/portfolios'
                    ? new Promise(resolve => pending.push(resolve)) : previous(url, ...args);
                try {
                    window.dispatchEvent(new StorageEvent('storage', {key:'portfolioRevision'}));
                    window.dispatchEvent(new Event('online'));
                    document.dispatchEvent(new Event('visibilitychange'));
                    document.getElementById('portfolio-load-retry').click();
                    const recovery = retryInitialPortfolioList();
                    const count = pending.length;
                    for (const resolve of pending) resolve(new Response(JSON.stringify(portfolios), {
                        status:200, headers:{'Content-Type':'application/json'}}));
                    await recovery;
                    return {count, id:currentPortfolioId(), changes:window.recoveryChanges};
                } finally {window.fetch = previous;}
            }''', real_portfolios)
            assert race['count'] == 1, race
            assert race['id'] == real_portfolios[0]['id'], race
            assert race['changes'] == [{'id':real_portfolios[0]['id'], 'previous':None}], race
            page.locator('#portfolio-load-status').wait_for(state='hidden')
            page.wait_for_function("window.PortfoliarrPerf.summary().marks['dashboard:summary']")
            context.close()
            browser.close()
    finally:
        server.stop()
"""
    result = subprocess.run(
        [browser_python, "-c", script, str(ROOT), sys.executable],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
