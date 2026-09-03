# Feature: Transaction Importer (Paste → Preview → Commit)

## Goal

Bulk-load an existing transaction history without typing rows one by one.
The source is a paste of tab-separated rows:

```
CM	16 Mar 2026	132.55	1.296383
CM	30 Mar 2026	128.89	1.333187
CM	14 Apr 2026	142.32	1.207422
CM	27 Apr 2026	149.91	1.146318
CM	11 May 2026	150.07	1.145075
CM	25 May 2026	160.07	1.07353
```

| Column | Meaning | Ledger mapping |
|---|---|---|
| 1 | ticker | `ticker` (trim + uppercase) |
| 2 | `DD Mon YYYY` date | `transaction_date` (ISO `2026-03-16`) |
| 3 | price | `price` |
| 4 | qty (fractional) | `qty` |

No buy/sell column, no currency. Currency is DERIVED from yfinance at
insert time (same rule as `POST /api/transactions`); the side is ALWAYS BUY.

Two-phase flow, decided with the user: **preview** parses + quote-checks
the paste and shows the rows (zero writes), then **commit** re-parses and
writes. The user sees exactly what will land before anything does.

## Decisions locked (with the user)

Each row names its rework trigger — when it fires, revisit the choice.

| Decision | Choice | Why | Rework trigger |
|---|---|---|---|
| Input | Paste textarea | No multipart/file handling anywhere; volumes are tiny | Imports too big to paste comfortably |
| Side | Every row BUY | Format has no side column | Source starts including sells → dropdown or column |
| Duplicates | No detection | Rows carry no usable identity | Re-importing becomes routine |
| Failure policy | Best-effort + report | Matches per-symbol resilience (indices bar, portfolio history): 50 rows shouldn't die on row 17 | — |
| Parser location | `app.py` | "Which data means what" is a route-layer product decision (same as `INDEX_SYMBOLS`); `db.py`/`market_data.py` stay pure | — |

Note: when this ships, the durable "why" gets encoded in code comments next
to the code (AGENTS.md rule) — this file is wiped per feature.

## Subtasks

### 1. `app.py` — `parse_import_text(text)`

One helper both routes share. Returns a list of row dicts, each either the
normalized fields (`ticker`, `transaction_date`, `price`, `qty`,
`transaction_type`) with `error: None`, or the offending input with
`error: "<reason>"` — the report shape both routes build on.

- Split on lines (tolerate `\r\n`), skip blank lines.
- Split each line on TAB; not exactly 4 fields → that row fails with a reason.
- Ticker: `strip().upper()` — same canonical form as `log_transaction`.
- Date: `datetime.strptime(value, "%d %b %Y").date().isoformat()`.
  VERIFIED: `"16 Mar 2026"` → `2026-03-16`; non-padded `"1 May 2026"` works
  too. The `.date()` matters — strptime hands back a DATETIME, and its
  isoformat would smuggle `T00:00:00` into the ledger. `%b` is the
  abbreviated ENGLISH month; a localized source fails loudly, which is fine.
- Price/qty: `float()`, must be > 0. Fractional qty (`1.296383`) is exactly
  why the qty column is REAL.
- `transaction_type`: forced `"BUY"`.

Deliberately strict: no `$`/comma stripping, no whitespace-split fallback.
Parse exactly the known format. Caveat to check against the REAL file: the
chat paste may have been reformatted — if the actual source is space-aligned
rather than tab-separated, only the splitter changes.

### 2. `app.py` — `POST /api/transactions/import/preview`

Body `{text}` (JSON). Parse, then `get_quote` per UNIQUE ticker (same dedup
as `list_transactions`; the 120s cache makes repeats free). A row whose
ticker can't be quoted is marked invalid ("unknown or unquotable ticker") —
same rule as `log_transaction`'s 404. Valid rows get the quote's currency
attached for display.

Returns `{"rows": [...], "valid_count": n, "invalid_count": m}`.
ZERO WRITES — the ledger is untouched; that's what makes the preview
trustworthy. Empty/missing text → 400.

### 3. `app.py` — `POST /api/transactions/import/commit`

Body `{text}` AGAIN — the server re-parses and trusts nothing the client
could have edited between preview and commit. One parse function, two
routes, single source of truth.

Per valid row: currency from `get_quote` (unique tickers only),
`db.add_transaction(..., transaction_type="BUY")`. Best-effort per row:
a ticker quotable at preview but dead by commit is skipped and reported,
never fatal.

Returns `{"imported": n, "failed": [{"row": ..., "error": ...}]}` at 200
even when `imported == 0` — the request succeeded; the report IS the answer.

Currency caveat, documented in the UI hint: the ledger stores the trading
currency of the ticker AS YAHOO QUOTES IT. `CM` on Yahoo is CIBC's NYSE
listing (USD — verified live). If a trade actually executed on TSX in CAD,
the paste must say `CM.TO`. Same rule as logging by hand; the importer
doesn't guess or convert.

### 4. `templates/index.html` + `static/js/main.js` — the panel

- "Import" button in the ledger card header.
- Toggles a small panel: textarea, Preview button, results area.
- Preview renders rows: valid ones (ticker, date, price, qty, currency);
  invalid ones red with their reason.
- "Import N rows" button (only when N > 0) → POST commit → `refreshLedger()`
  → close panel.
- Backend sends raw floats; number formatting stays frontend-only (existing
  rule). Pure fetch + DOM, no new dependencies.
- Hint text in the panel: every row is logged as a BUY; re-pasting the same
  rows creates duplicates (no detection); ticker must be the Yahoo form
  (`CM` = USD NYSE listing, `CM.TO` = CAD TSX listing).

### 5. `tests/test_import.py`

Parser unit tests (pure, no fixtures): happy path; `"1 May 2026"`
no-leading-zero; bad date; 3-column line; blank lines skipped; lowercase
ticker.

Route tests, following the house patterns (AGENTS.md): `fresh_db` for the
DB; `monkeypatch.setattr(app_module, "get_quote", Fake)` — patch WHERE
IT'S USED (`app.py` imports `get_quote` by name, so rebind it in app's
namespace, never `market_data`'s).

- preview inserts NOTHING (ledger still empty after the call)
- commit inserts the rows and derives currency from the fake quote
- unquotable ticker → its rows land in `failed`, the rest still import
- missing/empty text → 400

No test touches the network.

### 6. Manual verification

1. `python -m pytest` — full suite green.
2. `python app.py`; paste the real rows; Preview → check the valid-row list
   and derived currency against what Yahoo actually says.
3. Commit → ledger shows the rows grouped under CM; holdings and the
   portfolio chart react.
4. Re-paste the same rows → duplicates appear (known, documented behavior).

## Files changed

| File | What changes |
|---|---|
| `app.py` | `parse_import_text` + two import routes |
| `templates/index.html` | Import button + panel markup |
| `static/js/main.js` | Panel toggle, preview render, commit call |
| `tests/test_import.py` | New: parser + route tests |
| `feature.md` | This document |

`db.py`, `market_data.py` — **no changes**. The pure layers keep their
contracts; the browser gets one new panel.

## Non-goals (deliberately)

- SELL rows / side selector — rework trigger in the decisions table.
- Duplicate detection.
- File upload / multipart.
- `$`/comma stripping, whitespace-split fallback — strict to the known format.
- Localized month names — `%b` is English; a changed source fails loudly.
- FX conversion / ticker-form guessing (`CM` vs `CM.TO`) — the ledger stores
  what the paste says, same as manual logging.
