# tests/test_ledger_page.py
# =========================
# The page split: the transaction ledger (table, tx form, import panel,
# privacy eye) moves OFF the dashboard onto its own page at /ledger, and
# gains a "Closed sales" table fed by GET /api/portfolio/realized.
#
# WHY STRING CHECKS AGAIN: the pytest suite can't run a browser, but the
# failures that plague template work are wiring failures — a moved id
# that some JS still queries, a script tag nobody wrote, a navbar link
# that died in a refactor. These checks read the SHIPPED HTML (via the
# Flask test client, so Jinja has already rendered it) and the JS source
# files, pinning the wiring contracts:
#   - /ledger renders the ledger shell + the closed-sales table
#   - / renders the dashboard WITHOUT any ledger markup
#   - base.html's navbar links /ledger (one navbar, every page)
#   - stock.js's "log a transaction" button lands on /ledger?ticker=…
#     (the tx form moved with the ledger)
#   - ledger.js owns the ledger + closed-sales wiring (fetches the
#     realized endpoint, renders both tables)
#   - the closed-sales table's 8 columns exist with stable data-cs-col
#     hooks (the JS keys on these, like the ledger's data-col)

import re
from pathlib import Path

import pytest

# ── Paths ─────────────────────────────────────────────────────────────

LEDGER_JS = Path("static/js/ledger.js")
STOCK_JS = Path("static/js/stock.js")
LEDGER_HTML = Path("templates/ledger.html")

# Markers that identify the ledger's UI. If any of these ships on the
# dashboard again (or vanishes from /ledger), the split regressed.
LEDGER_MARKERS = [
    'id="ledger-body"',        # the transaction table's tbody
    'id="tx-form"',            # the log-a-transaction form
    'id="import-panel"',       # the paste-to-import panel
    'id="hide-ledger-toggle"', # the ledger's privacy eye
]

# The closed-sales table's column hooks — ledger.js reads these.
CLOSED_SALES_COLS = [
    "ticker", "name", "sold", "qty",
    "avg_cost", "sell_price", "realized", "realized_pct",
]


def rendered(client, url):
    res = client.get(url)
    assert res.status_code == 200
    return res.get_data(as_text=True)


# ── The new page exists ───────────────────────────────────────────────

def test_ledger_route_renders_ledger_shell(client):
    """/ledger ships every piece of ledger UI — the whole card moved,
    not a copy: table, tx form, import panel, privacy eye."""
    html = rendered(client, "/ledger")
    for marker in LEDGER_MARKERS:
        assert marker in html, f"/ledger is missing {marker}"


def test_ledger_page_ships_closed_sales_table(client):
    """/ledger also ships the Closed sales table with all 8 columns,
    each carrying its data-cs-col hook for ledger.js."""
    html = rendered(client, "/ledger")
    assert 'id="closed-sales-body"' in html
    for col in CLOSED_SALES_COLS:
        assert f'data-cs-col="{col}"' in html, f"missing column {col}"


def test_ledger_page_extends_shared_shell(client):
    """/ledger must render through base.html — the shared navbar, the
    Chart.js/theme head, common.js. Rendered proof: the navbar logo and
    the search box (both base.html fixtures) are present, and the page
    loads its own ledger.js."""
    html = rendered(client, "/ledger")
    assert 'class="logo"' in html
    assert "js/common.js" in html
    assert "js/ledger.js" in html


# ── The dashboard let go ──────────────────────────────────────────────

def test_dashboard_no_longer_ships_ledger_markup(client):
    """GET / must not carry ANY ledger UI. This is the split's core
    promise — the dashboard is the live view, /ledger is the records."""
    html = rendered(client, "/")
    for marker in LEDGER_MARKERS:
        assert marker not in html, f"dashboard still ships {marker}"


def test_dashboard_keeps_its_own_pieces(client):
    """The split must not over-delete: summary strip, value chart and
    watchlist all stay on the dashboard."""
    html = rendered(client, "/")
    assert 'id="portfolio-value"' in html
    assert 'id="portfolioChart"' in html
    assert 'class="card watchlist-card"' in html


# ── Navigation ────────────────────────────────────────────────────────

def test_navbar_links_to_ledger_from_both_pages(client):
    """base.html owns the navbar, so ONE link serves every page. Both
    routes must render it — a link on only one page means someone
    hand-copied markup instead of extending the shell."""
    for url in ("/", "/ledger"):
        assert 'href="/ledger"' in rendered(client, url), \
            f"navbar on {url} does not link /ledger"


def test_stock_log_button_targets_ledger(client):
    """stock.js's 'log a transaction' button used to redirect to the
    dashboard's tx form — which moved. It must now land on the ledger
    page's form, carrying the ticker prefill param."""
    js = STOCK_JS.read_text()
    assert "/ledger?ticker=" in js
    assert "'/?ticker=" not in js and '"/?ticker=' not in js


# ── ledger.js owns the moved wiring ───────────────────────────────────

def test_ledger_js_wires_ledger_and_closed_sales():
    """ledger.js must fetch the realized endpoint AND render into both
    tables' tbodies. If the fetch URL drifts from the route in app.py,
    the closed-sales table renders empty with no error anywhere."""
    js = LEDGER_JS.read_text()
    assert "/api/portfolio/realized" in js
    assert "ledger-body" in js
    assert "closed-sales-body" in js


def test_ledger_js_no_longer_lives_in_main_js():
    """main.js must not keep a second copy of the ledger wiring — two
    fetchers of /api/transactions means two pollers fighting over one
    tbody. The ledger code MOVES, it is not forked."""
    main_js = Path("static/js/main.js").read_text()
    assert "/api/transactions" not in main_js
    assert "ledger-body" not in main_js


def test_ledger_html_source_extends_base():
    """Source-level check the rendered tests can't make: ledger.html
    must EXTEND base.html (not copy its head/navbar). Copy-paste shells
    drift the first time someone edits base.html."""
    src = LEDGER_HTML.read_text()
    assert 'extends "base.html"' in src


# ── Phone card mode (stacked cards, like the ledger's) ────────────────
#
# The ≤600px media block transforms the 11-column ledger table into
# stacked labeled cards (its overflow:visible rule kills the swipe for
# EVERY .table-wrap at that width). The closed-sales table shares that
# wrapper, so it MUST get the same transformation — otherwise its 640px
# min-width survives with no scroll and drags the whole page sideways
# (the mobile bug that motivated this section).

def test_closed_sales_js_stamps_cell_attributes():
    """renderClosedSales must stamp data-cs-col + data-label on every
    cell it builds. Card mode's CSS identifies cells by data-cs-col and
    draws its caption from data-label. The labels must be read from the
    CLOSED-SALES thead at boot — captions can never drift from the
    column names (the same rule as the ledger's ledgerColLabels).
    Unstamped cells would render caption-less lines on phones with no
    error anywhere."""
    js = LEDGER_JS.read_text()
    assert "dataset.csCol" in js
    assert 'querySelectorAll(".closed-sales-table th")' in js


def test_closed_sales_card_mode_css():
    """At ≤600px the closed-sales table must transform into stacked
    cards like the ledger's: the 640px floor released (that floor, with
    the shared overflow:visible rule, was the page-overflow bug), the
    thead hidden, and each row a stack of labeled lines with ::before
    captions drawn from data-label. Checked INSIDE the @media block —
    these rules at top level would break the desktop swipe table."""
    css = Path("static/style.css").read_text()
    start = css.find("@media (max-width: 600px)")
    assert start != -1, "@media (max-width: 600px) block not found"
    end = css.find("@media", start + 10)
    block = css[start:end if end != -1 else len(css)]
    # the floor that dragged the page wide must be released in card mode
    assert re.search(r"\.closed-sales-table\s*\{[^}]*min-width:\s*0", block), \
        "card mode must release the 640px min-width"
    # headers are the desktop table's identity — gone in card mode
    assert re.search(r"\.closed-sales-table thead\s*\{[^}]*display:\s*none",
                     block), "card mode must hide the thead"
    # each fact line gets its caption from the stamped data-label
    assert re.search(
        r"\.closed-sales-table td::before\s*\{[^}]*attr\(data-label\)",
        block, re.S), "card mode must draw captions from data-label"


def test_closed_sales_card_mode_covers_label_cap():
    """The card-mode caption contract has a ceiling on the other side:
    the desktop min-width:640px must STILL exist outside the media
    query (desktop/tablet swipe table unchanged). A 'fix' that deleted
    the desktop rule would silently stretch the table columns weirdly
    on wide screens instead."""
    css = Path("static/style.css").read_text()
    start = css.find("@media (max-width: 600px)")
    desktop = css[:start]
    assert re.search(r"\.closed-sales-table\s*\{[^}]*min-width:\s*640px",
                     desktop), "desktop swipe table must keep its floor"


# ── Mutations refresh BOTH views ──────────────────────────────────────

def test_mutations_refresh_ledger_and_closed_sales():
    """A SELL changes the ledger AND the closed-sales card. Every
    transaction mutation handler must refresh both: skipping closed
    sales leaves a just-completed sale invisible until the next 60s
    poll (or a manual reload) — the bug this pins. The four mutation
    sites (delete ticker, delete row, log/edit submit, import commit)
    call the pair through refreshLedgerViews."""
    js = LEDGER_JS.read_text()
    assert "function refreshLedgerViews" in js, \
        "the ledger+closed-sales refresh pair must exist"
    start = js.find("function refreshLedgerViews")
    body = js[start:js.find("}", start)]
    assert "refreshLedger();" in body and "refreshClosedSales();" in body, \
        "the pair helper must refresh BOTH views"
    assert len(re.findall(r"refreshLedgerViews\s*\(\s*\)", js)) >= 4, \
        "every mutation path must refresh the ledger AND closed sales"
