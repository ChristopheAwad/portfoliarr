# Chart granularity fix: revert 3M to daily bars

**Scope (user-approved):** ONLY the 3M timeframe, reverting it from hourly back
to daily bars. This restores a clean, monotonic density progression across the
whole timeframe ladder. No other period changes.

## Why

The last feature moved 3M to hourly bars (`1h`, ~440 points) for intraday
texture — but research showed that breaks the density story: yfinance has NO
interval between hourly and daily (no "4h"/"12h"), so a 1h series followed by a
1d series produces an unbridgeable 7× cliff. With 3M on hourly:

- 3M (~440 pts) is 20× denser than 1M (~22) despite being only 3× longer
- 3M is denser than 6M (~126) and 1Y (~252) — a viewer clicking 3M → 6M sees
  the chart collapse from rich detail to blocky segments

The clean resolution (matches Yahoo/Google/TradingView): 3M → daily bars.
Resulting progression:

    1D(78) → 5D(65) → 1M(22) → 3M(63) → 6M(126) → YTD(~170) → 1Y(252) → 5Y(260) → MAX(~1200)

Intraday views (1D 78, 5D 65) are naturally the densest — they're the "now"
zoom. From 1M up the daily ranges are monotonically non-decreasing and sit in a
readable ~22–260 band: 22 → 63 → 126 → ~170 → 252 → 260 (5Y weekly holds the
rate; MAX at ~1200 monthly bars is the one deliberate outlier). No longer
timeframe out-densifies a shorter one — 3M was the only violation, with its
hourly ~440. 3M at ~63 points over 1000px is ~16px per segment — clearly
readable, and it sheds the datetime-label complexity.

## Changes

1. **Tests FIRST** (`tests/test_chart_speed.py`, rewriting the two 3M tests):
   - `test_3m_uses_hourly_bars_with_datetime_labels` → **becomes**
     `test_3m_uses_daily_bars_with_date_labels` — unpacking lock
     `("AAPL", "3mo", "1d")` in the call log + date-only `"YYYY-MM-DD"` keys.
     Fails today (map still serves `"1h"`, keys are datetime-shaped).
   - `test_3m_portfolio_chart_is_daily_shaped_on_hourly_bars` → **becomes**
     `test_3m_portfolio_chart_is_daily_shaped` — end-to-end daily bars: axis
     trims the pre-buy bar, a transaction applies at its DATE's bar, output
     uses `"YYYY-MM-DD"` labels. Fails today (hourly/datetime-shaped).
   - `test_intraday_and_live_flags_stay_exclusive` — UNCHANGED regression lock
     (passes before and after; 3M has neither flag, so it stays daily-shaped
     ledger math + settled 600s TTL).

2. **`market_data.py`** — PERIOD_MAP `"3M"` entry: `interval "1h" → "1d"`,
   `label "%Y-%m-%d %H:%M" → "%Y-%m-%d"`. Header comment (interval / intraday /
   live / label paragraphs) + `get_history` docstring updated: 3M leaves every
   hourly / "several bars per day" group and joins the date-spaced daily group.

3. **`app.py`** — comment-only: the daily-branch note (lines ~343-348) that names
   "3M's hourly bars" as spanning multiple days → 3M no longer does; only 5D's
   30-minute bars span days.

4. **Contract docs** — `project-brief.md` and `AGENTS.md`: remove 3M-hourly
   mentions (3M becomes date-spaced daily like 1M/6M/YTD/1Y).

No JS changes (backend sends raw labels; date-only is the standard case in
Chart.js). No TTL / flag changes (3M already had neither intraday nor live).

## Done when

- Rewritten tests fail BEFORE the map flip, pass AFTER.
- Full suite green: `python -m pytest`.
- User checks 3M (and 1M/6M/1Y next to it) in the browser GUI — the density
  progression now feels consistent (3M is smoother/less detailed than the old
  hourly view — that's the point: consistency).
