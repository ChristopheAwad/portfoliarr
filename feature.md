# Collapsible transaction logger (collapsed by default)

## Status and scope

Approved and implemented 2026-09-25. Tests written first and confirmed red
(4 failed in `tests/test_ledger_page.py`); after implementation the focused
file is green (17 passed) and the full `python -m pytest` suite is green
(975 passed). The user approved the browser GUI and requested the PR. Not a
roadmap item (UI tweak). The ledger page's inline
transaction logger (the `Logging in …` line, `#tx-form`, the edit notice, and
the error line) becomes collapsible and ships COLLAPSED on every page load.
This mirrors the existing Closed-sales collapse kit. It changes
`templates/ledger.html`, `static/js/ledger.js`, `static/style.css`, and
`tests/test_ledger_page.py` only. No route, API, or DB change.

Decisions locked with the user:
- Toggle is a dedicated sub-header row inside the Transactions card:
  caret + `Log a transaction` on the left, `Logging in <portfolio>` on the
  right.
- Three flows auto-expand the logger: edit-row, Quick Sell, and the stock
  page deep link `/ledger?ticker=AAPL#tx-form`.

## Hard contracts that must not break

- `id="tx-form"` stays. `tests/test_ledger_page.py:38` and
  `tests/test_ui_revamp.py:106` lock it.
- `id="portfolio-form-name"` stays. `static/js/common.js:49` writes into it.
- `.tx-error` and `.tx-editing` class hooks stay. `static/js/ledger.js:43-45`
  queries them.
- The `#tx-form` anchor must still work; auto-expand on deep link handles it.
- No page-level `setInterval`; polling stays in `setupAutoRefresh`.

## Tests first (write these, confirm RED, then implement)

Append to `tests/test_ledger_page.py`:

1. `test_tx_logger_ships_collapsed`
   - `client.get("/ledger")` returns 200.
   - HTML contains `id="tx-logger-toggle"`.
   - HTML contains `id="tx-logger-wrap"` and the wrap tag carries `hidden`.
     Use `re.search(r'id="tx-logger-wrap"[^>]*\bhidden\b', html)`.
   - The toggle carries `aria-expanded="false"`. Use
     `re.search(r'id="tx-logger-toggle"[^>]*aria-expanded="false"', html)`.
2. `test_tx_logger_js_wires_toggle`
   - `LEDGER_JS.read_text()` contains `"tx-logger-toggle"` and
     `"tx-logger-wrap"`.
   - Contains `setTxLoggerOpen` (the single state setter).
   - Contains `aria-expanded` (screen-reader state kept truthful).
   - Contains a `click` and a `keydown` listener on the toggle id.
3. `test_tx_logger_auto_expands_all_flows`
   - `setTxLoggerOpen(true)` appears at least 3 times in `LEDGER_JS`.
     That pins the deep-link, enterEditMode, and prepareFullSale flows.
4. Add `"tx-logger-toggle"` and `"tx-logger-wrap"` to `LEDGER_MARKERS` (or a
   separate assertion) so the hooks are locked on `/ledger` and absent from
   `/` like the other ledger markers.

Run: `python -m pytest tests/test_ledger_page.py`. Record the failures.

## Implementation after red tests

### A. `templates/ledger.html`

Replace the region from the `<p class="portfolio-destination">` line (118)
through the `.tx-error` line (164) with:

1. A toggle row ABOVE the form:
   ```html
   <div class="tx-logger-toggle" id="tx-logger-toggle" role="button"
        tabindex="0" aria-expanded="false">
       <span class="caret">
           <svg class="icon" viewBox="0 0 24 24" width="16" height="16"
                fill="none" stroke="currentColor" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round"
                aria-hidden="true">
               <polyline points="9 18 15 12 9 6"></polyline>
           </svg>
       </span>
       <span class="tx-logger-title">Log a transaction</span>
       <span class="portfolio-destination">Logging in
           <strong id="portfolio-form-name"></strong></span>
   </div>
   ```
   The chevron SVG is identical to Closed sales (`ledger.html:308-313`).
2. `<div id="tx-logger-wrap" hidden>` wrapping, in order:
   - the existing `<form id="tx-form" class="tx-form">…</form>` byte-identical,
   - the existing `<p class="tx-editing" hidden>…</p>`,
   - the existing `<p class="tx-error" hidden></p>`,
   - close `</div>` after `.tx-error`.
3. Keep/extend the teaching comments: state that the wrapper ships `hidden`
   so "collapsed on every page load" needs no boot JS, and that the three
   flows below auto-expand.

Do NOT touch the `#import-panel` (it is toggled separately from the header).

### B. `static/js/ledger.js`

1. Near the top, after `const txDateInput = txForm.elements.date;` (~line 50),
   add:
   ```js
   const txLoggerToggle = document.querySelector("#tx-logger-toggle");
   const txLoggerWrap = document.querySelector("#tx-logger-wrap");

   // The collapsed state ships in the HTML (`hidden` on the wrapper), so
   // page load needs no boot JS. This setter is the ONE place the wrapper,
   // the .open caret class, and aria-expanded change together.
   function setTxLoggerOpen(open) {
       txLoggerWrap.hidden = !open;
       txLoggerToggle.classList.toggle("open", open);
       txLoggerToggle.setAttribute("aria-expanded", String(open));
   }
   function toggleTxLogger() {
       setTxLoggerOpen(txLoggerWrap.hidden);
   }
   txLoggerToggle.addEventListener("click", toggleTxLogger);
   txLoggerToggle.addEventListener("keydown", (event) => {
       if (event.key !== "Enter" && event.key !== " ") return;
       event.preventDefault();
       toggleTxLogger();
   });
   ```
2. Deep-link prefill block (currently `ledger.js:1550-1554`): call
   `setTxLoggerOpen(true);` before `txForm.elements.ticker.focus();`.
3. `enterEditMode(tx)` (currently `ledger.js:811`): call
   `setTxLoggerOpen(true);` before `txForm.scrollIntoView(...)`.
4. `prepareFullSale(...)` (currently `ledger.js:883`): call
   `setTxLoggerOpen(true);` before `txForm.scrollIntoView(...)`.
   Use three explicit calls, not a shared wrapper, so each flow reads alone.

### C. `static/style.css`

1. Add a parallel `.tx-logger-toggle` block with the same four rules as
   Closed sales (`.tx-logger-toggle { cursor: pointer }`,
   `… .caret`, `…:hover`, `… .open .caret`). They are deliberately
   DUPLICATED, not merged into the `.closed-sales-toggle` selectors: the
   standalone selector shape is string-locked by
   `tests/test_closed_sales_collapse.py`, so grouping would break it.
2. Add:
   ```css
   .tx-logger-toggle {
       display: flex;
       align-items: center;
       gap: 8px;
       padding: 6px 8px;
   }
   .tx-logger-toggle .tx-logger-title {
       font-weight: 600;
       font-size: 14px;
   }
   .tx-logger-toggle .portfolio-destination {
       margin: 0 0 0 auto;
   }
   ```
   The `margin-left: auto` pins the "Logging in" text to the right of the row.
3. Do NOT touch the ≤600px card-mode block.

## Verification

1. `python -m pytest tests/test_ledger_page.py` — green.
2. `python -m pytest` — full suite green.
3. Browser GUI approval from the user:
   - Reload `/ledger`: only the toggle row shows; table is first.
   - Click toggle: form appears; caret rotates; click again: hides.
   - Keyboard: Tab to the toggle, Enter and Space both toggle.
   - From `/stock/AAPL`, press "Log Transaction": lands on `/ledger`, logger
     is OPEN, ticker prefilled, ticker field focused.
   - Expand a group, click a row's edit button: logger opens prefilled.
   - Click a group's Quick Sell: logger opens prefilled SELL.
4. Wait for GUI approval. Only then ask whether to commit/push.

## Expected files

`feature.md`, `tests/test_ledger_page.py`, `templates/ledger.html`,
`static/js/ledger.js`, `static/style.css`.
