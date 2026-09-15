# Feature: Ledger ticker autocomplete (search + suggest like the navbar)

## Status
Implemented; FULL suite green (445 passed). NEXT STEP: user GUI check of the
ledger ticker autocomplete, then commit gate on explicit yes.

## Delivered
- `common.js`: `setupTickerSuggestions(inputEl, resultsEl, onPick, options)`
  factory (per-instance debounce/stale-guard/Escape/Enter/delegated-click/
  outside-click close); navbar is a call site (`pickTypedTextOnEnter: true`,
  `scopeEl: .search-container`). Old module-level `searchInput`/`searchResultsEl`
  globals removed.
- `ledger.html`: ticker input wrapped in `.tx-ticker-field` with
  `#tx-ticker-results` (reuses `.search-results` classes).
- `style.css`: `.tx-ticker-field { position: relative; flex: 1 1 90px;
  min-width: 0 }` + inner input `width: 100%`; 600px query gives the wrapper
  `flex: 1 1 100%`.
- `ledger.js`: `setupTickerSuggestions(txForm.elements.ticker, txTickerResultsEl,
  (symbol) => { txForm.elements.ticker.value = symbol; })` — default options, so
  Enter submits the form once the dropdown closes. Edit mode is naturally inert
  (disabled input fires no events).
- `tests/test_ticker_suggestions.py`: 6 passing string-lock tests.

## Decision
Reuse the navbar's `/api/search` endpoint as-is (user approved: company-name
search included, NOT symbol-only). No backend changes — this is a pure
frontend reuse + refactor.

## Plan
1. `static/js/common.js` — extract the navbar search dropdown into a shared
   factory `setupTickerSuggestions(inputEl, resultsEl, onPick, options)`:
   - owns per-instance debounce (300ms), stale-guard, Escape/Enter, delegated
     row clicks, and the outside-click close;
   - calls `onPick(symbol)` on click or on Enter (preventDefault so a form
     never submits mid-pick);
   - Enter only intercepts while the dropdown is OPEN by default (so the
     ledger's Enter-to-submit keeps working once it closes); the navbar passes
     `pickTypedTextOnEnter: true` to keep its "Enter always navigates" behavior
     (first suggestion, else the raw typed text);
   - outside-click scopes to a `scopeEl` if given (navbar passes
     `.search-container`, exact parity); defaults to the input element.
   - Navbar becomes one call site: `onPick` = navigate to `/stock/<symbol>`.
     The module-level `searchInput`/`searchResultsEl` globals and the hand-wired
     listeners are removed. `buildSearchRow` stays a pure module helper;
     `renderSearchResults(resultsEl, results, message)` takes the results
     element as a param. `DEBOUNCE_MS` stays module-level.
2. `templates/ledger.html` — wrap the `name="ticker"` input in
   `<div class="tx-ticker-field">` and add an empty
   `<div id="tx-ticker-results" class="search-results" hidden></div>` inside it
   (reuses the navbar dropdown's classes). Input keeps `name="ticker"`,
   `autocomplete="off"`, `required`.
3. `static/style.css` — `.tx-ticker-field { position: relative; flex: 1 1 90px;
   min-width: 0; }` (wrapper takes over the input's flex sizing) and
   `.tx-ticker-field input { width: 100%; }`. `.search-results` already anchors
   to its positioned ancestor. In the 600px media query, make the wrapper go
   full width like the other fields (`flex: 1 1 100%`).
4. `static/js/ledger.js` — grab `#tx-ticker-results` and call the factory:
   `setupTickerSuggestions(txForm.elements.ticker, txTickerResultsEl,
   (symbol) => { txForm.elements.ticker.value = symbol; })`. The factory hides
   the dropdown after a pick; focus stays in the field (user flows into
   Price → Qty → Log).
   - Edit mode: the ticker input is `disabled` → fires no input/keydown events
     → the factory is naturally inert, no special handling.
   - Deep-link prefill (`/ledger?ticker=AAPL#tx-form`) sets `.value`
     programmatically → no events → no dropdown. Correct.
5. Tests: `tests/test_ticker_suggestions.py` (string-lock style, mirrors
   `test_web_refresh_wiring.py` / `test_chart_axis.py`).

## Test plan (FIRST — must fail until implemented)
1. common.js defines `function setupTickerSuggestions(` (present).
2. Both-directions lock on the navbar refactor: the old hand-wired block
   (`searchInput.addEventListener("input"`) is ABSENT, and the navbar now goes
   through the factory — `setupTickerSuggestions(document.getElementById(
   "ticker-search")` present with a navigation `onPick`.
3. ledger.js calls the factory with `txForm.elements.ticker` and an `onPick`
   that assigns `txForm.elements.ticker.value = symbol`.
4. ledger.html ships `id="tx-ticker-results"` and the ticker input keeps
   `name="ticker"` inside the wrapper.
5. style.css defines `.tx-ticker-field` with `position: relative`.

Existing tests must keep passing: `test_ui_revamp.py` only checks the navbar
IDs in base.html (untouched); `test_web_refresh_wiring.py` checks
setupAutoRefresh (untouched).

## Gates
Full `python -m pytest` green → user GUI check on /ledger → commit only on
explicit yes.