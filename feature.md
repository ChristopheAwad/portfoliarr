# Feature: Refine the Comparison Picker UI

## Roadmap

- Parent feature: Roadmap #17, Arbitrary Comparison Overlays.
- Parent status: `shipped 2026-09-20 (PR #60)`.
- This is a post-ship UI refinement to #17, not a new roadmap item.
- Do not change the shipped roadmap status and do not add a new permanent ID.

## Status

IMPLEMENTED. Awaiting user browser GUI approval.

The six intended comparison-picker contracts failed before implementation.
After the template, JavaScript, and CSS changes, the focused comparison and
frontend regression groups pass. The final full suite passes (`647 passed`).
Node is not installed in this environment, so the optional `node --check`
commands could not run. Do not commit or push before browser approval and
explicit user permission.

## Goal

Make the comparison picker read as one clear chart tool instead of an unlabeled
row of unrelated buttons, search input, and duplicate chips.

The finished desktop control must read in this order:

```text
Compare   S&P 500   Nasdaq   TSX   [custom comparison chips]   Search ticker...
```

On a narrow viewport, the label and selections stay together above a full-width
search input:

```text
Compare   S&P 500   Nasdaq   TSX   [AAPL x]
[Search ticker...                              ]
```

The picker remains visually inside the existing chart card. Do not add another
card, panel, outline, heading block, modal, disclosure, or popover around it.
The search suggestions continue to use the existing anchored dropdown.

## Design Decision

Use a persistent inline comparison tool, not a hidden `+ Add comparison`
control.

Reasons:

- The three benchmark shortcuts are useful and should remain discoverable.
- Hiding all controls behind a disclosure adds a click to a small, frequent
  chart action.
- The chart card is already the correct structural boundary. Another outlined
  box would create nested-card clutter.
- A visible `Compare` label explains the controls without adding help text.
- Portfoliarr's printed-money identity is restrained. Existing typography,
  borders, inset backgrounds, radii, focus rings, and theme tokens are enough.

The picker must use the existing Instrument Sans UI face and current design
tokens. Do not introduce new colors, shadows, radii, typefaces, icons, or
motion. Green and red remain reserved for market direction.

## Locked Interaction Contract

1. Show the visible text label `Compare` on both the dashboard and stock page.
2. Give the whole control `role="group"` and connect it to the visible label
   with `aria-labelledby="compare-label"`.
3. Keep S&P 500, Nasdaq, and TSX visible as quick-pick toggle buttons.
4. Keep each quick pick's current `aria-pressed` behavior.
5. A selected quick-pick symbol is represented only by its active quick-pick
   button. Do not also render a removable chip for it.
6. A selected custom ticker is represented by one removable chip between the
   quick picks and search input.
7. Keep the custom chip's existing remove button and accessible label.
8. Rename the input placeholder from `Compare to a ticker...` to
   `Search ticker...`.
9. Add `aria-label="Search ticker to compare"` to the input. The placeholder is
   visual guidance, not its accessible name.
10. Keep the maximum at three total symbols across quick picks and custom
    tickers.
11. Keep uppercase normalization and ordered, de-duplicated state.
12. Keep the stock page's primary-symbol exclusion.
13. Keep comparison state page-local and clear it on BFCache restoration.
14. Keep the dashboard's first-comparison switch to Performance mode.
15. Keep the stock chart's raw-price/normalized-chart transitions unchanged.
16. Keep search selection behavior: add the selected symbol, clear the input,
    and reload the current chart.
17. Keep comparison readout behavior and placement unchanged.
18. Keep all backend requests, endpoint shapes, chart math, error degradation,
    line colors, tooltip behavior, and maximum-three toast unchanged.

## DOM Structure

Use the same structure on both pages. Exact IDs already differ only where the
existing page requires them; comparison picker IDs stay as they are because
only one picker exists per page.

```html
<div class="compare-picker" role="group" aria-labelledby="compare-label">
    <span id="compare-label" class="compare-label">Compare</span>
    <div class="compare-selections">
        <div class="compare-quick-picks">
            <!-- Existing three buttons, unchanged. -->
        </div>
        <div id="compare-chips" class="compare-chips"></div>
    </div>
    <div class="compare-search">
        <input id="compare-input"
               type="text"
               autocomplete="off"
               aria-label="Search ticker to compare"
               placeholder="Search ticker...">
        <div id="compare-results" class="search-results" hidden></div>
    </div>
</div>
```

Do not use a heading element for `Compare`; it labels a compact control, not a
new content section. Do not connect the visible span with `for`, because it
labels the full group rather than only the search input.

## Part 1: Write Failing Tests First

All new tests belong in `tests/test_compare_ui.py`. Keep the existing comparison
backend, chart, tooltip, refresh, and readout tests unchanged.

### 1.1 Add a reusable picker-markup assertion

Add a small helper that receives one template string and checks only the
comparison picker span. Extract from `class="compare-picker"` through that
container's closing markup narrowly enough that the global navbar search cannot
satisfy comparison-picker assertions.

If reliable nested-element extraction would make the test parser complex, use
ordered marker positions bounded by the existing comparison-picker comment and
the parent chart-card closing marker. Do not add BeautifulSoup or another
dependency for this source contract.

### 1.2 Test the labelled group on both pages

Add `test_picker_is_a_labelled_chart_control_on_both_pages`.

For both `INDEX_HTML` and `STOCK_HTML`, require:

- `class="compare-picker"`.
- `role="group"` on that element.
- `aria-labelledby="compare-label"` on that element.
- one `id="compare-label" class="compare-label"` containing exactly
  `Compare`.
- one `class="compare-selections"`.
- the DOM order: label, selections, search.

This test must fail before implementation because the current picker has no
visible label, group semantics, or selections wrapper.

### 1.3 Test search copy and accessible naming

Add `test_picker_search_has_specific_copy_and_accessible_name`.

For both templates, require the comparison input to contain:

- `id="compare-input"`.
- `placeholder="Search ticker..."`.
- `aria-label="Search ticker to compare"`.

Also assert that `Compare to a ticker...` is absent from each comparison picker
span. Do not search all rendered HTML because unrelated copy can change without
breaking this control.

This test must fail before implementation because the current input has the old
placeholder and no explicit accessible name.

### 1.4 Test quick-pick and custom-chip grouping

Update `test_picker_markup_is_present_on_both_pages` rather than duplicating all
of its assertions. Retain the existing IDs and classes, and additionally
require:

- `.compare-quick-picks` and `#compare-chips` are both descendants of
  `.compare-selections`.
- `.compare-selections` appears before `.compare-search`.
- all three quick-pick symbols remain present on both pages.

Do not change `test_quick_pick_symbols_match_supported_index_symbols`.

### 1.5 Test that quick picks do not get duplicate chips

Add `test_picker_renders_chips_for_custom_symbols_only` using `_picker_body()`.

Require the implementation to:

- build a set of quick-pick symbols from `quickPickBar` button
  `data-symbol` values;
- check that set inside `renderChips()` before creating a `.compare-chip`;
- skip chip creation for a symbol in that set;
- continue to create `.compare-chip` and `.compare-chip-remove` elements for
  symbols outside that set;
- continue to update every quick-pick button's `active` class and
  `aria-pressed` value from the full `symbols` array.

Use narrow source assertions around `renderChips()`. Do not assert incidental
whitespace or an entire function snapshot.

This test must fail before implementation because every selected symbol
currently gets a chip, including quick picks.

### 1.6 Lock empty, invalid, duplicate, and boundary behavior

Add or extend narrow source-contract tests so the UI-only refactor cannot alter
picker state rules:

- Empty input returns before changing state.
- A symbol equal to `primarySymbol` shows the existing error and is not added.
- A symbol already in `symbols` returns without adding a duplicate.
- Exactly three total comparisons remain allowed.
- A fourth comparison shows `Up to 3 comparisons` and is not added.
- Removal filters only the requested symbol and notifies the chart once.
- Clearing state empties the same full symbol array, not only visible custom
  chips.
- BFCache restoration still calls `clearSymbols()`.

Prefer assertions against `_picker_body()` and the existing `COMPARE_MAX`
constant. Do not introduce a JavaScript test dependency for this small UI
refinement.

### 1.7 Lock desktop and mobile layout contracts

Extend `test_comparison_picker_has_shared_styles` and add
`test_comparison_picker_has_deliberate_mobile_layout`.

Require shared style selectors for:

- `.compare-picker`.
- `.compare-label`.
- `.compare-selections`.
- `.compare-quick-picks`.
- `.compare-chips`.
- `.compare-search`.

Require the base `.compare-picker` rule to use an aligned grid with three
conceptual columns: label, selections, and flexible search. Do not lock exact
pixel values, but require `display: grid` and a `grid-template-columns`
declaration.

Require `.compare-selections` to use flex layout with wrapping, so custom chips
join the quick picks without creating a detached third region.

Inside a `max-width: 600px` media query, require:

- `.compare-picker` uses two columns for label plus selections.
- `.compare-search` spans the full row with `grid-column: 1 / -1`.
- no fixed width that can exceed the viewport.
- no `overflow: hidden` on the picker, selections, or search wrapper.

Do not lock exact gaps, padding, or font sizes. Those are visual tuning values,
not behavioral contracts.

### 1.8 Run the red tests

Run:

```bash
source .venv/bin/activate
python -m pytest tests/test_compare_ui.py -q
```

Expected pre-implementation failures:

- no visible `Compare` label or labelled group;
- no `.compare-selections` wrapper;
- old search placeholder and missing input `aria-label`;
- quick-pick selections still produce duplicate chips;
- picker still uses a wrapping flex row rather than the locked grid layout;
- no mobile full-row search rule.

If any new test passes before implementation, verify that it matches the
comparison picker specifically and is not finding the navbar search or another
unrelated rule.

## Part 2: Update Both Templates

Edit `templates/index.html` and `templates/stock.html` in parallel. The two
pickers must retain matching structure.

For each picker:

1. Add `role="group"` and `aria-labelledby="compare-label"` to
   `.compare-picker`.
2. Add `<span id="compare-label" class="compare-label">Compare</span>` as its
   first child. Each template is a separate page, so this ID remains unique in
   the rendered document.
3. Add `<div class="compare-selections">` as its second child.
4. Move the existing `.compare-quick-picks` block into that wrapper without
   changing button text, symbols, types, or `aria-pressed` values.
5. Move the existing `#compare-chips` element directly after quick picks inside
   the same wrapper.
6. Keep `.compare-search` as the final child of `.compare-picker`.
7. Change the input placeholder to `Search ticker...`.
8. Add `aria-label="Search ticker to compare"` to the input.
9. Keep `autocomplete="off"`, existing IDs, and the hidden results element.
10. Update nearby teaching comments to describe quick picks, custom chips, and
    page-local state accurately. Do not add a long design rationale to HTML.

Do not change the chart canvas, readout, mode selector, timeframe selector, or
their relative order.

## Part 3: Stop Duplicate Quick-Pick Chips

Edit only `setupComparePicker()` in `static/js/common.js`.

### 3.1 Capture quick-pick symbols once

Immediately after `let symbols = [];`, create one set from the quick-pick
buttons supplied through `quickPickBar`.

The set must:

- be empty when `quickPickBar` is absent;
- read each button's `data-symbol` value;
- avoid querying the full document;
- be created once during picker setup, because the three button symbols are
  static markup.

Use one local name such as `quickPickSymbols`. Do not add this state globally.

### 3.2 Render custom chips only

Inside the existing `for (const symbol of symbols)` loop in `renderChips()`,
continue to iterate the full ordered symbol list but skip DOM chip creation when
`quickPickSymbols.has(symbol)` is true.

Do not remove quick-pick symbols from `symbols`. The full array remains the
single source for:

- the maximum-three boundary;
- request ordering;
- `getSymbols()`;
- active button state;
- `aria-pressed` state;
- chart reloads and benchmark query parameters;
- removal and BFCache clearing.

After custom chip rendering, keep the current quick-pick repaint loop exactly
in purpose: selected quick picks receive `.active` and `aria-pressed="true"`;
unselected buttons receive the inverse state.

### 3.3 Preserve all add/remove paths

Do not change `addSymbol()`, `removeSymbol()`, `clearSymbols()`, `notify()`,
search suggestion setup, or the delegated quick-pick click handler except for
any strictly necessary local rename caused by the new set.

In particular, do not create separate quick/custom state arrays. Two arrays
would make ordering, limits, removal, and requests easier to desynchronize.

## Part 4: Restyle the Picker as an Inline Tool

Edit the existing comparison-control section in `static/style.css`. Keep the
rules next to the chart controls and comparison readout.

### 4.1 Desktop layout

Change `.compare-picker` from a free-form flex row to a three-column grid:

- column 1: intrinsic-width `Compare` label;
- column 2: intrinsic/flexible selections group;
- column 3: search input with a practical minimum and remaining width;
- vertically center all three regions;
- retain a modest top margin from the timeframe controls;
- use the existing spacing rhythm rather than a new decorative container.

Use a template equivalent to:

```css
grid-template-columns: auto auto minmax(220px, 1fr);
```

The implementation may tune the second track to prevent crowding, but it must
not force the chart card wider than its grid column.

### 4.2 Label treatment

Style `.compare-label` as a quiet UI label:

- Instrument Sans through the inherited UI font;
- sentence case, never uppercase or tracked lettering;
- semibold;
- existing chart-control text size;
- secondary text color;
- no border, background, icon, or accent color.

### 4.3 Selections group

Add `.compare-selections` as an inline flex container that:

- aligns items centrally;
- allows wrapping;
- uses the existing six-pixel control gap;
- has `min-width: 0` so it can contract inside the chart card.

Keep `.compare-quick-picks` and `.compare-chips` as flex containers. Remove only
declarations made redundant by the wrapper; do not change the established
quick-pick and custom-chip visual recipes.

The active benchmark remains a bordered state button using the existing accent
and inset background. A custom symbol remains a removable accent-bordered chip.
They differ because one is a persistent toggle and the other is a user-added
selection.

### 4.4 Search treatment

Keep `.compare-search` positioned relative so the existing absolute suggestion
dropdown remains anchored to the input.

In the grid:

- use `min-width: 0` to prevent card overflow;
- let the input fill its grid track;
- retain the current inset background, border, radius, focus ring, text size,
  and result-dropdown minimum width;
- do not add a search icon or submit button.

### 4.5 Mobile layout

In the existing final `@media (max-width: 600px)` block, add picker rules next
to the comparison-readout rules.

At this breakpoint:

- set `.compare-picker` to `grid-template-columns: auto minmax(0, 1fr)`;
- keep `.compare-label` in the first column;
- keep `.compare-selections` in the second column and allow it to wrap;
- set `.compare-search` to `grid-column: 1 / -1` so it occupies the full next
  row;
- reduce only gaps if necessary; do not reduce text below the existing
  chart-control size;
- keep all controls inside the viewport without clipping;
- do not add horizontal scroll, scroll snap, or legacy momentum-scrolling
  properties to this control.

The expected common empty-state phone layout is two rows: label plus three
quick picks, then search. Additional custom chips may wrap the selections row
naturally before the search row.

## Part 5: Focused Verification

After implementation, run:

```bash
source .venv/bin/activate
python -m pytest tests/test_compare_ui.py -q
python -m pytest tests/test_chart_tooltip.py tests/test_chart_refresh.py -q
python -m pytest tests/test_compare.py -q
```

Then run frontend layout and chart regressions:

```bash
python -m pytest \
  tests/test_ui_redesign.py \
  tests/test_chart_speed.py \
  tests/test_prev_close.py \
  tests/test_price_diff.py \
  tests/test_chart_axis.py \
  tests/test_web_refresh_wiring.py -q
```

If Node is available, run:

```bash
node --check static/js/common.js
node --check static/js/main.js
node --check static/js/stock.js
```

`main.js` and `stock.js` are not expected to change, but syntax-check them
because both call the shared picker and chart factory.

## Part 6: Full-Suite Gate

The lead agent runs:

```bash
source .venv/bin/activate
python -m pytest
```

Do not report implementation complete unless the full suite passes. Do not
weaken existing tests to accommodate a visual change.

## Part 7: Browser GUI Approval Gate

After pytest is green, stop and ask the user to verify the UI before any commit
or push.

### Dashboard, desktop

- `Compare` clearly labels the benchmark buttons and ticker search.
- S&P 500, Nasdaq, and TSX remain visible without opening another control.
- Selecting S&P 500 activates its button but does not add an S&P 500 chip.
- Selecting Nasdaq and TSX behaves the same way.
- Searching for and selecting AAPL adds one removable AAPL chip.
- The custom chip appears between the quick picks and search input.
- Three total selections are allowed across both selection types.
- A fourth selection shows the existing limit toast.
- Removing a quick pick by pressing its active button updates the chart.
- Removing a custom ticker through its chip updates the chart.
- The first comparison still switches the dashboard to Performance.
- The bottom comparison readout remains correctly aligned with line colors.

### Stock page, desktop

- The picker has the same structure and visual rhythm as the dashboard.
- Searching for the current stock shows the existing exclusion error.
- A quick pick does not produce a duplicate chip.
- A custom ticker produces one removable chip.
- Removing all comparisons restores raw-price tools and tooltip behavior.

### Mobile, light and dark themes

- The first row shows `Compare` and visible benchmark shortcuts.
- The search input occupies the full next row.
- A custom chip wraps without widening or clipping the chart card.
- Search results remain anchored below the comparison input and fit the
  viewport.
- Focus rings are visible for quick picks, search, results, and remove buttons.
- Text and active states have sufficient contrast in both themes.
- The picker adds no nested-card appearance, unnecessary shadow, or decorative
  color.

### State and navigation regression

- Reload starts with no comparisons.
- Navigating to another page starts with no comparisons.
- Browser Back does not restore stale comparisons from BFCache.
- Changing timeframe retains active comparisons on the current page.
- Dashboard Value/Performance switching retains page-local selections while
  showing overlays only in Performance.

## Files Expected To Change

- `tests/test_compare_ui.py`: new markup, behavior, boundary, accessibility,
  and responsive CSS contracts.
- `templates/index.html`: labelled picker structure and search copy.
- `templates/stock.html`: matching labelled picker structure and search copy.
- `static/js/common.js`: suppress duplicate chips for selected quick picks.
- `static/style.css`: desktop grid and mobile two-row picker layout.
- `feature.md`: this approved implementation contract and eventual handoff.

No expected changes:

- `app.py`.
- `db.py`.
- `market_data.py`.
- `static/js/main.js`.
- `static/js/stock.js`.
- API response shapes or request parameters.
- comparison readout markup or rendering.
- `roadmap.md`.

## Scope Limits

- No new endpoint or backend behavior.
- No comparison persistence.
- No modal, popover, drawer, disclosure, or bottom sheet.
- No new outer card or decorative comparison box.
- No collapse/expand preference.
- No drag reordering.
- No configurable quick picks.
- No symbol names inside custom chips; retain ticker symbols.
- No line-color markers inside the picker; the bottom readout remains the
  authoritative line legend.
- No changes to benchmark normalization or performance calculations.
- No new dependency.
- No commit or push until browser approval and explicit user permission.

## Worktree Note

The untracked files `comparison.html` and `ui-nomenclature-audit.html` are user
files unrelated to this refinement. Do not edit, delete, stage, or commit them.

---

## Feature context (documented by document-bug)

### Authoritative status override

The plan and `IMPLEMENTED. Awaiting user browser GUI approval.` status above are
historical. **Do not continue to its browser gate and do not commit its current
UI.** The user reviewed that result and rejected the always-visible S&P 500,
Nasdaq, and TSX buttons because the control still looks crowded.

The new design below supersedes every earlier instruction that says to keep
benchmark quick-pick buttons permanently visible, to suppress chips for those
buttons, or to use a three-column label/selections/search grid.

Current status: **IMPLEMENTED AND TESTED. Awaiting user browser GUI
approval.** All new tests below were written and confirmed red first, then
the production code was adapted. Focused comparison/ticker-suggestion suites,
chart regressions, and the full pytest suite pass (`655 passed`). Node is not
installed, so the optional `node --check` commands could not run. Do not
commit or push before browser approval and explicit user permission.

### Feature summary

Replace the crowded comparison picker with one compact search control. At rest,
both the dashboard and stock page show only:

```text
Compare   [Search ticker or benchmark...]
```

Focusing the empty field opens its normal suggestion dropdown with three local
recommendations:

```text
Suggested
S&P 500    ^GSPC
Nasdaq     ^IXIC
TSX        ^GSPTSE
```

Typing replaces those recommendations with the existing `/api/search` results.
Selecting either a suggested benchmark or a search result creates one removable
chip below the input. The chart behavior and bottom performance readout do not
change.

### Locked design and behavior

1. Keep the visible `Compare` label and its accessible group association.
2. Remove S&P 500, Nasdaq, and TSX from the permanent picker surface.
3. Do not replace them with another button, disclosure, modal, drawer, or
   separate card.
4. Use the existing `.search-results` dropdown as the only selection surface.
5. When the comparison input gains focus while empty, show a sentence-case
   `Suggested` heading followed by S&P 500, Nasdaq, and TSX rows.
6. When the user deletes all typed text while the field remains focused, show
   the three suggested rows again instead of closing the dropdown.
7. When the user types non-empty text, use the existing debounce,
   `/api/search?q=...` request, stale-response guard, no-match state, and failure
   state without behavioral changes.
8. Escape and outside clicks close the dropdown. Refocusing the still-empty
   input opens suggestions again.
9. Clicking a suggested row and pressing Enter on the first visible suggested
   row use the same `addSymbol()` path as a remote search result.
10. Every selected comparison gets exactly one removable chip, including
    `^GSPC`, `^IXIC`, and `^GSPTSE`.
11. Benchmark chips use friendly labels (`S&P 500`, `Nasdaq`, `TSX`). Custom
    symbols use their uppercase ticker. Internal state and API requests always
    retain raw symbols.
12. Hide `#compare-chips` when there are no selections. Reveal it when at least
    one chip exists.
13. On a stock detail page, omit the primary symbol from local suggested
    benchmarks. For example, `/stock/%5EGSPC` must not suggest S&P 500. The
    existing primary-symbol rejection remains as a defense for typed results.
14. Keep one ordered `symbols` array as the source of truth. Do not split
    benchmark and custom state.
15. Keep the maximum at three total symbols, uppercase normalization,
    de-duplication, primary-symbol rejection, remove behavior, and BFCache reset.
16. Keep comparisons page-local. Do not add localStorage, sessionStorage, URL,
    cookie, or backend persistence.
17. Keep dashboard first-selection auto-switch to Performance mode.
18. Keep stock raw-price/normalized transitions and restoration unchanged.
19. Keep comparison request parameters, backend routes, response shapes,
    growth-of-$100 math, degraded benchmark behavior, line colors, date-only
    comparison tooltip, and bottom readout unchanged.
20. Use current printed-money tokens. Add no new palette, shadow, radius,
    typeface, animation, or decorative container.

### Final markup contract

Both `templates/index.html` and `templates/stock.html` must use the same picker
shape:

```html
<div class="compare-picker" role="group" aria-labelledby="compare-label">
    <span id="compare-label" class="compare-label">Compare</span>
    <div class="compare-search">
        <input id="compare-input"
               type="text"
               autocomplete="off"
               aria-label="Search ticker or benchmark to compare"
               placeholder="Search ticker or benchmark...">
        <div id="compare-results" class="search-results" hidden></div>
    </div>
    <div id="compare-chips" class="compare-chips" hidden></div>
</div>
```

Remove `.compare-selections`, `.compare-quick-picks`, and every `.compare-quick`
button from the picker markup. Keep the chart canvas, readout, mode selector,
and timeframe selector in their current relative positions.

### Detailed test-first plan

All production files currently contain the rejected visible-button design. Edit
`tests/test_compare_ui.py` first and run it red before changing production code.
Keep `_picker_markup()`, `_picker_body()`, `_comparison_readout_body()`, and the
useful existing state/readout tests.

#### Test A: compact picker markup on both pages

Replace the current quick-pick grouping assertions with a test that checks each
picker span contains, in order:

- `compare-label`;
- `compare-search` with `#compare-input` and `#compare-results`;
- `#compare-chips` with the `hidden` attribute.

Require `role="group"`, `aria-labelledby="compare-label"`, the visible text
`Compare`, placeholder `Search ticker or benchmark...`, and input
`aria-label="Search ticker or benchmark to compare"`.

Inside the extracted picker markup, assert these rejected elements are absent:

- `compare-selections`;
- `compare-quick-picks`;
- `compare-quick`;
- `data-symbol="^GSPC"`;
- `data-symbol="^IXIC"`;
- `data-symbol="^GSPTSE"`.

Do not search all of `index.html` for those symbols because the separate market
index chips legitimately use them.

#### Test B: local benchmark recommendation definitions

Replace `test_quick_pick_symbols_match_supported_index_symbols` with a test that
requires `common.js` to define one shared immutable/local recommendation list
containing exact symbol/name pairs:

- `^GSPC` / `S&P 500`;
- `^IXIC` / `Nasdaq`;
- `^GSPTSE` / `TSX`.

Still assert each raw symbol exists in `app_module.INDEX_SYMBOLS`. The frontend
names and backend-supported index set must not drift.

#### Test C: optional default-result support in the shared factory

Add source contracts around `setupTickerSuggestions()` that require:

- optional default results and an optional default heading are read from
  `options`;
- a local helper renders defaults only when the list is non-empty;
- the input `focus` handler renders defaults only when `inputEl.value.trim()` is
  empty;
- the existing `input` handler renders defaults, rather than calling `hide()`,
  when text becomes empty and defaults exist;
- a typed non-empty query still schedules `runSearch(query)`;
- Escape and outside-click paths still call `hide()`;
- the delegated `.search-row` click and Enter paths still call `onPick(symbol)`.

Do not require default-result behavior from navbar or ledger callers. The new
factory options must default to no recommendations, leaving those call sites
byte-for-byte behaviorally unchanged.

#### Test D: suggested heading renderer

Add a narrow source test around `renderSearchResults()` that requires an
optional heading argument and safe DOM construction:

- create an element with class `.search-section-label` only when a heading was
  supplied;
- assign the heading through `textContent`, never `innerHTML`;
- append the heading before result rows;
- keep `message` rendering for `No matches` and `Search unavailable`;
- keep all result rows built through `buildSearchRow()`.

#### Test E: picker wires filtered defaults

Replace `test_picker_renders_chips_for_custom_symbols_only` with contracts that
require `setupComparePicker()` to:

- filter the default recommendation list against `primarySymbol`;
- pass the filtered list and `Suggested` heading to
  `setupTickerSuggestions()`;
- route suggested and remote picks through the same callback and
  `addSymbol(symbol)` call;
- clear `inputEl.value` after a successful pick attempt, as it does now.

The default recommendation objects must have the same fields expected by
`buildSearchRow()` (`symbol`, `name`, and suitable `type`/`exchange` values), so
the dropdown reuses normal result rows without special click logic.

#### Test F: every selection renders one removable chip

Require `renderChips()` to iterate every symbol without a
`quickPickSymbols.has(symbol)` skip. Require:

- one `.compare-chip` per symbol;
- one `.compare-chip-remove` button per chip;
- benchmark-friendly label lookup with ticker fallback;
- raw symbol retained in `chip.dataset.symbol`;
- remove button calls `removeSymbol(symbol)`;
- chips container `hidden` state is set from whether `symbols.length === 0`.

Assert `quickPickBar`, `quickPickSymbols`, quick-pick active classes, and
quick-pick `aria-pressed` handling are absent from `_picker_body()`.

#### Test G: invalid, empty, boundary, and failure paths

Keep or add source contracts for all of these paths:

- empty symbol does nothing;
- primary symbol shows `That symbol is already the chart` and is not added;
- duplicate symbol does nothing;
- exactly three symbols are allowed;
- fourth symbol shows `Up to 3 comparisons` and is not added;
- removal changes only the requested symbol and notifies once;
- clearing empties all symbols, hides the chip row, and reloads without
  benchmarks through the existing callback;
- BFCache `pageshow` with `event.persisted` still calls `clearSymbols()`;
- typed search with zero results still shows `No matches`;
- network/HTTP/JSON search failure still shows `Search unavailable`;
- a stale typed response cannot overwrite the current empty-input suggested
  list because the existing query/value equality guard remains.

For the last case, preserve the current check
`inputEl.value.trim() !== query`; do not build a second request-generation
system.

#### Test H: compact desktop and mobile CSS

Replace the current three-column and quick-control CSS assertions. Require:

- `.compare-picker`, `.compare-label`, `.compare-search`, `.compare-chips`,
  `.compare-chip`, `.compare-chip-remove`, and `.search-section-label` rules;
- no `.compare-selections`, `.compare-quick-picks`, or `.compare-quick` rules;
- desktop `.compare-picker` uses a two-column grid: intrinsic label plus
  flexible search;
- `.compare-chips` occupies the search column on a second row, wraps, and is
  hidden through the global `[hidden]` contract when empty;
- `.compare-search` remains `position: relative` and `min-width: 0`;
- comparison results cannot exceed the available input width;
- at `max-width: 600px`, the picker becomes one column so label, search, and
  chips stack without viewport overflow;
- no horizontal scrolling, `100vw`, fixed over-wide width, scroll snap, or
  legacy momentum scrolling is added.

#### Required red run

Run before production edits:

```bash
source .venv/bin/activate
python -m pytest tests/test_compare_ui.py tests/test_ticker_suggestions.py -q
```

Expected failures include permanent quick controls still present, old search
copy, no default results or heading support, benchmark chip suppression still
present, and old three-column CSS still present. If all new tests pass before
implementation, they are not testing the intended change.

### Production implementation plan

#### 1. Extend shared result rendering in `static/js/common.js`

Change `renderSearchResults(resultsEl, results, message)` to accept a fourth,
optional heading argument. Clear the container as now. If heading is truthy,
create a `div.search-section-label`, set `textContent`, and append it before the
message/results. Preserve message and row rendering exactly otherwise.

Do not use `innerHTML` for headings, symbols, names, or search results.

#### 2. Extend `setupTickerSuggestions()` with optional defaults

Read options with defaults equivalent to:

```javascript
const defaultResults = options.defaultResults || [];
const defaultHeading = options.defaultHeading || null;
```

Add one local `showDefaults()` helper. It returns false without defaults;
otherwise it calls `renderSearchResults(resultsEl, defaultResults, null,
defaultHeading)` and returns true.

Register an input `focus` listener that calls `showDefaults()` only when the
trimmed value is empty. In the existing `input` listener, after clearing the
timer, replace the empty-query `hide()` path with: show defaults if available,
otherwise hide. Return immediately afterward.

Do not change `runSearch()`, debounce timing, response checks, stale guard,
error logging, Enter guard, delegated click handling, or outside-click logic.

#### 3. Define comparison recommendations once

Near `COMPARE_MAX`, define one constant recommendation list with the three
objects required by `buildSearchRow()`. Keep raw Yahoo symbols in `symbol` and
human labels in `name`. Use the same existing row component; do not invent
benchmark-only markup or handlers.

#### 4. Simplify `setupComparePicker()`

Remove `quickPickBar` from its parameter list. Delete `quickPickSymbols`, the
chip skip, active/`aria-pressed` repaint loop, and delegated quick-pick click
handler.

Create the per-page default list with the primary symbol removed. Pass it to
`setupTickerSuggestions()` as `defaultResults` with `defaultHeading:
"Suggested"`. Keep `scopeEl: inputEl` unless browser testing proves that the
dropdown closes when clicking its own rows; the shared handler already treats
`resultsEl` as inside.

In `renderChips()`, clear the container, render one chip for every symbol, use a
small lookup from the recommendation list for friendly benchmark text, and fall
back to the raw symbol. Keep raw symbols in data attributes and callbacks. Set
`chipsEl.hidden = symbols.length === 0` after rendering (or before the loop with
the same result).

Do not alter `addSymbol()`, `removeSymbol()`, `clearSymbols()`, `notify()`, or
the page-local state model beyond ensuring empty-state chip visibility repaints.

#### 5. Remove obsolete caller wiring

In `static/js/main.js` and `static/js/stock.js`, remove only:

```javascript
quickPickBar: document.querySelector(".compare-quick-picks"),
```

Keep input/results/chips elements, primary stock symbol, chart reload callbacks,
and dashboard Performance switching intact.

#### 6. Simplify both templates

Apply the final markup contract above to `templates/index.html` and
`templates/stock.html`. Remove permanent benchmark buttons and
`.compare-selections`. Put search before hidden chips. Update teaching comments
to explain that focusing the field shows suggested benchmarks and all selected
comparisons become removable chips.

#### 7. Simplify CSS

In `static/style.css`:

- change `.compare-picker` to two columns (`auto minmax(0, 1fr)`);
- keep current quiet `.compare-label` treatment;
- remove `.compare-selections`, `.compare-quick-picks`, `.compare-quick`,
  hover, active, and quick-pick focus rules;
- retain `.compare-chip` and `.compare-chip-remove` styles;
- make `.compare-chips` a wrapping flex row placed in grid column 2;
- retain `.compare-search` as the dropdown anchor;
- add `.search-section-label` near the shared search dropdown styles or the
  comparison section, using sentence case, secondary text, the existing small
  control size, and semibold weight; no all-caps tracking or decorative fill;
- at `max-width: 600px`, switch `.compare-picker` to one column and let search
  and chips occupy the full width;
- keep `.compare-search .search-results` constrained to available width.

### Verification after implementation

Run focused tests:

```bash
source .venv/bin/activate
python -m pytest tests/test_compare_ui.py tests/test_ticker_suggestions.py -q
python -m pytest tests/test_chart_tooltip.py tests/test_chart_refresh.py -q
python -m pytest tests/test_compare.py -q
```

Run frontend/chart regressions:

```bash
python -m pytest \
  tests/test_ui_redesign.py \
  tests/test_chart_speed.py \
  tests/test_prev_close.py \
  tests/test_price_diff.py \
  tests/test_chart_axis.py \
  tests/test_web_refresh_wiring.py -q
```

If Node is available, run:

```bash
node --check static/js/common.js
node --check static/js/main.js
node --check static/js/stock.js
```

Node was not installed during the previous run. Its absence is not a pytest
failure; report it honestly.

The lead agent must then run:

```bash
python -m pytest
```

The last full-suite baseline before this superseding plan was `647 passed`.

### Browser GUI approval checklist

After all tests pass, stop for user approval. Verify both dashboard and stock
pages in light/dark themes and desktop/phone widths:

- resting picker shows only `Compare` and one search input;
- focusing empty input opens `Suggested` with the three benchmarks;
- suggestions use friendly names and recognizable raw symbols;
- typing replaces local suggestions with remote results;
- clearing text restores local suggestions;
- Escape and outside clicks close the dropdown;
- refocus opens it again;
- mouse selection and Enter selection both work;
- each benchmark and custom ticker creates one removable chip;
- benchmark chips use friendly names;
- selecting three mixed comparisons works and a fourth shows the existing
  limit toast;
- current stock does not appear in local suggestions on its detail page;
- dashboard first selection switches to Performance;
- removing all stock comparisons restores raw-price tools;
- bottom comparison readout and date-only tooltip remain unchanged;
- chip rows wrap without widening the chart card;
- no permanent benchmark buttons remain;
- no nested card, extra shadow, clipping, or horizontal page overflow appears.

Do not commit or push until this new browser design is approved and the user
explicitly requests git action.

### Investigation log

- Reviewed the shipped comparison implementation in commit `b3bc6fd` (PR #60):
  comparison overlays, quick picks, search, and bottom readout already exist.
- First refinement implemented a visible `Compare` label, permanent benchmark
  buttons, custom-only chips, and responsive grid. New contracts failed red,
  then passed; focused suites and the full suite passed (`647 passed`).
- User reviewed the explanation before GUI approval and identified the core
  remaining issue: permanent S&P 500, Nasdaq, and TSX controls make the picker
  crowded.
- Considered a generic `+ Add comparison` popover earlier, but rejected it
  because it hides the feature and adds an extra click.
- Chosen compromise: keep one always-visible search field and reveal benchmark
  recommendations inside its existing dropdown on focus. This preserves
  discoverability without permanent control clutter.
- Verified `setupTickerSuggestions()` already owns safe row construction,
  debounce, stale-response protection, click delegation, Enter selection,
  Escape, outside click, no-match, and failure states (`static/js/common.js`,
  current lines 533-672). Extend it instead of creating another dropdown.
- Verified the current dirty picker implementation is in
  `static/js/common.js` around current lines 681-793, both chart templates, and
  `static/style.css` around current lines 1055-1156.
- No backend or database change is needed.

### Implementation progress

- Superseded visible-button refinement: implemented and tested, but rejected
  before browser approval. Its dirty changes were adapted into the compact
  design rather than reverted.
- Compact search design: plan complete and approved for handoff.
- Compact search tests: written (Tests A–H; shared-factory contracts live in
  `tests/test_ticker_suggestions.py`). Confirmed red against the old visible
  works (10 failed before implementation).
- Compact search production code: implemented across `static/js/common.js`,
  `static/js/main.js`, `static/js/stock.js`, `templates/index.html`,
  `templates/stock.html`, and `static/style.css`.
- Compact search focused/full verification: `41 passed` (compare UI +
  ticker suggestions), `47 passed` (tooltip/refresh/compare), `82 passed`
  (layout/chart regressions), full suite `655 passed`. Node not installed;
  `node --check` could not run.
- Compact search browser approval: not started.
- Git commit/push: not authorized and not performed.

### Current blocker

None. Ready to continue with the new failing tests. The new thread should treat
the existing dirty changes as a base to edit, not as approved work and not as
changes to revert wholesale.

### Next steps for next agent

1. Read this appended authoritative section before acting; the earlier plan is
   superseded.
2. Run `git status --short`. Preserve untracked `comparison.html` and
   `ui-nomenclature-audit.html`; they are unrelated user files.
3. Open `tests/test_compare_ui.py`. Replace the visible quick-pick assertions
   with Tests A-H above. Add shared-factory option contracts either there or in
   `tests/test_ticker_suggestions.py`; do not duplicate equivalent assertions.
4. Run
   `python -m pytest tests/test_compare_ui.py tests/test_ticker_suggestions.py -q`
   and confirm the intended failures before production edits.
5. Implement the seven production steps in order, beginning with
   `renderSearchResults()` and `setupTickerSuggestions()` in
   `static/js/common.js`.
6. Run focused tests, regression groups, and the full suite exactly as listed.
7. Update the status in this authoritative section with test counts. Do not
   rewrite history above merely to make it look current.
8. Stop for browser GUI approval. Do not commit or push.
