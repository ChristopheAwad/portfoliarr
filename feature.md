# Parallel preload for Markets today

## Status and scope

Approved and implemented 2026-09-24. The user approved the browser GUI and requested PR #82. Roadmap #24 is marked shipped in the PR. The focused tests failed before implementation (9 failed, 53 passed); the full `python -m pytest` suite passed after implementation (970 passed). This changes the existing dashboard market tabs: all six categories start loading in parallel as soon as the page script runs. The selected tab remains North America on a fresh load. No API shape or market-symbol configuration changes.

## Tests first

1. Update `tests/test_market_tabs.py` to replace the old assertion that boot fetches only the active category. Check that boot enumerates the rendered market tabs or panels, starts `refreshMarketOverview` once for each configured category without awaiting the preceding request, and does not introduce a second hard-coded category list. Assert that the boot call precedes the normal watchlist/chart work and that `setupAutoRefresh` still owns polling.
2. Add a focused JavaScript behavior test in `tests/test_market_tabs.py` or a separate market behavior test, using the existing `py_mini_racer` test pattern. Execute the actual market functions with a small fake document and controlled, pending fetch promises. Assert that all six category URLs have been requested before any response resolves; initial North America remains selected and the other panels remain hidden. Resolve replies out of order and verify that each panel alone gets its own quotes and unanswered-symbol dashes. Do not rely on six sequential awaits or a single all-markets API call.
3. Simulate a tab click while that tab's initial fetch remains pending. The click must show the correct panel and must not issue another request. Resolve the pending fetch and confirm its values appear. Click back to a category whose successful reply is within the 120-second quote lifetime; the existing cells must remain visible without a new request. Advance the fake clock past the lifetime and click again: one new request must start for that category.
4. Check failure paths: a category-wide HTTP error, rejected network request, and malformed JSON leave both cell rows as dashes, clear positive/negative styling, and remain retryable by switching away and back. An empty success response is handled as unanswered symbols (dashes). One failed category must not affect successful siblings or prevent their fetches from finishing.
5. Simulate a newer forced poll while an older request for the same category is still pending; resolve them in reverse order. Assert that neither an older success nor an older failure overwrites the newer result. A failed poll must not leave a successful freshness stamp that blocks a subsequent retry. Keep the existing source checks for per-panel symbol scoping, ARIA tab state, keyboard navigation, formatting, and absence of page-level `setInterval`.
6. Run the new focused tests before production edits and record the failing result. Existing route tests for `GET /api/indices?category=` already cover configured order, partial/all-symbol failures, and invalid keys; only extend them if a server behavior actually changes.

## Implementation after red tests

1. Keep `MARKET_CATEGORIES` in `app.py` as the sole source of category names and symbols. Derive the preload keys from the rendered tab `data-category` values in `static/js/main.js`. Start all requests in a plain loop on page load, without waiting for another category or for portfolio/chart requests. Do not change which tab the template selects.
2. Track, per category, a successful fetch time and any in-flight request. `refreshMarketOverview(category, { force = false } = {})` should reuse a pending request or fresh painted panel on tab clicks. Use the quote cache's 120-second life for successful browser-side data; failure never counts as fresh. The existing `marketRequestTokens` must still reject older results if a forced refresh overtakes an earlier request.
3. Each successful reply paints only the matching panel and gap-fills omitted symbols with dashes. Each current HTTP, network, or JSON failure paints dashes in that panel and permits a later click/poll retry. A tab click only changes selection, focus, ARIA, and panel visibility before it asks for data. Clicking a loaded tab within the freshness window makes no network call; clicking an old tab refreshes it. A pending initial request is shared rather than repeated.
4. Keep the existing `setupAutoRefresh` callback refreshing the active category only, with a forced request so the 60-second poll still updates prices. Visibility and online recovery remain owned by that callback. No new timer or all-tab polling. Update the teaching comments in `static/js/main.js`, `templates/index.html`, the market Design Rule in `project-brief.md`, and the roadmap description to describe the new behavior.
5. Run `python -m pytest tests/test_market_tabs.py tests/test_routes.py`, then the full `python -m pytest` suite. Review the diff and leave the unrelated untracked files alone.

## Browser check

1. Reload the dashboard and inspect Network: six `/api/indices?category=...` requests start together. North America shows by default; after the others complete, switching tabs shows prices immediately and issues no duplicate request within 120 seconds.
2. Use slow network conditions and switch to a still-loading category. It shows the loading state until its reply arrives. Switch across tabs as replies arrive in a different order; each set of prices stays in its own panel. Check keyboard arrow, Home, and End navigation.
3. Simulate a failed category request and retry by switching away and back. Both rows show dashes during a failure and recover on retry. Wait for the regular poll or return to the app from the background and confirm the selected category refreshes.
4. Wait for user browser GUI approval before asking whether to commit or push. Never commit or push without explicit permission.

## Expected files

`feature.md`, `roadmap.md`, `tests/test_market_tabs.py`, `tests/test_market_preload.py`, `static/js/main.js`, `templates/index.html`, `project-brief.md`. No backend endpoint change was needed.
