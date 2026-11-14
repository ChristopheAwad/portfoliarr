"""Exercise the real ledger page in Chromium with controlled API responses.

The project venv runs pytest, while the already-installed system Python owns
Playwright. The child process needs no Flask server, market data, or real DB:
it serves the rendered page and static files through Playwright routes and
controls fetch completion order in the browser.
"""

import json
import mimetypes
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
SYSTEM_PYTHON = Path("/usr/bin/python3")


if __name__ != "__main__":
    import pytest

    @pytest.mark.parametrize("scenario", [
        "collapsed_and_actions",
        "quick_sell_submission",
        "poll_sort_privacy_failure",
        "currency_and_portfolio_races",
        "closed_sales",
        "closed_sales_failure_and_loading",
        "invalid_ledger_and_latest_failure",
        "empty_and_closed_positions",
        "portfolio_list_becomes_empty",
        "portfolio_startup_recovery",
        "portfolio_initial_empty",
    ])
    def test_ledger_in_browser(client, tmp_path, scenario):
        probe = subprocess.run(
            [str(SYSTEM_PYTHON), "-c", "import playwright.sync_api"],
            capture_output=True, text=True,
        ) if SYSTEM_PYTHON.exists() else None
        if probe is None or probe.returncode:
            pytest.skip("system Python has no Playwright installation")
        page_html = tmp_path / "ledger.html"
        page_html.write_text(client.get("/ledger").get_data(as_text=True))
        result = subprocess.run(
            [str(SYSTEM_PYTHON), str(Path(__file__).resolve()),
             scenario, str(page_html)],
            cwd=ROOT, capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr


FETCH_STUB = r"""(() => {
    const pending = [];
    window.ledgerTestRequests = pending;
    window.ledgerTestPortfolioReplies = [];
    window.fetch = (input, options = {}) => {
        const url = new URL(String(input), location.href);
        const method = options.method || 'GET';
        if (url.pathname === '/api/portfolios') {
            const reply = window.ledgerTestPortfolioReplies.shift();
            return Promise.resolve(new Response(JSON.stringify(reply ? reply.body : [
                {id: 1, name: 'First'}, {id: 2, name: 'Second'}
            ]), {status: reply ? reply.status : 200,
                headers: {'Content-Type': 'application/json'}}));
        }
        if (url.pathname.startsWith('/api/transactions') ||
                url.pathname === '/api/portfolio/realized') {
            return new Promise((resolve, reject) => {
                pending.push({url: url.href, path: url.pathname, method,
                              body: options.body || null, resolve, reject});
            });
        }
        return Promise.resolve(new Response('{}', {status: 200}));
    };
    window.answerLedgerRequest = (index, body, status = 200) => {
        const request = pending[index];
        if (!request) throw new Error(`Missing request ${index}`);
        request.resolve(new Response(status === 204 ? null : JSON.stringify(body), {
            status, headers: {'Content-Type': 'application/json'}
        }));
    };
    window.rejectLedgerRequest = (index) => pending[index].reject(new Error('offline'));
})();"""


def tx(ident, ticker="BRK.B", *, qty=1, kind="BUY", currency="CAD",
       price=10.12345, quoted=True):
    row = {
        "id": ident, "ticker": ticker, "transaction_date": "2026-01-02",
        "transaction_type": kind, "qty": qty, "price": price,
        "currency": currency, "display_currency": currency,
        "price_display": price, "fee": 0.5,
        "group_avg_cost": 10.0,
    }
    if quoted:
        row.update({
            "price_now": 12.34567, "value": qty * 12.34567,
            "total_gain": qty * 2, "total_gain_pct": 20.0,
            "group_value": 123.0, "group_total_gain": 20.0,
            "group_total_gain_pct": 20.0, "group_day_gain": 5.0,
            "group_day_gain_pct": 4.0,
        })
    return row


def sale(ticker="BRK.B", *, realized=4.0, degraded=None):
    return {
        "ticker": ticker, "name": "Company <literal>",
        "transaction_date": "2026-01-02", "qty": 1,
        "avg_cost": 10.0, "price": 14.0, "currency": "USD",
        "realized": realized,
        "realized_pct": None if realized is None else 40.0,
        "degraded": degraded,
    }


def request_indices(page, path, method="GET"):
    return page.evaluate("""([path, method]) => window.ledgerTestRequests
        .map((r, i) => ({...r, i})).filter(r => r.path === path && r.method === method)
        .map(r => r.i)""", [path, method])


def wait_request(page, path, count=1, method="GET"):
    page.wait_for_function("""([path, count, method]) =>
        window.ledgerTestRequests.filter(r => r.path === path && r.method === method).length >= count
    """, arg=[path, count, method])
    return request_indices(page, path, method)[count - 1]


def answer(page, index, body, status=200):
    page.evaluate("([i, body, status]) => answerLedgerRequest(i, body, status)",
                  [index, body, status])


def reject(page, index):
    page.evaluate("i => rejectLedgerRequest(i)", index)


def boot(page, rows, sales=None):
    page.goto("http://ledger.test/ledger", wait_until="load")
    ledger = wait_request(page, "/api/transactions")
    realized = wait_request(page, "/api/portfolio/realized")
    answer(page, ledger, rows)
    answer(page, realized, sales or {"rows": [], "total_realized": 0})
    page.wait_for_function("document.querySelector('#ledger-body').children.length > 0")
    page.wait_for_function("document.querySelector('#realized-total').textContent.length > 0")


def click_group(page, ticker):
    page.locator(f'.ledger-group[data-ticker="{ticker}"] td[data-col="date"]').click()


def detail_ids(page):
    return page.locator("#ledger-body .tx-detail").evaluate_all(
        "rows => rows.map(row => Number(row.dataset.id))")


def flush_response(page):
    # Let fetch/json continuations and the next paint opportunity finish.
    page.evaluate("async () => { await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame); }")


def collapsed_and_actions(page):
    rows = [tx(i, f"SYN{i % 8}") for i in range(5000)]
    boot(page, rows)
    assert page.locator("#ledger-body .ledger-group").count() == 8
    assert detail_ids(page) == [], "collapsed ledger created transaction details"
    click_group(page, "SYN0")
    expected = [row["id"] for row in rows if row["ticker"] == "SYN0"]
    assert detail_ids(page) == expected
    click_group(page, "SYN1")
    assert len(detail_ids(page)) == 1250
    click_group(page, "SYN0")
    assert len(detail_ids(page)) == 625, "collapse must remove only that group's details"
    click_group(page, "SYN0")
    assert len(detail_ids(page)) == 1250, "re-expansion must not duplicate details"

    # Use a smaller payload to exercise real delegated actions and punctuation.
    page.evaluate("() => { refreshLedger(); }")
    poll = wait_request(page, "/api/transactions", 2)
    answer(page, poll, [tx(2, qty=2), tx(1, qty=3), tx(3, "ZZZ")])
    page.wait_for_function("document.querySelector('[data-ticker=\"BRK.B\"]') !== null")
    group = page.locator('.ledger-group[data-ticker="BRK.B"]')
    assert group.locator("a.ticker-link").get_attribute("href") == "/stock/BRK.B"
    page.evaluate("document.addEventListener('click', e => { if (e.target.closest('a')) e.preventDefault(); }, true)")
    group.locator("a.ticker-link").dispatch_event("click")
    assert not group.evaluate("el => el.classList.contains('open')")
    group.locator(".ticker-sell-btn").dispatch_event("click")
    assert page.locator('#tx-form [name="ticker"]').input_value() == "BRK.B"
    assert page.locator('#tx-form [name="qty"]').input_value() == "5"
    assert page.locator('#tx-form [name="price"]').input_value() == "12.35"
    assert page.locator('#tx-form [name="type"]').input_value() == "SELL"
    assert request_indices(page, "/api/transactions", "POST") == []
    assert not group.evaluate("el => el.classList.contains('open')")

    click_group(page, "BRK.B")
    assert detail_ids(page) == [2, 1]
    page.locator('.tx-detail[data-id="2"] td[data-col="actions"]').focus()
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.matches('.tx-detail[data-id=\"2\"] .edit')")
    page.locator('.tx-detail[data-id="2"] .edit').dispatch_event("click")
    assert page.locator('#tx-form [name="ticker"]').is_disabled()
    assert page.locator('#tx-form [name="qty"]').input_value() == "2"
    assert page.locator('#tx-form [name="fee"]').input_value() == "0.5"
    page.locator('#tx-form [name="qty"]').fill("2.25")
    page.locator("#tx-form").dispatch_event("submit")
    update = wait_request(page, "/api/transactions/2", method="PUT")
    body = json.loads(page.evaluate("i => ledgerTestRequests[i].body", update))
    assert body["qty"] == 2.25 and body["price"] == 10.12345 and body["fee"] == 0.5
    answer(page, update, {"warnings": []})
    ledger = wait_request(page, "/api/transactions", 3)
    sales = wait_request(page, "/api/portfolio/realized", 2)
    answer(page, ledger, [tx(2, qty=2.25), tx(1, qty=3), tx(3, "ZZZ")])
    answer(page, sales, {"rows": [], "total_realized": 0})
    page.wait_for_function("document.querySelector('.tx-detail[data-id=\"2\"] td[data-col=\"qty\"]').textContent === '2.25'")
    page.locator('.tx-detail[data-id="2"] .edit').dispatch_event("click")
    page.evaluate("showConfirm = async () => true; showPrompt = async () => 'BRK.B'")
    page.locator('.tx-detail[data-id="2"] .delete').dispatch_event("click")
    delete = wait_request(page, "/api/transactions/2", method="DELETE")
    answer(page, delete, None, 204)
    ledger = wait_request(page, "/api/transactions", 4)
    sales = wait_request(page, "/api/portfolio/realized", 3)
    answer(page, ledger, [tx(1, qty=3), tx(3, "ZZZ")])
    answer(page, sales, {"rows": [], "total_realized": 0})
    page.wait_for_function("document.querySelectorAll('.tx-detail[data-id=\"1\"]').length === 1")
    assert detail_ids(page) == [1]
    assert not page.locator('#tx-form [name="ticker"]').is_disabled()
    page.locator('.ledger-group[data-ticker="BRK.B"] .ticker-delete-btn').dispatch_event("click")
    bulk = wait_request(page, "/api/transactions/ticker/BRK.B", method="DELETE")
    answer(page, bulk, None, 204)
    ledger = wait_request(page, "/api/transactions", 5)
    sales = wait_request(page, "/api/portfolio/realized", 4)
    answer(page, ledger, [tx(3, "ZZZ")])
    answer(page, sales, {"rows": [], "total_realized": 0})
    page.wait_for_function("!document.querySelector('.ledger-group[data-ticker=\"BRK.B\"]')")


def quick_sell_submission(page):
    boot(page, [tx(1, qty=5)])
    page.locator(".ticker-sell-btn").dispatch_event("click")
    assert request_indices(page, "/api/transactions", "POST") == []
    page.locator('#tx-form [name="qty"]').fill("4")
    page.locator("#tx-form").dispatch_event("submit")
    request = wait_request(page, "/api/transactions", method="POST")
    body = json.loads(page.evaluate("i => ledgerTestRequests[i].body", request))
    assert body["ticker"] == "BRK.B" and body["type"] == "SELL"
    assert body["qty"] == 4 and body["price"] == 12.34567
    answer(page, request, {"warnings": []}, 201)
    ledger = wait_request(page, "/api/transactions", 2)
    sales = wait_request(page, "/api/portfolio/realized", 2)
    answer(page, ledger, [tx(2, qty=4, kind="SELL"), tx(1, qty=5)])
    answer(page, sales, {"rows": [sale()], "total_realized": 4})
    page.wait_for_function("document.querySelector('.tx-detail[data-id=\"2\"]')")
    assert detail_ids(page) == [2, 1]
    assert "4.00" in page.locator("#realized-total").inner_text()


def poll_sort_privacy_failure(page):
    boot(page, [tx(2, qty=2), tx(1, qty=1), tx(3, "ZZZ")])
    click_group(page, "BRK.B")
    page.evaluate("() => { refreshLedger(); }")
    answer(page, wait_request(page, "/api/transactions", 2),
           [tx(4, qty=4), tx(1, qty=1), tx(3, "ZZZ")])
    page.wait_for_function("document.querySelector('.tx-detail[data-id=\"4\"]')")
    assert detail_ids(page) == [4, 1]
    assert page.locator('.ledger-group[data-ticker="BRK.B"]').evaluate(
        "el => el.classList.contains('open')"), "open caret lost after poll"
    page.locator('.ledger-table th[data-col="ticker"]').dispatch_event("click")
    assert detail_ids(page) == [4, 1]
    page.evaluate("moveLedgerColumn('qty', 'date', true)")
    assert page.locator(".ledger-table thead th").first.get_attribute("data-col") == "qty"
    assert page.locator(".tx-detail td").first.get_attribute("data-col") == "qty"
    page.locator("#hide-ledger-toggle").click()
    assert page.locator('.tx-detail[data-id="4"] td[data-col="qty"]').inner_text() == "****"
    assert page.locator('.tx-detail[data-id="4"] td[data-col="fee"]').inner_text() == "****"
    click_group(page, "BRK.B")
    page.locator("#hide-ledger-toggle").click()
    assert detail_ids(page) == []

    # The failure occurs with only summaries in the DOM.
    page.evaluate("() => { refreshLedger(); }")
    reject(page, wait_request(page, "/api/transactions", 3))
    page.wait_for_function("!document.querySelector('.ticker-sell-btn')")
    assert page.locator(".ledger-group").count() == 2
    assert page.locator('.ledger-group[data-ticker="BRK.B"] td[data-col="value"]').inner_text() == "—"
    click_group(page, "BRK.B")
    assert page.locator('.tx-detail[data-id="4"] td[data-col="value"]').inner_text() == "—"
    page.locator('.ledger-table th[data-col="ticker"]').dispatch_event("click")
    assert page.locator(".ticker-sell-btn").count() == 0
    page.evaluate("() => { refreshLedger(); }")
    answer(page, wait_request(page, "/api/transactions", 4), [tx(4, qty=4)])
    page.wait_for_function("document.querySelector('.ticker-sell-btn')")
    assert detail_ids(page) == [4]


def currency_and_portfolio_races(page):
    cad = tx(1, currency="CAD")
    native = tx(1, currency="USD")
    boot(page, [cad])
    click_group(page, "BRK.B")
    page.locator("#usd-native-toggle").check()
    old_native = wait_request(page, "/api/transactions", 2)
    assert not page.locator(".tx-detail").count(), "old currency details remain while loading"
    page.locator("#usd-native-toggle").uncheck()
    new_cad = wait_request(page, "/api/transactions", 3)
    answer(page, new_cad, [cad])
    page.wait_for_function("document.querySelector('.tx-detail[data-id=\"1\"]')")
    answer(page, old_native, [native])
    flush_response(page)
    assert "CAD" in page.locator('.tx-detail td[data-col="price"]').inner_text()

    page.evaluate("() => { refreshLedger(); refreshLedger(); }")
    old = wait_request(page, "/api/transactions", 4)
    new = wait_request(page, "/api/transactions", 5)
    answer(page, new, [tx(5)])
    page.wait_for_function("document.querySelector('.tx-detail[data-id=\"5\"]')")
    reject(page, old)
    flush_response(page)
    assert page.locator(".ticker-sell-btn").count() == 1
    assert detail_ids(page) == [5]

    page.locator("#usd-native-toggle").check()
    failed_currency = wait_request(page, "/api/transactions", 6)
    reject(page, failed_currency)
    page.wait_for_function("document.querySelector('#ledger-body').textContent.includes('Ledger unavailable')")
    page.locator('.ledger-table th[data-col="ticker"]').dispatch_event("click")
    page.locator("#hide-ledger-toggle").click()
    assert "Ledger unavailable" in page.locator("#ledger-body").inner_text()
    page.locator("#hide-ledger-toggle").click()
    page.evaluate("() => { refreshLedger(); }")
    answer(page, wait_request(page, "/api/transactions", 7), [tx(7, currency="USD")])
    page.wait_for_function("document.querySelector('.tx-detail[data-id=\"7\"]')")
    assert "USD" in page.locator('.tx-detail td[data-col="price"]').inner_text()

    page.locator("#portfolio-select").select_option("2")
    old_b = wait_request(page, "/api/transactions", 8)
    old_b_sales = wait_request(page, "/api/portfolio/realized", 2)
    page.locator("#portfolio-select").select_option("1")
    new_a = wait_request(page, "/api/transactions", 9)
    new_a_sales = wait_request(page, "/api/portfolio/realized", 3)
    answer(page, new_a, [tx(8, "FIRST")])
    answer(page, new_a_sales, {"rows": [], "total_realized": 0})
    page.wait_for_function("document.querySelector('.ledger-group[data-ticker=\"FIRST\"]')")
    answer(page, old_b, [tx(9, "SECOND")])
    answer(page, old_b_sales, {"rows": [sale("SECOND")], "total_realized": 99})
    flush_response(page)
    assert page.locator('.ledger-group[data-ticker="SECOND"]').count() == 0
    assert detail_ids(page) == [], "portfolio switch must clear expanded tickers"
    assert "99" not in page.locator("#realized-total").inner_text()


def closed_sales(page):
    boot(page, [tx(1)], {"rows": [sale()], "total_realized": 4})
    assert "4.00" in page.locator("#realized-total").inner_text()
    assert page.locator(".closed-sales-row").count() == 0, "collapsed sales created detail rows"
    toggle = page.locator("#closed-sales-toggle")
    toggle.focus()
    page.keyboard.press("Enter")
    assert toggle.get_attribute("aria-expanded") == "true"
    assert page.locator(".closed-sales-row").count() == 1
    assert page.locator('.closed-sales-row td[data-cs-col="name"]').inner_text() == "Company <literal>"
    assert page.locator('.closed-sales-row td[data-cs-col="ticker"] a').get_attribute("href") == "/stock/BRK.B"
    page.keyboard.press("Space")
    assert toggle.get_attribute("aria-expanded") == "false"
    assert page.locator(".closed-sales-row").count() == 0

    page.evaluate("() => { refreshClosedSales(); }")
    answer(page, wait_request(page, "/api/portfolio/realized", 2),
           {"rows": [sale("NEW", realized=None, degraded="Missing FX")],
            "total_realized": None})
    page.wait_for_function("document.querySelector('#realized-total').textContent === '—'")
    assert page.locator(".closed-sales-row").count() == 0
    toggle.click()
    assert page.locator('.closed-sales-row a').inner_text() == "NEW"
    assert page.locator('td[data-cs-col="realized"]').get_attribute("title") == "Missing FX"

    page.evaluate("() => { refreshClosedSales(); refreshClosedSales(); }")
    old = wait_request(page, "/api/portfolio/realized", 3)
    new = wait_request(page, "/api/portfolio/realized", 4)
    reject(page, new)
    page.wait_for_function("document.querySelector('#closed-sales-body').textContent.includes('unavailable')")
    assert page.locator("#realized-total").inner_text() == "—"
    assert not page.locator("#realized-total").evaluate("el => el.classList.contains('pos') || el.classList.contains('neg')")
    answer(page, old, {"rows": [sale("OLD")], "total_realized": 4})
    flush_response(page)
    assert "unavailable" in page.locator("#closed-sales-body").inner_text()

    page.evaluate("() => { refreshClosedSales(); refreshClosedSales(); }")
    old = wait_request(page, "/api/portfolio/realized", 5)
    new = wait_request(page, "/api/portfolio/realized", 6)
    answer(page, new, {"rows": [], "total_realized": 0})
    page.wait_for_function("document.querySelector('#closed-sales-body').textContent.includes('No closed sales')")
    reject(page, old)
    flush_response(page)
    assert "No closed sales" in page.locator("#closed-sales-body").inner_text()

    page.locator("#portfolio-select").select_option("2")
    sales = wait_request(page, "/api/portfolio/realized", 7)
    assert page.locator("#realized-total").inner_text() == "—"
    assert "Loading" in page.locator("#closed-sales-body").inner_text()
    answer(page, sales, {"rows": [sale("SECOND")], "total_realized": -2})
    page.wait_for_function("document.querySelector('.closed-sales-row a')?.textContent === 'SECOND'")


def closed_sales_failure_and_loading(page):
    boot(page, [tx(1)], {"rows": [sale()], "total_realized": 4})
    assert page.locator("#realized-total").evaluate("el => el.classList.contains('pos')")
    page.evaluate("() => { refreshClosedSales(); }")
    request = wait_request(page, "/api/portfolio/realized", 2)
    page.locator("#closed-sales-toggle").click()
    assert "Loading" in page.locator("#closed-sales-body").inner_text()
    assert page.locator(".closed-sales-row").count() == 0
    reject(page, request)
    page.wait_for_function("document.querySelector('#closed-sales-body').textContent.includes('unavailable')")
    assert page.locator("#realized-total").inner_text() == "—"
    assert not page.locator("#realized-total").evaluate("el => el.classList.contains('pos') || el.classList.contains('neg')")
    page.locator("#closed-sales-toggle").click()
    page.locator("#closed-sales-toggle").click()
    assert "unavailable" in page.locator("#closed-sales-body").inner_text()
    page.evaluate("() => { refreshClosedSales(); }")
    answer(page, wait_request(page, "/api/portfolio/realized", 3), {"rows": []})
    page.wait_for_function("document.querySelector('#closed-sales-body').textContent.includes('unavailable')")
    assert page.locator("#realized-total").inner_text() == "—"


def invalid_ledger_and_latest_failure(page):
    rows = [tx(i, f"SYN{i % 8}") for i in range(1000)]
    boot(page, rows)
    assert detail_ids(page) == [], "1,000 collapsed transactions must not make details"
    page.evaluate("() => { refreshLedger(); }")
    answer(page, wait_request(page, "/api/transactions", 2), {"bad": "payload"})
    page.wait_for_function("!document.querySelector('.ticker-sell-btn')")
    assert page.locator(".ledger-group").count() == 8
    click_group(page, "SYN0")
    assert len(detail_ids(page)) == 125
    assert page.locator('.tx-detail td[data-col="value"]').first.inner_text() == "—"
    page.evaluate("() => { refreshLedger(); refreshLedger(); }")
    old = wait_request(page, "/api/transactions", 3)
    new = wait_request(page, "/api/transactions", 4)
    reject(page, new)
    flush_response(page)
    answer(page, old, [tx(1234, "OLD")])
    flush_response(page)
    assert page.locator('.ledger-group[data-ticker="OLD"]').count() == 0
    assert page.locator(".ticker-sell-btn").count() == 0
    assert len(detail_ids(page)) == 125


def empty_and_closed_positions(page):
    boot(page, [])
    assert "No transactions yet" in page.locator("#ledger-body").inner_text()
    page.evaluate("() => { refreshLedger(); }")
    rows = [tx(1, "CLOSED", qty=1), tx(2, "CLOSED", qty=1, kind="SELL")]
    answer(page, wait_request(page, "/api/transactions", 2), rows)
    page.wait_for_function("document.querySelector('#ledger-body').textContent.includes('No open positions')")
    page.evaluate("() => { localStorage.setItem('showClosedPositions', 'true'); refreshLedger(); }")
    answer(page, wait_request(page, "/api/transactions", 3), rows + [tx(3, "SHORT", kind="SELL", quoted=False)])
    page.wait_for_function("document.querySelectorAll('.ledger-group').length === 2")
    assert page.locator(".ticker-sell-btn").count() == 0
    click_group(page, "SHORT")
    assert page.locator('.tx-detail[data-id="3"] td[data-col="value"]').inner_text() == "—"


def portfolio_list_becomes_empty(page):
    boot(page, [tx(1)], {"rows": [sale()], "total_realized": 4})
    click_group(page, "BRK.B")
    page.locator("#closed-sales-toggle").click()
    assert page.locator(".closed-sales-row").count() == 1
    page.evaluate("() => { refreshLedger(); refreshClosedSales(); }")
    old_ledger = wait_request(page, "/api/transactions", 2)
    old_sales = wait_request(page, "/api/portfolio/realized", 2)
    page.evaluate("""async () => {
        ledgerTestPortfolioReplies.push({status: 200, body: []});
        await refreshPortfolioList();
    }""")
    assert page.locator(".ledger-group").count() == 0
    assert page.locator(".tx-detail").count() == 0
    assert page.locator(".closed-sales-row").count() == 0
    assert page.locator("#realized-total").inner_text() == "—"
    assert "No portfolios" in page.locator("#ledger-body").inner_text()
    assert "No portfolios" in page.locator("#closed-sales-body").inner_text()
    answer(page, old_ledger, [tx(99, "STALE")])
    answer(page, old_sales, {"rows": [sale("STALE")], "total_realized": 99})
    flush_response(page)
    assert page.locator(".ledger-group").count() == 0
    assert page.locator(".closed-sales-row").count() == 0
    assert page.locator("#realized-total").inner_text() == "—"
    page.evaluate("async () => { await refreshPortfolioList(); }")
    ledger = wait_request(page, "/api/transactions", 3)
    sales = wait_request(page, "/api/portfolio/realized", 3)
    answer(page, ledger, [tx(1)])
    answer(page, sales, {"rows": [], "total_realized": 0})
    page.wait_for_function("document.querySelector('.ledger-group[data-ticker=\"BRK.B\"]')")
    assert detail_ids(page) == []
    assert len(request_indices(page, "/api/transactions")) == 3
    assert len(request_indices(page, "/api/portfolio/realized")) == 3


def portfolio_startup_recovery(page):
    page.goto("http://ledger.test/ledger", wait_until="load")
    page.wait_for_function("!document.querySelector('#portfolio-load-status').hidden")
    page.wait_for_function("document.querySelector('#ledger-body').textContent.includes('Portfolio unavailable')")
    assert "Could not load portfolios" in page.locator("#portfolio-load-message").inner_text()
    page.locator("#closed-sales-toggle").click()
    assert "unavailable" in page.locator("#closed-sales-body").inner_text().lower()
    assert request_indices(page, "/api/transactions") == []
    assert request_indices(page, "/api/portfolio/realized") == []
    page.locator("#portfolio-load-retry").click()
    ledger = wait_request(page, "/api/transactions")
    sales = wait_request(page, "/api/portfolio/realized")
    answer(page, ledger, [tx(1)])
    answer(page, sales, {"rows": [], "total_realized": 0})
    page.wait_for_function("document.querySelector('.ledger-group')")
    flush_response(page)
    assert len(request_indices(page, "/api/transactions")) == 1
    assert len(request_indices(page, "/api/portfolio/realized")) == 1


def portfolio_initial_empty(page):
    page.goto("http://ledger.test/ledger", wait_until="load")
    page.wait_for_function("document.querySelector('#portfolio-load-message').textContent.includes('No portfolios')")
    assert request_indices(page, "/api/transactions") == []
    assert request_indices(page, "/api/portfolio/realized") == []
    assert "unavailable" in page.locator("#ledger-body").inner_text().lower() or \
        "No portfolios" in page.locator("#ledger-body").inner_text()
    page.locator("#closed-sales-toggle").click()
    assert "unavailable" in page.locator("#closed-sales-body").inner_text().lower() or \
        "No portfolios" in page.locator("#closed-sales-body").inner_text()
    page.locator("#portfolio-load-retry").click()
    ledger = wait_request(page, "/api/transactions")
    sales = wait_request(page, "/api/portfolio/realized")
    answer(page, ledger, [tx(1)])
    answer(page, sales, {"rows": [], "total_realized": 0})
    page.wait_for_function("document.querySelector('.ledger-group')")
    flush_response(page)
    assert len(request_indices(page, "/api/transactions")) == 1
    assert len(request_indices(page, "/api/portfolio/realized")) == 1


def main():
    from playwright.sync_api import sync_playwright

    scenario, html_path = sys.argv[1:]
    html = Path(html_path).read_text()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        stub = FETCH_STUB
        if scenario == "portfolio_startup_recovery":
            stub = stub.replace("window.ledgerTestPortfolioReplies = [];",
                                "window.ledgerTestPortfolioReplies = [{status: 503, body: {}}];")
        elif scenario == "portfolio_initial_empty":
            stub = stub.replace("window.ledgerTestPortfolioReplies = [];",
                                "window.ledgerTestPortfolioReplies = [{status: 200, body: []}];")
            # Simulate the initial list event firing before ledger.js can
            # subscribe. Subsequent recovery events still reach the page.
            stub += """(() => {
                const dispatch = document.dispatchEvent.bind(document);
                let firstListEvent = true;
                document.dispatchEvent = event => {
                    if (event.type === 'portfoliolistchange' && firstListEvent) {
                        firstListEvent = false;
                        return true;
                    }
                    return dispatch(event);
                };
            })();"""
        context.add_init_script(stub)

        def route_request(route):
            url = urlsplit(route.request.url)
            if url.netloc == "ledger.test" and url.path == "/ledger":
                route.fulfill(status=200, content_type="text/html", body=html)
            elif url.netloc == "ledger.test" and url.path.startswith("/static/"):
                path = ROOT / url.path.lstrip("/")
                if path.is_file():
                    if scenario == "portfolio_initial_empty" and path.name == "ledger.js":
                        # The list can resolve before a slower page script runs.
                        time.sleep(0.2)
                    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                    route.fulfill(status=200, content_type=content_type, body=path.read_bytes())
                else:
                    route.fulfill(status=404, body="")
            else:
                route.fulfill(status=200, content_type="text/css", body="")

        context.route("**/*", route_request)
        page = context.new_page()
        page.set_default_timeout(8000)
        page.set_default_navigation_timeout(10000)
        errors = []
        console_errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: console_errors.append(message.text)
                if message.type == "error" else None)
        try:
            globals()[scenario](page)
            assert not errors, f"Unexpected browser errors: {errors}"
            allowed = ["ledger refresh failed:", "closed sales refresh failed:"]
            if scenario == "portfolio_startup_recovery":
                allowed.append("portfolio list failed")
            unexpected = [error for error in console_errors if not error.startswith(
                tuple(allowed))]
            assert not unexpected, f"Unexpected console errors: {unexpected}"
        finally:
            browser.close()


if __name__ == "__main__":
    main()
