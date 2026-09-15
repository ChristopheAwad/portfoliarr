# Bug fix: Nav buttons to Ledger/Portfolio disappear on stock detail page

Status: **COMPLETE — merged via PR #39** (`stock-page-bottom-tabs`).

## The bug

On `/stock/<symbol>` the bottom tab bar (Dashboard + Ledger nav) is absent —
the only ways out are the logo or the search box.

**Root cause:** the tab bar is opt-in per page.
- `base.html` has an empty `{% block bottom_tabs %}` hole before `</body>`;
  pages that fill it get the bar, pages that don't get nothing.
- `index.html` and `ledger.html` fill the block (they `{% set tab_active = 'dashboard' | 'ledger' %}`
  then `{% include '_bottom_tabs.html' %}`) AND stamp `class="has-bottom-tabs"`
  on `<body>` via the `body_attrs` block.
- `stock.html` fills **neither** block. base.html's comment even documents the
  old design: "stock detail and preferences don't" — that opt-out is now
  considered the bug.

The `has-bottom-tabs` body class is not cosmetic: `style.css` uses it for
`.has-bottom-tabs .container { padding-bottom: 72px }` (so content doesn't
hide behind the fixed 56px bar) and `.has-bottom-tabs #toast-container
{ bottom: 72px }` (toasts lift above the bar). Both come free with the class.

## User decisions (asked & answered)

1. **Preferences page:** stays tabs-free — fix only the stock detail page.
2. **Active tab on stock pages:** neither tab lights up. A stock page is
   neither Dashboard nor Ledger; tabs highlight their own page only
   (`tab_active = ''` → no `active` class, no `aria-current`).

## The fix — as shipped (actual edits differed slightly from the plan)

0. **Same-root-cause glue bug (discovered during implementation):**
   `base.html` renders `<body{% block body_attrs %}` with NO space, so the
   block MUST carry a leading space. index.html/ledger.html shipped
   `<bodyclass="has-bottom-tabs">` (bogus tag name — cosmetically lost the
   padding/toast offsets); stock.html's `data-symbol` was functionally
   required by stock.js, so the glue bug was FATAL there (blank page).
   All three templates got the leading-space fix, and the tests lock the
   EXACT well-formed body tag (a substring check can't catch the glue bug).

1. **`templates/stock.html`**
   - `body_attrs` block becomes:
     `{% block body_attrs %} class="has-bottom-tabs" data-symbol="{{ symbol }}"{% endblock %}`
     — leading space preserved, keeps stock.js's `data-symbol` identity hook,
     adds the tab-bar class.
   - `{% block bottom_tabs %}{% set tab_active = '' %}{% include '_bottom_tabs.html' %}{% endblock %}`
     (empty `tab_active` = neither tab active).

2. **`templates/index.html` + `templates/ledger.html`** — leading space in
   `body_attrs`: ` class="has-bottom-tabs"`.

3. **`templates/base.html`** + **`static/style.css`** + **`_bottom_tabs.html`**
   — stale comments updated (stock detail now opts in; partial lists all
   three includers).

4. **`tests/test_stock.py`** — `test_stock_page_ships_bottom_tab_bar`: both
   tabs render (scraped from the `.bottom-tabs` nav, so the hrefs bind to
   the bar, not the navbar logo), neither tab active / `aria-current`, and
   the EXACT well-formed `<body>` tag.

5. **`tests/test_ui_redesign.py`** — `test_tabbed_pages_ship_well_formed_body_tag`:
   `/` and `/ledger` render the exact `<body class="has-bottom-tabs">` tag.

## Why no CSS changes are needed

- Modal overlay (`z-index: 300`) already sits above the tab bar (`z-index: 100`).
- Padding + toast offsets come free from `has-bottom-tabs`.
- No existing test locked the old "no tabs on stock page" behavior (grep
  confirmed), so nothing to un-lock.

## Workflow gates

- [x] Full `python -m pytest` green (438 passed).
- [x] GUI check by user (stock page renders + tab bar; Dashboard/Ledger
      padding + toasts restored).
- [x] Commit only on explicit user yes.
- [x] PR #39 opened, reviewed (approve, 3 nits all fixed), merged.
