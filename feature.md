# Feature: "Printed money" — UI identity + dashboard completion

Branch: `ui-printed-money` (rollback = `git checkout main && git branch -D ui-printed-money`;
merging to main is the user's explicit yes). Chunked commits on the branch.

## What

Two things in one feature:

1. **Identity pass** — replace the default-generated look (Inter + Tailwind
   blue-600 + identical white cards) with a deliberate "printed money"
   identity: engraved serif display voice (Fraunces) + Instrument Sans UI,
   porcelain/ink light palette, slate/banknote-gold dark palette, and a
   borderless hero card so the page stops reading as "identical rounded cards".
2. **Dashboard completion** — the brief's summary strip gains the missing
   **cost basis**, and the brief-listed **allocation donut** (absent from the
   codebase today) ships, fed by a new `holdings` breakdown on
   `/api/portfolio/summary` (computed at read time, no schema change).

## Design tokens

| Token | Light | Dark |
|---|---|---|
| Paper (page bg) | `#f7f7f5` porcelain | `#101318` slate |
| Card | `#ffffff` | `#181c24` |
| Ink (text) | `#171a20` | `#e7e8ea` |
| Accent | ink-navy `#1c3a5e` | banknote gold `#d0a959` |

Type: **Fraunces** (Google Fonts) for wordmark + h2/h3 display voice;
**Instrument Sans** for UI/body; ALL figures stay tabular-nums in the UI face
(no live-refresh jiggle). pos/neg green/red keep their color monopoly — the
accent never competes with market data.

Motion budget: one moment — donut sweep + hero settle on first paint, guarded
by `prefers-reduced-motion`. Everything else keeps today's quiet transitions.

## Test plan (tests written FIRST, must fail until implemented)

New `tests/test_ui_redesign.py` (uses existing `fresh_db`/`client`/`fake_market`):

1. `GET /` fonts URL contains both `Fraunces` and `Instrument+Sans`
   (base.html identity lock).
2. `GET /` contains `id="portfolio-cost-basis"` (brief's summary strip).
3. `GET /` contains donut canvas `id="allocationChart"` inside a card.
4. Timeframe buttons on `/` and `/stock/AAPL` read exactly
   `1D 5D 1M 3M 6M YTD 1Y 5Y MAX` (main/stock.js read textContent as
   PERIOD_MAP keys — the segmented-control restyle must not rename them).
5. `GET /api/portfolio/summary` reply grows `holdings`:
   `[{ticker, value, weight}]` CAD. Tests: weights sum to 1 (1e-9);
   single holding → weight 1.0; mixed USD/CAD converts at the LIVE rate
   (mirror of existing conversion tests); unpriced ticker absent from
   `holdings` (priced-only-slice rule); empty ledger → `[]`.
6. All existing contract tests stay green.

## Implementation chunks

**Chunk A — foundation (lead, sequential; everything depends on it)**
- `style.css`: token swap + dark overrides; `.stock-header-card` becomes the
  borderless hero (larger type scale, no box); Fraunces on headings/wordmark;
  segmented-control styles; donut card styles.
- `base.html`: Google Fonts link swap (Fraunces + Instrument Sans), keep
  preconnect pattern.
- `common.js`: `getChartColors()` recolor + new `ALLOCATION_COLORS`
  categorical set (10 distinguishable, theme-aware) — same sync contract as
  CHART_COLORS.

**Chunk B — dashboard (subagent, parallel with C)**
- `app.py`: `portfolio_summary` reply gains `holdings` (per-ticker CAD value
  + weight; unpriced excluded). No new endpoint; math server-side, testable.
- `templates/index.html` + `static/js/main.js`: hero block (title + big value
  + day/total pills + quiet "Cost basis" caption), chips row below hero;
  donut card in sidebar under watchlist (Chart.js doughnut, ticker legend,
  privacy eye masks CAD values in tooltips — weights stay visible).

**Chunk C — ledger / stock / UX (subagent, parallel with B)**
- Ledger: stamp-style BUY/SELL badges, quieter chrome — ZERO contract changes
  (11 columns × 4 places, data-cs-col untouched).
- Stock page: stats `<dl>` grouped with cluster labels (Day / Range /
  Valuation / Profile) — `dd` ids unchanged, stock.js untouched.
- Timeframe row → scroll-snapped segmented control on both pages
  (textContent untouched).
- Empty states: actionable copy; ledger/preferences pick up new tokens free.

**Integration (lead)**: review both diffs, resolve style.css overlap, full
`python -m pytest` green.

## Out of scope

Period-aware pills (roadmap #9), sector donut (roadmap #4), PWA (banned by
design rule), any schema change.

## Defaults chosen (user-approved)

- Donut lives in the sidebar under the watchlist.
- Cost basis = quiet caption under the hero pills, not a fourth pill.

## Status

- [x] Plan approved (user, with branch-based rollback guarantee)
- [ ] Tests written + failing
- [ ] Chunk A
- [ ] Chunk B
- [ ] Chunk C
- [ ] Integration + full suite green
- [ ] GUI gate
- [ ] Commit gate (merge to main = user's explicit yes)
