# Bug fix: Nav buttons to Ledger/Portfolio disappear on stock detail page

Status: **PLAN APPROVED — NOT YET IMPLEMENTED** (user said write the plan, don't implement yet).

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

## The fix — 4 files, no CSS changes

1. **`templates/stock.html`**
   - `body_attrs` block (line ~16) becomes:
     `{% block body_attrs %}class="has-bottom-tabs" data-symbol="{{ symbol }}"{% endblock %}`
     — keeps stock.js's `data-symbol` identity hook, adds the tab-bar class.
   - Add after the `content` block's `{% endblock %}`:
     `{% block bottom_tabs %}{% set tab_active = '' %}{% include '_bottom_tabs.html' %}{% endblock %}`
     with a short teaching comment (empty `tab_active` = neither tab active).

2. **`templates/base.html`** (~lines 182-183) — comment currently says
   "Dashboard and Ledger opt in; stock detail and preferences don't." Update
   to "Dashboard, Ledger, and stock detail opt in; preferences doesn't."
   (Comments must not lie.)

3. **`static/style.css`** (~lines 208-211) — same stale sentence in the
   `.bottom-tabs` comment; update identically.

4. **`tests/test_stock.py`** — new rendered-HTML test (matches the file's
   existing `client.get("/stock/aapl")` style):
   - both bottom tabs render: `href="/"` labeled Dashboard, `href="/ledger"`
     labeled Ledger;
   - NEITHER tab carries the `active` class or `aria-current="page"`;
   - `<body>` tag still carries `data-symbol="AAPL"` AND now carries
     `class="has-bottom-tabs"`.

## Why no CSS changes are needed

- Modal overlay (`z-index: 300`) already sits above the tab bar (`z-index: 100`).
- Padding + toast offsets come free from `has-bottom-tabs`.
- No existing test locks the old "no tabs on stock page" behavior (grep
  confirmed), so nothing to un-lock.

## Test plan (pytest)

Single new test in `tests/test_stock.py` (e.g.
`test_stock_page_ships_bottom_tab_bar`), assertions as listed in file 4
above. Must fail before the template edits, pass after. Full suite green:
`python -m pytest`.

## Workflow gates after implementation

- [ ] Full `python -m pytest` green.
- [ ] GUI check by user (stock page shows tabs; tabs still active-correct on
      Dashboard and Ledger; toasts on stock page sit above the bar).
- [ ] Commit only on explicit user yes.
