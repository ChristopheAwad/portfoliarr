# Roadmap #62 — Accurate allocation for all fund types (look-through + manual classification)

Status: in progress
Branch: feat/62-fund-allocation-lookthrough
Roadmap: #62, Tier 2, ~4–6 days
Plan reviewed by the `reviewer` subagent (plan mode); findings folded in.

## Problem

The allocation donut misrepresents funds. Verified against live Yahoo:

- `get_profile` reads `Ticker.info`. For every ETF/mutual fund, Yahoo returns
  `country = None`, `sector = None`, and usually `marketCap = None`
  (checked: SPY, VXUS, GLD, BND, XIC.TO, VEQT.TO, XEQT.TO). So ETFs silently
  drop out of By Sector / By Country / By Cap with a "no X data" exclusion.
- Crypto (`BTC-USD`) and commodity futures (`GC=F`) also have `country = None`.
- yfinance `funds_data` DOES expose real look-through: `asset_classes`
  (stocks/bonds/cash/other), `sector_weightings` (11 sectors),
  `fund_overview.categoryName`. It does NOT expose any country/region split.

## Goal

Every holding contributes its real composition to the donut:

- Funds are decomposed by asset class and sector from Yahoo look-through.
- Non-funds map from `quote_type` / `sector` / `country`.
- Where the concept does not apply, the wedge is `n/a`; where the data is
  missing, the wedge is `Unknown`. Both are shown as real slices and can be
  replaced by an install-wide, user-entered classification.
- New carousel view **By Asset Class**.

## Non-goals

- No external fund-data provider. No scraping provider factsheets.
- Cap dimension keeps its current "excluded" behavior (funds have no
  `marketCap`); it is not part of the assignable set.
- No per-slice `source: manual` marker in v1 (the editor already shows
  whether an override exists).
- Manual overrides cover the three assignable dimensions only:
  `country`, `sector`, `asset`.

## Product-brief amendment (deliberate exception)

The brief says "every row of user data belongs to exactly one account". Fund
composition is NOT user data — it is objective reference data about a security,
the same category as the market overview / search / stock detail, which the
brief already keeps global (`project-brief.md:140-149`). So
`classification_overrides` is **install-wide, ownerless**, and any signed-in
person may edit it; all signed-in people see the same value. The brief gets an
explicit exception bullet stating this, and a test asserts two users read the
same entry. (This was the user's explicit choice.)

## Data shapes

`market_data.get_profile(symbol)` gains keys (base 4 unchanged, plus 3):

```
sector, country, quote_type, market_cap,     # existing
asset_mix:     {"Stocks": 0.9975, "Cash": 0.0025} | None  # funds only
sector_mix:    {"Technology": 0.40, ...} | None           # equity funds only
fund_degraded: False | True     # True when a fund fetch failed this call
```

Folding rules for funds (`quote_type in {"ETF","MUTUALFUND"}`):

- Every candidate weight passes through `_finite_number` (`market_data.py:160`)
  — bool/None/NaN/inf are dropped, and weights `<= 0` are dropped.
- `asset_mix` from `funds_data.asset_classes` (must be a `dict`, else treat as
  empty): stockPosition→Stocks, bondPosition→Bonds, cashPosition→Cash,
  preferredPosition→Preferred, convertiblePosition→Convertible, and
  otherPosition→Commodities | Crypto | Real Estate | Other,
  chosen by `str(fund_overview.get("categoryName") or "").lower()`:
  contains `commodit`→Commodities, contains `digital`/`crypto`→Crypto,
  contains `real estate`→Real Estate, else Other. Unrecognized keys are
  skipped (never guessed). Surviving weights are normalized to sum 1.
  Empty result → `None`.
- `sector_mix` from `funds_data.sector_weightings` (dict; unrecognized snake
  keys skipped); Yahoo snake keys map to the `info.sector` display names
  (realestate→Real Estate, consumer_cyclical→Consumer Cyclical,
  basic_materials→Basic Materials, consumer_defensive→Consumer Defensive,
  technology→Technology, communication_services→Communication Services,
  financial_services→Financial Services, utilities→Utilities,
  industrials→Industrials, energy→Energy, healthcare→Healthcare). Normalized
  to sum 1. Empty → `None`.
- `funds_data` is fetched exactly once per symbol, process-lifetime cached
  (successes only), through a NEW `_fund_cache {symbol: {asset_mix,
  sector_mix}}` + `_inflight_funds` (mirroring `_profile_cache` /
  `_inflight_profiles`), cleared by `clear_market_caches()` and a new
  `clear_fund_cache()`.
- `_profile_cache` stores ONLY the base 4 fields. `get_profile`
  merges mixes onto a fresh `dict(base)` each call, so a failed fund fetch is
  never cached (it retries next call) and cannot poison the base profile.
- Failure handling: `_get_fund_mix` raises; `get_profile` catches
  `Exception`, returns `asset_mix=None, sector_mix=None, fund_degraded=True`.
  The route logs the aggregate (pure layer never logs). The early base-cache
  hit return MUST still resolve mixes (a `_profile_cache` hit with no
  `_fund_cache` entry attempts the fund fetch).
- All returned dicts are defensive copies (`dict(...)`).

Allocation reply `GET /api/portfolio/allocation` gains per-dimension
`unclassified[]`:

```
{
  by, currency,
  slices: [{key, value, weight}],        # now includes "n/a"/"Unknown" wedges
  unclassified: [{ticker, reason}],      # only for by in {sector,country,asset_class}
  excluded: [{ticker, reason}]           # unpriced / unsupported currency /
                                         # missing live rate / profile fetch failed
}
```

Shorts and zero-net positions produce NEITHER a slice NOR `unclassified` NOR
`excluded` (unchanged from today, `app.py:2876-2878`).

## Classification rules (per by-key)

`n/a` = concept does not apply; `Unknown` = applies but data is missing.
An install-wide override (if present) always wins and replaces the whole
result for that dimension.

- `sector` (override key `sector`):
  - override → its fractions.
  - fund with `sector_mix`: `e = (asset_mix or {}).get("Stocks", 0) if
    asset_mix is not None else 1.0` (a present mix with no `Stocks` key
    defaults to 0, NOT 1). Parts = `[(sector, w*e) for sector in
    sector_mix]`; if `e < 1` add `("n/a", 1-e)` (the non-equity sleeve;
    reason "sector not applicable to non-equity holdings"). If `e == 0` →
    `n/a` only.
  - `sector` (string) → single.
  - equity (`(asset_mix or {}).get("Stocks", 0) > 0` or
    `quote_type == "EQUITY"`), no data → `Unknown` (reason "no sector data").
  - non-equity (fund or non-security) → `n/a` (reason
    "sector not applicable").
- `country` (override key `country`):
  - override → its fractions.
  - `country` (string) → single.
  - fund (`quote_type in {ETF,MUTUALFUND}`):
    - `asset_mix` present and `(asset_mix or {}).get("Stocks", 0) == 0 and
      (asset_mix or {}).get("Bonds", 0) == 0` (pure commodity/crypto/other
      fund) → `n/a` (reason "country not applicable").
    - else → `Unknown` (reason "no country data").
  - `quote_type in {CRYPTOCURRENCY,FUTURE,CURRENCY}` → `n/a`
    (reason "country not applicable").
  - else → `Unknown` (reason "no country data").
- `asset_class` (override key `asset`):
  - override → its fractions.
  - `asset_mix` → its fractions.
  - `quote_type` map: EQUITY→Stocks, CRYPTOCURRENCY→Crypto, FUTURE→Commodities,
    CURRENCY→Cash, BOND→Bonds, ETF/MUTUALFUND (no mix)→`Unknown`
    (reason "no asset-class data"), else→`Unknown`.
- `type`: friendly `quote_type` label — EQUITY→Stock, ETF→ETF,
  MUTUALFUND→Mutual Fund, CRYPTOCURRENCY→Crypto, FUTURE→Future,
  CURRENCY→Currency, INDEX→Index, BOND→Bond, None→Unknown, else raw. No
  override, no unclassified (a label always exists).
- `cap`: unchanged bucket / excluded. No override.
- `currency`: unchanged. No override, no unclassified.

Aggregation: for each priced long holding, `value × fraction` per part;
`slices[label] += value * fraction`. A ticker lands in `unclassified` when its
result includes ANY `n/a` OR `Unknown` part — both a missing-data `Unknown` (a
gap to fill) and an applicable `n/a` (e.g. the non-equity sleeve, a commodity
fund's country, crypto's sector) are user-assignable, per the product
decision behind this feature. The `reason` string is the rule's reason. A
ticker fully classified (real labels only) is never in `unclassified`.
Weights divide by the sum of ALL wedge values (n/a/Unknown included).

## Steps

### 1. `db.py` — override table + functions

Table in `init()` (after `widget_tokens`, same idempotent style):

```sql
CREATE TABLE IF NOT EXISTS classification_overrides (
    symbol     TEXT NOT NULL,
    dimension  TEXT NOT NULL CHECK (dimension IN ('country','sector','asset')),
    weights    TEXT NOT NULL,      -- JSON object {label: fraction}
    as_of      TEXT,               -- ISO date or NULL, display-only
    updated_at TEXT NOT NULL,      -- ISO-8601 UTC
    PRIMARY KEY (symbol, dimension)
)
```

No owner column (install-wide, per the amendment above).

Functions (json is a storage detail; take/return dicts):

- `get_classification_override(symbol, dimension)` → `{weights, as_of,
  updated_at}` | None.
- `get_classification_overrides(dimension=None)` → list of rows (route reads
  the whole dimension at once; the table is tiny).
- `set_classification_override(symbol, dimension, weights, as_of)` — upsert
  (`ON CONFLICT ... DO UPDATE`), stamping `updated_at`.
- `delete_classification_override(symbol, dimension)` → bool.
- `delete_classification_overrides(symbol)` → count.

### 2. `market_data.py` — fund look-through

- Add `_fund_cache`, `_inflight_funds`, `clear_fund_cache()`; wire into
  `clear_market_caches()` (`market_data.py:143`).
- New `_get_fund_mix(symbol)` — successes-only, in-flight-coordinated (mirror
  `get_profile`'s owner/waiter pattern), `perf.record("market.get_fund_mix",
  ..., cache=hit|miss|wait)` bounded key; folds per the rules above; raises on
  failure.
- `get_profile(symbol)`: store only base fields in `_profile_cache`; build
  `result = dict(base)`; for funds, `try: mixes = _get_fund_mix(symbol)` → set
  `asset_mix`/`sector_mix`/`fund_degraded=False`; `except Exception` → both
  None, `fund_degraded=True`. Non-funds get `asset_mix=None, sector_mix=None,
  fund_degraded=False`. Return a fresh dict (so the two existing cache tests
  still pass, `tests/test_allocation.py:330,357`).

### 3. `app.py` — dimension + resolver + aggregation

- `ALLOCATION_DIMENSIONS`: add
  `"asset_class": {"label": "By Asset Class", "field": "asset_mix"}`. Order:
  sector, country, type, asset_class, cap, currency.
- New `_OVERRIDE_DIM = {"country": "country", "sector": "sector",
  "asset_class": "asset"}` (the value is the DB `dimension`).
- New `_quote_type_label(qt)`.
- New pure helper `_classify_holding(by, profile, override)` →
  `(parts, reason)`: `parts` is a non-empty `[(label, fraction)]` for the 4
  wedge dimensions, empty for cap/currency; `reason` is None when fully
  classified else the rule's reason string. It reads `quote_type` and the
  mixes from `profile` (no separate `quote_type` argument, so the two can
  never diverge).
- Pass 3 keeps the existing `profiles.get(symbol) is None → excluded
  ("couldn't fetch profile")` check (`app.py:2890-2894`) BEFORE calling the
  helper; the helper never receives `None`.
- Pass 2.5 prefetch unchanged; `asset_class` now qualifies like sector/country.
- Pass 3 rewrite: classify, multiply, fill `slices`, `unclassified`,
  `excluded`. Overrides read once per request via
  `db.get_classification_overrides(_OVERRIDE_DIM[by])` when `by` is
  assignable. Aggregate fund degradation → one
  `event=market_fund_degraded` warning (no symbols, no amounts), gated to the
  assignable dimensions (`sector`, `country`, `asset_class`) where mixes are
  actually consumed.
- Empty-ledger early return (`app.py:2747-2749`) includes `"unclassified": []`.
- Response adds `unclassified` sorted by ticker.

### 4. `app.py` — classification routes

- `GET /api/fund-classification/<symbol>` → `{symbol, overrides:{dim:{weights,
  as_of, updated_at}}}`.
- `PUT /api/fund-classification/<symbol>` body `{dimension, weights, as_of?}`
  → 200 `{symbol, dimension, weights, as_of}`.
- `DELETE /api/fund-classification/<symbol>?dimension=<dim>` (missing
  dimension clears all) → 200 `{deleted: n}`.
- Symbol: `strip().upper()`, must match `^[A-Z0-9.\-=^]{1,20}$` (allows
  `BTC-USD`, `GC=F`, `^GSPC`); else 400.
- Dimension: lowercased; must be in `{country,sector,asset}`; else 400.
- `weights`: must be a JSON object, 1–50 entries after dropping zero values.
  Keys: `str`, strip, 1–40 chars, non-empty; uniqueness is case-insensitive
  after trim (duplicate → 400). Values: reject `bool`, must be `int`/`float`
  and finite, `0 <= w <= 100`. Zero values are dropped; if that empties the
  set or the sum is not `> 0` → 400. Server normalizes to sum-1 fractions.
  Unknown top-level body keys are ignored.
- `as_of`: optional; if present must parse with
  `datetime.date.fromisoformat` (the repo convention, `app.py:3131`), so
  impossible dates like `2026-13-40` are 400; display-only, never read by
  `_classify_holding`.
- Mutation audit: one INFO line per write (`event=classification_override_set`
  / `_deleted`, symbol, dimension), no amounts.

### 5. Frontend

- `templates/index.html`: `1 / 6` → `1 / 7` (`index.html:312-313`); add
  `<p id="alloc-unclassified" class="alloc-excluded"></p>` after
  `#alloc-excluded` (`index.html:315`).
- `static/js/main.js`:
  - Add `{ key: "asset_class", label: "By Asset Class" }` after `type`
    (`main.js:1098`), 7 entries.
  - `paintAllocation(slices, excluded, by = null, unclassified = [])`;
    `updateAllocUnclassified(list)` renders `Ticker — reason` links to
    `/stock/<ticker>#classification-card`, called from `paintAllocation` and
    cleared with `updateAllocUnclassified([])` at every site that clears the
    excluded note (`main.js:1209,1246,1733` region).
  - `lastAllocPayload = { by, slices, excluded, unclassified }`
    (`main.js:1410`).
  - Pass `entry.data.unclassified` / `data.unclassified` at
    `main.js:1244,1281`; ticker-view calls (`main.js:768,1206`) use the
    default `[]`.
- `templates/stock.html`: add a `#classification-card` section, collapsed
  inside a `<details>` so it is unobtrusive (title, dimension `<select>` with
  values `country|sector|asset`, a rows container, Add row, Save, Clear,
  optional as-of date).
- `static/js/stock.js`: on load, GET the overrides and wire
  add/remove/save/clear to the routes; percent inputs = fraction × 100. The
  card is available for EVERY symbol (no `quote_type` gate) so a stock,
  fund, crypto, or commodity can all be assigned — this is what makes both
  `n/a` and `Unknown` wedges assignable from the dashboard note.
- `static/style.css`: card + unclassified-note styling.

### 6. Docs

- `project-brief.md`: add a Design Rules bullet — fund look-through for asset
  class/sector with the non-equity sleeve handled; Yahoo has no fund country
  data, so funds show `Unknown` (or `n/a` for pure commodity/crypto funds and
  non-securities and their non-equity sleeve); install-wide, ownerless
  classification overrides (the documented global-data exception behind the
  "every row belongs to one account" rule) may replace them; by-key no longer
  silently excludes.
- `roadmap.md`: #62 entry added (in progress → shipped on merge); graph stanza
  appended (`62. Fund Allocation Look-through ─────┘`); Suggested-Order line
  added after #4.

## Test matrix (failing first)

`tests/test_fund_allocation.py` (new) — route look-through + n/a/Unknown:
- Asset-class split: ETF `asset_mix {"Stocks":0.6,"Bonds":0.4}` contributes
  60/40; weights sum to 1.
- Sector look-through (all-equity): ETF `asset_mix {"Stocks":1.0}` +
  `sector_mix` splits across sectors.
- Mixed fund sector sleeve: `asset_mix {"Stocks":0.6,"Bonds":0.4}` +
  `sector_mix {"Technology":1.0}` → Technology 0.6 + `n/a` 0.4; sums to 1; the
  ticker is in `unclassified` (reason "sector not applicable to non-equity
  holdings").
- Bond-only fund with a stray `sector_mix` and `asset_mix {"Bonds":1.0}` →
  `n/a` only (e = 0), never equity sectors.
- Override precedence: manual country weights replace the Unknown wedge;
  delete reverts to Unknown.
- Country: fund → Unknown; commodity fund (`asset_mix {"Commodities":1.0}`)
  → n/a; `BTC-USD`→n/a; `GC=F`→n/a; stock with country→country; stock without
  country→Unknown.
- Sector: equity without sector→Unknown; crypto/bond fund→n/a.
- Asset class: EQUITY→Stocks, CRYPTOCURRENCY→Crypto, FUTURE→Commodities,
  CURRENCY→Cash, BOND→Bonds, no-mix fund→Unknown.
- Type labels (EQUITY→Stock, CRYPTOCURRENCY→Crypto).
- `unclassified` is populated for BOTH `Unknown` and applicable-`n/a` parts of
  sector/country/asset_class (e.g. a commodity fund's country `n/a`, crypto's
  sector `n/a`), and is empty for type/cap/currency; a fully classified ticker
  is never in `unclassified`; an override for one dimension leaves the others
  Unknown.
- Empty ledger → slices/unclassified/excluded all empty.
- Failure: profile fetch fails → excluded; fund fetch fails → Unknown, no
  raise, `fund_degraded` logged aggregate.
- Invalid `by` 400; `asset_class` accepted; short/zero produce nothing.
- Override present on an unpriced/short/unsupported-currency holding still
  excludes it (override cannot resurrect it).
- `b"NaN" not in res.data` on a fund with sparse/empty `funds_data`.

`tests/test_fund_classification.py` (new) — override CRUD:
- PUT then GET round-trip (weights normalized to fractions).
- Validation 400s: unknown dimension; empty weights; negative; NaN/inf;
  bool value; string value; all-zero; `{A:0,B:50}` normalizes to B only;
  `{A:0}` 400; >50 entries; blank/long/duplicate (case-insensitive) labels;
  bad `as_of`; bad symbol charset/length.
- DELETE one dimension; DELETE all; DELETE unknown symbol → `deleted 0`;
  DELETE `?dimension=bogus` → 400.
- Auth: signed-out GET/PUT/DELETE → 401 (JSON).
- Two users: user A's PUT is visible to user B's GET (install-wide, intended).
- db layer: upsert replaces; missing row → None; JSON round-trips.

`tests/test_allocation.py` (update):
- `make_profile` gains `asset_mix=None, sector_mix=None, fund_degraded=False`.
- `test_missing_sector_appears_in_excluded_with_reason` → crypto now yields an
  `n/a` sector wedge + `unclassified`, not `excluded`.
- `test_all_unclassified_returns_empty_slices_and_full_excluded_list` → one
  `n/a` slice, two `unclassified`, empty `excluded`.
- `test_weights_sum_to_one_over_classified_slices_only` → BTC enters the
  denominator via the `n/a` wedge; Technology weight < 1.
- `test_get_profile_extracts_and_renames_fields` /
  `_missing_fields_become_none` → assert `asset_mix is None`,
  `sector_mix is None`, `fund_degraded is False`.
- New: `get_profile` fund path with a fake `funds_data` (mixes folded, one
  fetch per symbol cached); fund fetch failure → mixes None, `fund_degraded`
  True, no raise, retried next call (not cached); non-funds never touch
  `funds_data`; sparse/None `asset_classes` → None.
- `test_cap_missing_market_cap_excluded` unchanged.

`tests/test_allocation_ui.py` (update):
- 7 views incl. "By Asset Class"; `1 / 7`; `#alloc-unclassified` present;
  the `paintAllocation(entry.data.slices, entry.data.excluded, by)` lock
  (`test_allocation_ui.py:220`) updated for the new 4th argument; stock
  classification card present in `templates/stock.html`.

`tests/test_allocation_behavior.py` (update):
- The `paintAllocation(tickerSlices, tickerExcluded)` source locks
  (`test_allocation_behavior.py:86-91`) still hold (default 4th arg); add a
  lock that the dimension path passes `unclassified`.

## Gates

- `source .venv/bin/activate && python -m pytest` (first run ~90 s warm-up).
- `scripts/perf_server.py` monkeypatches `module.get_profile`
  (`perf_server.py:145`); it replaces the function entirely, so it stays
  valid — no change needed.
- No container/CI change planned; if one slips in, run `tests/test_docker.py`.
- Diff review gate (`reviewer`, diff mode) before merge; user approval before
  merge.

## Verification commands

```
source .venv/bin/activate
python -m pytest tests/test_fund_allocation.py tests/test_fund_classification.py -q
python -m pytest tests/test_allocation.py tests/test_allocation_ui.py tests/test_allocation_behavior.py -q
python -m pytest
```
