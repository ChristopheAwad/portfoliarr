# Design Fix: Phone Market Strip ("Markets today") — one scrolling row

## Status

SHIPPING 2026-09-22 (PR #73). Phone-only redesign of the market strip shipped
in PR #70. Revision 1 stacked phone cells into three lines ("double row"). The
user rejected revision 2 (2-column, one-line cells) too: the approved phone
layout is ONE HORIZONTAL SCROLLING ROW of instruments per category, like the
pre-#70 index chips. No roadmap item: it is a design correction.

Verification: implementation complete; full `python -m pytest` is 894 passed;
focused `python -m pytest tests/test_market_tabs.py` is 55 passed. GUI approved
by the user (they said "Push pr"). The `static/js/main.js` currency-span revert
(Step 2) turned out to be a no-op — main.js already matched the target.

## User Goal

The user dislikes the market strip on phones. The strip MUST stay the first thing
on the page (pinned by `project-brief.md` and `tests/test_market_tabs.py`). Fix
the phone presentation only. Desktop and tablet must stay byte-identical.

Approved phone layout: each category's instruments are one HORIZONTAL SCROLLING
ROW of flat divided chips. Each chip is as wide as its content, so names are
never truncated and nothing is hidden.

```
Markets today
[North America] Europe  Asia-Pacific  ...        <- underlined rail (scrolls)
┌────────────────────────────────────────────────────┐
│ S&P 500   7,650.50 USD │ Nasdaq 26,522.54 USD │ →  │
│ +12.74 (+0.17%)        │ +104.24 (+0.39%)      │    │
└────────────────────────────────────────────────────┘
```

## Approved Decisions

1. Phone tab rail: flat underlined rail. Active tab underlines with
   `var(--accent)` and drops the accent fill.
2. Phone header: `.market-header h2` shrinks to 18px; `.market-live` hidden on
   phones (stays in the HTML, so `test_market_heading_and_live_label` passes).
3. Phone panel: no box shadow; padding 6px.
4. Phone instrument row: `.market-grid` becomes a non-wrapping horizontal scroll
   container (`display: flex`), each `.market-item` `flex: 0 0 auto`. Hairlines
   are drawn per-pair (`.market-item + .market-item { border-left: 1px solid
   var(--border-color); }`) with the base gap/background dropped — a border-
   coloured background gap would paint a grey tail after the last chip when the
   row is narrower than the panel.
5. The odd-count `.market-grid-filler` is DELETED (template + CSS + tests). It
   only plugged the empty cell of the old 2-column phone grid; a scrolling row
   has no empty cell.
6. The `main.js` currency-span change from revision 2 is REVERTED. Natural-width
   chips have room, so the price goes back to one text run with its native
   currency.
7. `project-brief.md` gains a note that phones use a one-row scrolling strip,
   overriding the PR #70 "two-column instrument grid on phones" language.

## Implementation Steps (test-first)

### Step 1 — Update tests (write first; they must fail before code edits)

In `tests/test_market_tabs.py`:

- KEEP `test_market_phone_header_is_quiet`.
- KEEP `test_market_phone_tabs_are_underlined_not_pills`.
- KEEP `test_market_phone_active_tab_underlines_with_accent`.
- KEEP `test_market_phone_panel_is_flat`.
- DELETE `test_market_phone_cells_are_single_line`.
- DELETE `test_market_phone_labels_truncate_on_one_line`.
- DELETE `test_market_js_wraps_currency_in_hideable_span`.
- DELETE `test_market_phone_last_item_does_not_span_two_columns`.
- REPLACE `test_market_phone_grid_is_two_columns` with
  `test_market_phone_instruments_scroll_in_one_row`:
  - `media_body("600px", ".market-grid")` is not None.
  - It contains `display: flex` and `overflow-x: auto`.
  - It does NOT contain `grid-template-columns`.
  - `media_body("600px", ".market-item")` contains `flex: 0 0 auto`.
- REPLACE `test_odd_category_ships_phone_grid_filler` with
  `test_odd_category_has_no_grid_filler`:
  - `"market-grid-filler"` not in `STYLE_CSS`.
  - `"market-grid-filler"` not in `(ROOT / "templates" / "index.html").read_text()`.

Also update the section header comment above the phone-redesign tests to say
"one horizontal scrolling row".

Run `python -m pytest tests/test_market_tabs.py -k phone` and confirm the
intended failures (old grid rule present, filler still present), not syntax
errors.

### Step 2 — `static/js/main.js`

Revert the revision-2 currency span. In `updateMarketItem` replace:
```js
priceEl.replaceChildren(
    document.createTextNode(formatMarketLevel(quote.price)),
    marketTextSpan("market-item-ccy", ` ${quote.currency}`)
);
```
with:
```js
priceEl.textContent = `${formatMarketLevel(quote.price)} ${quote.currency}`;
```
and restore the original teaching comment:
```js
// textContent (never innerHTML): plain text, immune to HTML injection.
// Every price carries its native currency code — native display, no FX.
```

DONE status: this edit was already satisfied when the branch was created —
`static/js/main.js:94` already used `textContent` with the original comment, so
main.js has NO net change in this PR (kept out of the commit).

### Step 3 — `templates/index.html`

Remove the odd-count filler block (the `{% if cat['instruments']|length % 2 == 1 %}`
block containing `<span class="market-grid-filler" aria-hidden="true"></span>`)
and adjust the surrounding comment so the grid comment no longer mentions a
phone 2-column grid.

### Step 4 — `static/style.css`

In the `@media (max-width: 600px)` market block:

- REPLACE `.market-grid { grid-template-columns: 1fr 1fr; }` with:
  ```css
  .market-grid {
      display: flex;
      flex-wrap: nowrap;
      overflow-x: auto;
      scrollbar-width: none;
  }

  .market-grid::-webkit-scrollbar {
      display: none;
  }
  ```
- REPLACE `.market-item { padding: 12px 10px; }` with:
  ```css
  .market-item {
      flex: 0 0 auto;
      padding: 10px 12px;
  }
  ```
- DELETE the phone `.market-item-top`, `.market-item-label`,
  `.market-item-price`, `.market-item-change`, `.market-item-ccy`, and
  `.market-item-move` rules added in revision 2.
- DELETE the phone `.market-grid-filler` rule.
- KEEP `.market-panel`, `.market-header h2`, `.market-live`, `.market-tab`,
  `.market-tab.active`, `.market-tabs`.

In the BASE (desktop) rules, DELETE the `.market-grid-filler { display: none; }`
rule (the class no longer exists).

Update comments: the phone market block comment must describe the one-row
scrolling strip; the base `.market-grid` comment must drop the filler mention.

### Step 5 — `project-brief.md`

In the `Markets today` dashboard bullet, change the phone clause from a
two-column grid to one horizontal scrolling row of chips.

### Step 6 — Verify

1. `source .venv/bin/activate`
2. `python -m pytest tests/test_market_tabs.py` (all green).
3. `python -m pytest` (full suite green; previously 898 passed).
4. `python -m pytest tests/test_docker.py` is unaffected but run it once if any
   container file changed (it did not).
5. STOP. Ask the user to open the dashboard at phone width and approve the GUI
   before any commit.

## Out Of Scope

- Do not move the strip below the portfolio.
- Do not change the desktop grid (one equal track per instrument).
- Do not remove the "Live" text from the template; hide it with CSS only.
- Do not add scroll fades, snap, or new motion.
- Do not touch `app.py`.

## Files

`static/style.css`, `templates/index.html`, `project-brief.md`,
`tests/test_market_tabs.py`, `feature.md`. (`static/js/main.js` has no net
change; see Step 2.)
