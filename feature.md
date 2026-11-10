# Chart tooltip: translucent and more compact

Status: implemented, awaiting code review and merge.
Branch: `make-chart-hover-tooltip-transparent-smaller` from main `10e272b`.
This is a small fix: one source file and one test file, no schema, auth,
money, or route change. Plan review gate skipped; code review gate applies.

## Request

The portfolio/stock line-chart hover tooltip was a large opaque dark card that
hid most of the chart. Make it more transparent and reduce its footprint.

## Approved plan

1. `static/js/common.js`: change the shared line-chart tooltip background from
   opaque `#1a1f36` to `hexToRgba("#1a1f36", 0.75)` so the plot shows through,
   and shrink padding 10 -> 8 and body font 13 -> 12. White title/body text and
   the existing green/red footer stay unchanged.
2. `tests/test_chart_tooltip.py`: add a source-level test that locks a
   translucent `hexToRgba` background and rejects the old opaque literal.
3. Run the tooltip tests, the full suite, code review, and a Playwright
   screenshot check in light and dark mode.

Acceptance: the tooltip is visibly see-through in both themes, white text stays
readable, the card is smaller, and no other chart's tooltip changes (the
allocation donut keeps its own config).

## Verification

| Check | Result | Evidence |
|---|---|---|
| Tooltip tests | Pass | `pytest tests/test_chart_tooltip.py` - 10 passed |
| Full suite | Pass | `pytest` - 1534 passed |
| Build/lint/type | Not applicable | Project has no JS build, lint, or type step; CI runs pytest only |
| GUI check | Pass | Playwright hover screenshots, light + dark |
| CI | Pending | Checked after PR push |
| Code review | Pending | Reviewer runs on the PR diff |

GUI evidence:
- `/tmp/opencode/tooltip-light.png`
- `/tmp/opencode/tooltip-chart-light.png`
- `/tmp/opencode/tooltip-dark.png`
- `/tmp/opencode/tooltip-chart-dark.png`

The chart line and grid are visible through the card in both themes; white
text is readable.

## Review log

(Pending)

## Results

(Pending)
