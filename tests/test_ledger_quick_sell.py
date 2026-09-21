# tests/test_ledger_quick_sell.py
# =================================
# The ledger's Quick Sell action: one Sell button per positively held and
# currently quoted ticker group. It PREPARES the existing transaction form
# (ticker, full net quantity, exact native price, local date, SELL) and never
# submits. The user reviews and presses Log.
#
# WHY STRING CHECKS: pytest cannot run the browser, so these tests READ the
# shipped ledger.js/style.css and pin the wiring contracts the same way the
# other ledger meta-tests do. The backend half (POST /api/transactions) is
# already covered by its own route tests — this feature adds no route.
#
# WHAT THESE TESTS CANNOT PROVE: that the button visibly works in a browser.
# That remains the user's manual GUI gate.

import re
from pathlib import Path

import pytest

LEDGER_JS = Path("static/js/ledger.js")
LEDGER_CSS = Path("static/style.css")


@pytest.fixture(scope="module")
def js():
    return LEDGER_JS.read_text()


@pytest.fixture(scope="module")
def css():
    return LEDGER_CSS.read_text()


def function_block(js, name):
    """Return the source between a named function's outer braces. Used to
    scope assertions to ONE function so a string elsewhere in the file
    cannot satisfy them by accident."""
    marker = f"function {name}("
    start = js.find(marker)
    assert start != -1, f"{name} not found in ledger.js"
    brace = js.index("{", start)
    depth = 0
    for i in range(brace, len(js)):
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if depth == 0:
                return js[brace:i + 1]
    raise AssertionError(f"unbalanced braces in {name}")


# ── A. Eligibility and construction ───────────────────────────────────

def test_group_row_builds_a_sell_button(js):
    """buildGroupRow must create one Sell action in the existing actions
    cell with the shared action class, a dedicated hook, explicit button
    type, and a ticker identity."""
    block = function_block(js, "buildGroupRow")
    assert '"tx-action-btn ticker-sell-btn"' in block, (
        "the Sell action must carry .tx-action-btn plus a .ticker-sell-btn hook"
    )
    assert 'sellBtn.type = "button"' in block, (
        "the Sell action must be an explicit non-submitting button"
    )
    assert 'sellBtn.textContent = "Sell"' in block, (
        "the Sell action label must be the literal text Sell"
    )
    assert "sellBtn.dataset.ticker = ticker" in block, (
        "the Sell action must carry the canonical ticker in data-ticker"
    )


def test_group_sell_is_ordered_before_destructive_delete(js):
    """The recoverable Sell action comes before the destructive delete-all
    action so the two reads in a stable, least-destructive-first order."""
    block = function_block(js, "buildGroupRow")
    assert block.index("sellBtn") < block.index("deleteTickerBtn"), (
        "Sell must be appended before the ticker delete-all button"
    )


def test_group_sell_requires_positive_net_and_live_price(js):
    """Eligibility is exact: more than the flat tolerance of net shares AND
    a finite, positive live native quote."""
    block = function_block(js, "buildGroupRow")
    assert "netQty > 1e-9" in block, (
        "Sell requires a net quantity above the flat-position tolerance"
    )
    assert "Number.isFinite(priceNow)" in block, (
        "Sell requires a finite live quote"
    )
    assert "priceNow > 0" in block, (
        "Sell requires a positive live quote"
    )


def test_group_sell_reads_native_price_now_not_display(js):
    """The prepared price is the native quote, even while the ledger shows
    converted CAD. price_display and group_value must not feed the button."""
    block = function_block(js, "buildGroupRow")
    assert "price_now" in block, (
        "Sell must read the native price_now quote field"
    )
    assert "price_display" not in block, (
        "Sell must never prepare a currency-converted price"
    )


def test_group_sell_keyed_on_its_own_quote(js):
    """One unquoted ticker must suppress only ITS action. Eligibility is
    computed inside buildGroupRow from that group's own priceNow — never
    from a shared/global quote state."""
    block = function_block(js, "buildGroupRow")
    assert "const priceNow = txs[0].price_now" in block, (
        "eligibility must read THIS group's first-row quote"
    )
    assert "Number.isFinite(priceNow)" in block


def test_group_sell_reuses_group_net_quantity(js):
    """The row's displayed quantity and its Sell eligibility must come from
    the SAME groupSortKeys net quantity — no second arithmetic path."""
    block = function_block(js, "buildGroupRow")
    assert block.count("const { netQty } = groupSortKeys(txs);") == 1, (
        "the group's exact net quantity must be read exactly once"
    )
    assert re.search(r"netQty > 1e-9", block), (
        "Sell eligibility must reuse that same netQty value"
    )


# ── B. Form preparation helper ────────────────────────────────────────

def test_prepare_helper_leaves_edit_mode_first(js):
    """A prepared sale is a NEW transaction (POST): the helper must exit any
    edit mode first so the form is not a PUT correction of an old row."""
    block = function_block(js, "prepareFullSale")
    assert "exitEditMode();" in block
    assert block.index("exitEditMode();") < block.index("txForm.elements.qty.value"), (
        "exitEditMode must run before the fields are filled"
    )


def test_prepare_helper_fills_every_field(js):
    """Ticker, unrounded quantity, local date, and SELL operation."""
    block = function_block(js, "prepareFullSale")
    assert "txForm.elements.ticker.value = ticker" in block
    assert "txForm.elements.qty.value = netQty" in block
    assert "todayLocalISO()" in block, (
        "the date must come from the local-time helper, never UTC ISO"
    )
    assert 'txForm.elements.type.value = "SELL"' in block


def test_prepare_helper_backs_rounded_price_with_exact_value(js):
    """The field SHOWS two decimals, the ledger STORES full precision."""
    block = function_block(js, "prepareFullSale")
    assert "autofillPrice = livePrice" in block, (
        "the exact live price must back the two-decimal display"
    )
    assert "priceEdited = false" in block, (
        "a programmatic fill is untouched, so priceEdited must be reset"
    )
    assert "txForm.elements.price.value = livePrice.toFixed(2)" in block


def test_prepare_helper_never_submits_or_fetches(js):
    """The action only fills the form. It must never submit, dispatch a
    submit event, or call the network on the user's behalf."""
    block = function_block(js, "prepareFullSale")
    assert "requestSubmit" not in block
    assert "dispatchEvent" not in block
    assert "fetch(" not in block


def test_prepare_helper_rechecks_eligibility(js):
    """A click can race a poll. The helper must re-verify the same exact
    positive quantity and live price before touching the form."""
    block = function_block(js, "prepareFullSale")
    assert "netQty > 1e-9" in block
    assert "Number.isFinite(livePrice)" in block
    assert "livePrice > 0" in block


def test_prepare_helper_scrolls_form_into_view(js):
    block = function_block(js, "prepareFullSale")
    assert "txForm.scrollIntoView(" in block


# ── C. Delegated click wiring ─────────────────────────────────────────

def test_delegated_listener_handles_sell(js):
    """The actions listener must detect .ticker-sell-btn, look the ticker's
    fresh cached rows up by id-equivalent identity, prepare the form, and
    return before any delete branch can swallow the click."""
    pattern = re.compile(
        r'event\.target\.closest\("\.ticker-sell-btn"\)'
        r"[\s\S]{0,400}?prepareFullSale\(ticker, txs\)"
        r"[\s\S]{0,80}?return;",
    )
    assert pattern.search(js), (
        "the delegated actions listener must wire .ticker-sell-btn to "
        "prepareFullSale and return"
    )
    sell_idx = js.index("prepareFullSale(ticker, txs)")
    delete_idx = js.index('event.target.closest(".ticker-delete-btn")')
    assert sell_idx < delete_idx, (
        "the Sell branch must run before the bulk delete branch"
    )


def test_group_toggle_guard_still_ignores_action_buttons(js):
    """Clicking Sell must not also expand/collapse the group: the toggle
    listener's .tx-action-btn guard stays in place."""
    assert re.search(
        r'if \(event\.target\.closest\("\.tx-action-btn"\)\) return;', js
    ), "the group toggle must keep ignoring .tx-action-btn clicks"


# ── D. Stale-quote safety on failed refresh ───────────────────────────

def test_failed_refresh_removes_unclicked_sell_actions(js):
    """When a whole refresh fails, the live quote behind a rendered Sell
    button is no longer trustworthy. Remove the unclicked action so the
    user cannot prepare a sale from a stale price."""
    block = function_block(js, "markLedgerUnavailable")
    assert re.search(
        r'querySelectorAll\("\.ticker-sell-btn"\)[\s\S]{0,120}?'
        r"\.remove\(\)",
        block,
    ), "stale Sell actions must be removed, not merely queried"
    # Only the Sell action is targeted — edit and both deletes must survive.
    assert "edit" not in block, "edit actions must not be removed"
    assert "ticker-delete-btn" not in block, (
        "delete actions must not be removed"
    )


def test_failed_refresh_marks_quotes_stale_for_later_renders(js):
    """A failed refresh must set the module stale flag, and the group
    builders must honor it. Otherwise a header sort or column drag calls
    renderLedger(lastTransactions) and resurrects the stale Sell actions
    (and live values) that were just removed."""
    stale_block = function_block(js, "markLedgerUnavailable")
    assert "ledgerStale = true" in stale_block, (
        "the failed refresh must mark cached quotes stale"
    )
    assert "!ledgerStale" in function_block(js, "buildGroupRow"), (
        "buildGroupRow must suppress stale eligibility"
    )
    assert "!ledgerStale" in function_block(js, "buildTxRow"), (
        "buildTxRow must suppress stale live cells"
    )
    # A successful fetch clears the flag before rendering.
    assert re.search(
        r"lastTransactions = transactions;[\s\S]{0,120}?ledgerStale = false;",
        js,
    ), "a successful refresh must clear the stale flag"


def test_failed_refresh_still_degrades_live_cells(js):
    """The existing live-cell degradation must survive the extension."""
    block = function_block(js, "markLedgerUnavailable")
    assert ".ledger-live" in block
    assert 'textContent = "—"' in block
    assert 'classList.remove("pos", "neg")' in block


# ── E. Touch visibility regression ────────────────────────────────────

def test_sell_action_visible_without_hover(css):
    """Touch devices have no hover: the shared action visibility rule must
    keep covering .tx-action-btn, which the Sell button reuses."""
    start = css.find("@media (hover: none)")
    assert start != -1, "@media (hover: none) block not found"
    end = css.find("}", css.find("{", start))
    block = css[start:end]
    assert ".tx-action-btn" in block, (
        "touch devices must reveal the shared action buttons without hover"
    )


def test_sell_action_reachable_by_keyboard(css):
    """visibility:hidden removes a button from the tab order, so the group
    actions need a :focus-within reveal for keyboard users, plus a visible
    focus indicator on the focused button itself."""
    assert re.search(
        r"\.ledger-(row|group):focus-within\s+\.tx-action-btn", css
    ), "a keyboard user must be able to focus and reveal the row actions"
    assert re.search(r"\.tx-action-btn:focus-visible", css), (
        "the focused action must show a visible focus indicator"
    )


def test_detail_row_has_a_focusable_tab_stop(js):
    """The :focus-within reveal is only usable if the row can receive
    focus. Group rows have the ticker link; detail rows have no focusable
    content of their own, so their actions cell must be an explicit tab
    stop — otherwise the keyboard fix is dead code for edit/delete."""
    block = function_block(js, "buildTxRow")
    assert "actionsCell.tabIndex = 0" in block, (
        "buildTxRow must give its actions cell a tab stop so :focus-within "
        "can reveal the edit/delete buttons"
    )
