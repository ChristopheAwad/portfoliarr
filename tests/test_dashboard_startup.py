"""Run the dashboard's real boot block with controlled pending requests."""

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1] + '/static/js/main.js', 'utf8');
const start = source.indexOf('// BOOT —');
assert(start >= 0, 'dashboard boot block exists');
const requests = [], actions = [], listeners = {};
let selected = null, masked = false, resolveReady, refresh;
globalThis.portfolioReady = new Promise(resolve => { resolveReady = resolve; });
globalThis.currentPortfolioId = () => selected;
globalThis.activeMarketCategory = 'north-america';
const categories = ['north-america', 'europe', 'asia-pacific',
                    'crypto', 'commodities', 'currencies'];
const pendingMarkets = new Set();
globalThis.setupMarketTabs = () => {};
globalThis.refreshMarketOverview = (category = activeMarketCategory, options = {}) => {
    if (!options.force && pendingMarkets.has(category)) return;
    pendingMarkets.add(category);
    requests.push('market:' + category);
};
globalThis.preloadMarketOverview = () => categories.forEach(c => refreshMarketOverview(c));
globalThis.refreshWatchlist = () => requests.push('watchlist');
globalThis.refreshVolumeLeaders = () => requests.push('volume');
// Leave the scoped requests pending. Background sections must start without
// depending on a successful summary or chart response.
globalThis.refreshPortfolioSummary = () => {
    if (!selected) return;
    requests.push('summary:' + selected);
    return new Promise(() => {});
};
globalThis.refreshPortfolioChart = () => {
    requests.push('chart:' + selected);
    return new Promise(() => {});
};
globalThis.portfolioMasked = () => masked;
globalThis.applyPortfolioPrivacy = () => actions.push('mask');
globalThis.setupAutoRefresh = callback => { refresh = callback; };
globalThis.document = {addEventListener(name, fn) { listeners[name] = fn; }};
globalThis.ALLOCATION_VIEWS = [{key:null}, {key:'sector'}];
globalThis.allocViewIndex = 0;
globalThis.fetchAllocDimension = key => requests.push('allocation:' + key);
globalThis.portfolioDayChangeEl = {textContent:'old'};
globalThis.portfolioTotalReturnEl = {textContent:'old'};
globalThis.portfolioCostBasisEl = {textContent:'old'};
globalThis.setPortfolioUnavailable = message => actions.push(message);
globalThis.updateAllocExcluded = () => {};
globalThis.updateAllocUnclassified = () => {};
globalThis.updateAllocCoverage = () => {};
globalThis.setAllocState = state => actions.push('allocation-state:' + state);
globalThis.portfolioChartHandle = {
    invalidate() { actions.push('chart:invalidate'); },
    reload() { requests.push('chart:reload:' + selected); }
};
async function flush() { for (let i = 0; i < 5; i++) await Promise.resolve(); }
"""


def run_boot(case, *, masked=False):
    if not NODE:
        pytest.skip("Node is required for dashboard startup behavior tests")
    script = HARNESS + f"\nmasked = {str(masked).lower()};\n" + r"""
vm.runInThisContext(source.slice(start));
(async () => {
""" + case + r"""
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(
        [NODE, "-e", script, str(ROOT)], capture_output=True,
        text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("masked", [False, True])
def test_portfolio_requests_precede_hidden_markets_and_volume(masked):
    run_boot(r"""
        // The portfolio list has not arrived yet.
        assert.deepEqual(requests, ['market:north-america', 'watchlist']);
        assert.deepEqual(actions, masked ? ['mask'] : []);
        selected = 7;
        resolveReady(7);
        await flush();
        assert.deepEqual(requests, [
            'market:north-america', 'watchlist', 'summary:7', 'chart:7',
            'market:europe', 'market:asia-pacific', 'market:crypto',
            'market:commodities', 'market:currencies', 'volume'
        ]);
        assert.equal(requests.filter(r => r === 'summary:7').length, 1);
        assert.equal(requests.filter(r => r === 'chart:7').length, 1);
    """, masked=masked)


def test_empty_or_failed_portfolio_list_does_not_block_unscoped_sections():
    run_boot(r"""
        // common.js resolves startup with null for either an empty list or
        // a failed initial read. Recovery later emits portfoliochange.
        resolveReady(null);
        await flush();
        assert.deepEqual(requests, [
            'market:north-america', 'watchlist', 'market:europe',
            'market:asia-pacific', 'market:crypto', 'market:commodities',
            'market:currencies', 'volume'
        ]);
        assert(!requests.some(r => r.startsWith('summary:') || r.startsWith('chart:')));
        selected = 8;
        listeners.portfoliochange();
        assert.deepEqual(requests.slice(-2), ['chart:reload:8', 'summary:8']);
    """)


def test_poll_refreshes_only_the_active_market_category():
    run_boot(r"""
        selected = 7; resolveReady(7); await flush();
        requests.length = 0;
        activeMarketCategory = 'europe';
        refresh();
        assert.deepEqual(requests, [
            'market:europe', 'watchlist', 'volume', 'summary:7'
        ]);
    """)


def test_portfolio_switch_reloads_current_chart_without_restarting_preloads():
    run_boot(r"""
        selected = 7; resolveReady(7); await flush();
        requests.length = 0;
        selected = 9;
        listeners.portfoliochange();
        assert.deepEqual(requests, ['chart:reload:9', 'summary:9']);
        assert(actions.includes('chart:invalidate'));
        assert.equal(portfolioDayChangeEl.textContent, '');
        assert.equal(portfolioTotalReturnEl.textContent, '');
        assert.equal(portfolioCostBasisEl.textContent, '');
        requests.length = 0;
        selected = null;
        listeners.portfoliochange();
        assert.deepEqual(requests, []);
        assert(actions.includes('No portfolios available.'));
    """)
