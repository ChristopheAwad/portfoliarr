# Ticker Page Fundamentals Expansion (roadmap #52)

Status: in progress

The stock detail page's stats grid already fetches Yahoo's full company
profile through `get_stats` (one heavy `Ticker.info` call, once per page
load) but shows only 18 values. This feature adds the rest of the profile to
the SAME call. **No new endpoint, no new network call, no cache change.**
Missing fields degrade to "—", exactly like today.

This is item 1 of a five-item ticker-page batch (#52–#56). Do NOT touch the
other four here.

## Locked decisions (user-approved)

- **Numeric normalization happens in the DATA layer** (`get_stats`), not the
  frontend. The frontend only formats.
- Yahoo sends these as FRACTIONS → multiply by 100 → percent number:
  `payoutRatio`, `grossMargins`, `operatingMargins`, `profitMargins`,
  `returnOnEquity`, `revenueGrowth`, `earningsGrowth`.
  (Verified live on AAPL Sep 2026: `payoutRatio=0.1204`,
  `grossMargins=0.48653`, `returnOnEquity=1.4875101`.)
- Yahoo sends `debtToEquity` ALREADY SCALED (AAPL `78.445` = 78.4%) → pass
  through with `_finite_number`, NEVER ×100. (This is the same class of bug
  the `dividend_yield` double-scaling note warns about; a test locks it.)
- Text fields (`country`, `quote_type`, `website`, `business_summary`) pass
  through with plain `.get()`, no numeric coercion.
- The stock page stays native-currency and un-polled: stats are still fetched
  once per page load.

## Exact snake_case keys to add to `get_stats`

Mapping from Yahoo `.info` key → app key → coercion:

| Yahoo `.info` key        | app key                  | coercion                          |
|--------------------------|--------------------------|-----------------------------------|
| `forwardPE`              | `forward_pe`             | `_finite_number`                  |
| `priceToBook`            | `price_to_book`          | `_finite_number`                  |
| `pegRatio`               | `peg_ratio`              | `_finite_number`                  |
| `payoutRatio`            | `payout_ratio`           | `_percent_number`                 |
| `grossMargins`           | `gross_margin`           | `_percent_number`                 |
| `operatingMargins`       | `operating_margin`       | `_percent_number`                 |
| `profitMargins`          | `profit_margin`          | `_percent_number`                 |
| `returnOnEquity`         | `return_on_equity`       | `_percent_number`                 |
| `revenueGrowth`          | `revenue_growth`         | `_percent_number`                 |
| `earningsGrowth`         | `earnings_growth`        | `_percent_number`                 |
| `totalCash`              | `total_cash`             | `_finite_number`                  |
| `totalDebt`              | `total_debt`             | `_finite_number`                  |
| `freeCashflow`           | `free_cashflow`          | `_finite_number`                  |
| `ebitda`                 | `ebitda`                 | `_finite_number`                  |
| `debtToEquity`           | `debt_to_equity`         | `_finite_number` (verbatim)       |
| `sharesOutstanding`      | `shares_outstanding`     | `_finite_number`                  |
| `floatShares`            | `float_shares`           | `_finite_number`                  |
| `recommendationMean`     | `recommendation_mean`    | `_finite_number`                  |
| `numberOfAnalystOpinions`| `num_analyst_opinions`   | `_finite_number`                  |
| `fullTimeEmployees`      | `employees`              | `_finite_number`                  |
| `targetLowPrice`         | `target_low`             | `_finite_number`                  |
| `targetHighPrice`        | `target_high`            | `_finite_number`                  |
| `targetMedianPrice`      | `target_median`          | `_finite_number`                  |
| `country`                | `country`                | plain `.get()`                    |
| `quoteType`              | `quote_type`             | plain `.get()`                    |
| `website`                | `website`                | plain `.get()`                    |
| `longBusinessSummary`    | `business_summary`       | plain `.get()`                    |

## Exact template ids (new)

- Valuation: `stat-forward-pe`, `stat-price-to-book`, `stat-peg`
- Dividends & analysts: `stat-payout-ratio`, `stat-target-low`,
  `stat-target-high`, `stat-target-median`, `stat-num-analysts`,
  `stat-recommendation-mean`
- Profitability: `stat-gross-margin`, `stat-operating-margin`,
  `stat-profit-margin`, `stat-return-on-equity`, `stat-revenue-growth`,
  `stat-earnings-growth`
- Balance sheet: `stat-total-cash`, `stat-total-debt`, `stat-debt-to-equity`,
  `stat-free-cash-flow`, `stat-ebitda`, `stat-shares-out`, `stat-float-shares`
- Profile: `stat-country`, `stat-quote-type`, `stat-employees`, `stat-website`
- About: `stat-about`

Existing ids MUST NOT change: `stat-open`, `stat-day-high`, `stat-day-low`,
`stat-prev-close`, `stat-volume`, `stat-avg-volume`, `stat-week52-range`,
`stat-50d-avg`, `stat-200d-avg`, `stat-market-cap`, `stat-pe`, `stat-eps`,
`stat-dividend-yield`, `stat-beta`, `stat-target-price`, `stat-rating`,
`stat-sector`, `stat-industry`.

## 1. `market_data.py` — helper + `get_stats`

### 1a. New helper `_percent_number`
Place it immediately after the existing `_finite_number` helper (read the
file to find it). It must:
- return `None` when `_finite_number(value)` is `None`,
- otherwise return the finite float multiplied by 100.

Do NOT round. The frontend owns display rounding.

```python
def _percent_number(value):
    """A Yahoo fraction (0.12 = 12%) as a percent number (12.0).

    Returns None for a missing or non-finite value (same rule as
    _finite_number). No rounding — the frontend formats.
    """
    number = _finite_number(value)
    return None if number is None else number * 100
```

### 1b. Extend the `get_stats` return dict
Add every row from the table above to the returned dict, using the exact
coercion shown. Keep the existing keys and their comments untouched. Insert
the new keys in logical groups (valuation near `pe_ratio`, profitability and
balance after `beta`, analysts near `target_price`, profile near `sector`).

Update the `get_stats` docstring:
- The line that says the grid gets "nineteen Nones" is now wrong — say the
  list is long and point to the returned keys.
- Add a bullet: percent fields are already ×100 percent numbers
  (`payout_ratio`, the margins, `return_on_equity`, growth); `debt_to_equity`
  is passed through as Yahoo scales it.
- Add a bullet: `business_summary` is free text and is the longest field.

## 2. `templates/stock.html`

Reorganize the FOUR existing clusters and add the new cells + clusters. The
classification comments above the stats card must be updated to mention the
new clusters. Rules that MUST hold:
- Every numeric `<dd>` ships EMPTY (the `:empty` shimmer rule).
- A `dl` contains only `dt`/`dd`; the cluster `<h4>` stays OUTSIDE the `dl`.
- Keep the `.stats-grid` class on every `dl`.

Final cluster layout:

**Today** (unchanged): Open, Day High, Day Low, Prev Close, Volume,
Avg Volume.

**Ranges & averages** (unchanged): 52W Range, 50-Day Avg, 200-Day Avg.

**Valuation**: Market Cap (`stat-market-cap`), P/E (`stat-pe`),
Forward P/E (`stat-forward-pe`), PEG (`stat-peg`),
Price/Book (`stat-price-to-book`), EPS (`stat-eps`), Beta (`stat-beta`).

**Dividends & analysts** (new cluster label; moves Div Yield, Analyst Target
and Rating here from Valuation): Div Yield (`stat-dividend-yield`),
Payout Ratio (`stat-payout-ratio`), Analyst Target (`stat-target-price`),
Target Low (`stat-target-low`), Target High (`stat-target-high`),
Target Median (`stat-target-median`), Rating (`stat-rating`),
Analysts (`stat-num-analysts`),
Recommendation Mean (`stat-recommendation-mean`).

**Profitability** (new): Gross Margin (`stat-gross-margin`),
Operating Margin (`stat-operating-margin`),
Profit Margin (`stat-profit-margin`),
Return on Equity (`stat-return-on-equity`),
Revenue Growth (`stat-revenue-growth`),
Earnings Growth (`stat-earnings-growth`).

**Balance sheet** (new): Total Cash (`stat-total-cash`),
Total Debt (`stat-total-debt`), Debt/Equity (`stat-debt-to-equity`),
Free Cash Flow (`stat-free-cash-flow`), EBITDA (`stat-ebitda`),
Shares Out (`stat-shares-out`), Float (`stat-float-shares`).

**Profile**: Sector (`stat-sector`), Industry (`stat-industry`),
Country (`stat-country`), Type (`stat-quote-type`),
Employees (`stat-employees`), Website (`stat-website`).

**About** (new, AFTER the Profile cluster, OUTSIDE any `dl`):
```html
            <!-- Free-text company description from Yahoo's profile. A
                 paragraph, not a dt/dd pair: it is prose, not a number.
                 Ships EMPTY (the shimmer rule); stock.js fills it or "—". -->
            <div class="stats-cluster">
                <h4 class="stats-cluster-label">About</h4>
                <p class="stats-about" id="stat-about"></p>
            </div>
```

Website cell (an anchor so it is clickable, inside a normal `stat` div):
```html
                    <div class="stat"><dt>Website</dt><dd><a id="stat-website" target="_blank" rel="noopener"></a></dd></div>
```

## 3. `static/js/stock.js`

### 3a. Extend `paintStats`
Add `setStat` calls using the EXISTING formatter rules:
- **Percent cells** — `${formatNumber(v)}%`: `stat-payout-ratio`,
  `stat-gross-margin`, `stat-operating-margin`, `stat-profit-margin`,
  `stat-return-on-equity`, `stat-revenue-growth`, `stat-earnings-growth`,
  `stat-debt-to-equity`. Use `stats.key === null ? null : \`${formatNumber(stats.key)}%\``
  (same pattern as `stat-dividend-yield`).
- **Plain ratio cells** — `formatNumber`: `stat-forward-pe`,
  `stat-price-to-book`, `stat-peg`, `stat-recommendation-mean`.
- **Price cells** — `formatPrice`: `stat-target-low`, `stat-target-high`,
  `stat-target-median`.
- **Compact cells** — `compactFormat.format`: `stat-total-cash`,
  `stat-total-debt`, `stat-free-cash-flow`, `stat-ebitda`,
  `stat-shares-out`, `stat-float-shares`.
- **Integer cell** — `integerFormat.format`: `stat-employees`.
- **Text cells** — `setStat`: `stat-country`, `stat-quote-type`.
- **Website** — a DEDICATED block (the `setStat` helper only sets text):
  ```js
  // Website is a link, so setStat's text-only rule is not enough.
  if (stats.website == null) {
      setStat("stat-website", null);
      document.getElementById("stat-website").removeAttribute("href");
  } else {
      const link = document.getElementById("stat-website");
      link.textContent = stats.website;
      link.href = stats.website;
  }
  ```
- **About** — `setStat("stat-about", stats.business_summary)`. The shared
  null rule renders "—" when Yahoo has no summary.

### 3b. Extend `STAT_IDS`
Add every new id from the "Exact template ids (new)" list, INCLUDING
`stat-website` and `stat-about`, so a total stats failure degrades them all
to "—". Organize the array to mirror the template's cluster order.

## 4. `static/style.css`

Add one rule for the About paragraph near the existing `.stats-cluster`
rules (~line 3200):
```css
/* The company description: prose, so it wraps over the full card width
   instead of the tight stat-cell column. */
.stats-about {
    grid-column: 1 / -1;
    margin: 0;
    line-height: 1.5;
    color: var(--text-secondary);
}
```
Use the real secondary-text token in this file if `--text-secondary` is not
the one in use (check the surrounding rules; pick the existing muted token).

## 5. `project-brief.md`

- Update the `/stock/<symbol>` bullet list to add one line: more fundamentals
  (margins, multiples, balance-sheet figures, analyst depth, company profile
  and business summary) plus the position card is a LATER batch item — only
  mention what #52 ships (fundamentals + About).
- Update the "Stock-detail stats come from the heavy `Ticker.info` endpoint"
  Temporary Decision note so its field list includes the new values. The
  "not polled" rationale stays true and must stay.

## 6. Tests — WRITE FIRST, all must fail before implementation

New file: `tests/test_stock_stats.py`.

Imports (mirror `tests/test_stock.py`):
```python
from types import SimpleNamespace

import market_data
from conftest import make_quote
```

Fake helper (patch `market_data.yf`, WHERE MARKET_DATA USES IT — the
`test_stock.py` NaN test is the pattern):
```python
class FakeTicker:
    def __init__(self, info):
        self.info = info


def patch_info(monkeypatch, info):
    monkeypatch.setattr(
        market_data, "yf",
        SimpleNamespace(Ticker=lambda symbol: FakeTicker(info)),
    )
```

A full fake `.info` (use these exact values so assertions are exact):
```python
FULL_INFO = {
    "open": 148.0, "dayHigh": 152.0, "dayLow": 147.5,
    "regularMarketPreviousClose": 145.0, "volume": 55_000_000,
    "fiftyTwoWeekLow": 164.0, "fiftyTwoWeekHigh": 237.25,
    "marketCap": 3_500_000_000_000,
    "trailingPE": 28.5, "trailingEps": 6.10, "dividendYield": 0.57,
    "beta": 1.2, "fiftyDayAverage": 228.4,
    "twoHundredDayAverage": 210.15, "avgVolume10days": 42_000_000,
    "targetMeanPrice": 260.0, "recommendationKey": "buy",
    "sector": "Technology", "industry": "Consumer Electronics",
    # new:
    "forwardPE": 35.5, "priceToBook": 46.3, "pegRatio": 2.74,
    "payoutRatio": 0.1204, "grossMargins": 0.48653,
    "operatingMargins": 0.32623, "profitMargins": 0.27619,
    "returnOnEquity": 1.4875, "revenueGrowth": 0.164,
    "earningsGrowth": 0.287, "totalCash": 62_399_000_576,
    "totalDebt": 84_343_996_416, "freeCashflow": 107_721_875_456,
    "ebitda": 167_959_003_136, "debtToEquity": 78.445,
    "sharesOutstanding": 14_594_180_000, "floatShares": 14_569_078_010,
    "recommendationMean": 2.20455, "numberOfAnalystOpinions": 39,
    "fullTimeEmployees": 150_000, "targetLowPrice": 215.0,
    "targetHighPrice": 405.0, "targetMedianPrice": 340.0,
    "country": "United States", "quoteType": "EQUITY",
    "website": "https://www.apple.com",
    "longBusinessSummary": "Apple Inc. designs and sells electronics.",
}
```

Data-layer tests:
1. `test_get_stats_returns_new_keys` — patch FULL_INFO; assert every new app
   key is present and equals its expected value (ratios and text included).
2. `test_fraction_fields_are_percent_numbers` — assert
   `payout_ratio == 12.04`, `gross_margin == 48.653`,
   `operating_margin == pytest.approx(32.623)`,
   `profit_margin == pytest.approx(27.619)`,
   `return_on_equity == pytest.approx(148.75)`,
   `revenue_growth == pytest.approx(16.4)`,
   `earnings_growth == pytest.approx(28.7)`.
3. `test_debt_to_equity_verbatim` — `debt_to_equity == 78.445` (NOT 7844.5).
4. `test_missing_fields_are_none` — patch `{"marketCap": 5}`; every new key
   is `None`, and `get_stats` does NOT raise.
5. `test_non_finite_becomes_none` — patch
   `{"profitMargins": float("nan"), "totalCash": float("inf")}`; both keys
   `None`.
6. `test_empty_info_raises` — patch `{}`; `pytest.raises(ValueError)`.

Route test (uses the `client` + `fake_market` fixtures):
7. `test_stats_route_passes_new_keys_through` — set
   `fake_market.stats["AAPL"] = FULL_INFO_in_APP_SHAPE` (any dict with a few
   new keys is fine); assert `/api/stock/AAPL/stats` returns it UNCHANGED.

UI meta-tests (render `client.get("/stock/AAPL")` HTML):
8. `test_stock_page_has_all_new_stat_ids` — every new id appears as
   `id="<id>"`.
9. `test_new_stat_cells_ship_empty` — for each new numeric id, the regex
   `r'<dd id="<id>">([^<]*)</dd>'` matches and group(1) == ""; for
   `stat-about`, the regex `r'<p class="stats-about" id="stat-about">([^<]*)</p>'`
   matches and group(1) == "".

## 7. Order of work
1. Write ALL tests in `tests/test_stock_stats.py`.
2. Run `python -m pytest tests/test_stock_stats.py` — expect failures.
3. Add `_percent_number` and the new keys in `market_data.py`; update the
   docstring.
4. Update `templates/stock.html`.
5. Update `static/js/stock.js` (`paintStats`, `STAT_IDS`).
6. Update `static/style.css`.
7. Update `project-brief.md`.
8. `python -m pytest tests/test_stock_stats.py` → green.
9. Run the FULL `python -m pytest` (the suite is ~17s steady state).
10. Capture a screenshot of the expanded stats card (UI PR rule).
11. Report; await the user's GUI gate and commit approval. Do NOT commit.

## 8. Guardrails
- Do not add a second symbol list, a new endpoint, a cache, or a poll.
- Do not `round()` percent values in Python; the frontend formats.
- Do not multiply `debt_to_equity` by 100.
- Do not change any existing key name or any existing template id.
- Match the file's existing heavy explanatory-comment style.
