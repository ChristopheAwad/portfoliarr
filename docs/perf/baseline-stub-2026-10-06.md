# Portfoliarr performance baseline — 2026-10-06

- Mode: **stub 80 ms per Yahoo call**
- Runs per page: 2
- Settle after load: 4.0 s
- Run 1 is the first measured visit; later runs reuse the 120–600 s TTL caches. Compare like for like.

## Page loads (browser navigation timing)

| page | run | ttfb ms | dom ms | load ms | lcp ms | observed s | fetches |
|---|---|---|---|---|---|---|---|
| dashboard | 1 | 5 | 55 | 56 | 52 | 5.2 | 19 |
| dashboard | 2 | 4 | 101 | 102 | 72 | 5.27 | 19 |
| ledger | 1 | 28 | 103 | 103 | 112 | 4.8 | 3 |
| ledger | 2 | 3 | 43 | 44 | 52 | 4.76 | 3 |
| stock | 1 | 17 | 119 | 119 | 104 | 4.86 | 7 |
| stock | 2 | 6 | 99 | 99 | 80 | 4.84 | 7 |
| preferences | 1 | 14 | 63 | 63 | 68 | 4.66 | 5 |
| preferences | 2 | 4 | 27 | 28 | 40 | 4.62 | 5 |

## Render marks and slowest fetches

### dashboard run 1
- marks: dashboard:markets=141 ms  dashboard:watchlist=224 ms  dashboard:volume=242 ms  dashboard:summary=334 ms  chart:paint=335 ms  dashboard:chart=335 ms
- fetch /api/portfolio/history: 343 ms (server 164)
- fetch /api/portfolio/history: 342 ms (server 163)
- fetch /api/portfolio/summary: 261 ms (server 164)
- fetch /api/portfolio/history: 260 ms (server 164)
- fetch /api/indices: 190 ms (server 89)

### dashboard run 2
- marks: dashboard:markets=174 ms  dashboard:volume=266 ms  dashboard:watchlist=356 ms  dashboard:summary=366 ms  chart:paint=368 ms  dashboard:chart=368 ms
- fetch /api/portfolio/history: 350 ms (server 165)
- fetch /api/portfolio/history: 350 ms (server 164)
- fetch /api/watchlist: 269 ms (server 168)
- fetch /api/portfolio/history: 256 ms (server 166)
- fetch /api/portfolio/summary: 253 ms (server 165)

### ledger run 1
- marks: ledger:closed=115 ms  ledger:rows=280 ms
- fetch /api/transactions: 170 ms (server 164)
- fetch /api/portfolios: 14 ms (server 1)
- fetch /api/portfolio/realized: 7 ms (server 2)

### ledger run 2
- marks: ledger:closed=52 ms  ledger:rows=217 ms
- fetch /api/transactions: 168 ms (server 163)
- fetch /api/portfolios: 8 ms (server 1)
- fetch /api/portfolio/realized: 6 ms (server 1)

### stock run 1
- marks: stock:financials=216 ms  stock:events=217 ms  chart:paint=223 ms  stock:chart=223 ms  stock:quote=292 ms
- fetch /api/stock/:symbol: 179 ms (server 165)
- fetch /api/portfolio/position: 97 ms (server 81)
- fetch /api/stock/AAPL/history: 97 ms (server 83)
- fetch /api/stock/AAPL/events: 94 ms (server 84)
- fetch /api/stock/AAPL/financials: 93 ms (server 85)

### stock run 2
- marks: stock:events=182 ms  chart:paint=186 ms  stock:chart=186 ms  stock:financials=208 ms  stock:quote=263 ms
- fetch /api/stock/:symbol: 172 ms (server 164)
- fetch /api/stock/AAPL/financials: 97 ms (server 81)
- fetch /api/stock/AAPL/events: 89 ms (server 83)
- fetch /api/stock/AAPL/history: 89 ms (server 82)
- fetch /api/stock/AAPL/stats: 88 ms (server 82)

### preferences run 1
- marks: preferences:perf-card=70 ms
- fetch /api/portfolios: 14 ms (server 1)
- fetch /api/users: 9 ms (server 3)
- fetch /api/widget/tokens: 9 ms (server 3)
- fetch /api/auth/signup-toggle: 8 ms (server 3)
- fetch /api/perf: 6 ms (server 1)

### preferences run 2
- marks: preferences:perf-card=37 ms
- fetch /api/users: 11 ms (server 5)
- fetch /api/widget/tokens: 11 ms (server 4)
- fetch /api/auth/signup-toggle: 10 ms (server 4)
- fetch /api/perf: 8 ms (server 3)
- fetch /api/portfolios: 7 ms (server 1)

## Server endpoints (p95, process lifetime)

| endpoint | calls | p50 ms | p95 ms | max ms |
|---|---|---|---|---|
| portfolio_history | 27 | 164.5 | 169.9 | 170.4 |
| watchlist_quotes | 3 | 167.8 | 168.6 | 168.6 |
| portfolio_summary | 3 | 164.1 | 165.4 | 165.4 |
| stock_quote | 2 | 164.4 | 165.1 | 165.1 |
| list_transactions | 2 | 162.9 | 163.9 | 163.9 |
| log_transaction | 2 | 81.7 | 162.1 | 162.1 |
| index_quotes | 18 | 93.1 | 109.9 | 109.9 |
| volume_leaders | 3 | 85.3 | 87.2 | 87.2 |
| stock_financials | 2 | 80.8 | 84.8 | 84.8 |
| stock_events | 2 | 82.6 | 83.8 | 83.8 |
| stock_history | 2 | 82.1 | 83.4 | 83.4 |
| stock_stats | 2 | 82.2 | 83.3 | 83.3 |
| add_to_watchlist | 2 | 81.2 | 81.8 | 81.8 |
| portfolio_position | 2 | 80.9 | 81 | 81 |
| auth_setup | 1 | 67.9 | 67.9 | 67.9 |
| ledger_page | 2 | 0.6 | 22.1 | 22.1 |
| stock_page | 2 | 1.8 | 10.8 | 10.8 |
| index | 3 | 1.3 | 9.5 | 9.5 |
| preferences_page | 2 | 0.9 | 9.2 | 9.2 |
| perf_api | 10 | 2.1 | 5.8 | 5.8 |
| list_users_api | 2 | 3.3 | 5.3 | 5.3 |
| signup_toggle_api | 2 | 2.9 | 4.5 | 4.5 |
| auth_setup | 2 | 0.8 | 3.9 | 3.9 |
| widget_tokens_api | 2 | 3.1 | 3.6 | 3.6 |
| perf_client | 8 | 1.3 | 2.9 | 2.9 |
| portfolio_realized | 2 | 1.3 | 1.9 | 1.9 |
| portfolios_api | 10 | 0.9 | 1.8 | 1.8 |

## Market cache (process lifetime)

| operation | hit | miss | wait | hit rate | miss p95 ms |
|---|---|---|---|---|---|

