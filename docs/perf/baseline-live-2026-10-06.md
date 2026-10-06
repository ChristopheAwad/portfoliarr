# Portfoliarr performance baseline — 2026-10-06

- Mode: **live Yahoo**
- Runs per page: 2
- Settle after load: 4.0 s
- Run 1 is the first measured visit; later runs reuse the 120–600 s TTL caches. Compare like for like.

## Page loads (browser navigation timing)

| page | run | ttfb ms | dom ms | load ms | lcp ms | observed s | fetches |
|---|---|---|---|---|---|---|---|
| dashboard | 1 | 3 | 45 | 46 | 48 | 5.56 | 19 |
| dashboard | 2 | 3 | 35 | 36 | 40 | 4.65 | 19 |
| ledger | 1 | 12 | 58 | 58 | 60 | 4.62 | 3 |
| ledger | 2 | 3 | 32 | 32 | 36 | 4.6 | 3 |
| stock | 1 | 11 | 75 | 76 | 72 | 5.27 | 7 |
| stock | 2 | 4 | 39 | 40 | 44 | 4.89 | 7 |
| preferences | 1 | 5 | 46 | 47 | 52 | 4.59 | 5 |
| preferences | 2 | 3 | 23 | 23 | 28 | 4.6 | 5 |

## Render marks and slowest fetches

### dashboard run 1
- marks: dashboard:markets=50 ms  dashboard:volume=54 ms  chart:paint=398 ms  dashboard:chart=398 ms  dashboard:summary=412 ms  dashboard:watchlist=479 ms
- fetch /api/portfolio/history: 632 ms (server 378)
- fetch /api/portfolio/history: 600 ms (server 327)
- fetch /api/watchlist: 436 ms (server 425)
- fetch /api/portfolio/history: 380 ms (server 374)
- fetch /api/portfolio/history: 374 ms (server 294)

### dashboard run 2
- marks: dashboard:markets=48 ms  dashboard:volume=59 ms  dashboard:watchlist=63 ms  chart:paint=65 ms  dashboard:chart=65 ms  dashboard:summary=77 ms
- fetch /api/watchlist: 27 ms (server 4)
- fetch /api/portfolio/summary: 25 ms (server 5)
- fetch /api/market/volume-leaders: 24 ms (server 1)
- fetch /api/portfolio/history: 23 ms (server 4)
- fetch /api/portfolio/history: 22 ms (server 4)

### ledger run 1
- marks: ledger:closed=71 ms  ledger:rows=73 ms
- fetch /api/transactions: 10 ms (server 4)
- fetch /api/portfolio/realized: 7 ms (server 2)
- fetch /api/portfolios: 6 ms (server 1)

### ledger run 2
- marks: ledger:closed=42 ms  ledger:rows=45 ms
- fetch /api/transactions: 8 ms (server 3)
- fetch /api/portfolios: 5 ms (server 1)
- fetch /api/portfolio/realized: 4 ms (server 1)

### stock run 1
- marks: chart:paint=93 ms  stock:chart=93 ms  stock:financials=302 ms  stock:stats=485 ms  stock:quote=537 ms  stock:events=754 ms
- fetch /api/stock/:symbol/events: 680 ms (server 668)
- fetch /api/stock/:symbol: 458 ms (server 453)
- fetch /api/stock/:symbol/stats: 410 ms (server 404)
- fetch /api/stock/:symbol/financials: 220 ms (server 216)
- fetch /api/portfolios: 21 ms (server 1)

### stock run 2
- marks: stock:financials=50 ms  stock:quote=52 ms  stock:events=52 ms  chart:paint=58 ms  stock:chart=58 ms  stock:stats=366 ms
- fetch /api/stock/:symbol/stats: 335 ms (server 330)
- fetch /api/portfolios: 15 ms (server 0)
- fetch /api/stock/:symbol/history: 13 ms (server 6)
- fetch /api/stock/:symbol: 12 ms (server 3)
- fetch /api/stock/:symbol/events: 12 ms (server 5)

### preferences run 1
- marks: preferences:perf-card=53 ms
- fetch /api/portfolios: 13 ms (server 1)
- fetch /api/perf: 11 ms (server 4)
- fetch /api/auth/signup-toggle: 11 ms (server 3)
- fetch /api/widget/tokens: 10 ms (server 2)
- fetch /api/users: 10 ms (server 2)

### preferences run 2
- marks: preferences:perf-card=34 ms
- fetch /api/widget/tokens: 12 ms (server 4)
- fetch /api/auth/signup-toggle: 11 ms (server 5)
- fetch /api/perf: 10 ms (server 3)
- fetch /api/users: 9 ms (server 3)
- fetch /api/portfolios: 5 ms (server 0)

## Server endpoints (p95, process lifetime)

| endpoint | calls | p50 ms | p95 ms | max ms |
|---|---|---|---|---|
| volume_leaders | 3 | 2.1 | 1272.9 | 1272.9 |
| index_quotes | 18 | 11.9 | 1141.9 | 1141.9 |
| stock_events | 2 | 4.9 | 667.9 | 667.9 |
| log_transaction | 2 | 418.8 | 466 | 466 |
| stock_quote | 2 | 3.2 | 452.8 | 452.8 |
| watchlist_quotes | 3 | 26 | 424.6 | 424.6 |
| stock_stats | 2 | 330.4 | 403.9 | 403.9 |
| portfolio_history | 27 | 11.2 | 374.4 | 378.5 |
| portfolio_summary | 3 | 9.4 | 337.8 | 337.8 |
| add_to_watchlist | 2 | 262 | 280.3 | 280.3 |
| stock_financials | 2 | 1.1 | 215.5 | 215.5 |
| auth_setup | 1 | 70.5 | 70.5 | 70.5 |
| index | 3 | 0.8 | 18.7 | 18.7 |
| stock_page | 2 | 0.8 | 7.5 | 7.5 |
| perf_api | 10 | 2 | 7.3 | 7.3 |
| auth_setup | 2 | 1.3 | 6.8 | 6.8 |
| stock_history | 2 | 1.8 | 5.9 | 5.9 |
| ledger_page | 2 | 0.6 | 5.6 | 5.6 |
| signup_toggle_api | 2 | 2.9 | 5.1 | 5.1 |
| perf_client | 8 | 1.6 | 5 | 5 |
| widget_tokens_api | 2 | 1.5 | 4.5 | 4.5 |
| list_transactions | 2 | 2.9 | 3.9 | 3.9 |
| list_users_api | 2 | 2.1 | 3.1 | 3.1 |
| preferences_page | 2 | 0.6 | 2.4 | 2.4 |
| portfolio_position | 2 | 0.7 | 2.2 | 2.2 |
| portfolio_realized | 2 | 1.4 | 1.7 | 1.7 |
| portfolios_api | 10 | 0.8 | 1.1 | 1.1 |

## Market cache (process lifetime)

| operation | hit | miss | wait | hit rate | miss p95 ms |
|---|---|---|---|---|---|
| market.get_quote | 86 | 30 | 1 | 74% | 855.5 |
| market.get_history | 20 | 18 | 0 | 53% | 209.2 |
| market.get_name | 3 | 3 | 0 | 50% | 448.6 |
| market.get_financials | 1 | 1 | 0 | 50% | 214 |
| market.get_events | 1 | 1 | 0 | 50% | 665.9 |
| market.get_volume_leaders | 2 | 1 | 0 | 67% | 1267.5 |

