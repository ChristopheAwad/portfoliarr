# tests/test_privacy_toggles.py
# ================================
# Tests for the privacy eye buttons that hide sensitive financial values.
#
# WHY THIS FILE EXISTS:
#   Two eye-icon buttons let users hide portfolio values and ledger holding
#   values for privacy (like a show-password toggle). These tests lock the
#   CONTRACT between the HTML (button elements exist with correct IDs),
#   the CSS (button styles + icon swap), and the JS (data-hidden attribute
#   + localStorage persistence). Like test_ledger_col_count.py and
#   test_ui_revamp.py, these are string checks — pytest can't run a browser,
#   but it CAN verify the structural hooks that make the feature work.

import re
from pathlib import Path

import pytest

# ── Paths ─────────────────────────────────────────────────────────────
#
# TWO HTML FILES, TWO JS FILES since the ledger moved to /ledger: the
# portfolio eye lives on the dashboard (index.html + main.js), the
# ledger eye lives on the ledger page (ledger.html + ledger.js). Every
# assertion below checks the file that OWNS the button — an assertion
# against the wrong file would pass vacuously (the button is simply
# absent there) or fail spuriously.

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = PROJECT_ROOT / "templates" / "index.html"
LEDGER_HTML_PATH = PROJECT_ROOT / "templates" / "ledger.html"
JS_PATH = PROJECT_ROOT / "static" / "js" / "main.js"
LEDGER_JS_PATH = PROJECT_ROOT / "static" / "js" / "ledger.js"
CSS_PATH = PROJECT_ROOT / "static" / "style.css"


# ── Helpers ───────────────────────────────────────────────────────────

def _read_html():
    return HTML_PATH.read_text()

def _read_ledger_html():
    return LEDGER_HTML_PATH.read_text()

def _read_js():
    return JS_PATH.read_text()

def _read_ledger_js():
    return LEDGER_JS_PATH.read_text()

def _read_css():
    return CSS_PATH.read_text()


# ── HTML tests ────────────────────────────────────────────────────────

def test_hide_portfolio_button_exists():
    """The portfolio privacy button must exist in the dashboard HTML with
    the correct ID so main.js can find it and wire up the click handler."""
    html = _read_html()
    assert 'id="hide-portfolio-toggle"' in html, \
        "hide-portfolio-toggle button not found in index.html"


def test_hide_ledger_button_exists():
    """The ledger privacy button must exist in the LEDGER PAGE's HTML
    with the correct ID so ledger.js can find it and wire up the click
    handler. (It moved off the dashboard with the ledger card.)"""
    html = _read_ledger_html()
    assert 'id="hide-ledger-toggle"' in html, \
        "hide-ledger-toggle button not found in ledger.html"


def test_privacy_buttons_are_button_elements():
    """Both privacy controls must be <button> elements (not <label> or
    <input>), matching the show-password eye button pattern — each in
    the file that ships it."""
    portfolio_html = _read_html()
    ledger_html = _read_ledger_html()
    portfolio_match = re.search(
        r'<button[^>]*id="hide-portfolio-toggle"[^>]*>',
        portfolio_html
    )
    assert portfolio_match, "hide-portfolio-toggle must be a <button> element"
    ledger_match = re.search(
        r'<button[^>]*id="hide-ledger-toggle"[^>]*>',
        ledger_html
    )
    assert ledger_match, "hide-ledger-toggle must be a <button> element"


def test_privacy_buttons_have_privacy_btn_class():
    """Both privacy buttons must have the .privacy-btn class for styling."""
    portfolio_match = re.search(
        r'<button[^>]*class="[^"]*privacy-btn[^"]*"[^>]*id="hide-portfolio-toggle"',
        _read_html()
    )
    assert portfolio_match, "portfolio button must have .privacy-btn class"
    ledger_match = re.search(
        r'<button[^>]*class="[^"]*privacy-btn[^"]*"[^>]*id="hide-ledger-toggle"',
        _read_ledger_html()
    )
    assert ledger_match, "ledger button must have .privacy-btn class"


def test_privacy_buttons_have_data_hidden():
    """Both privacy buttons must start with data-hidden="false" (visible
    by default), which the page's JS toggles to "true" on click. Checked
    per-button, per-file: one button drifting to "true" must fail this
    test, not hide behind the other button's correct attribute."""
    for read_html, button_id in (
        (_read_html, "hide-portfolio-toggle"),
        (_read_ledger_html, "hide-ledger-toggle"),
    ):
        html = read_html()
        start = html.find(f'id="{button_id}"')
        assert start != -1, f"{button_id} not found"
        chunk = html[start:start + 400]
        assert 'data-hidden="false"' in chunk, \
            f"{button_id} must start with data-hidden=false"


def test_portfolio_button_in_stock_title():
    """The portfolio privacy button must sit inside the .stock-title div
    (the portfolio header area), next to the existing USD toggle."""
    html = _read_html()
    stock_title_match = re.search(
        r'<div class="stock-title">(.*?)</div>',
        html, re.DOTALL
    )
    assert stock_title_match, "stock-title div not found"
    stock_title_content = stock_title_match.group(1)
    assert 'hide-portfolio-toggle' in stock_title_content, \
        "hide-portfolio-toggle must be inside .stock-title div"


def test_ledger_button_in_card_header_actions():
    """The ledger privacy button must sit inside the .card-header-actions
    div (the ledger header area), next to the Import button — checked in
    the LEDGER PAGE's HTML, where the card now lives."""
    html = _read_ledger_html()
    ledger_card_start = html.find('class="card ledger-card"')
    assert ledger_card_start != -1, "ledger card not found"
    card_header_start = html.find('class="card-header-actions"', ledger_card_start)
    assert card_header_start != -1, "card-header-actions not found in ledger card"
    div_open = html.rfind('<div', 0, card_header_start)
    assert div_open != -1, "opening <div> not found for card-header-actions"
    div_depth = 0
    i = div_open
    card_header_content = None
    while i < len(html):
        if html[i:i+4] == '<div':
            div_depth += 1
        elif html[i:i+6] == '</div>':
            div_depth -= 1
            if div_depth == 0:
                card_header_content = html[div_open:i+6]
                break
        i += 1
    assert card_header_content is not None, "could not find closing </div>"
    assert 'hide-ledger-toggle' in card_header_content, \
        "hide-ledger-toggle must be inside .card-header-actions div"


def test_privacy_buttons_use_eye_icon():
    """Both privacy buttons must display an eye icon (inline SVG) as their
    default visible state, plus an eye-off icon for the hidden state —
    each read from the file that ships the button."""
    eye_path = "M1 12s4-8 11-8"
    eye_off_path = "M17.94 17.94"
    # Portfolio button (dashboard HTML)
    portfolio_start = _read_html().find('id="hide-portfolio-toggle"')
    assert portfolio_start != -1, "portfolio button not found"
    portfolio_chunk = _read_html()[portfolio_start:portfolio_start + 1200]
    assert eye_path in portfolio_chunk, \
        "portfolio button must contain eye icon SVG"
    assert eye_off_path in portfolio_chunk, \
        "portfolio button must contain eye-off icon SVG"
    # Ledger button (ledger page HTML)
    ledger_html = _read_ledger_html()
    ledger_start = ledger_html.find('id="hide-ledger-toggle"')
    assert ledger_start != -1, "ledger button not found"
    ledger_chunk = ledger_html[ledger_start:ledger_start + 1200]
    assert eye_path in ledger_chunk, \
        "ledger button must contain eye icon SVG"
    assert eye_off_path in ledger_chunk, \
        "ledger button must contain eye-off icon SVG"


# ── JS tests ──────────────────────────────────────────────────────────

# (No common.js ICONS tests here: the privacy buttons draw their eye icons
# as inline SVGs in their pages' HTML — locked by
# test_privacy_buttons_use_eye_icon. ICONS.eye / ICONS["eye-off"] briefly
# existed in common.js but had no call site — dead code with misleading
# comments, removed in the same review round that caught it.)


def test_js_references_hide_portfolio_toggle():
    """main.js must reference the hide-portfolio-toggle element by ID."""
    js = _read_js()
    assert 'hide-portfolio-toggle' in js, \
        "main.js must reference hide-portfolio-toggle"


def test_js_references_hide_ledger_toggle():
    """ledger.js must reference the hide-ledger-toggle element by ID —
    the ledger eye's wiring moved to the ledger page's script."""
    js = _read_ledger_js()
    assert 'hide-ledger-toggle' in js, \
        "ledger.js must reference hide-ledger-toggle"


def test_js_reads_localStorage_for_privacy_state():
    """Each page's script must read from localStorage to restore privacy
    button state across page refreshes — the feature's core persistence
    contract, checked per file: main.js owns hidePortfolio, ledger.js
    owns hideLedger."""
    js = _read_js()
    assert 'localStorage.getItem("hidePortfolio")' in js or \
           "localStorage.getItem('hidePortfolio')" in js, \
        "main.js must read hidePortfolio from localStorage"
    ledger_js = _read_ledger_js()
    assert 'localStorage.getItem("hideLedger")' in ledger_js or \
           "localStorage.getItem('hideLedger')" in ledger_js, \
        "ledger.js must read hideLedger from localStorage"


def test_js_saves_localStorage_on_click():
    """Each page's script must save state to localStorage when the user
    clicks its privacy button — the write side of the persistence
    contract, split the same way as the read side."""
    js = _read_js()
    assert 'localStorage.setItem("hidePortfolio"' in js or \
           "localStorage.setItem('hidePortfolio'" in js, \
        "main.js must save hidePortfolio to localStorage"
    ledger_js = _read_ledger_js()
    assert 'localStorage.setItem("hideLedger"' in ledger_js or \
           "localStorage.setItem('hideLedger'" in ledger_js, \
        "ledger.js must save hideLedger to localStorage"


def test_js_uses_click_event_not_change():
    """Privacy buttons must use 'click' event listeners (not 'change'),
    since they are <button> elements, not checkboxes. Registered
    per-toggle via regex, each checked in the script that wires it: the
    original version sliced from the portfolio listener to end-of-file,
    so a portfolio regression to 'change' still passed via the ledger's
    'click' further down — the same half-hollow trap this fix round
    closed for the ledger mask test."""
    js = _read_js()
    ledger_js = _read_ledger_js()
    for toggle, source in (("hidePortfolioToggle", js),
                           ("hideLedgerToggle", ledger_js)):
        assert re.search(rf'{toggle}\.addEventListener\("click"', source), \
            f"{toggle} must register a click event listener"
        assert re.search(rf'{toggle}\.addEventListener\("change"', source) is None, \
            f"{toggle} must NOT register a change event listener"


def test_js_uses_data_hidden_not_checked():
    """Privacy state must be read from data-hidden attribute, not .checked,
    since these are <button> elements, not checkboxes — in BOTH scripts."""
    js = _read_js()
    assert 'dataset.hidden' in js, \
        "main.js must use dataset.hidden to read privacy state"
    ledger_js = _read_ledger_js()
    assert 'dataset.hidden' in ledger_js, \
        "ledger.js must use dataset.hidden to read privacy state"
    # Ensure no references to .checked for privacy toggles
    assert 'hidePortfolioToggle.checked' not in js, \
        "main.js must not use .checked on portfolio toggle (it's a button)"
    assert 'hideLedgerToggle.checked' not in js, \
        "main.js must not use .checked on ledger toggle (it's a button)"
    assert 'hideLedgerToggle.checked' not in ledger_js, \
        "ledger.js must not use .checked on ledger toggle (it's a button)"


def test_js_has_apply_portfolio_privacy_function():
    """main.js must define an applyPortfolioPrivacy function that masks
    or unmasks the portfolio header values."""
    js = _read_js()
    assert 'applyPortfolioPrivacy' in js, \
        "main.js must define applyPortfolioPrivacy function"


def test_js_masks_qty_in_ledger_when_hidden():
    """ledger.js's buildTxRow AND buildGroupRow must BOTH mask the Qty cell
    with asterisks when the ledger privacy button is hidden. A bare `in`
    check passes if either builder's mask block is deleted, so this counts
    the assignment — exactly one per builder. (The builders live in
    ledger.js since the ledger moved to its own page.)"""
    js = _read_ledger_js()
    assert js.count('qtyCell.textContent = "****"') == 2, \
        "both buildTxRow and buildGroupRow must mask qtyCell with asterisks"


def test_js_masks_ledger_values_when_hidden():
    """ledger.js's buildTxRow AND buildGroupRow must BOTH gate their mask
    block on the ledger toggle state and mask Value, Total Gain and Day
    Gain cells (plus strip pos/neg). The original version of this test
    only asserted the string 'hideLedgerToggle' existed anywhere in the
    file — it would have passed even if both mask blocks were emptied
    out."""
    js = _read_ledger_js()
    for fn in ("function buildTxRow(", "function buildGroupRow("):
        body = _function_body(js, fn)
        assert 'hideLedgerToggle.dataset.hidden === "true"' in body, \
            f"{fn}...) must gate its mask block on the ledger toggle state"
        for cell in ("qtyCell", "valueCell", "gainCell", "dayGainCell"):
            assert f'{cell}.textContent = "****"' in body, \
                f"{fn}...) must mask {cell} with asterisks"
        assert 'gainCell.classList.remove("pos", "neg")' in body, \
            f"{fn}...) must strip pos/neg from the masked gain cells"


# ── CSS tests ─────────────────────────────────────────────────────────

def test_css_has_privacy_btn_style():
    """style.css must define styling for .privacy-btn elements."""
    css = _read_css()
    assert '.privacy-btn' in css, \
        "style.css must define .privacy-btn styles"


def test_css_privacy_btn_has_no_background():
    """The .privacy-btn must have background: none so it looks like a plain
    icon, not a filled button."""
    css = _read_css()
    start = css.find('.privacy-btn {')
    assert start != -1, ".privacy-btn rule not found"
    end = css.find('}', start)
    rule = css[start:end]
    assert 'background' in rule and 'none' in rule, \
        ".privacy-btn must have background: none"


def test_css_privacy_btn_icon_swap():
    """style.css must swap icons using data-hidden attribute — hiding the
    first SVG when data-hidden='true' to show the eye-off icon."""
    css = _read_css()
    assert 'data-hidden' in css, \
        "style.css must use data-hidden for icon swap"
    assert '.privacy-btn[data-hidden="true"]' in css, \
        "style.css must define icon swap rule for data-hidden=true"


def test_css_privacy_btn_no_opacity():
    """The .privacy-btn rule must NOT dim the icon with opacity. This is the
    regression lock for the original bug: opacity: 0.6 multiplied the theme
    color down until the eye icon nearly vanished against the dark card
    (#1a1d27). Visibility comes from the color token alone, at full opacity
    — so opacity is banned outright, for every state and both themes."""
    css = _read_css()
    start = css.find('.privacy-btn {')
    assert start != -1, ".privacy-btn rule not found"
    end = css.find('}', start)
    rule = css[start:end]
    assert 'opacity' not in rule, \
        ".privacy-btn must not use opacity — it makes the icon blend into dark mode"


def test_css_privacy_btn_uses_theme_token():
    """The .privacy-btn rule must take its color from --text-secondary, not
    a hardcoded hex. The token resolves per theme (#5b6472 on white in
    light mode, #9ca3af on #1a1d27 in dark — both ≥6:1 contrast), which is
    exactly what keeps the icon readable in BOTH modes. Both SVGs inherit
    it via stroke="currentColor", so the on (eye-off) and off (eye) states
    are equally visible too."""
    css = _read_css()
    start = css.find('.privacy-btn {')
    assert start != -1, ".privacy-btn rule not found"
    end = css.find('}', start)
    rule = css[start:end]
    assert 'color: var(--text-secondary)' in rule, \
        ".privacy-btn must use the --text-secondary token, not a hardcoded color"


def test_css_mobile_flex_wrap():
    """At ≤600px, .stock-title and .card-header-actions must have
    flex-wrap: wrap so the eye buttons and other controls wrap on narrow
    screens instead of overflowing."""
    css = _read_css()
    media_start = css.find('@media (max-width: 600px)')
    assert media_start != -1, "@media (max-width: 600px) block not found"
    media_end = css.find('@media', media_start + 10)
    if media_end == -1:
        media_end = len(css)
    media_block = css[media_start:media_end]
    assert '.stock-title' in media_block and 'flex-wrap' in media_block, \
        "@media (max-width: 600px) must include .stock-title flex-wrap: wrap"
    assert '.card-header-actions' in media_block and 'flex-wrap' in media_block, \
        "@media (max-width: 600px) must include .card-header-actions flex-wrap: wrap"


def test_css_has_no_dead_mask_rules():
    """style.css must NOT define .privacy-mask or .price-change.privacy-masked.
    Both were dead code: the JS only ever applies `privacy-masked`, and the
    mask's box geometry is owned by main.js's inline min-width/min-height
    locks (inline styles beat any stylesheet rule, and the class is
    stripped in the same turn the locks release) — so those rules never
    visually applied and only misled readers into trusting CSS that does
    nothing. The privacy-masked CLASS survives in main.js as a semantic
    marker and the **** strings live in the JS masked branches."""
    css = _read_css()
    assert '.privacy-mask {' not in css, \
        ".privacy-mask applies to nothing (JS uses privacy-masked) — dead rule"
    assert '.price-change.privacy-masked' not in css, \
        "the masked pill's geometry is owned by main.js's inline locks, not CSS"
    assert 'privacy-masked' in _read_js(), \
        "main.js must keep setting/stripping privacy-masked as a marker"


def test_js_uses_privacy_masked_class():
    """main.js applyPortfolioPrivacy must use the 'privacy-masked' class
    on the price-change elements to prevent layout shift."""
    js = _read_js()
    assert 'privacy-masked' in js, \
        "main.js must reference privacy-masked class"


def test_asterisk_masks_painted_in_js():
    """applyPortfolioPrivacy must paint the **** masks on the portfolio
    header spans themselves — checked INSIDE the function body, because a
    file-wide '"****"' check passes on the eight ledger-builder
    occurrences alone and would stay green even if all three portfolio
    mask assignments were deleted. (The ledger cells are covered
    per-builder by test_js_masks_ledger_values_when_hidden.)"""
    js = _read_js()
    body = _function_body(js, "function applyPortfolioPrivacy()")
    for el in ("portfolioValueEl", "portfolioDayChangeEl",
               "portfolioTotalReturnEl"):
        assert f'{el}.textContent = "****"' in body, \
            f"applyPortfolioPrivacy must mask {el} with asterisks"


# ── Bugfix locks (GUI-verified 2026-09-13) ────────────────────────────
#
# The first round of fixes removed the opacity dim and added the
# privacy-masked class — but the user's GUI re-check proved the two
# symptoms were caused by deeper bugs this file never looked at:
#
#   1. The eye-off SVGs carried inline style="display:none". Inline
#      styles beat ANY CSS selector, so the data-hidden="true" swap
#      rule could never un-hide them — the button rendered EMPTY when
#      privacy was ON (icon "disappears when on", any theme).
#   2. Masked text is far narrower than real numbers. The value row is
#      plain wrapping inline content, so masking changed the wrap point:
#      pills that wrapped below the value jumped up inline with it and
#      everything below shifted (min-height alone preserved HEIGHT, not
#      WIDTH/position).
#   3. refreshPortfolioSummary painted real values unconditionally and
#      the setInterval poll kept calling it — the **** masks silently
#      lifted within one refresh cycle.
#
# These tests fail while the bugs exist and lock the fixes afterwards.

def _function_body(js, signature):
    """Extract a top-level function's text: from its signature line to the
    closing brace at column 0. main.js indents nested braces, so the first
    '\n}' is the function's own end."""
    start = js.find(signature)
    assert start != -1, f"{signature} not found in main.js"
    end = js.find("\n}", start)
    assert end != -1, f"{signature} has no closing brace"
    return js[start:end]


def test_html_eye_off_has_no_inline_display():
    """The eye-off SVGs must NOT carry an inline style="display:none".

    An inline style has higher priority than any stylesheet rule, so the
    swap rule (`.privacy-btn[data-hidden="true"] .privacy-eye-off
    { display: block }`) could never override it. Result: privacy ON hid
    the eye AND left the eye-off hidden — an empty, invisible button.
    Default-hiding is the CSS's job now (base rule + data-hidden rules).
    Each button checked in the file that ships it."""
    portfolio_html = _read_html()
    portfolio_start = portfolio_html.find('id="hide-portfolio-toggle"')
    ledger_html = _read_ledger_html()
    ledger_start = ledger_html.find('id="hide-ledger-toggle"')
    assert portfolio_start != -1 and ledger_start != -1, \
        "privacy buttons not found in their pages"
    portfolio_chunk = portfolio_html[portfolio_start:portfolio_start + 1200]
    ledger_chunk = ledger_html[ledger_start:ledger_start + 1200]
    assert 'style="display:none"' not in portfolio_chunk, \
        "portfolio eye-off SVG must not hide itself with an inline style " \
        "(inline beats the CSS swap rule, so the icon vanishes when ON)"
    assert 'style="display:none"' not in ledger_chunk, \
        "ledger eye-off SVG must not hide itself with an inline style"


def test_css_eye_off_hidden_by_default():
    """style.css must hide .privacy-eye-off with a rule that does NOT
    depend on data-hidden — the safety net that replaces the old inline
    style. Missing attribute or no JS yet: eye shows, eye-off stays
    hidden. data-hidden="true" then swaps them via its higher-specificity
    rule."""
    css = _read_css()
    assert re.search(
        r'\.privacy-btn\s+\.privacy-eye-off\s*\{[^}]*display:\s*none', css), \
        "style.css must hide .privacy-eye-off by default without a " \
        "data-hidden qualifier"


def test_js_mask_persists_across_refresh():
    """refreshPortfolioSummary and setPortfolioUnavailable must skip
    painting while the portfolio header is privacy-masked. ROOT CAUSE:
    the setInterval poll keeps calling refreshPortfolioSummary, which
    painted live numbers unconditionally — the **** masks were silently
    overwritten within one refresh cycle."""
    js = _read_js()
    assert 'function portfolioMasked()' in js, \
        "main.js must define a portfolioMasked() helper reading data-hidden"
    refresh = _function_body(js, "async function refreshPortfolioSummary()")
    assert 'portfolioMasked()' in refresh, \
        "refreshPortfolioSummary must skip painting while privacy-masked " \
        "(the poll would otherwise lift the mask)"
    unavailable = _function_body(js, "function setPortfolioUnavailable(")
    assert 'portfolioMasked()' in unavailable, \
        "setPortfolioUnavailable must not paint over the **** masks either"


def test_js_locks_masked_geometry():
    """applyPortfolioPrivacy must freeze each span's measured box BEFORE
    overwriting the values with ****. ROOT CAUSE: masked text is much
    narrower, so where the real row wrapped onto two lines the masked row
    fit on one — the pills jumped up inline with the value and the
    content below shifted. min-width is ignored on plain inline elements,
    so the value span is also flipped to inline-block while masked.

    UNMASK CONTRACT (GUI-verified 2026-09-13): applyPortfolioPrivacy must
    NOT release the locks on unmask — the fresh values are still a fetch
    away, so releasing early lets the still-painted **** collapse to its
    natural (tiny) width: the row jumps narrow, then snaps back when the
    data lands. The locks must ride along and be released ONLY after the
    real content is painted, inside refreshPortfolioSummary, so the
    transition renders as one layout pass."""
    js = _read_js()
    body = _function_body(js, "function applyPortfolioPrivacy()")
    assert 'offsetWidth' in body and 'offsetHeight' in body, \
        "applyPortfolioPrivacy must measure the real boxes before masking"
    assert 'minWidth' in body and 'minHeight' in body, \
        "applyPortfolioPrivacy must lock min-width/min-height while masked"
    assert 'inline-block' in body, \
        "the value span must flip to inline-block or min-width is ignored"
    assert 'style.minWidth = ""' not in body, \
        "unmask must NOT release the geometry locks early — the repaint " \
        "releases them after real values are painted back"
    refresh = _function_body(js, "async function refreshPortfolioSummary()")
    assert 'clearPortfolioGeometryLocks()' in refresh, \
        "refreshPortfolioSummary must release the locks right after " \
        "painting real values"
    unavailable = _function_body(js, "function setPortfolioUnavailable(")
    assert 'clearPortfolioGeometryLocks()' in unavailable, \
        "setPortfolioUnavailable must release the locks after painting the " \
        "degraded '—'"
    assert 'function clearPortfolioGeometryLocks()' in js, \
        "main.js must define a clearPortfolioGeometryLocks() helper"
    helper = _function_body(js, "function clearPortfolioGeometryLocks()")
    assert 'style.minWidth = ""' in helper, \
        "clearPortfolioGeometryLocks must clear the inline min-width locks"
    assert 'privacy-masked' in helper, \
        "clearPortfolioGeometryLocks must strip the privacy-masked class " \
        "(paintChange only toggles pos/neg, it never removes it)"


def test_js_unmask_restores_cached_values_instantly():
    """Unmasking must repaint the header from a mask-time snapshot, NOT
    wait for the fetch. ROOT CAUSE (GUI-reported): hide was instant (pure
    local DOM swap) but show waited for refreshPortfolioSummary's fetch
    (~1s), because while masked the refresh cycle is guard-skipped and the
    frontend keeps no copy of values it isn't displaying. applyPortfolioPrivacy
    must therefore snapshot the three spans' real content at mask time and
    repaint it from memory on unmask — in the same JS turn as the lock
    release — letting the background refresh swap in fresh numbers after.
    The snapshot is only usable when real values were on screen (masked
    before the first fetch landed = nothing to restore)."""
    js = _read_js()
    assert 'let lastPortfolioPaint = null' in js, \
        "main.js must declare a lastPortfolioPaint cache for instant unmask"
    body = _function_body(js, "function applyPortfolioPrivacy()")
    assert 'lastPortfolioPaint' in body, \
        "applyPortfolioPrivacy must capture values at mask time and " \
        "repaint them on unmask"
    assert 'lastPortfolioPaint.value' in body, \
        "unmask must paint the cached values back instantly"
    assert 'lastPortfolioPaint = null' in body, \
        "the cache must be consumed (nulled) on unmask"
