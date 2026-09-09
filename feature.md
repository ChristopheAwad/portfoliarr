# Feature: Previous Day Close Reference Line (1D)

## Problem
No visual reference for where the stock/portfolio closed yesterday. On a 1D intraday chart, it's hard to tell at a glance whether the current price is above or below yesterday's close. Google Finance shows this as a horizontal dotted line — we want the same.

## Plan

### 1. CDN: Add chartjs-plugin-annotation
In `templates/base.html`, add the annotation plugin CDN `<script>` after the existing Chart.js tag (line 52). This plugin handles horizontal reference lines out of the box.

```html
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3"></script>
```

### 2. JS: Modify `setupTimeframeChart()` in `common.js`
Add prev-close support to the shared chart factory (lines 772–1024):

**New closure variables:**
- `let prevClose = null;` — the previous close value
- `let currentPeriod = defaultPeriod;` — track the active period

**New chart-local plugin** (inline, same pattern as `crosshairPlugin`):
```js
{
    id: "prevCloseLine",
    afterDraw(chart) {
        if (currentPeriod !== "1D" || prevClose == null) return;
        const y = chart.scales.y.getPixelForValue(prevClose);
        const { left, right } = chart.chartArea;
        const ctx = chart.ctx;
        ctx.save();
        // Dashed horizontal line
        ctx.beginPath();
        ctx.setLineDash([5, 3]);
        ctx.moveTo(left, y);
        ctx.lineTo(right, y);
        ctx.strokeStyle = getComputedStyle(document.documentElement)
            .getPropertyValue("--text-muted").trim();
        ctx.lineWidth = 1;
        ctx.stroke();
        // Right-aligned label
        ctx.setLineDash([]);
        ctx.font = "11px sans-serif";
        ctx.textAlign = "right";
        ctx.textBaseline = "bottom";
        ctx.fillText(`Prev close ${formatPrice(prevClose)}`, right, y - 4);
        ctx.restore();
    },
}
```

**In `refresh()`:**
- Store the period being fetched into `currentPeriod`
- After `chart.update()`, the plugin auto-draws when period is 1D

**New method on return handle:**
```js
updatePrevClose(val) {
    prevClose = val;
    chart.update();
}
```

**Return object** changes from `{ chart, refresh }` to `{ chart, refresh, updatePrevClose }`.

### 3. JS: Stock detail page (`stock.js`)
In `refreshStockQuote()` (line 68–103), read `quote.previous_close` and pass it to the chart handle:

```js
// After existing paintChange call (line 88):
if (stockChartHandle && quote.previous_close != null) {
    stockChartHandle.updatePrevClose(quote.previous_close);
}
```

This runs on every 60s poll cycle, so the value stays current. The line only renders when the period is 1D.

### 4. JS: Portfolio dashboard (`main.js`)
In `refreshPortfolioSummary()` (line 1657–1699), compute yesterday's portfolio value and pass it to the chart handle:

```js
// After existing paintChange calls (around line 1694):
if (portfolioChartHandle && data.total_value != null && data.day_gain != null) {
    portfolioChartHandle.updatePrevClose(data.total_value - data.day_gain);
}
```

This runs on every 60s poll cycle. The value is `total_value - day_gain` = portfolio value at yesterday's close.

## Files touched
- `templates/base.html` — annotation plugin CDN tag
- `static/js/common.js` — `setupTimeframeChart()` modifications (closure vars, plugin, `updatePrevClose`)
- `static/js/stock.js` — read `quote.previous_close`, call `updatePrevClose()`
- `static/js/main.js` — compute `total_value - day_gain`, call `updatePrevClose()`

## Data flow
```
Stock page:
  quote fetch (60s poll) → quote.previous_close → stockChartHandle.updatePrevClose()
  chart refresh (button click) → period tracked in closure → plugin draws line if 1D

Dashboard:
  summary fetch (60s poll) → total_value - day_gain → portfolioChartHandle.updatePrevClose()
  chart refresh (button click) → period tracked in closure → plugin draws line if 1D
```

## Visual spec
- **Line**: horizontal, dashed (`[5, 3]`), color from `--text-muted` CSS var
- **Label**: "Prev close $123.45" right-aligned at chart edge, 11px sans-serif, same muted color
- **Scope**: 1D only — plugin short-circuits when period is not `"1D"`
- **No line** if prevClose is null (graceful degradation during initial load)

## Test plan
- `setupTimeframeChart()` accepts `prevClose` and exposes `updatePrevClose()`
- When period is 1D and prevClose is set, the annotation plugin draws
- When period is not 1D, no annotation is drawn (short-circuit)
- When prevClose is null, no annotation is drawn
- Stock page reads `previous_close` from quote and passes to chart handle
- Dashboard computes `total_value - day_gain` and passes to chart handle
- Full `python -m pytest` passes
