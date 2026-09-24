# tests/test_market_tabs.py
# =========================
# Contracts for the tabbed market overview that sits ABOVE the portfolio.
#
# Three layers, three test styles (pytest cannot run a browser):
#   1. RENDERED HTML (client fixture) — tabs, panels, links, ARIA ids:
#      what the browser actually receives from Flask.
#   2. JS SOURCE/META — main.js's market block, extracted between BEGIN/
#      END markers: category fetching, race tokens, keyboard handling,
#      adaptive precision. String checks on the source text.
#   3. CSS SOURCE — style.css's market rules: grid, phone layout, focus.
#      Comments are stripped first so teaching prose can't satisfy a rule.

import html as html_mod
import re
from pathlib import Path

import app as app_module

ROOT = Path(__file__).resolve().parent.parent
MAIN_JS = (ROOT / "static" / "js" / "main.js").read_text()
COMMON_JS = (ROOT / "static" / "js" / "common.js").read_text()
STYLE_CSS = (ROOT / "static" / "style.css").read_text()


# ── Extraction helpers ────────────────────────────────────────────────

def _strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def market_section(html: str) -> str:
    """The rendered <section class="market-overview">...</section>, with
    HTML comments removed and entities unescaped so label assertions see
    the text a reader sees (S&P, not S&amp;P)."""
    html = _strip_comments(html)
    start = html.index('<section class="market-overview"')
    end = html.index("</section>", start)
    return html_mod.unescape(html[start:end + len("</section>")])


def market_js() -> str:
    """The market-overview block of main.js between its BEGIN/END markers."""
    start = MAIN_JS.index("// MARKET OVERVIEW BEGIN")
    end = MAIN_JS.index("// MARKET OVERVIEW END")
    return MAIN_JS[start:end]


def _css_no_comments() -> str:
    return re.sub(r"/\*.*?\*/", "", STYLE_CSS, flags=re.S)


def _body_for(container: str, selector: str):
    """Declaration body of the first rule whose comma-separated selector
    list contains `selector` exactly, else None. Exact part matching
    keeps `.market-item` from matching `.market-item-price`."""
    for m in re.finditer(r"([^{}]+)\{([^}]*)\}", container):
        parts = [p.strip() for p in m.group(1).split(",")]
        if selector in parts:
            return m.group(2)
    return None


def css_body(selector: str) -> str:
    body = _body_for(_css_no_comments(), selector)
    assert body is not None, f"no CSS rule selects {selector!r}"
    return body


def _media_blocks(css: str, max_width: str):
    """Every @media (max-width: <max_width>) block's inner text, found by
    brace-depth counting so nested rules stay intact."""
    blocks = []
    for m in re.finditer(
        r"@media\s*\(max-width:\s*" + re.escape(max_width) + r"\)\s*\{", css
    ):
        start, depth, i = m.end(), 1, m.end()
        while depth > 0:
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        blocks.append(css[start:i - 1])
    return blocks


def media_body(max_width: str, selector: str):
    """Declaration body of `selector` inside SOME max-width media block,
    else None. The market phone rules live in their own block, so this
    scans every block of that width."""
    for block in _media_blocks(_css_no_comments(), max_width):
        body = _body_for(block, selector)
        if body is not None:
            return body
    return None


# ═══ 1. RENDERED TEMPLATE + ACCESSIBILITY ════════════════════════════

def test_market_overview_precedes_whole_portfolio(client):
    """The market snapshot must read FIRST — before the 'Your Portfolio'
    headline and every portfolio value — so it frames the page as outside
    market context, not as chart or portfolio metadata."""
    html = _strip_comments(client.get("/").get_data(as_text=True))
    market_at = html.index('class="market-overview"')
    portfolio_at = html.index("Your Portfolio")
    value_at = html.index('id="portfolio-value"')
    assert market_at < portfolio_at < value_at


def test_market_heading_and_live_label(client):
    section = market_section(client.get("/").get_data(as_text=True))
    assert "Markets today" in section
    assert "Live" in section


def test_six_tabs_in_approved_order(client):
    section = market_section(client.get("/").get_data(as_text=True))
    tab_tags = re.findall(r"<button[^>]*role=\"tab\"[^>]*>", section)
    assert len(tab_tags) == 6, "market overview must render six category tabs"
    keys = [re.search(r'data-category="([^"]+)"', t).group(1) for t in tab_tags]
    assert keys == [
        "north-america", "europe", "asia-pacific",
        "crypto", "commodities", "currencies",
    ]


def test_tab_labels_match_configuration(client):
    section = market_section(client.get("/").get_data(as_text=True))
    start = section.index('role="tablist"')
    tablist = section[start:section.index("</div>", start)]
    labels = re.findall(r"</button>", tablist)
    assert len(labels) == 6
    for key, cat in app_module.MARKET_CATEGORIES.items():
        assert f'data-category="{key}"' in tablist
        assert cat["label"] in tablist


def test_north_america_selected_initially(client):
    section = market_section(client.get("/").get_data(as_text=True))
    for tag in re.findall(r"<button[^>]*role=\"tab\"[^>]*>", section):
        key = re.search(r'data-category="([^"]+)"', tag).group(1)
        if key == "north-america":
            assert 'aria-selected="true"' in tag
            assert 'tabindex="0"' in tag
        else:
            assert 'aria-selected="false"' in tag
            assert 'tabindex="-1"' in tag


def test_aria_id_pairs_are_reciprocal(client):
    section = market_section(client.get("/").get_data(as_text=True))
    ids = set(re.findall(r'\bid="([^"]+)"', section))
    controls = re.findall(r'aria-controls="([^"]+)"', section)
    labelledby = re.findall(r'aria-labelledby="([^"]+)"', section)
    assert len(controls) == 6, "every tab must point at a panel"
    assert len(labelledby) >= 7, "section heading + six panels label back"
    for ref in controls + labelledby:
        assert ref in ids, f"aria reference {ref!r} has no matching id"


def test_panels_visibility_initial(client):
    section = market_section(client.get("/").get_data(as_text=True))
    panels = re.findall(r"<div[^>]*role=\"tabpanel\"[^>]*>", section)
    assert len(panels) == 6, "market overview must render six panels"
    for tag in panels:
        key = re.search(r'data-category="([^"]+)"', tag).group(1)
        if key == "north-america":
            assert "hidden" not in tag, "default panel must start visible"
        else:
            assert "hidden" in tag, "inactive panels must start hidden"


def test_every_configured_symbol_is_a_market_item(client):
    section = market_section(client.get("/").get_data(as_text=True))
    expected = {
        inst["symbol"]
        for cat in app_module.MARKET_CATEGORIES.values()
        for inst in cat["instruments"]
    }
    item_tags = [t for t in re.findall(r"<a\s[^>]*>", section) if "market-item" in t]
    found = {re.search(r'data-symbol="([^"]+)"', t).group(1) for t in item_tags}
    assert found == expected, "every configured symbol needs one market item"


def test_item_labels_present(client):
    section = market_section(client.get("/").get_data(as_text=True))
    for cat in app_module.MARKET_CATEGORIES.values():
        for inst in cat["instruments"]:
            assert inst["label"] in section, f"missing label {inst['label']!r}"


def test_price_and_change_spans_ship_empty(client):
    section = market_section(client.get("/").get_data(as_text=True))
    prices = re.findall(r'<span class="market-item-price">([^<]*)</span>', section)
    changes = re.findall(r'<span class="market-item-change[^"]*">([^<]*)</span>', section)
    assert prices and changes, "every market item needs empty price/change spans"
    assert all(p == "" for p in prices), "prices must ship empty (no mock numbers)"
    assert all(c == "" for c in changes), "changes must ship empty (no mock numbers)"


def test_currencies_caption_only_in_currencies_panel(client):
    section = market_section(client.get("/").get_data(as_text=True))
    assert section.count("1 CAD buys") == 1, "exactly one currency caption"
    assert "1 CAD buys" in section[section.index('data-category="currencies"'):]


def test_no_market_breadth_language(client):
    section = market_section(client.get("/").get_data(as_text=True)).lower()
    for phrase in ("higher", "lower", "of 4", "of 5", "of 6", "breadth"):
        assert phrase not in section, f"market overview must not claim {phrase!r}"


def test_market_items_are_plain_anchors(client):
    section = market_section(client.get("/").get_data(as_text=True))
    tags = re.findall(r"<(\w+)[^>]*data-symbol=\"", section)
    assert set(tags) == {"a"}, "market items must stay real anchors, not buttons"


def test_tabs_are_type_button(client):
    section = market_section(client.get("/").get_data(as_text=True))
    for tag in re.findall(r"<button[^>]*role=\"tab\"[^>]*>", section):
        assert 'type="button"' in tag, "tabs must not submit a future form"


def test_first_tab_ships_selected_pill_class(client):
    """CSS paints the selected pill ONLY from `.market-tab.active`, and
    main.js adds that class on click alone — so a fresh load would show the
    default tab unselected unless the template emits the class too."""
    section = market_section(client.get("/").get_data(as_text=True))
    tabs = re.findall(r"<button[^>]*role=\"tab\"[^>]*>", section)
    assert len(tabs) == len(app_module.MARKET_CATEGORIES)
    assert 'class="market-tab active"' in tabs[0], (
        "the default tab must ship already painted as selected"
    )
    for tag in tabs[1:]:
        assert 'class="market-tab active"' not in tag, (
            "only the default tab ships active on a fresh load"
        )


def test_odd_category_has_no_grid_filler():
    """Phones now show ONE scrolling row, so there is no empty grid cell to
    plug. The odd-count filler class must be gone from both the template and
    the stylesheet."""
    assert "market-grid-filler" not in STYLE_CSS, (
        "the filler's CSS must be removed with the two-column phone grid"
    )
    template = (ROOT / "templates" / "index.html").read_text()
    assert "market-grid-filler" not in template, (
        "the template must stop emitting a filler that no layout needs"
    )


# ═══ 2. FRONTEND BEHAVIOR (JS SOURCE/META) ═══════════════════════════

def test_market_js_block_exists_with_markers():
    js = market_js()
    assert "MARKET OVERVIEW BEGIN" in MAIN_JS
    assert "MARKET OVERVIEW END" in MAIN_JS
    assert len(js) > 0


def test_market_js_reads_active_category_not_flat_list():
    js = market_js()
    assert "activeMarketCategory" in js, "must track which tab is active"
    assert "data-category" in js, "active category comes from the tab"


def test_market_js_sends_category_query():
    js = market_js()
    assert "category=" in js, "API request must name the selected category"
    assert "/api/indices" in js


def test_market_js_scopes_managed_items_to_panel():
    js = market_js()
    assert "managedMarketItems" in js, "items must be scoped to a panel"
    assert "querySelectorAll" in js
    assert ".market-item[data-symbol]" in js


def test_market_js_paints_by_data_symbol():
    js = market_js()
    assert 'data-symbol="' in js, "response must paint each item by its symbol"


def test_market_js_gap_fills_unanswered_symbols():
    js = market_js()
    assert '"—"' in js, "unanswered symbols degrade to an em dash"
    assert "answered" in js, "gap-fill tracks which symbols responded"


def test_market_js_gap_fill_marks_both_rows_unavailable():
    """:empty IS the loading skeleton. If a failed symbol degraded only its
    level row, its change row would stay empty and shimmer forever — the
    exact "skeleton outlives the data" bug the shimmer block forbids."""
    js = market_js()
    block = js[js.index("const answered"):]
    block = block[: block.index("} catch")]
    assert '".market-item-price").textContent = "—"' in block, (
        "a failed symbol's level row must show —"
    )
    assert 'changeEl.textContent = "—"' in block, (
        "a failed symbol's change row must show —, not stay empty"
    )
    assert 'classList.remove("pos", "neg")' in block, (
        "a degraded cell must not keep the template's green .pos"
    )


def test_market_js_panel_placeholder_covers_change_row_and_color():
    """setMarketPanelValues drives BOTH placeholder states: "" while loading
    and "—" for a category-wide failure (503 / network error). It must write
    the SAME text to the change row as to the level row, or every change row
    shimmers until the next successful poll."""
    js = market_js()
    fn = js[js.index("function setMarketPanelValues"):]
    fn = fn[: fn.index("\n}")]
    assert 'changeEl.textContent = text' in fn, (
        "the change row must take the same placeholder as the level row"
    )
    assert 'classList.remove("pos", "neg")' in fn, (
        "a placeholder is not a move — clear pos/neg so a degraded "
        "cell cannot paint its em dash green"
    )


def test_market_js_race_token_guards_stale_responses():
    js = market_js()
    assert "marketRequestTokens" in js, "per-category request tokens required"
    assert "requestToken" in js
    assert js.count("marketRequestTokens") >= 2, "token must be both set and checked"


def test_market_js_activation_syncs_aria_and_hidden():
    js = market_js()
    assert "aria-selected" in js, "activation must update aria-selected"
    assert "tabIndex" in js, "activation must move roving tabindex"
    assert ".hidden =" in js or "hidden =" in js, "activation must show/hide panels"


def test_market_js_handles_arrow_home_end_keys():
    js = market_js()
    for key in ("ArrowLeft", "ArrowRight", "Home", "End"):
        assert key in js, f"keyboard handler must respond to {key}"


def test_market_js_arrow_navigation_wraps():
    js = market_js()
    assert "% tabs.length" in js, "arrow navigation must wrap at both ends"


def test_market_js_tab_click_triggers_immediate_refresh():
    js = market_js()
    assert "activateMarketTab" in js
    assert "refreshMarketOverview(category)" in js or "refreshMarketOverview(" in js


def test_market_js_boot_preloads_all_categories_in_parallel():
    boot = MAIN_JS[MAIN_JS.index("// BOOT — the script's entry point."):]
    js = market_js()
    assert "preloadMarketOverview()" in boot, "boot must start all market requests"
    assert boot.index("preloadMarketOverview()") < boot.index("refreshWatchlist()")
    assert "function preloadMarketOverview()" in js
    preload = js.split("function preloadMarketOverview()", 1)[1].split("\n}", 1)[0]
    assert 'document.querySelectorAll(".market-tab")' in preload
    assert "refreshMarketOverview(" in preload
    assert "await " not in preload, "requests must start without waiting for another tab"
    assert "refreshIndices" not in MAIN_JS, "old flat indices fetch must be gone"


def test_market_js_boot_wires_tab_handlers():
    """Defining setupMarketTabs is not enough — boot must CALL it, or the
    tabs never receive their click/keyboard listeners."""
    boot = MAIN_JS[MAIN_JS.index("// MARKET OVERVIEW END"):]
    assert "setupMarketTabs()" in boot, "boot must wire the tab handlers"


def test_market_js_polls_active_category_only():
    start = MAIN_JS.index("setupAutoRefresh(() =>")
    callback = MAIN_JS[start:]
    assert "refreshMarketOverview(activeMarketCategory, { force: true })" in callback, (
        "poll must refresh only the active market, even while cached"
    )
    assert "refreshIndices" not in callback


def test_market_js_adds_no_raw_setinterval():
    assert "setInterval" not in MAIN_JS, "polling stays with setupAutoRefresh"


def test_market_js_does_not_persist_active_tab():
    js = market_js()
    assert "localStorage" not in js, "active tab must not persist to localStorage"
    assert "sessionStorage" not in js, "active tab must not persist to sessionStorage"


def test_market_js_adaptive_precision_below_one_uses_four():
    js = market_js()
    assert "formatMarketLevel" in js, "market levels need their own formatter"
    assert "Math.abs(value) < 1" in js, "sub-unit values (FX) need more precision"
    assert "? 4 : 2" in js, "four decimals below 1, two otherwise"


def test_market_js_percentage_keeps_two_decimals():
    js = market_js()
    assert "change_pct.toFixed(2)" in js, "percent change stays two decimals"


def test_market_js_zero_change_is_positive():
    js = market_js()
    assert "quote.change >= 0" in js, "zero counts as positive, as before"


def test_market_js_toggles_pos_neg_classes():
    js = market_js()
    assert 'classList.toggle("pos"' in js, "JS paints up/down via .pos/.neg"
    assert 'classList.toggle("neg"' in js


def test_market_js_tab_switch_isolated_from_other_refreshes():
    js = market_js()
    for other in (
        "refreshPortfolioSummary", "refreshWatchlist", "refreshVolumeLeaders",
        "refreshPortfolioChart", "fetchAllocDimension",
    ):
        assert other not in js, f"market tab switching must not call {other}"


def test_common_formatPrice_stays_two_decimals():
    """Guard: the shared money formatter must NOT be widened to four
    decimals — portfolio/ledger/stock money stays two. Only the market
    block gets adaptive precision."""
    m = re.search(r"function formatPrice\(value\) \{.*?\}", COMMON_JS, re.S)
    assert m, "common.js must keep formatPrice"
    body = m.group(0)
    assert "minimumFractionDigits: 2" in body
    assert "maximumFractionDigits: 2" in body


# ═══ 3. CSS + RESPONSIVE ═════════════════════════════════════════════

def test_market_grid_uses_dynamic_column_tracks():
    """Equal tracks driven by the panel's own item count — a fixed
    repeat(4, ...) would break the five-instrument Asia-Pacific tab."""
    body = css_body(".market-grid")
    assert "grid-template-columns" in body
    assert "repeat(4" not in body and "repeat(5" not in body, (
        "column count must not be hard-coded to one category's size"
    )
    assert "var(--market-cols" in body or "auto" in body


def test_market_panel_is_one_card():
    body = css_body(".market-panel")
    assert "border" in body and "background" in body
    assert "border-radius" in body and "box-shadow" in body


def test_market_items_have_no_individual_shadow():
    body = css_body(".market-item")
    assert "box-shadow" not in body, (
        "cells are divided parts of one strip, not separate SaaS cards"
    )


def test_market_figures_use_tabular_numerals():
    price = css_body(".market-item-price")
    change = css_body(".market-item-change")
    assert "tabular-nums" in price
    assert "tabular-nums" in change


def test_market_change_colors_come_from_theme_tokens():
    """Market up/down reuses the app-wide .pos/.neg ink (green/red stay a
    monopoly), which must read theme tokens so dark mode recolors for free."""
    assert "var(--green-pos)" in css_body(".pos")
    assert "var(--red-neg)" in css_body(".neg")


def test_market_items_have_visible_focus():
    body = css_body(".market-item:focus-visible")
    assert "outline" in body or "box-shadow" in body


def test_market_labels_do_not_force_page_overflow():
    body = css_body(".market-item-label")
    assert "min-width: 0" in body
    assert "overflow" in body and "ellipsis" in body


def test_market_phone_instruments_scroll_in_one_row():
    body = media_body("600px", ".market-grid")
    assert body is not None, "phone media query must style .market-grid"
    assert "display: flex" in body, (
        "the phone strip is one flex row, not a two-column grid"
    )
    assert "overflow-x" in body and "auto" in body, (
        "the phone strip scrolls sideways"
    )
    assert "grid-template-columns" not in body, (
        "the two-column phone grid is gone"
    )

    item = media_body("600px", ".market-item")
    assert item is not None and "flex: 0 0 auto" in item, (
        "each chip keeps its natural width and the row scrolls"
    )


def test_market_phone_tabs_scroll_plainly():
    body = media_body("600px", ".market-tabs")
    assert body is not None, "phone media query must style .market-tabs"
    assert "overflow-x" in body and "auto" in body
    assert "scroll-snap" not in body, "scroll-snap caused Android tab-bar jitter"
    assert "-webkit-overflow-scrolling" not in body, (
        "legacy momentum hint made the fixed bottom tab bar vanish"
    )


def test_market_tab_scrollbars_hidden_but_scroll_enabled():
    body = css_body(".market-tabs")
    assert "overflow-x" in body and "auto" in body
    assert "scrollbar-width" in body and "none" in body


def test_market_reduced_motion_freezes_skeleton():
    reduced = None
    css = _css_no_comments()
    m = re.search(r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{", css)
    assert m, "reduced-motion block required"
    start, depth, i = m.end(), 1, m.end()
    while depth > 0:
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
        i += 1
    reduced = css[start:i - 1]
    assert ".market-item-price" in reduced, (
        "market loading shimmer must freeze under reduced motion"
    )
    assert "animation: none" in reduced


# ═══ 4. PHONE REDESIGN (mobile-only market strip) ═══════════════════════
# The strip stays first on the page, but on phones its presentation is
# corrected: the pill rail becomes a flat underlined rail, the header goes
# quiet, and each category's instruments become ONE horizontal scrolling row
# of flat divided chips. Every assertion reads the ≤600px block, so a base
# (desktop) rule can never satisfy it.

def test_market_phone_header_is_quiet():
    heading = media_body("600px", ".market-header h2")
    assert heading is not None, "phone block must shrink the market heading"
    assert "font-size: 18px" in heading

    live = media_body("600px", ".market-live")
    assert live is not None, "phone block must hide the Live badge"
    assert "display: none" in live


def test_market_phone_tabs_are_underlined_not_pills():
    body = media_body("600px", ".market-tab")
    assert body is not None, "phone block must style .market-tab"
    assert "border-radius: 0" in body, "phone tabs drop the pill radius"
    assert "border-bottom" in body and "transparent" in body, (
        "phone tabs reserve a transparent underline track"
    )
    assert "999px" not in body, "phone tabs must not keep the pill radius"


def test_market_phone_active_tab_underlines_with_accent():
    active = media_body("600px", ".market-tab.active")
    assert active is not None, "phone block must style the active tab"
    assert "var(--accent)" in active, "active underline wears the accent"
    assert "background: transparent" in active, (
        "active tab drops the accent fill on phones"
    )

    tabs = media_body("600px", ".market-tabs")
    assert tabs is not None
    assert "scroll-snap" not in tabs, "scroll-snap caused Android tab-bar jitter"
    assert "-webkit-overflow-scrolling" not in tabs, (
        "legacy momentum hint made the fixed bottom tab bar vanish"
    )


def test_market_phone_panel_is_flat():
    body = media_body("600px", ".market-panel")
    assert body is not None, "phone block must flatten the market panel"
    assert "box-shadow: none" in body
