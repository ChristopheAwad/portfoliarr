# Feature #20: Dashboard Market Overview Tabs

## Status

PLANNED - awaiting implementation. The product direction and this test-first
plan were approved on 2026-09-22. Roadmap item #20 is in progress.

Do not implement a different instrument set, add a market breadth roll-up, or
replace the requested `Live` label without new user approval.

## Problem

The dashboard currently renders four independent market chips after the
portfolio headline and before the portfolio chart. This placement makes the
chips look like portfolio or chart metadata. They are intended to answer a
broader question first: "What do the markets look like today?"

The current bar is also too narrow for that job. It contains only the S&P 500,
Nasdaq, TSX, and Bitcoin, with no way to inspect Europe, Asia-Pacific, other
major cryptocurrencies, commodities, or currencies.

## Goal

Turn the existing index chips into a full-width, tabbed market overview at the
top of the dashboard, before the complete portfolio section.

The overview must:

1. Appear before the `Your Portfolio` headline and all portfolio values.
2. Present one cohesive market strip rather than unrelated floating cards.
3. Offer North America, Europe, Asia-Pacific, Crypto, Commodities, and
   Currencies tabs.
4. Fetch only the active category on initial load, tab selection, and polling.
5. Keep every instrument as a real link to its existing stock-detail page.
6. Preserve per-symbol failure handling so one failed Yahoo quote cannot blank
   its category.
7. Work on desktop and mobile without widening the viewport.
8. Keep the visible `Live` label requested by the user.

## Approved Product Decisions

1. The section heading is `Markets today`.
2. A small visible `Live` label sits with the section heading.
3. Do not add a sentence such as `3 of 4 higher`. These instruments overlap,
   so that count would not be honest market-breadth data.
4. The category order is fixed:
   - North America
   - Europe
   - Asia-Pacific
   - Crypto
   - Commodities
   - Currencies
5. North America is the default category on every fresh dashboard load.
6. Do not persist the selected tab in localStorage or sessionStorage in this
   feature.
7. The approved market configuration is:

| Category key | Label | Yahoo symbol | Display label |
|---|---|---|---|
| `north-america` | North America | `^GSPC` | S&P 500 |
| `north-america` | North America | `^IXIC` | Nasdaq |
| `north-america` | North America | `^GSPTSE` | TSX |
| `north-america` | North America | `^RUT` | Russell 2000 |
| `europe` | Europe | `^STOXX` | STOXX Europe 600 |
| `europe` | Europe | `^FTSE` | FTSE 100 |
| `europe` | Europe | `^GDAXI` | DAX |
| `europe` | Europe | `^FCHI` | CAC 40 |
| `asia-pacific` | Asia-Pacific | `^N225` | Nikkei 225 |
| `asia-pacific` | Asia-Pacific | `^HSI` | Hang Seng |
| `asia-pacific` | Asia-Pacific | `000001.SS` | Shanghai Composite |
| `asia-pacific` | Asia-Pacific | `^NSEI` | Nifty 50 |
| `asia-pacific` | Asia-Pacific | `^AXJO` | ASX 200 |
| `crypto` | Crypto | `BTC-USD` | Bitcoin |
| `crypto` | Crypto | `ETH-USD` | Ethereum |
| `crypto` | Crypto | `SOL-USD` | Solana |
| `crypto` | Crypto | `XRP-USD` | XRP |
| `commodities` | Commodities | `GC=F` | Gold |
| `commodities` | Commodities | `CL=F` | WTI Oil |
| `commodities` | Commodities | `HG=F` | Copper |
| `commodities` | Commodities | `NG=F` | Natural Gas |
| `currencies` | Currencies | `CADUSD=X` | CAD/USD |
| `currencies` | Currencies | `CADEUR=X` | CAD/EUR |
| `currencies` | Currencies | `CADGBP=X` | CAD/GBP |
| `currencies` | Currencies | `CADJPY=X` | CAD/JPY |

8. Currency pairs all use CAD as the base. The Currencies panel includes the
   short explanatory caption `1 CAD buys`.
9. Positive currency movement therefore consistently means that CAD
   strengthened against the displayed quote currency.
10. Keep Natural Gas in Commodities. Do not substitute Wheat in this feature.
11. Daily percentage movement is visually more prominent than absolute point
    movement because percentages are comparable across instruments.
12. Continue to show the current level, absolute daily move, percentage daily
    move, and Yahoo-provided native currency. Do not invent conversions.
13. Currency levels need adaptive precision. Values with an absolute value
    below 1 use four decimal places; all other market levels keep the existing
    two-decimal presentation. Do not globally change `formatPrice`, because
    portfolio and stock-page money formatting remains two decimals.
14. On desktop, the active category is one bordered strip divided into equal
    instrument cells. Individual cells do not get separate card shadows.
15. The five-instrument Asia-Pacific category must fit the same strip without
    hard-coding a four-column layout.
16. On phones, category tabs may scroll horizontally, but the instrument panel
    uses a two-column grid. Do not create nested horizontal scrolling for both
    tabs and instruments.
17. An odd fifth instrument stays one normal-width grid cell. It must not
    stretch across both phone columns.
18. Each instrument cell remains a plain anchor with native Enter,
    open-in-new-tab, and middle-click behavior.
19. The existing green/red semantics remain: zero counts as positive, matching
    the current chip behavior.
20. Failed symbols display `—` and no stale change. Successful siblings remain
    visible.
21. If every symbol in the active category fails, all cells in that panel show
    `—`; no global modal or toast is added.
22. This feature does not add market-open detection, timestamps, breadth,
    interest rates, bonds, market signals, sectors, Latin America, Africa, or
    Middle East categories.

## Backend Contract

### Market Configuration

Replace the single flat product configuration with one ordered market-category
configuration in `app.py`. Use insertion order as the category and instrument
display order. Each category stores its human label and ordered instruments;
each instrument stores its Yahoo symbol and display label.

Keep `INDEX_SYMBOLS` available as an ordered flat list derived from the market
configuration, not as a second manually maintained source. Existing comparison
recommendation tests use it to confirm that supported benchmark symbols exist.

The `/` route passes the category configuration to `templates/index.html` so
Jinja renders tabs, panels, labels, symbols, and stock-detail links from the
same backend source used by the API. Do not duplicate all symbols in template
markup or JavaScript.

### `GET /api/indices`

1. Accept an optional `category` query parameter.
2. Missing or empty `category` selects `north-america`, preserving the current
   no-query smoke-check URL.
3. A recognized category fetches only that category's symbols.
4. An unknown category returns HTTP 400 with
   `{ "error": "invalid market category" }` before any quote call.
5. Keep parallel quote fetching, but size the worker pool from the selected
   category only, capped at eight workers.
6. Keep wide exception handling and warning logging at the route boundary for
   each failed symbol.
7. Return successful quote objects only, in the configured category order.
8. If some symbols fail, return HTTP 200 with successful siblings only.
9. If every selected symbol fails, return the existing HTTP 503 payload
   `{ "error": "quote service unavailable" }`.
10. Logging must identify the selected category and relevant symbol/count so a
    failure can be diagnosed from server output.
11. Do not fetch or return symbols from inactive categories.
12. Do not change `market_data.get_quote`, its cache, or its native quote
    payload.

## Template And Accessibility Contract

Move the market section to the first dashboard content inside `<main>`, before
`.stock-header-card`.

Render:

1. One semantic `<section>` labelled by the `Markets today` heading.
2. The visible `Live` label beside the heading.
3. One tab list with six real `<button type="button">` controls.
4. Stable ids that connect each tab's `aria-controls` to its panel and each
   panel's `aria-labelledby` back to its tab.
5. `role="tablist"`, `role="tab"`, and `role="tabpanel"` semantics.
6. North America with `aria-selected="true"` and `tabindex="0"`.
7. All inactive tabs with `aria-selected="false"` and `tabindex="-1"`.
8. North America visible initially; every inactive panel has `hidden`.
9. Every instrument anchor with `class="market-item"`, `data-symbol`, and a
   `url_for('stock_page', symbol=...)` href generated from the same configured
   symbol.
10. Empty level and change spans so CSS loading skeletons cannot be mistaken
    for market data.
11. The `1 CAD buys` caption only in the Currencies panel.

Keyboard tab behavior follows the WAI-ARIA tabs pattern:

1. Click activates the selected tab.
2. Left and Right arrows move focus and selection, wrapping at both ends.
3. Home selects the first tab.
4. End selects the last tab.
5. Activation updates `aria-selected`, roving `tabindex`, and panel `hidden`
   states together.
6. The newly active category fetch starts immediately after activation.

## Frontend Data Contract

Refactor the top market code in `static/js/main.js` around the active panel:

1. Track the active category from the selected tab's `data-category`.
2. Scope managed instruments to the requested panel. Never reset or gap-fill
   hidden panels while processing another category's response.
3. Build the request with `URLSearchParams` or equivalent safe encoding:
   `/api/indices?category=<active-key>`.
4. Set an unrequested panel's values to empty so its skeleton is visible on
   first activation.
5. Set only the requested panel to loading before its fetch.
6. Paint each response by `data-symbol`, not DOM position.
7. Gap-fill unanswered symbols in that panel with `—` and clear their changes.
8. On HTTP, JSON, or network failure, mark only that requested panel
   unavailable.
9. Protect rapid tab switching and overlapping poll/tab requests with a
   monotonically increasing request token per category. An older response must
   not overwrite a newer response for that same category.
10. A response for a panel that became inactive may populate that hidden panel,
    but it must not switch tabs or alter the active panel.
11. Keep user-entered category choice during ordinary polling; polling refreshes
    the active category only.
12. The one existing `setupAutoRefresh` callback calls the active-category
    market refresh. Do not add `setInterval`.
13. Use a market-specific formatter for levels. Currency pairs below 1 get
    four decimals; other levels get two. Absolute change uses the same
    precision decision as its level. Percentage change remains two decimals.
14. Do not change shared portfolio, ledger, watchlist, stock-page, or chart
    formatters.

## Visual Contract

Preserve the current printed-money identity: Fraunces display headings,
Instrument Sans data, paper-like cards, ink navy/gold accents, and existing
positive/negative colors.

Desktop and tablet:

1. The heading row and category tabs read as one section above the portfolio.
2. The panel is one bordered, rounded, card-background strip with the existing
   small shadow.
3. Instruments use equal grid tracks based on that panel's actual item count.
4. Hairline dividers separate instruments; cells do not look like six SaaS
   cards.
5. Hover and `:focus-visible` identify the complete cell as a link without
   shifting the whole strip.
6. Long labels such as `Shanghai Composite` and `STOXX Europe 600` do not force
   page overflow.
7. Figures use tabular numerals.
8. The daily percentage has stronger weight than the absolute daily move.

Phone, at the existing 600px breakpoint:

1. The category tab list scrolls horizontally with its scrollbar hidden, using
   the repository's plain-overflow rule. Do not add scroll snap or legacy
   `-webkit-overflow-scrolling`.
2. The active market panel becomes a two-column grid.
3. Borders adapt so cells retain clear separation without double-thick lines.
4. The page viewport does not grow wider than the device.
5. Each tab and linked market cell keeps a practical touch target.
6. The existing bottom tab bar must remain stable while category tabs scroll.

Reduced motion:

1. Loading shimmer follows the existing reduced-motion rule.
2. Do not add automatic carousel movement, sliding panels, or decorative entry
   animation.

## Existing Contracts To Preserve

1. `/api/indices` remains the live-smoke endpoint and works without a query.
2. Quote responses contain raw finite floats from `market_data.get_quote`.
3. Market instruments stay in native quote currency.
4. One failed symbol does not remove successful siblings.
5. HTTP 503 occurs only when all requested symbols fail.
6. Stock links percent-encode symbols such as `^GSPC`, `GC=F`, and `CADUSD=X`
   through `url_for` and round-trip through `/stock/<symbol>`.
7. Comparison recommendations for S&P 500, Nasdaq, and TSX remain supported by
   `INDEX_SYMBOLS`.
8. Dashboard portfolio summary, history chart, comparison overlays,
   watchlist, volume leaders, allocation carousel, privacy state, and polling
   cadence do not change.
9. `setupAutoRefresh` remains the sole dashboard polling owner.
10. No database, transaction, FX conversion, Android, Docker, dependency, or
    market-data-cache change is part of this feature.
11. Backend data stays unformatted; frontend code owns number text and
    positive/negative classes.
12. Failed and unrequested data never masquerades as a live value.

## Files

Production:

- `app.py` - ordered market configuration, dashboard template context, and
  category-aware `/api/indices` validation/fetching.
- `templates/index.html` - move the market overview above the portfolio and
  render accessible tabs/panels from backend configuration.
- `static/js/main.js` - tab behavior, active-panel quote fetching, adaptive
  market precision, race protection, and active-category polling.
- `static/style.css` - cohesive market strip, tabs, loading/failure states,
  desktop item-count layout, phone two-column layout, focus, and dark mode.
- `project-brief.md` - replace the old fixed four-chip wording with the durable
  tabbed-market contract after implementation is complete.

Tests:

- `tests/test_routes.py` - category API behavior, configuration order, partial
  and total failures, default behavior, validation, and rendered links.
- `tests/test_market_tabs.py` - focused template, JavaScript source/meta, CSS,
  accessibility, responsive, precision, and polling contracts.
- `tests/test_compare_ui.py` - adjust the flat-symbol compatibility assertion
  only if the configuration refactor requires it; preserve recommendation
  coverage.

Planning:

- `feature.md`
- `roadmap.md`

## Test-First Plan

Write all tests in sections A-E before production edits. Run the focused tests
and confirm they fail because the category configuration, query validation,
tabbed markup, scoped fetching, and new layout do not exist. Do not weaken
existing index failure tests to make the new tests pass.

### A. Backend Configuration And Route Tests - `tests/test_routes.py`

1. Replace assumptions that `INDEX_SYMBOLS` is manually declared with a test
   that the flattened list exactly equals the symbols from all ordered market
   categories, with no duplicates.
2. Assert the six category keys and labels exactly match the approved order.
3. Assert every category's exact ordered `(symbol, display label)` pairs,
   including all five Asia-Pacific instruments and all CAD-base currency pairs.
4. Update the no-query success test to seed North America only and assert the
   response contains exactly North America in configured order.
5. Add a test that an empty `?category=` also defaults to North America.
6. Parameterize all six valid category keys. For each key, seed only that
   category and assert HTTP 200 and exact configured response order.
7. Add a category-isolation test that records calls to `get_quote`; request
   Europe and assert no North America, Asia-Pacific, Crypto, Commodities, or
   Currencies symbol was called.
8. Add an invalid-category test. Assert HTTP 400, exact error payload, and zero
   quote calls.
9. Adapt the existing partial-failure test to a non-default category. Seed two
   Europe symbols, leave the others failed, and assert HTTP 200 with only the
   successful symbols in configured order.
10. Parameterize total failure for a four-symbol category and the five-symbol
    Asia-Pacific boundary. Assert HTTP 503 and the existing error payload.
11. Assert a zero change quote remains a successful object; failure handling
    must not confuse a zero with missing data.
12. Capture logs for one partial failure and assert the category and failed
    symbol are identifiable.
13. Capture logs for all-failed and assert the selected category and selected
    symbol count are identifiable.
14. Preserve the existing stock-detail encoded-symbol round-trip test and add
    representative `=` and dot symbols: `GC=F`, `CADUSD=X`, and `000001.SS`.
15. Keep `test_compare_ui.py` proving S&P 500, Nasdaq, and TSX remain in the
    flattened supported-symbol list.

### B. Rendered Template And Accessibility Tests - `tests/test_market_tabs.py`

1. Request `/` and assert the `Markets today` heading and visible `Live` text
   occur before `Your Portfolio` and `portfolio-value` in rendered HTML.
2. Assert one tablist and exactly six tab buttons in approved order.
3. Assert North America is selected/focusable and all other tabs are
   unselected with `tabindex="-1"`.
4. Assert every tab and panel has a unique, reciprocal
   `aria-controls`/`aria-labelledby` id pair.
5. Assert North America is initially visible and all other panels are hidden.
6. Assert every configured symbol appears exactly once as a market-item
   `data-symbol` and has the correctly URL-encoded stock-detail href.
7. Assert rendered item labels come from the approved configuration.
8. Assert each market level and change span ships empty, with no hard-coded
   quote-like number.
9. Assert only the Currencies panel contains `1 CAD buys`.
10. Assert no market breadth phrase such as `higher`, `lower`, or `of 4`
    appears in the market section.
11. Assert market cells are anchors rather than buttons or JavaScript-only
    clickable wrappers.
12. Assert tab controls are `type="button"` so they cannot submit a future
    surrounding form.

### C. Frontend Behavior Source/Meta Tests - `tests/test_market_tabs.py`

1. Extract the market-overview JavaScript block and assert it reads the active
   tab's category rather than using a constant flat chip list.
2. Assert the API request includes the selected `category` query parameter.
3. Assert managed market items are queried within a category panel, not across
   the whole document.
4. Assert response painting still finds instruments by `data-symbol` rather
   than array index.
5. Assert unanswered symbols receive `—` and have stale change text cleared.
6. Assert fetch/HTTP/JSON failures update only the requested panel.
7. Assert a per-category request token is incremented and checked before a
   response paints, protecting newer same-category data.
8. Assert activation synchronizes `aria-selected`, roving `tabindex`, and
   panel `hidden` state.
9. Assert click, ArrowLeft, ArrowRight, Home, and End are handled.
10. Assert arrow navigation wraps first-to-last and last-to-first.
11. Assert selecting a tab triggers an immediate refresh for that category.
12. Assert the dashboard boot performs one North America market request, not
    eager requests for all six categories.
13. Assert the existing `setupAutoRefresh` callback refreshes the active
    category only.
14. Assert no new `setInterval` exists in `main.js`.
15. Assert no localStorage or sessionStorage key is introduced for market tabs.
16. Assert market formatting uses four decimals below absolute value 1 and two
    otherwise, for both level and absolute move.
17. Assert percentage formatting remains two decimals.
18. Assert `formatPrice` in `common.js` is not modified to four decimals.
19. Assert zero change gets the positive class and explicit plus/neutral text
    according to the current behavior rather than becoming unavailable.
20. Assert switching tabs does not call history, portfolio-summary,
    allocation, watchlist, or volume-leader refresh functions.

### D. CSS And Responsive Contract Tests - `tests/test_market_tabs.py`

1. Assert the active panel uses CSS Grid with dynamic equal-width tracks, not
   a fixed four-column declaration.
2. Assert the panel has one outer border/background/radius/shadow treatment.
3. Assert market items do not get individual box shadows.
4. Assert market levels and changes use tabular numerals.
5. Assert positive and negative values continue to use existing theme tokens.
6. Assert linked cells have a visible `:focus-visible` rule.
7. Assert long labels can shrink or wrap without forcing horizontal page
   overflow (`min-width: 0` and suitable overflow/wrap behavior).
8. Assert the phone media query makes the panel exactly two columns.
9. Assert the phone rule does not make the last odd item span two columns.
10. Assert the phone category tablist has plain horizontal overflow.
11. Assert the phone tablist rule contains neither scroll snap nor legacy
    `-webkit-overflow-scrolling`.
12. Assert market panel items do not use horizontal overflow on phones.
13. Assert market tab scrollbars are visually hidden while scrolling remains
    enabled.
14. Assert loading skeleton animation is disabled by the existing
    `prefers-reduced-motion` handling.
15. Preserve the existing chart-timeframe and dashboard-grid overflow tests.

### E. Regression Tests

1. Keep existing `/api/indices` no-query smoke behavior green.
2. Run all current `tests/test_routes.py` index partial/all-failure tests after
   adapting their fixture data to North America defaults.
3. Run `tests/test_compare_ui.py` to protect benchmark recommendations.
4. Run `tests/test_ui_redesign.py` to protect dashboard ordering, phone chart
   overflow, fonts, portfolio summary, and allocation rendering.
5. Run `tests/test_dark_mode.py` because the market strip must remain legible
   under both token sets.
6. Run `tests/test_polling.py` or the repository's equivalent polling contract
   tests to confirm `setupAutoRefresh` remains the only timer owner.

### F. Focused Red Run

After writing tests and before production edits, run:

```bash
source .venv/bin/activate
python -m pytest tests/test_routes.py tests/test_market_tabs.py tests/test_compare_ui.py
```

Expected failure reasons include missing `MARKET_CATEGORIES`, missing category
validation, missing tab/panel markup, old global chip queries, no tab keyboard
handler, and the old standalone-card CSS. Fix test syntax or fixture mistakes,
but do not change production code until failures prove the intended gaps.

## Implementation Sequence

1. Add the ordered market configuration to `app.py` with the exact approved
   keys, labels, symbols, and display names.
2. Derive `INDEX_SYMBOLS` from that configuration.
3. Pass the configuration from `/` to `templates/index.html`.
4. Add optional category parsing and validation to `/api/indices`.
5. Scope parallel fetches, ordered success output, all-failed behavior, and
   logging to the selected category.
6. Run backend-focused tests and make them green before touching frontend
   behavior.
7. Replace the old four-chip markup with the configuration-driven market
   section before the portfolio hero.
8. Add complete tabs/panels/links/accessibility markup and currency caption.
9. Refactor market JavaScript to use active-panel state, scoped loading,
   category requests, gap filling, and per-category race tokens.
10. Add click and keyboard tab activation without persistence.
11. Change boot and the shared polling callback to fetch only the active tab.
12. Add the market-only adaptive precision formatter.
13. Replace standalone chip CSS with the cohesive strip, divided cells,
    heading row, tab controls, focus treatment, skeleton, and dark-mode-safe
    token usage.
14. Add the phone two-column panel and horizontal tab tray.
15. Run the complete focused set and correct failures without weakening tests.
16. Update durable comments in `app.py`, `index.html`, `main.js`, and
    `style.css`; remove comments that still describe a fixed four-chip bar.
17. Update `project-brief.md` Design Rules and dashboard description with the
    final market-category contract. Do not leave durable rationale only here.

## Verification Gates

### Automated

Run focused suites during implementation:

```bash
source .venv/bin/activate
python -m pytest tests/test_routes.py tests/test_market_tabs.py tests/test_compare_ui.py tests/test_ui_redesign.py tests/test_dark_mode.py
```

Then the lead agent must run the complete suite:

```bash
source .venv/bin/activate
python -m pytest
```

Do not report completion unless the full suite passes. The first run may spend
about 90 seconds warming pandas/numpy.

### Live Smoke

With the development server running and Yahoo reachable:

1. Request `/api/indices` and confirm it returns North America only.
2. Request each valid category and confirm at least one real quote when Yahoo
   supports the configured symbols.
3. Request an invalid category and confirm HTTP 400 without a server error.
4. If a configured Yahoo symbol proves permanently invalid during this smoke
   test, stop and report it. Do not silently substitute a different product
   instrument without user approval.

### Browser GUI Approval

After automated tests pass, wait for the user's browser approval. Ask the user
to verify:

1. Markets appear above the whole portfolio.
2. The section reads as one coherent overview rather than separate cards.
3. All six tabs show the approved instruments and retain the visible `Live`
   label.
4. Clicking every instrument opens the correct stock-detail page.
5. Rapid tab changes never paint data into the wrong visible panel.
6. Failed quotes show `—` without blanking healthy instruments.
7. Currency values below 1 retain useful precision and `1 CAD buys` is clear.
8. Desktop, narrow browser, and Android WebView layouts do not overflow.
9. Phone tabs scroll smoothly and the instrument panel remains a two-column
   grid.
10. Light and dark themes both have readable borders, focus, green, and red.

Do not commit or push before this GUI approval. After approval, ask whether to
commit/push. Mark roadmap item #20 shipped only in that approved commit or PR.

## Out Of Scope

- Market-open/closed state and exchange-local timestamps.
- Replacing the user-requested `Live` label.
- Market breadth or a generated market-sentiment sentence.
- User-customizable categories, symbols, or ordering.
- Persisting the selected market tab.
- Additional regions or categories beyond the approved six.
- Interest rates, bond yields, VIX, DXY, sector indices, agriculture, or wheat.
- Historical mini charts or sparklines inside market cells.
- Changing quote/history cache policy.
- Changing dashboard polling cadence.
- Database, ledger, portfolio math, or Android-native changes.
