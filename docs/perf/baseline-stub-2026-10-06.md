# Portfoliarr performance baseline — 2026-10-06

- Mode: **stub 80 ms per Yahoo call**
- Runs per page: 2
- Settle after load: 4.0 s
- Run 1 is the first measured visit; later runs reuse the 120–600 s TTL caches. Compare like for like.

## Page loads (browser navigation timing)

| page | run | ttfb ms | dom ms | load ms | lcp ms | observed s | fetches |
|---|---|---|---|---|---|---|---|
| dashboard | 1 | 12 | 92 | 92 | 72 | 5.35 | 19 |
| dashboard | 2 | 6 | 42 | 42 | 48 | 5.22 | 19 |
| ledger | 1 | 5 | 36 | 36 | 44 | 4.73 | 3 |
| ledger | 2 | 6 | 36 | 36 | 48 | 4.74 | 3 |
| stock | 1 | 7 | 49 | 49 | 56 | 4.73 | 7 |
| stock | 2 | 3 | 40 | 41 | 36 | 4.72 | 7 |
| preferences | 1 | 6 | 38 | 38 | 48 | 4.57 | 5 |
| preferences | 2 | 3 | 23 | 23 | 32 | 4.55 | 5 |

## Render marks and slowest fetches

### dashboard run 1
- marks: dashboard:markets=184 ms  dashboard:watchlist=267 ms  dashboard:volume=296 ms  dashboard:summary=396 ms  chart:paint=399 ms  dashboard:chart=399 ms
- fetch /api/portfolio/history: 382 ms (server 178)
- fetch /api/portfolio/history: 381 ms (server 179)
- fetch /api/portfolio/summary: 287 ms (server 174)
- fetch /api/portfolio/history: 287 ms (server 173)
- fetch /api/indices: 214 ms (server 98)

### dashboard run 2
- marks: dashboard:markets=150 ms  dashboard:volume=245 ms  dashboard:watchlist=332 ms  dashboard:summary=342 ms  chart:paint=343 ms  dashboard:chart=343 ms
- fetch /api/portfolio/history: 359 ms (server 164)
- fetch /api/portfolio/history: 355 ms (server 169)
- fetch /api/watchlist: 292 ms (server 165)
- fetch /api/portfolio/history: 287 ms (server 171)
- fetch /api/portfolio/summary: 285 ms (server 167)

### ledger run 1
- marks: ledger:closed=45 ms  ledger:rows=211 ms
- fetch /api/transactions: 170 ms (server 162)
- fetch /api/portfolio/realized: 6 ms (server 2)
- fetch /api/portfolios: 5 ms (server 1)

### ledger run 2
- marks: ledger:closed=46 ms  ledger:rows=208 ms
- fetch /api/transactions: 167 ms (server 163)
- fetch /api/portfolios: 7 ms (server 1)
- fetch /api/portfolio/realized: 6 ms (server 2)

### stock run 1
- marks: stock:financials=146 ms  stock:events=147 ms  chart:paint=160 ms  stock:chart=160 ms  stock:quote=211 ms
- fetch /api/stock/:symbol: 171 ms (server 163)
- fetch /api/portfolio/position: 98 ms (server 81)
- fetch /api/stock/:symbol/events: 92 ms (server 81)
- fetch /api/stock/:symbol/financials: 92 ms (server 82)
- fetch /api/stock/:symbol/history: 91 ms (server 81)

### stock run 2
- marks: stock:events=127 ms  stock:financials=138 ms  chart:paint=146 ms  stock:chart=146 ms  stock:quote=208 ms
- fetch /api/stock/:symbol: 170 ms (server 164)
- fetch /api/stock/:symbol/history: 104 ms (server 82)
- fetch /api/stock/:symbol/financials: 92 ms (server 84)
- fetch /api/stock/:symbol/stats: 91 ms (server 82)
- fetch /api/stock/:symbol/events: 89 ms (server 81)

### preferences run 1
- marks: preferences:perf-card=49 ms
- fetch /api/portfolios: 11 ms (server 1)
- fetch /api/auth/signup-toggle: 10 ms (server 2)
- fetch /api/perf: 10 ms (server 3)
- fetch /api/users: 9 ms (server 3)
- fetch /api/widget/tokens: 8 ms (server 2)

### preferences run 2
- marks: preferences:perf-card=33 ms
- fetch /api/portfolios: 13 ms (server 7)
- fetch /api/users: 11 ms (server 4)
- fetch /api/widget/tokens: 9 ms (server 3)
- fetch /api/auth/signup-toggle: 9 ms (server 3)
- fetch /api/perf: 7 ms (server 1)

## Server endpoints (p95, process lifetime)

| endpoint | calls | p50 ms | p95 ms | max ms |
|---|---|---|---|---|
| portfolio_history | 27 | 177 | 190.9 | 199.7 |
| portfolio_summary | 3 | 166.9 | 174.1 | 174.1 |
| watchlist_quotes | 3 | 165.1 | 174.1 | 174.1 |
| log_transaction | 2 | 86.2 | 164.6 | 164.6 |
| stock_quote | 2 | 163.1 | 163.8 | 163.8 |
| list_transactions | 2 | 162.4 | 163.4 | 163.4 |
| index_quotes | 18 | 97.7 | 106.4 | 106.4 |
| add_to_watchlist | 2 | 83.1 | 85.8 | 85.8 |
| stock_financials | 2 | 81.9 | 84.3 | 84.3 |
| stock_stats | 2 | 81.7 | 82.7 | 82.7 |
| volume_leaders | 3 | 82.2 | 82.7 | 82.7 |
| stock_history | 2 | 81.3 | 82.1 | 82.1 |
| portfolio_position | 2 | 80.9 | 81.6 | 81.6 |
| stock_events | 2 | 80.7 | 81.4 | 81.4 |
| auth_setup | 1 | 69.1 | 69.1 | 69.1 |
| index | 3 | 3.9 | 9 | 9 |
| portfolios_api | 10 | 0.8 | 7.1 | 7.1 |
| list_users_api | 2 | 2.9 | 4.3 | 4.3 |
| preferences_page | 2 | 0.7 | 3.9 | 3.9 |
| auth_setup | 2 | 1.1 | 3.7 | 3.7 |
| stock_page | 2 | 0.7 | 3.7 | 3.7 |
| ledger_page | 2 | 1.3 | 3.4 | 3.4 |
| perf_api | 10 | 1.1 | 3.1 | 3.1 |
| widget_tokens_api | 2 | 2.5 | 3.1 | 3.1 |
| perf_client | 8 | 0.8 | 2.6 | 2.6 |
| signup_toggle_api | 2 | 2.1 | 2.6 | 2.6 |
| portfolio_realized | 2 | 1.6 | 1.6 | 1.6 |

## Market cache (process lifetime)

| operation | hit | miss | wait | hit rate | miss p95 ms |
|---|---|---|---|---|---|

