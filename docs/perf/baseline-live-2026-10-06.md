# Portfoliarr performance baseline — 2026-10-06

- Mode: **live Yahoo**
- Runs per page: 2
- Settle after load: 4.0 s
- Run 1 is the first measured visit; later runs reuse the 120–600 s TTL caches. Compare like for like.

## Page loads (browser navigation timing)

| page | run | ttfb ms | dom ms | load ms | lcp ms | observed s | fetches |
|---|---|---|---|---|---|---|---|
| dashboard | 1 | 3 | 79 | 80 | 56 | 5.63 | 19 |
| dashboard | 2 | 3 | 45 | 45 | 52 | 4.64 | 19 |
| ledger | 1 | 6 | 34 | 36 | 36 | 4.56 | 3 |
| ledger | 2 | 4 | 26 | 27 | 36 | 4.57 | 3 |
| stock | 1 | 7 | 38 | 38 | 48 | 5.22 | 7 |
| stock | 2 | 4 | 53 | 54 | 56 | 4.98 | 7 |
| preferences | 1 | 13 | 50 | 51 | 60 | 4.63 | 5 |
| preferences | 2 | 6 | 55 | 55 | 60 | 4.6 | 5 |

## Render marks and slowest fetches

### dashboard run 1
- marks: dashboard:markets=88 ms  dashboard:volume=92 ms  dashboard:summary=377 ms  chart:paint=382 ms  dashboard:chart=382 ms  dashboard:watchlist=538 ms
- fetch /api/portfolio/history: 716 ms (server 391)
- fetch /api/portfolio/history: 656 ms (server 385)
- fetch /api/watchlist: 472 ms (server 466)
- fetch /api/portfolio/history: 424 ms (server 270)
- fetch /api/portfolio/history: 397 ms (server 391)

### dashboard run 2
- marks: dashboard:markets=53 ms  dashboard:volume=65 ms  dashboard:watchlist=68 ms  dashboard:summary=78 ms  chart:paint=79 ms  dashboard:chart=79 ms
- fetch /api/indices: 37 ms (server 23)
- fetch /api/watchlist: 33 ms (server 10)
- fetch /api/indices: 32 ms (server 17)
- fetch /api/indices: 30 ms (server 11)
- fetch /api/indices: 29 ms (server 16)

### ledger run 1
- marks: ledger:rows=44 ms  ledger:closed=44 ms
- fetch /api/portfolio/realized: 7 ms (server 2)
- fetch /api/transactions: 6 ms (server 2)
- fetch /api/portfolios: 5 ms (server 0)

### ledger run 2
- marks: ledger:rows=38 ms  ledger:closed=39 ms
- fetch /api/portfolio/realized: 8 ms (server 2)
- fetch /api/transactions: 6 ms (server 2)
- fetch /api/portfolios: 5 ms (server 1)

### stock run 1
- marks: chart:paint=46 ms  stock:chart=47 ms  stock:financials=249 ms  stock:quote=336 ms  stock:stats=451 ms  stock:events=695 ms
- fetch /api/stock/AAPL/events: 662 ms (server 644)
- fetch /api/stock/AAPL/stats: 417 ms (server 412)
- fetch /api/stock/:symbol: 300 ms (server 294)
- fetch /api/stock/AAPL/financials: 208 ms (server 202)
- fetch /api/portfolios: 16 ms (server 0)

### stock run 2
- marks: stock:quote=59 ms  stock:events=60 ms  stock:financials=67 ms  chart:paint=74 ms  stock:chart=74 ms  stock:stats=423 ms
- fetch /api/stock/AAPL/stats: 380 ms (server 375)
- fetch /api/portfolios: 19 ms (server 1)
- fetch /api/portfolio/position: 14 ms (server 1)
- fetch /api/stock/AAPL/financials: 13 ms (server 6)
- fetch /api/stock/AAPL/history: 13 ms (server 5)

### preferences run 1
- marks: preferences:perf-card=58 ms
- fetch /api/auth/signup-toggle: 13 ms (server 5)
- fetch /api/widget/tokens: 13 ms (server 6)
- fetch /api/portfolios: 12 ms (server 1)
- fetch /api/users: 11 ms (server 3)
- fetch /api/perf: 10 ms (server 2)

### preferences run 2
- marks: preferences:perf-card=66 ms
- fetch /api/users: 14 ms (server 5)
- fetch /api/auth/signup-toggle: 13 ms (server 5)
- fetch /api/widget/tokens: 12 ms (server 4)
- fetch /api/perf: 9 ms (server 3)
- fetch /api/portfolios: 7 ms (server 1)

## Server endpoints (p95, process lifetime)

| endpoint | calls | p50 ms | p95 ms | max ms |
|---|---|---|---|---|
| volume_leaders | 3 | 3.6 | 1620.4 | 1620.4 |
| index_quotes | 18 | 13.8 | 1376.8 | 1376.8 |
| stock_events | 2 | 3.2 | 643.8 | 643.8 |
| watchlist_quotes | 3 | 34.4 | 466 | 466 |
| stock_stats | 2 | 375.3 | 411.7 | 411.7 |
| add_to_watchlist | 2 | 213.8 | 399.5 | 399.5 |
| portfolio_history | 27 | 8 | 390.7 | 390.8 |
| log_transaction | 2 | 260.3 | 357 | 357 |
| stock_quote | 2 | 2.9 | 294.1 | 294.1 |
| portfolio_summary | 3 | 7.6 | 280.9 | 280.9 |
| stock_financials | 2 | 5.6 | 202.3 | 202.3 |
| auth_setup | 1 | 73.2 | 73.2 | 73.2 |
| index | 3 | 0.8 | 9.5 | 9.5 |
| preferences_page | 2 | 1.3 | 7.2 | 7.2 |
| stock_history | 2 | 4.6 | 5.9 | 5.9 |
| widget_tokens_api | 2 | 4 | 5.5 | 5.5 |
| auth_setup | 2 | 0.9 | 5.4 | 5.4 |
| signup_toggle_api | 2 | 4.9 | 5.3 | 5.3 |
| perf_api | 10 | 1.3 | 5.1 | 5.1 |
| list_users_api | 2 | 3 | 4.8 | 4.8 |
| stock_page | 2 | 1.2 | 4.4 | 4.4 |
| perf_client | 8 | 1.2 | 4.1 | 4.1 |
| ledger_page | 2 | 0.9 | 3.5 | 3.5 |
| portfolio_position | 2 | 1.1 | 2.7 | 2.7 |
| list_transactions | 2 | 2.3 | 2.4 | 2.4 |
| portfolio_realized | 2 | 2.1 | 2.4 | 2.4 |
| portfolios_api | 10 | 0.6 | 0.9 | 0.9 |

## Market cache (process lifetime)

| operation | hit | miss | wait | hit rate | miss p95 ms |
|---|---|---|---|---|---|
| market.get_quote | 86 | 30 | 1 | 74% | 1031.5 |
| market.get_history | 20 | 18 | 0 | 53% | 376.9 |
| market.get_name | 3 | 3 | 0 | 50% | 460.6 |
| market.get_financials | 1 | 1 | 0 | 50% | 200.3 |
| market.get_events | 1 | 1 | 0 | 50% | 643.1 |
| market.get_volume_leaders | 2 | 1 | 0 | 67% | 1616.5 |

