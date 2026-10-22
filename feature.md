# Tweak: reverse the Currencies tab pairs

Status: shipped 2026-10-22
Branch: fix/reverse-market-currency-pairs (merged)
Scope: tweak (not a roadmap item)

## Goal

The dashboard "Markets today" Currencies tab must quote each foreign
currency in CAD:

- USD/CAD
- EUR/CAD
- GBP/CAD
- JPY/CAD

This replaces CAD/USD, CAD/EUR, CAD/GBP, CAD/JPY. Positive movement now
means the foreign currency strengthened against CAD.

The user chose the caption `1 unit buys CAD`.

## Verified symbols

Live Yahoo chart check returned a quote and `currency=CAD` for all four:

- `USDCAD=X` 1.4006
- `EURCAD=X` 1.5709
- `GBPCAD=X` 1.8747
- `JPYCAD=X` 0.0089

## Files

1. `app.py` (`MARKET_CATEGORIES["currencies"]`, around lines 241-249)
   - Replace instruments with:
     * `{"symbol": "USDCAD=X", "label": "USD/CAD"}`
     * `{"symbol": "EURCAD=X", "label": "EUR/CAD"}`
     * `{"symbol": "GBPCAD=X", "label": "GBP/CAD"}`
     * `{"symbol": "JPYCAD=X", "label": "JPY/CAD"}`
   - `INDEX_SYMBOLS` stays derived; do not edit it.
2. `templates/index.html` line 75
   - Change the currencies caption from `1 CAD buys` to
     `1 unit buys CAD`.
3. `tests/test_routes.py`
   - Update the `APPROVED_CATEGORIES` currencies block (around lines
     199-202) to the new symbol/label pairs.
   - Change the URL round-trip parametrization (line 396) from
     `CADUSD=X` to `USDCAD=X`.
4. `tests/test_market_tabs.py`
   - Update `test_currencies_caption_only_in_currencies_panel`
     (lines 203-206): assert `1 unit buys CAD` appears exactly once and
     only inside the currencies panel.
5. `project-brief.md`
   - Lines 349-351: state that every currency pair quotes a foreign
     currency in CAD (USD/CAD, EUR/CAD, GBP/CAD, JPY/CAD) under a
     `1 unit buys CAD` caption, so positive movement = the foreign
     currency strengthened against CAD.
   - Lines 363-364: replace "for CAD-based FX pairs" with wording that
     the adaptive precision keeps sub-unit FX quotes such as JPY/CAD
     readable.
6. `static/js/main.js` lines 64-65
   - Update the example from `CAD/USD ≈ 0.73` to `JPY/CAD ≈ 0.009`.
7. `static/style.css` lines 717-718
   - Update the caption comment: `"1.4006" means 1 USD buys 1.4006 CAD`.
8. `feature.md` - this plan.

## Non-goals

- Do not change `market_data.py` FX helpers.
- Do not change portfolio FX (`USDCAD` live/historical).
- Do not change `/api/indices` logic, validation, or failure paths.
- Do not change `comparison.html`.

## Tests

1. Write/update tests first.
2. Run:
   `.venv/bin/python -m pytest tests/test_routes.py tests/test_market_tabs.py -v`
   Confirm the updated assertions fail before the config change.
3. Implement, then rerun the targeted tests.
4. Run the full suite: `.venv/bin/python -m pytest`.

## Edge cases

- JPY/CAD is below 1, so adaptive precision must still give 4 decimals;
  USD/EUR/GBP pairs above 1 keep 2 decimals.
- A missing quote still degrades to an em dash per cell.
- The caption must appear only in the currencies panel.
- The exact-config test must catch a silent symbol/label drift.

## Review

After the full suite passes, run the `reviewer` subagent in diff mode on
`git diff main...HEAD` plus uncommitted changes. Fix blocking issues, then
wait for the user's approval before merging.
