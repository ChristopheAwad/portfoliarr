# Feature: Closed sales collapsed by default; Realized to date always visible

## Status
Implemented; FULL suite green (466 passed). NEXT STEP: user GUI check of
the collapsible Closed sales card, then commit gate on explicit yes.

## Decision
The Closed sales card's table ships COLLAPSED on every page load; the card
header — "Closed sales" + "Realized to date: X" — stays fully visible, so
the realized-to-date total is always on screen. Clicking anywhere on the
header toggles the table, with a right-pointing caret that rotates when
expanded (the ledger-group-row visual language).
- NO persistence: every load starts collapsed (explicit user choice).
- Backend untouched: `refreshClosedSales()` still fetches + renders every
  60s regardless of collapsed state; collapsing is pure visibility, so
  expanding always reveals freshly-fetched rows instantly.
- A11y: the header is `role="button"`, `tabindex="0"`, `aria-expanded` (JS
  keeps it in sync), Enter/Space keyboard parity (sortable-`<th>` precedent).

## Test plan (FIRST — must fail until implemented)
New file `tests/test_closed_sales_collapse.py`:
1. `test_ledger_ships_closed_sales_collapsed_by_default` — rendered
   `/ledger` carries the closed-sales table wrapper with the `hidden`
   attribute (`id="closed-sales-wrap"`), i.e. collapsed-by-default lives in
   HTML, no boot JS required.
2. `test_ledger_ships_closed_sales_toggle_header` — the header carries the
   toggle hooks: `id="closed-sales-toggle"`, `role="button"`,
   `aria-expanded="false"`, `tabindex="0"`.
3. `test_realized_total_always_visible` — `id="realized-total"` renders and
   sits BEFORE the hidden wrapper in the HTML (order assertion: total is in
   the always-visible header, never inside the collapsible region).
4. `test_ledger_js_wires_closed_sales_toggle` — ledger.js reads
   `#closed-sales-toggle` and `#closed-sales-wrap`, toggles `wrapper.hidden`
   and `.open`, updates `aria-expanded`, and handles Enter/Space.
5. `test_closed_sales_toggle_css` — style.css has the caret rotate rule and
   pointer cursor for `.closed-sales-toggle`.

Existing locks stay valid: `closed-sales-body`, the 8 `data-cs-col` hooks,
and `realized-total` still render (hidden ≠ removed).

## Implementation (after tests exist and fail)
1. `templates/ledger.html` — closed-sales card:
   - header: `id="closed-sales-toggle"` `role="button"` `tabindex="0"`
     `aria-expanded="false"`; `.caret` span with inline right-chevron SVG
     (template icon precedent) inside the `<h3>`.
   - `.table-wrap`: `id="closed-sales-wrap"` + `hidden` attribute.
2. `static/js/ledger.js` (CLOSED SALES section) — grab toggle + wrap;
   click handler toggles `wrap.hidden`, `.open` on header, `aria-expanded`;
   keydown handler for Enter/Space.
3. `static/style.css` — `.closed-sales-toggle` cursor: pointer + subtle
   hover tint; `.closed-sales-toggle .caret` rotate-on-`.open` (mirrors
   `.ledger-group`).

## Notes
- Collapsed state is HTML-default; JS never resets at boot.
- No effect on mobile card-mode CSS (hidden wrapper is display:none
  absolutely; the header renders normally at every width).
- Gates after implementation: full `python -m pytest` green → user GUI
  check → commit only on explicit yes.