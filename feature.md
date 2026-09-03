# Feature: CAD Display Conversion + "Show USD in USD" Ledger Toggle

## What (user story)

Everything is either CAD or USD. The dashboard's portfolio views (summary
strip, value chart, transaction ledger) display in **CAD by default**: USD
holdings convert at Yahoo's `USDCAD=X` FX rate. A dashboard toggle
("Show USD in USD") flips **only the ledger** back to native-USD display —
the total value and chart are ALWAYS CAD regardless. Watchlist, index
chips, stock detail page, and importer report stay native currency always.

## Decisions already made (planning session — don't re-litigate)

- **Scope of CAD conversion**: summary strip + chart + ledger ONLY.
  Watchlist, chips, stock page: native forever.
- **Toggle**: flips only the ledger; session-only (no localStorage);
  always starts CAD; label "Show USD in USD". Never touches the summary
  or chart ("not affecting the total portfolio value" — user requirement).
- **Historical FX is a FACT** (user requirement): every transaction stores
  `fx_rate` = the USDCAD=X daily close **on the transaction's date** (last
  close on-or-before it), derived automatically from Yahoo at
  log/import/edit time. Never changes afterwards. Used for the Price
  column and cost basis (past facts). **Current values (price_now, value,
  day gain) use the LIVE rate** — "I need today's CAD value of a potential
  sell". Consequence: CAD gain % includes currency movement (honest).
- **Legacy rows** (pre-feature USD rows, fx_rate NULL) → display falls
  back to the live rate per request; editing a row backfills the real
  date-based fact. CAD rows backfill to 1.0 in the migration.
- **Chart FX = flat live rate** (user choice, not per-point history).
  FX failure → USD tickers contribute 0 (per-ticker resilience rule).
- **PUT contract unchanged**: body stays `{date, price, qty, type}`;
  `fx_rate` is re-derived server-side from the new date (Yahoo-derived
  fact that follows the DATE, unlike currency which follows the
  non-editable ticker).
- **API surface**: ledger + watchlist stay raw-facts-plus-display-math;
  ledger rows gain `price_display` + `display_currency` (always present,
  equal to the native facts in native mode). Stored `price`/`currency`
  stay native so edit-mode prefill and group-% math can't corrupt facts.
- **Conversion is math → backend-only** (routes); frontend stays a pure
  renderer. `?currency=` values: `CAD` (server default) | `native`;
  anything else → 400 listing options (same pattern as `?period=`).
- **Summary/chart/ledger in CAD mode treat non-USD-non-CAD currencies**
  as convertible-failure (unpriced / native-degrade / contribute-0) —
  only USD↔CAD is supported (user: everything will be CAD or USD).

## Subtasks (in order — check off as done)

- [x] **1. Tests first** (all red before implementation):
      - `tests/test_market_data.py`: `get_fx_rate` (same-currency → 1.0
        with no network; live rate via `USDCAD=X` quote, cached; raises).
        `get_fx_rate_on(date)` (close on-or-before date; weekend → prior
        Friday; empty window → ValueError).
      - `tests/test_db.py`: migration adds `fx_rate` to a legacy table;
        CAD rows backfill 1.0, USD stay NULL; add/get roundtrip carries
        fx_rate; update_transaction writes it.
      - fx-at-log-date derivation: POST /api/transactions stores the tx
        date's rate; PUT re-derives on date change; import preview shows
        it, commit stores it (new tests/test_currency_display.py).
      - Summary: rewrite `test_mixed_currencies_sum_as_is` (the locking
        test FLIPS to lock conversion); cost basis uses per-tx stored fx;
        live-FX failure → unpriced; legacy NULL fx → live-rate fallback;
        reply carries `"currency": "CAD"`; CAD-only portfolio makes no FX
        call.
      - Ledger `?currency=`: CAD default conversions (price_display at
        stored fx, value/gains at live rate, pct includes FX); `native`
        pins today's shape; invalid param 400; unquoted rows; live-FX
        failure → full native degrade; watchlist-stays-native regression.
      - History: USD contributions × flat live rate; FX failure → 0;
        CAD-only makes no FX call; existing history tests reseeded CAD.
- [x] **2. `db.py`** — migration (ALTER TABLE + CAD backfill), column in
      SELECT lists, add/update params.
- [x] **3. `market_data.py`** — `get_fx_rate`, `get_fx_rate_on`.
- [x] **4. `app.py` fx derivation** — shared `_fx_rate_for_date` (history
      → fallback live rate + warning); POST/PUT/import.
- [x] **5. `app.py` summary conversion** — cost × stored fx, value/day ×
      live rate; FX failure → unpriced; `"currency": "CAD"`.
- [x] **6. `app.py` ledger `?currency=`** + price_display/display_currency.
- [x] **7. `app.py` history conversion** — flat live rate.
- [x] **8. Frontend** — toggle in portfolio card header; ledger fetches
      carry the param; buildTxRow/buildGroupRow use price_display/
      display_currency; summary value paints "CAD" suffix; chart dataset
      label "(CAD)". GUI-verified by the user (no JS test infra).
- [x] **9. Docs** — project-brief.md: resolve the mixed-currency temporary
      decision (keep as history), add a permanent display-currency design
      rule, update Data Source + MVP scope lines. AGENTS.md: update the
      native-currency scope line.
- [x] **10. Verify** — `python -m pytest` fully green; live curl pass
      (summary/ledger CAD + native, history, fx degradation); GUI gate
      with the user; commit gate.

## Contracts that must NOT break (AGENTS.md)

- Ledger table HTML column count stays 11 (no new visible columns).
- PUT body = exactly the 4 editable fields; ticker/currency never user-
  writable; fx_rate is server-derived, never accepted from clients.
- Backend sends raw floats; formatting stays frontend-only.
- Patch-where-used mocking; logging only in app.py; pure layers raise.
- Quote dicts are SHARED with the cache — copy before decorating.
