"""Execute the market block with controlled requests and a small fake DOM."""

import json
from pathlib import Path

import pytest


MAIN = (Path(__file__).resolve().parents[1] / "static/js/main.js").read_text()
MARKET = MAIN.split("// MARKET OVERVIEW BEGIN", 1)[1].split(
    "// MARKET OVERVIEW END", 1
)[0]


@pytest.fixture
def js():
    MiniRacer = pytest.importorskip("py_mini_racer").MiniRacer
    engine = MiniRacer()
    engine.eval("""
        var clock = 1000;
        Date.now = () => clock;
        var keys = ['north-america', 'europe', 'asia-pacific',
                    'crypto', 'commodities', 'currencies'];
        var pending = [];
        var errors = [];
        var console = {error: (...args) => errors.push(args[0])};
        var Intl = {NumberFormat: function () {
            this.format = value => Number(value).toFixed(2);
        }};
        var fetch = (url) => new Promise((resolve, reject) => {
            pending.push({url, resolve, reject});
        });
        function classes() {
            return {
                values: new Set(),
                toggle(name, enabled) {
                    if (enabled) this.values.add(name);
                    else this.values.delete(name);
                },
                remove(...names) { names.forEach(name => this.values.delete(name)); }
            };
        }
        function item(symbol) {
            const price = {textContent: ''};
            const change = {textContent: '', classList: classes(),
                            replaceChildren(...spans) { this.textContent = spans; }};
            change.classList.values.add('pos');
            return {
                dataset: {symbol},
                price, change,
                querySelector(selector) {
                    return selector === '.market-item-price' ? price : change;
                }
            };
        }
        var panels = {};
        var tabs = keys.map((key, index) => ({
            dataset: {category: key}, classList: classes(),
            tabIndex: index === 0 ? 0 : -1, attributes: {},
            setAttribute(name, value) { this.attributes[name] = value; },
            focus() { document.activeElement = this; },
            addEventListener() {}
        }));
        tabs[0].classList.values.add('active');
        keys.forEach((key, index) => {
            panels[key] = {
                dataset: {category: key}, hidden: index !== 0,
                items: [item(key + '-A'), item(key + '-B')],
                querySelectorAll() { return this.items; },
                querySelector(selector) {
                    const symbol = selector.split('data-symbol="')[1].split('"')[0];
                    return this.items.find(row => row.dataset.symbol === symbol);
                }
            };
        });
        var document = {
            activeElement: tabs[0],
            querySelector(selector) {
                if (selector === '.market-tabs') return {addEventListener() {}};
                const key = selector.split('data-category="')[1].split('"')[0];
                return panels[key];
            },
            querySelectorAll(selector) {
                return selector === '.market-tab' ? tabs : Object.values(panels);
            },
            createElement() { return {className: '', textContent: ''}; }
        };
    """)
    engine.eval(MARKET)
    return engine


def _succeed(js, index, category):
    quotes = [{"symbol": category + "-A", "price": 1.5,
               "change": 0.25, "change_pct": 20, "currency": "USD"}]
    js.eval(f"pending[{index}].resolve({{ok:true, json:() => Promise.resolve({json.dumps(quotes)})}})")


def _fail(js, index, mode):
    if mode == "network":
        js.eval(f'pending[{index}].reject(new Error("offline"))')
    elif mode == "json":
        js.eval(f'pending[{index}].resolve({{ok:true,json:() => Promise.reject(new Error("bad json"))}})')
    else:
        js.eval(f'pending[{index}].resolve({{ok:false,status:503}})')


def test_all_six_start_before_a_reply_and_paint_their_own_panels(js):
    js.eval("preloadMarketOverview()")
    assert json.loads(js.eval("JSON.stringify(pending.map(req => req.url))")) == [
        "/api/indices?category=" + key for key in
        ["north-america", "europe", "asia-pacific", "crypto", "commodities", "currencies"]
    ]
    assert js.eval("panels['north-america'].hidden") is False
    assert js.eval("panels.europe.hidden") is True
    assert js.eval("tabs[0].classList.values.has('active')") is True
    assert js.eval("document.activeElement === tabs[0]") is True
    _succeed(js, 1, "europe")
    assert "USD" in js.eval("panels.europe.items[0].price.textContent")
    assert js.eval("panels['north-america'].items[0].price.textContent") == ""
    assert js.eval("panels.europe.items[1].price.textContent") == "—"
    assert js.eval("panels.europe.items[1].change.textContent") == "—"
    _succeed(js, 0, "north-america")
    assert "USD" in js.eval("panels['north-america'].items[0].price.textContent")


def test_pending_tab_click_is_shared_and_success_is_reused_until_expiry(js):
    js.eval("preloadMarketOverview()")
    js.eval("activateMarketTab(tabs[1])")
    assert js.eval("pending.length") == 6
    assert js.eval("panels.europe.hidden") is False
    _succeed(js, 1, "europe")
    js.eval("activateMarketTab(tabs[0])")
    js.eval("activateMarketTab(tabs[1])")
    assert js.eval("pending.length") == 6
    assert "USD" in js.eval("panels.europe.items[0].price.textContent")
    js.eval("clock += 120001; activateMarketTab(tabs[0]); activateMarketTab(tabs[1])")
    assert js.eval("pending.length") == 7
    assert js.eval("pending[6].url") == "/api/indices?category=europe"


@pytest.mark.parametrize("mode", ["http", "network", "json"])
def test_failed_category_degrades_and_tab_click_retries(js, mode):
    js.eval("preloadMarketOverview()")
    _succeed(js, 0, "north-america")
    _fail(js, 1, mode)
    assert js.eval("panels.europe.items[0].price.textContent") == "—"
    assert js.eval("panels.europe.items[0].change.textContent") == "—"
    assert js.eval("panels.europe.items[0].change.classList.values.has('pos')") is False
    assert "USD" in js.eval("panels['north-america'].items[0].price.textContent")
    js.eval("activateMarketTab(tabs[1]); activateMarketTab(tabs[0]); activateMarketTab(tabs[1])")
    assert js.eval("pending.length") == 7
    _succeed(js, 6, "europe")
    assert "USD" in js.eval("panels.europe.items[0].price.textContent")


def test_empty_reply_gap_fills_without_a_freshness_failure(js):
    js.eval("preloadMarketOverview()")
    js.eval("pending[1].resolve({ok:true,json:() => Promise.resolve([])})")
    assert js.eval("panels.europe.items[0].price.textContent") == "—"
    js.eval("activateMarketTab(tabs[1])")
    assert js.eval("pending.length") == 6


def test_late_success_or_failure_cannot_replace_newer_poll(js):
    js.eval("preloadMarketOverview()")
    js.eval('refreshMarketOverview("north-america", {force:true})')
    _succeed(js, 6, "north-america")
    _fail(js, 0, "network")
    assert "USD" in js.eval("panels['north-america'].items[0].price.textContent")
    assert js.eval("pending.length") == 7

    js.eval('refreshMarketOverview("north-america", {force:true})')
    _fail(js, 7, "http")
    js.eval("activateMarketTab(tabs[1]); activateMarketTab(tabs[0])")
    assert js.eval("pending.length") == 9


def test_late_success_cannot_replace_newer_failed_refresh(js):
    js.eval("preloadMarketOverview()")
    js.eval('refreshMarketOverview("north-america", {force:true})')
    _fail(js, 6, "http")
    _succeed(js, 0, "north-america")
    assert js.eval("panels['north-america'].items[0].price.textContent") == "—"
    js.eval("activateMarketTab(tabs[1]); activateMarketTab(tabs[0])")
    assert js.eval("pending.length") == 8
    assert js.eval("pending[7].url") == "/api/indices?category=north-america"


def test_forced_poll_fetches_even_when_tab_is_fresh(js):
    js.eval("preloadMarketOverview()")
    _succeed(js, 0, "north-america")
    js.eval('refreshMarketOverview("north-america", {force:true})')
    assert js.eval("pending.length") == 7
    assert js.eval("pending[6].url") == "/api/indices?category=north-america"
