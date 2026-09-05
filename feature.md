# Feature: UI Revamp — "Portfoliarr, polished"

## Goal

The app works but looks barebones. One coherent visual pass: refined light
theme (typography, spacing, elevation, hover/focus states), rebrand from
"Google Finance Clone" to **Portfoliarr** (+ favicon), SVG icons instead of
text glyphs, custom modals/toasts instead of `prompt()`/`alert()`/`confirm()`,
and skeleton shimmer while quotes load. No data-flow changes.

User approved: light-only theme, rebrand, SVG icons, modals/toasts,
skeletons — "all of it".

## Hard contracts (locked by tests — must survive)

- `<table class="ledger-table">` immediately inside `<div class="table-wrap">`
  (test_routes.py). Keep both class strings verbatim.
- 11 `<th>` with the exact data-col order and the 7 `.sortable` — header TEXT
  stays pure text (no SVG inside `<th>`; the regex tests read textContent).
- Chips stay `<a class="chip" data-symbol=... href=...>` with
  `.index-name` / `.index-price` / `.index-change` spans inside.
- Every id/class JS hooks: #ticker-search, #search-results, all ids on both
  pages, .time-btn, .ledger-group/.ledger-row/.tx-detail/.tx-action-btn,
  .tx-badge buy/sell, .watchlist-item/.watch-price/.change-tag/.remove-btn,
  .search-row/.search-meta/.sub-text, .caret, .price-change.pos/.neg, etc.
  Restyle, never rename; adding decorative wrappers/spans is fine.
- The ≤600px phone-card ledger layout, the `[hidden]{display:none!important}`
  guard, and `@media (hover: none)` button visibility all survive.
- favicon + branding are NEW locks (see test plan).

## Shared contract (subagent A = JS, subagent B = HTML/CSS — no file overlap)

### Palette (B defines in :root; A mirrors the chart values exactly)
- --green-pos: #059669, --green-bg: #e7f6ef
- --red-neg: #dc2626, --red-bg: #fdecec
- --blue-accent: #2563eb, --blue-bg: #eaf1fe
- --bg-color: #f6f7f9, --card-bg: #ffffff, --text-primary: #1a1f36,
  --text-secondary: #5b6472, --border-color: #e4e7ec
- A's common.js: CHART_COLORS up line #059669 / fill rgba(5,150,105,0.12),
  down line #dc2626 / fill rgba(220,38,38,0.10); crosshair #e4e7ec;
  tooltip bg #1a1f36; y-grid #eef1f5. Keep the anchor comment in sync.

### UI kit (A adds to common.js; B styles the exact classes)
- `icon(name, className)` → SVG element (createElementNS, 24×24 viewBox,
  stroke currentColor, fill none, stroke-width 2, feather-style STATIC path
  data only — never string-built from data). Names: pencil, trash, x, plus,
  search, caret, check. Base class `.icon`.
- `showConfirm({title, message, confirmLabel, cancelLabel, danger})` →
  Promise<boolean>; `showPrompt({title, message, placeholder, confirmLabel,
  danger})` → Promise<string|null>; `showToast(message, type)` type
  "error"|"success". Built per call: `.modal-overlay > .modal` with
  `.modal-title`, `.modal-message`, `.modal-input` (prompt only),
  `.modal-actions` > `.btn .btn-quiet` cancel + `.btn .btn-primary` /
  `.btn .btn-danger` confirm. Escape / overlay-click = cancel; Enter in
  input = confirm; focus input (prompt) or confirm button (confirm) on open;
  focus restored on close. Toast singleton `#toast-container` fixed
  bottom-right, `.toast .toast-error / .toast-success`, auto-dismiss ~4s.
- All existing callers SWAP: main.js prompt→showPrompt (watchlist add, bulk
  type-ticker), confirm→showConfirm (single tx delete), alert→showToast
  (every network-failure + cancelled notice). stock.js one line: the
  "✓ On Watchlist" state becomes icon("check") + " On Watchlist" text node.
- Icon swaps in JS-built DOM: edit ✎→icon("pencil"), delete ×→icon("trash"),
  watchlist remove ×→icon("x"), group caret keeps span.caret wrapper with
  icon("caret") inside (CSS rotate untouched). ALL data-* hooks and title
  attrs preserved.

### Skeleton loading (pure CSS on :empty — B styles, A+B ship empty)
- Shimmer on `.current-price:empty`, `.chip .index-price:empty`,
  `.watchlist .watch-price:empty`, `.stats-grid .stat dd:empty`.
- Templates must ship these spans/dds TRULY EMPTY (`></span>` — no
  whitespace inside, or :empty is false forever).
- A: setChipState("") instead of "…"; watchlist watch-price builds empty.
  Degraded "—" fills still win over :empty, so degradation is unaffected.
  Watchlist name keeps its "…"→"" behavior (it can be legitimately empty —
  no shimmer rule for it).
- `prefers-reduced-motion: reduce` disables shimmer/modal/toast animation.

### B: rebrand + restyle
- base.html: Inter via Google Fonts CDN (preconnect + css2 link, system
  fallback stack), favicon `<link rel="icon" ... favicon.svg>`, Portfoliarr
  wordmark (inline SVG spark + text, still `a.logo`, still links home),
  search input gets an inline search SVG (id untouched).
- index/stock titles → "Portfoliarr" / "{{ symbol }} — Portfoliarr"; stale
  brand comments updated where they name the product.
- static/favicon.svg: simple rounded square + upward spark line.
- style.css: new tokens (radii, shadows/elevation, spacing), refined navbar/
  chips/cards/buttons (unified primary/quiet/danger), form focus rings,
  ledger table polish (row hover, nicer group rows/badges/sort/drag states),
  watchlist, stats grid, custom scrollbars, tabular-nums on numeric cells.
  PRESERVE: all responsive blocks (≤920px, ≤600px card layout, hover:none).
- NO sticky thead (considered, dropped: fights the sticky navbar offset).

## Test plan (tests/test_ui_revamp.py — written FIRST, fails before impl)

pytest, template-level only (client fixture; no network, no fakes):
1. test_base_links_favicon_and_file_exists — dashboard html has
   `rel="icon"` + favicon.svg; static/favicon.svg exists; GET
   /static/favicon.svg → 200 with svg content type.
2. test_branding_rebranded_to_portfoliarr — "/" and "/stock/AAPL" html
   (comments stripped) contain no "Google"; title contains "Portfoliarr".
3. test_dashboard_js_hooks_present — the id list above renders.
4. test_stock_js_hooks_present — stock-page ids render.
5. test_loading_placeholders_ship_empty — portfolio-value, stock-price,
   and one stat dd have empty text content between tags (the :empty
   shimmer contract).
Then: FULL suite green (`python -m pytest`) — existing locks prove the
table/chips/wrapper survived the restyle.

## Execution order

1. feature.md (this) → approved.
2. Failing tests (test_ui_revamp.py) → run to confirm red.
3. Parallel subagents: A = common.js/main.js/stock.js kit+swaps+chart colors;
   B = templates/style.css/favicon. Both get the contract above verbatim.
4. Lead integrates, reviews diffs, runs FULL suite.
5. GUI gate: user checks both pages desktop + phone width.
6. Commit gate: explicit yes only.
