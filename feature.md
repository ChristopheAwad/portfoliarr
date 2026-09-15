# Feature: Trim allocation donut carousel 8 → 6 views

## Status
Implemented; FULL suite green (439 passed). NEXT STEP: user GUI check of the
donut carousel arrows, then commit gate on explicit yes.

## Decision
Cut **By Industry** and **By Exchange** from the donut carousel. Keep 6 views:
Ticker, Sector, Country, Type, Cap Bucket, Currency.
- Industry cut: at small-portfolio scale it restates By Ticker with noisier labels
  (most wedges = 1 company).
- Exchange cut: raw Yahoo codes ("NMS", "TOR") — cryptic and near-duplicates
  Currency/Country.
- All profile views share one cached `get_profile` call per ticker, so there are
  no network savings — this is a UI-clutter cut (7 arrow-presses to cycle → 5).

## Test plan (FIRST — must fail until implemented)
1. `tests/test_allocation_ui.py`
   - Rename `test_main_js_defines_eight_allocation_views` →
     `test_main_js_defines_six_allocation_views`. Label list: By Ticker, By
     Sector, By Country, By Type, By Cap Bucket, By Currency. ALSO assert
     "By Industry" and "By Exchange" are ABSENT from main.js (both-directions
     lock, test_docker style).
   - `test_js_dimension_keys_match_backend_whitelist`: unchanged, auto-adapts
     (iterates the backend dict).
2. `tests/test_allocation.py`
   - NEW: `?by=industry` and `?by=exchange` → 400 (locked at the API boundary).
   - `test_get_profile_extracts_and_renames_fields`: assert only the 4 surviving
     keys + `"industry" not in profile` and `"exchange" not in profile`.
   - `test_get_profile_missing_fields_become_none`: same trim.
   - Update header comment (mentions the 6 dimensions).

## Implementation (after tests exist and fail)
1. `app.py` `ALLOCATION_DIMENSIONS` (~line 65): remove `"industry"` +
   `"exchange"`; update the product-decision comment.
2. `static/js/main.js` `ALLOCATION_VIEWS` (~line 812): 6 entries; update the
   "8 views"/"7 views" comments (~lines 725, 798).
3. `market_data.py` `get_profile` (~line 304): return 4 fields (sector, country,
   quote_type, market_cap); docstring "six non-currency dimensions" → "four".
4. `templates/index.html` ~line 205: "cycle through 8 views" → 6.

## Notes
- localStorage saved dimension index: a stale index just opens a different view
  (bounds-checked on read); persistence format unchanged.
- Gates after implementation: full `python -m pytest` green → user GUI check of
  the carousel arrows → commit only on explicit yes.
