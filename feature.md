# Feature: Pre-fetch all chart timeframes after default load

## Problem
Clicking a timeframe button for the first time (e.g., switching from "5D" to "1M") is slow because the backend has to fetch all ticker histories from yfinance for that uncached period. The frontend cache we added helps on *repeat* clicks, but the first click on each timeframe still waits for yfinance.

## Solution
After the default "5D" chart loads, fire off requests for ALL other timeframes in the background. By the time the user clicks any button, the backend cache is already warm and the frontend cache serves instantly.

## Files to change
- `static/js/main.js` — make `refreshPortfolioChart` return its promise + add pre-fetch loop after boot

## Changes

### 1. `refreshPortfolioChart` returns the promise (main.js:1777-1779)

Current:
```javascript
function refreshPortfolioChart(period = DEFAULT_CHART_PERIOD) {
    if (portfolioChartHandle) portfolioChartHandle.refresh(period);
}
```

Change to:
```javascript
function refreshPortfolioChart(period = DEFAULT_CHART_PERIOD) {
    if (portfolioChartHandle) return portfolioChartHandle.refresh(period);
}
```

### 2. Pre-fetch loop after default chart loads (after line 1812)

```javascript
// Pre-fetch all other timeframes in the background so switching is instant.
// Fire-and-forget — no UI feedback needed. The frontend cache stores each
// response for its TTL (120s live, 600s settled), so by the time the user
// clicks a button, the data is already there.
const ALL_PERIODS = ["1D", "1M", "3M", "6M", "YTD", "1Y", "5Y", "MAX"];
refreshPortfolioChart().then(() => {
    for (const period of ALL_PERIODS) {
        refreshPortfolioChart(period);
    }
});
```

## Why this order
- Default "5D" fires first (user sees chart immediately)
- Pre-fetch starts AFTER "5D" completes — avoids hammering Yahoo before the user's chart renders
- All 8 pre-fetches fire in parallel — total time is ~1×slowest call
- Backend `_history_cache` warms up from these requests too

## Test plan
- Run `python -m pytest` — no backend changes
- Manual: load dashboard, verify 8 extra history requests fire after "5D" completes, click any button for instant render
