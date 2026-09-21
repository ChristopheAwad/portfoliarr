# Bug Fix: Fast and Reliable Allocation Donut Refresh

## Status

SHIPPED 2026-09-20 (PR #62). All 673 tests pass (full `python -m pytest`);
dashboard GUI verified by the user before the PR was opened.

This is a performance and reliability bug fix for the existing allocation
donut carousel. It is not a new roadmap feature. Do not add a roadmap item or
change any shipped roadmap status.

The previous `feature.md` described comparison-picker work that shipped in
commit `e66c805` through PR #61. This plan replaces that stale handoff.

## Problem

The dashboard allocation donut can stay blank for too long, load malformed, or
appear to lose data after a browser refresh. The problem is most visible after
the Flask process restarts, when the selected allocation view uses company
profiles, or when Yahoo temporarily fails.

The Chart.js drawing operation is not the primary delay. The donut cannot draw
until its market-data request finishes, and the current request path has these
problems:

1. Concurrent routes can miss the same process-memory cache and make duplicate
   Yahoo requests for one symbol.
2. Sector, Country, Type, and Cap allocation views fetch company profiles one
   ticker at a time. A cold request therefore waits for the sum of all slow
   `Ticker.info` calls.
3. Repeated frontend refresh triggers can start more than one request for the
   same allocation dimension or portfolio summary.
4. The first load has no explicit donut loading state. The user sees an empty
   canvas while requests are pending.
5. A failed non-ticker refresh calls `paintAllocation([], [])`, which destroys
   a valid donut and incorrectly presents a temporary failure as an empty
   portfolio.
6. A failed portfolio-summary request leaves the By Ticker donut blank or stale
   without explaining its state.
7. The donut canvas does not have the explicit sizing rule used by the line
   chart. A hidden-to-visible transition can leave Chart.js with stale canvas
   dimensions in a browser or Android WebView.

Warm reloads are usually faster because the Python quote/profile caches and the
browser's Chart.js resource cache are already warm. That difference makes the
cold-refresh behavior look intermittent.

## Goal

Make every allocation view load as quickly as the available Yahoo response
allows and always show an honest state.

After this fix:

- concurrent callers share one in-flight quote or profile fetch per symbol;
- different symbols still fetch concurrently;
- cold profile-based allocation requests fetch eligible profiles in parallel;
- the browser starts at most one active request per allocation dimension and
  one portfolio-summary request;
- stale cached allocation data remains visible while it is refreshed;
- temporary failures never masquerade as an empty portfolio;
- first-load loading, successful empty, initial failure, and stale-after-failure
  states are visibly different;
- the displayed donut always belongs to the selected carousel dimension; and
- the donut resizes correctly after it becomes visible.

## Locked Scope

This is the focused fix approved by the user.

In scope:

- per-symbol in-flight request deduplication for `get_quote()` and
  `get_profile()`;
- bounded parallel profile loading in `/api/portfolio/allocation`;
- per-dimension frontend allocation request deduplication;
- frontend portfolio-summary request deduplication;
- stale-while-revalidate behavior for cached allocation dimensions;
- explicit donut loading, empty, unavailable, and stale-warning states; and
- explicit responsive canvas sizing plus resize-after-reveal behavior.

Out of scope:

- changing the Chart.js or annotation-plugin CDN delivery;
- changing `setupAutoRefresh()` for every page;
- redesigning all dashboard startup request scheduling;
- changing the 60-second browser refresh interval;
- changing quote, history, or allocation cache persistence;
- moving process-memory caches into SQLite;
- changing allocation calculations, supported currencies, or API response
  shapes;
- changing the six allocation dimensions, their order, localStorage format,
  arrows, swipe behavior, pagination, labels, or animations;
- adding a dependency; and
- changing database code or schema.

## Existing Contracts To Preserve

1. Successful market data only is cached. A Yahoo failure must remain
   retryable.
2. The quote cache keeps its 120-second TTL.
3. The profile cache remains process-lifetime and separate from the name
   cache.
4. Cache callers receive defensive dictionaries that they cannot mutate for
   another caller.
5. Different symbols must not wait behind one global network lock.
6. Flask routes own exception logging and HTTP degradation. `market_data.py`
   continues to raise.
7. Allocation values remain long-only, priced-only, and CAD-based.
8. USD values use the live USDCAD rate. Missing conversion excludes the ticker;
   it never assumes 1:1.
9. Unsupported currencies remain excluded.
10. Missing profile fields remain honest exclusions rather than an `Unknown`
    category.
11. Slice weights divide by classified slice values only.
12. Slices remain sorted by descending value.
13. `/api/portfolio/allocation` retains
    `{by, currency, slices, excluded}`.
14. `/api/portfolio/summary` retains its current payload, including holdings.
15. Currency allocation must not call `get_profile()`.
16. A short or flat position must not call `get_profile()` or receive a wedge.
17. Only the selected allocation dimension can paint the shared canvas.
18. By Ticker continues to use the summary response instead of the allocation
    endpoint.
19. Poll updates remain animation-free. Carousel navigation retains its
    reduced-motion-safe crossfade.
20. The page continues to use `setupAutoRefresh()` from `common.js`.

## Part 1: Write Failing Market-Data Concurrency Tests

Write tests before changing `market_data.py`.

### 1.1 Quote callers share one in-flight cache miss

Add a test to `tests/test_market_data.py` named similarly to
`test_concurrent_quote_cache_misses_share_one_yahoo_request`.

The test must:

- call `market_data.get_quote("AAPL")` concurrently from at least four worker
  threads;
- hold the fake Yahoo operation open with `threading.Event` or a barrier until
  all callers have had time to enter `get_quote()`;
- release the fake operation once the concurrent callers are waiting;
- assert that `yf.Ticker("AAPL")` or its `fast_info` network stand-in was
  invoked exactly once;
- assert that every caller receives the expected quote values; and
- assert that callers receive distinct dictionary objects.

The test must fail before implementation because each thread can currently see
the empty cache and start its own Yahoo operation.

Do not use `sleep()` as the only synchronization mechanism. Use deterministic
thread synchronization and give every wait a finite timeout so a broken test
cannot hang pytest.

### 1.2 Profile callers share one in-flight cache miss

Add a test to `tests/test_allocation.py` named similarly to
`test_concurrent_profile_cache_misses_share_one_yahoo_request`.

Use the same deterministic synchronization pattern as the quote test. Require:

- at least four concurrent `get_profile("AAPL")` calls;
- exactly one fake `Ticker.info` fetch;
- equivalent profile values for every caller; and
- distinct returned dictionaries.

### 1.3 Different quote symbols are not globally serialized

Add `test_different_quote_symbols_can_fetch_concurrently` to
`tests/test_market_data.py`.

The fake Yahoo implementation for `AAPL` and `MSFT` must wait at a two-party
barrier. Call both symbols from separate worker threads. Both calls must cross
the barrier and return successfully.

This test prevents an incorrect implementation that holds one global mutex
during all Yahoo network work. A global mutex would deduplicate requests but
would make a multi-ticker dashboard slower by fetching every symbol in series.

### 1.4 Different profile symbols are not globally serialized

Add the equivalent profile test to `tests/test_allocation.py`. Two distinct
symbols must both enter their fake `Ticker.info` operations before either is
released.

### 1.5 Quote failures wake waiters and remain retryable

Add a concurrent failure test to `tests/test_market_data.py`.

Require:

- concurrent calls for one symbol share the first in-flight operation;
- the first fake Yahoo operation raises a named exception;
- every caller finishes and receives that failure rather than hanging;
- the failed result is absent from `_cache`;
- the symbol has no stale in-flight entry after completion; and
- a later call starts one new Yahoo operation and can succeed.

Do not require permanent negative caching. Failed market data must remain
retryable.

### 1.6 Profile failures wake waiters and remain retryable

Add the equivalent test for `get_profile()` in `tests/test_allocation.py`.
Require no `_profile_cache` entry after failure and a successful later retry.

### 1.7 Preserve existing cache behavior

Keep all existing tests for:

- quote TTL expiry;
- finite-number validation;
- profile missing fields;
- empty profiles raising;
- successful process-lifetime profile caching; and
- defensive copies.

### 1.8 Run the first red tests

Run:

```bash
source .venv/bin/activate
python -m pytest tests/test_market_data.py tests/test_allocation.py -q
```

Expected pre-implementation failures are duplicate same-symbol Yahoo calls and
failure of the in-flight-map cleanup assertions. Existing tests must stay
green. If the different-symbol concurrency tests fail before implementation
because the current code already permits concurrency, record them as
regression guards rather than expected red tests.

## Part 2: Deduplicate In-Flight Market Requests

Edit `market_data.py` only after Part 1 has produced the intended failures.

### 2.1 Add coordination state

Use one short-held `threading.Lock` to protect cache inspection and in-flight
map mutation. Add two separate in-flight maps:

- quote symbol to `concurrent.futures.Future`; and
- profile symbol to `concurrent.futures.Future`.

The maps coordinate work only while a request is running. They are not caches
and must not retain completed entries.

Do not hold the coordination lock while calling yfinance. The lock can protect
dictionary operations, but unrelated symbols must perform network work in
parallel.

### 2.2 Change `get_quote()`

Implement this exact ownership flow:

1. Normalize nothing new; retain the caller's current symbol contract.
2. Acquire the coordination lock.
3. Check `_cache` and return a defensive copy when the entry is still inside
   `TTL_SECONDS`.
4. If an in-flight future already exists for the symbol, retain that future and
   mark this caller as a waiter.
5. Otherwise create and store a future and mark this caller as the owner.
6. Release the lock.
7. A waiter calls `future.result()` outside the lock and returns a defensive
   copy of the successful dictionary. The same exception must propagate if the
   owner fails.
8. The owner performs the existing `fast_info` fetch, validation, and payload
   construction outside the lock.
9. On success, acquire the lock, write the completed quote and a completion-time
   `fetched_at`, complete the future, and remove that exact future from the
   in-flight map.
10. On failure, acquire the lock, complete the future with the exception, remove
    that exact future, and re-raise.

Use an identity check before removing an in-flight entry so cleanup cannot
delete a newer future if later code changes allow an immediate retry.

Successful data remains the only data written to `_cache`.

### 2.3 Change `get_profile()`

Use the same owner/waiter flow with `_profile_cache` and the profile in-flight
map.

Preserve:

- the existing `Ticker.info` source;
- empty-profile `ValueError` behavior;
- the four returned fields;
- finite market-cap filtering; and
- defensive copies for owners, waiters, and later cache hits.

### 2.4 Keep cache clearing safe

`clear_market_caches()` must clear completed cache data as it does now. Tests
call it only when no market operation is active. Do not add production logic
that cancels active futures or leaves waiters blocked.

Add short comments beside the lock and in-flight maps. Explain that the lock is
released before Yahoo calls so same-symbol work is deduplicated without
serializing different symbols.

### 2.5 Verify the data layer

Run:

```bash
python -m pytest tests/test_market_data.py tests/test_allocation.py -q
```

All concurrency, retry, TTL, validation, and defensive-copy tests must pass
before changing the route.

## Part 3: Write a Failing Allocation-Route Parallelism Test

Add the route test to `tests/test_allocation.py` before editing `app.py`.

### 3.1 Prove eligible profiles overlap

Add `test_profile_dimensions_fetch_eligible_profiles_in_parallel`.

The test must:

- seed at least three positive, priced, supported-currency holdings;
- patch `app_module.get_profile`, because the route uses the imported name;
- make each fake profile call wait at a barrier whose party count equals the
  number of eligible symbols;
- give the barrier a finite timeout;
- request `/api/portfolio/allocation?by=sector`;
- assert every profile call crossed the barrier;
- assert every ticker appears in the correct slice; and
- assert the route retains its value, weight, and sorting contracts.

The current serial profile loop must fail this test. A broken barrier must make
the route result fail its slice assertions rather than hang the suite.

### 3.2 Lock the eligible-symbol boundary

Add or extend tests to prove profile workers are not started for:

- a quote failure;
- a flat position;
- a short position;
- an unsupported quote currency; and
- a USD holding when the required live USDCAD conversion failed.

Retain the existing Currency test that proves `get_profile()` is never called.

### 3.3 Preserve per-symbol failure degradation

Keep the existing profile-failure test and strengthen it if necessary so one
worker failure excludes only that symbol while successful workers still
produce slices.

### 3.4 Run the route red test

Run:

```bash
python -m pytest tests/test_allocation.py -q
```

The new profile-overlap test must fail before the route change. Existing
grouping and resilience tests must remain green.

## Part 4: Parallelize Cold Profile Loading

Edit `portfolio_allocation()` in `app.py`.

### 4.1 Identify eligible symbols first

After quotes and the optional live FX rate are available, derive the symbols
that can contribute to a profile-based allocation:

- `held > 0`;
- quote exists;
- quote currency is CAD or USD; and
- a USD quote has an available live USDCAD rate.

Do not fetch a profile for a symbol that already has a final exclusion reason
or cannot receive a wedge.

### 4.2 Skip profile work for Currency

When the selected dimension has `profile_field is None`, do not create a
profile executor and do not call `get_profile()`.

### 4.3 Fetch profiles through a bounded pool

For Sector, Country, Type, and Cap:

- define a small route-local worker that returns `(symbol, profile)`;
- catch and log `get_profile()` failures at the route boundary;
- return `(symbol, None)` for a failed profile;
- use `ThreadPoolExecutor(max_workers=min(len(eligible_symbols), 8))` when the
  list is non-empty; and
- collect results into a symbol-keyed dictionary before aggregation.

Do not make Flask calls, database calls, or `jsonify()` calls in worker
threads.

### 4.4 Aggregate with the prefetched profiles

Keep the existing aggregation pass and exclusion wording. Replace the serial
`get_profile(symbol)` call with the prefetched dictionary lookup.

The response must be byte-for-byte equivalent in shape and equivalent in
meaning. Only request timing and execution order change.

### 4.5 Verify the route

Run:

```bash
python -m pytest tests/test_allocation.py tests/test_portfolio_summary.py -q
```

All allocation calculations and failure paths must pass.

## Part 5: Write Failing Frontend State Contracts

The repository does not run JavaScript in pytest. Add narrow source-contract
tests to `tests/test_allocation_ui.py`; do not snapshot whole functions or add a
JavaScript dependency.

### 5.1 One in-flight request per allocation dimension

Replace the generation-based same-dimension test with a test that requires:

- one `allocInFlight` object keyed by dimension;
- `fetchAllocDimension(by)` to return the existing promise when that key is
  already in flight;
- a newly created promise to be stored before callers can start another fetch;
- cleanup in `finally`; and
- cleanup to delete only the promise that is still registered for that key.

Remove requirements for `allocRequestGenerations` and
`isLatestAllocRequest()`. Same-key requests cannot arrive out of order when
only one can exist.

### 5.2 Retain active-view protection

Keep a source contract that successful and failed requests inspect
`isActiveAllocView(by)` before changing visible state.

A request may populate its cache after the user leaves that slide. It must not
paint or show a warning on another slide.

### 5.3 Stale-while-revalidate

Add a test that requires an existing `allocCache[by]` entry to paint before a
stale entry starts its network refresh. A fresh entry must still paint and
return without fetching.

The cached entry can contain a successful empty result. Do not use truthiness
of `slices.length` as the test for whether a valid cache entry exists.

### 5.4 Failed refresh preserves valid state

Add contracts that require the allocation catch path to:

- avoid `paintAllocation([], [])`;
- keep the matching last valid data visible when it exists;
- show a stale warning for that selected dimension; and
- show an unavailable state when no valid result exists for the selected
  dimension.

### 5.5 Portfolio summary is single-flight

Add a test that requires one module-level summary promise. Repeated
`refreshPortfolioSummary()` calls must return that promise while it is active,
and `finally` must clear it after success or failure.

### 5.6 By Ticker failure states

Add contracts requiring the summary failure and `nothingPriced` paths to
update donut state when By Ticker is active:

- retain the previous By Ticker donut and mark it stale if valid prior ticker
  data exists; and
- otherwise show unavailable, never a successful empty-portfolio message.

The portfolio header's existing unavailable behavior must remain.

### 5.7 Explicit accessible status markup

Add a rendered-template test requiring one allocation status element inside
`.donut-card` with:

- `id="alloc-status"`;
- `class="empty-state"` or an existing compatible quiet status style;
- `role="status"`;
- `aria-live="polite"`; and
- initial text `Loading allocation...`.

Require the donut box to start hidden until valid data is painted. Use the HTML
`hidden` attribute rather than an inline `display` declaration.

### 5.8 Distinct state messages

Add narrow source assertions for four semantic states:

- loading before the selected dimension has returned;
- successful empty using the existing no-priced-holdings wording;
- unavailable after initial failure; and
- stale warning after a refresh failure with valid prior data.

Do not lock punctuation if that would make the test brittle. Lock the distinct
state-setting calls and their important wording.

### 5.9 Canvas sizing and reveal resize

Add CSS and JavaScript source contracts requiring:

- `.donut-box` to keep its fixed height and positioned ancestor;
- `.donut-box > canvas` to use `display: block`;
- width and height to be `100% !important`, matching `.chart-box > canvas`;
- a scheduled `allocationChart.resize()` after a hidden donut box is revealed;
  and
- the resize to tolerate a null chart handle.

Use `requestAnimationFrame()` for the resize so layout has completed before
Chart.js measures the box.

### 5.10 Run the frontend red tests

Run:

```bash
python -m pytest tests/test_allocation_ui.py -q
```

Expected failures include no in-flight promise map, destructive failure paint,
no explicit status element, no donut canvas sizing rule, and no reveal resize.

## Part 6: Implement Frontend Request Coordination

Edit `static/js/main.js` after Part 5 is red.

### 6.1 Track valid displayed data

Keep these pieces of state local to the allocation section:

- the existing per-dimension `allocCache`;
- an `allocInFlight` object keyed by non-ticker dimension;
- the dimension key represented by the currently displayed chart, where
  `null` means By Ticker; and
- whether successful By Ticker data has been received.

Do not add localStorage fields. Only the existing selected index persists.

### 6.2 Replace request generations with one promise per key

Refactor `fetchAllocDimension(by)` in this order:

1. Read any cache entry.
2. If it exists, paint it immediately when `by` is active.
3. If it exists and is fresh, return without fetching.
4. If no cache entry exists and `by` is active, show loading unless the exact
   same dimension already has valid displayed data.
5. If `allocInFlight[by]` exists, return that promise.
6. Create an async request promise and store it in `allocInFlight[by]` before
   yielding control.
7. On success, cache `{data, fetchedAt}` and paint only if `by` is still active.
8. On failure, log once and change visible state only if `by` is still active.
9. In `finally`, delete the map entry only when it still equals this request
   promise.
10. Return the promise to every caller.

Do not use `AbortController` for this fix. Cached background completion is
useful when the user returns to a slide.

### 6.3 Preserve stale data on allocation failure

If the selected dimension has a prior successful cache entry, repaint or retain
that exact entry and show the stale-warning state. Do not change its
`fetchedAt`; it must stay stale and retry on the next refresh.

If it has no prior successful entry, hide data from any previous dimension and
show unavailable.

Never call `paintAllocation([], [])` from a request catch block. Empty arrays
are valid only when the server successfully returned an empty result.

### 6.4 Make portfolio summary single-flight

Wrap the existing summary fetch/paint operation in one stored promise:

- return the existing promise when present;
- preserve every current summary paint and privacy behavior;
- clear the promise in `finally`; and
- continue to catch and log at the frontend boundary.

Do not debounce or delay the initial summary request.

### 6.5 Handle By Ticker degradation honestly

On a successful summary response, cache and paint its holdings as now.

If all quotes failed (`nothingPriced`) or the summary request failed:

- when By Ticker is active and prior successful ticker slices exist, retain
  them and show the stale warning;
- when By Ticker is active without prior successful ticker slices, hide any
  other dimension and show unavailable; and
- when another view is active, do not alter that view's visible donut status.

Do not treat `[]` as failure. A successful summary can honestly report no
holdings.

## Part 7: Implement Explicit Donut States and Sizing

Edit `templates/index.html`, `static/js/main.js`, and `static/style.css`.

### 7.1 Add status markup

Inside `.donut-card`, keep the header first. Add the status element before or
after `.donut-box`, but keep it in the card and outside the canvas box.

Initial markup:

```html
<p id="alloc-status" class="empty-state" role="status"
   aria-live="polite">Loading allocation...</p>
```

Add `hidden` to `.donut-box` initially. Keep pagination and the excluded note in
their current order and preserve all existing IDs.

### 7.2 Replace the dynamically created empty paragraph

Remove the JavaScript-created `donutEmptyState`. Use the template's persistent
`#alloc-status` element for all non-chart state and refresh warnings.

Create small state functions with one responsibility each, or one function
with an explicit state argument. It must support:

- loading: chart hidden when no matching valid data exists, status visible;
- ready: chart visible, status hidden;
- empty: chart hidden, status visible with the no-holdings message;
- unavailable: chart hidden, status visible with failure wording; and
- stale: matching chart remains visible, status visible with warning wording.

Use `hidden` properties or attributes as the source of truth. Do not mix them
with inline `style.display` state.

### 7.3 Prevent cross-dimension stale displays

When loading an uncached slide, data from the previously selected dimension
must not remain visible under the new label. Hide the box and show loading.

Only show stale data when its recorded dimension key equals the selected key.

### 7.4 Paint successful empty responses

`paintAllocation()` must continue to destroy the Chart.js instance after a
successful empty response so no obsolete wedges remain associated with an
honest empty result. Record the dimension as successfully loaded even when its
slice list is empty.

This is different from a catch path, which must never pass fabricated empty
arrays into the painter.

### 7.5 Resize after reveal

When ready or stale state changes `.donut-box.hidden` from true to false,
schedule:

```javascript
requestAnimationFrame(() => allocationChart?.resize());
```

Creating a new chart can proceed normally. Updating an existing hidden chart
must still receive the scheduled resize after reveal.

### 7.6 Add the canvas sizing contract

Immediately after `.donut-box`, add:

```css
.donut-box > canvas {
    display: block;
    width: 100% !important;
    height: 100% !important;
}
```

Do not change the 220px donut-box height in this fix.

### 7.7 Preserve carousel behavior

Keep:

- the six-view source array;
- saved `allocationDimension` parsing;
- previous/next wrapping;
- clickable pagination dots;
- position counter;
- swipe threshold;
- crossfade on deliberate navigation only;
- reduced-motion behavior;
- excluded-ticker note; and
- tooltip privacy behavior.

## Part 8: Focused Verification

Run the core changed areas:

```bash
source .venv/bin/activate
python -m pytest \
  tests/test_market_data.py \
  tests/test_allocation.py \
  tests/test_allocation_ui.py \
  tests/test_portfolio_summary.py -q
```

Run nearby frontend and route regressions:

```bash
python -m pytest \
  tests/test_ui_redesign.py \
  tests/test_web_refresh_wiring.py \
  tests/test_routes.py \
  tests/test_quote.py \
  tests/test_ledger_groups.py -q
```

If Node is available, run:

```bash
node --check static/js/main.js
```

Node was not installed during the prior feature. Its absence is not a pytest
failure; report it accurately.

## Part 9: Full-Suite Gate

The lead agent must run:

```bash
source .venv/bin/activate
python -m pytest
```

Do not report implementation complete unless the full suite passes. Do not
weaken existing tests to accommodate this fix.

## Part 10: Browser GUI Approval Gate

After pytest is green, stop and wait for the user's browser approval before any
commit or push.

### Cold-load preparation

- Restart the Flask process so quote and profile caches are empty.
- Open the dashboard with browser developer tools visible.
- Test once with By Ticker saved and once with a profile-based view such as By
  Sector saved.

### Initial loading

- The selected view label and pagination position are correct immediately.
- `Loading allocation...` appears instead of an unexplained blank canvas.
- Data from a previously selected dimension never appears under the new label.
- The donut becomes visible when its data arrives.
- The donut has a circular shape and correct legend placement on first paint.

### Profile-based cold load

- Sector, Country, Type, and Cap no longer wait for profiles one ticker at a
  time.
- The request completes near the duration of the slowest worker batch, not the
  sum of every ticker's profile duration.
- Currency remains faster and does not require profile metadata.

### Refresh and stale behavior

- Refresh after a successful load keeps the existing donut visible while new
  data is pending.
- A temporary failed refresh keeps the previous valid donut and displays a
  clear stale warning.
- A first-load failure displays unavailable, not the no-holdings message.
- Reconnecting and triggering refresh restores ready state without reloading
  the page.
- A successful genuinely empty portfolio shows the existing no-holdings
  message.

### Rapid interaction

- Click arrows and pagination dots quickly across all six views.
- Swipe rapidly on a phone-sized viewport.
- The selected label, dots, counter, wedges, legend, tooltip, excluded note,
  and status always refer to the same dimension.
- Repeated selection of one stale dimension does not launch duplicate browser
  requests while its first request remains active.

### Layout and recovery

- Test desktop and phone widths in light and dark themes.
- Hide and restore the tab, then return to the donut.
- If available, repeat the hide/restore test in Android WebView.
- The canvas fills its 220px box after every hidden-to-visible transition.
- No zero-size canvas, clipped legend, horizontal overflow, or stretched donut
  appears.
- Reduced-motion preference still disables the crossfade and first-build
  Chart.js animation as before.

## Success Criteria

Implementation is complete only when all of these are true:

1. Concurrent same-symbol quote misses perform one Yahoo quote operation.
2. Concurrent same-symbol profile misses perform one Yahoo profile operation.
3. Different symbols still perform network operations concurrently.
4. Failed market operations wake all waiters, cache nothing, and permit retry.
5. Profile-based allocation requests use at most eight workers and preserve all
   existing response semantics.
6. One browser request exists per active allocation dimension at a time.
7. One portfolio-summary browser request exists at a time.
8. No request failure destroys valid donut data or pretends the portfolio is
   empty.
9. Every first load has a visible loading or error explanation.
10. The displayed chart and status always belong to the selected dimension.
11. The donut canvas has correct dimensions after it is revealed.
12. Focused tests and the full pytest suite pass.
13. The user approves the browser behavior.

## Files Expected To Change During Implementation

- `feature.md`: plan, progress, verification results, and final handoff.
- `market_data.py`: per-symbol quote/profile in-flight coordination.
- `app.py`: bounded parallel profile retrieval in the allocation route.
- `static/js/main.js`: request coordination, stale cache behavior, and donut
  states.
- `static/style.css`: explicit donut canvas sizing.
- `templates/index.html`: persistent accessible allocation status element and
  initial hidden canvas box.
- `tests/test_market_data.py`: quote concurrency and retry tests.
- `tests/test_allocation.py`: profile concurrency and route parallelism tests.
- `tests/test_allocation_ui.py`: frontend state, request, markup, and sizing
  contracts.

No expected changes:

- `roadmap.md`;
- `project-brief.md`;
- `db.py`;
- `static/js/common.js`;
- `templates/base.html`;
- dependency files;
- API response shapes; or
- Docker and Android files.

## Worktree Note

The untracked files `comparison.html` and `ui-nomenclature-audit.html` are user
files unrelated to this bug. Do not edit, delete, stage, or commit them.

Do not commit or push until implementation passes pytest, the user approves the
browser behavior, and the user explicitly authorizes git action.
