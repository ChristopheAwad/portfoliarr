# Feature #21: High-Value Operational Logging

## Status

SHIPPED 2026-09-22 in PR #71. Automated verification passed; live Docker log
approval remains a post-deployment check because the image is published only
after this PR reaches `main`.

This file is the complete test-first implementation handoff. Write all failing
tests before production edits. After implementation and a green full pytest
suite, stop for the user's live-log approval. Do not commit or push before that
approval.

## Problem

The application already logs caught failures at the Flask route boundary, which
is the correct architectural location. However, the current output is difficult
to use in production:

1. Flask's production logger level is not explicitly configured, so useful
   `INFO` events may be hidden.
2. Concurrent requests and worker-thread failures have no correlation ID.
3. Most successful ledger and watchlist mutations have no audit record.
4. Routine Yahoo outages can emit one full traceback per symbol, producing more
   noise than diagnosis.
5. Normal request durations exist only at `DEBUG`; unusually slow requests are
   not promoted to a visible warning.
6. Some degradation paths, including transaction-list and import quote
   failures, are silent.
7. The failed-search warning includes the user's raw query.
8. Docker log storage has no explicit size or file-count limit.

The goal is not to log every action or payload. The goal is to make a small
production log answer: what operation failed, which request it belonged to,
whether stored data changed, and whether the app was unusually slow.

## Approved Product And Engineering Decisions

1. Logs remain console-only. Python writes to stderr and Docker collects the
   stream. Do not add files, SQLite log tables, cloud services, or a logging
   dependency.
2. Use one human-readable `key=value` line per event. Do not emit application
   JSON inside Docker's JSON log envelope.
3. The stable line prefix is local ISO-8601 time with numeric offset, level,
   logger name, then the event fields:

   ```text
   2026-09-22T14:31:05-0400 INFO app event=transaction_created request_id=... tx_id=42 ticker='AAPL'
   ```

4. Production defaults to `INFO`. `LOG_LEVEL` may override it only with one of
   `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`, case-insensitively. A
   missing value means `INFO`. An invalid value falls back to `INFO` and emits
   one warning that names the invalid level with `%r`; it must not prevent boot.
5. Configure Python logging before constructing the Flask app. Use the standard
   library only. Keep existing loggers enabled so Gunicorn can retain its own
   process lifecycle output.
6. Do not enable Gunicorn access logging. Browser polling would duplicate the
   application request records and produce low-value volume.
7. Keep logging ownership in `app.py`. `db.py` and `market_data.py` continue to
   raise and never log.
8. Every request gets a new server-generated `uuid.uuid4().hex` ID. Do not trust
   or reuse an inbound `X-Request-ID`; this LAN app has no trusted reverse-proxy
   correlation contract, and server generation prevents log injection.
9. Return the ID on every Flask response as `X-Request-ID`, including 4xx and
   handled 500 responses.
10. Every application log emitted while serving a request includes
    `request_id=<32 lowercase hex characters>`. Worker closures capture the
    string before entering a thread; they do not access Flask `request` or `g`
    from worker threads.
11. User-controlled strings are formatted with `%r`, so quotes, newlines, and
    other control characters are escaped instead of creating forged log lines.
12. Never log request or response bodies, pasted import text, transaction price,
    quantity, FX rate, portfolio value, cost basis, gain, or complete database
    rows.
13. Tickers and database IDs may be logged where they identify a mutation or a
    failed market lookup. They are useful operational identifiers, but no
    financial amounts accompany them.
14. Do not log the raw ticker-search query. A failed search records only
    `query_length` and the exception type.
15. Successful read-only requests do not appear at `INFO`. Their completion
    event remains `DEBUG`.
16. A request taking at least `SLOW_REQUEST_MS = 2000` is logged once at
    `WARNING` instead of also receiving a duplicate `DEBUG` completion line.
    Keep this threshold as a named code constant, not an environment setting.
17. Request completion logs use the route path only. Do not include query
    strings, fragments, bodies, client IPs, or user-agent strings.
18. Routine Yahoo/yfinance failures are recovered degradation, not bugs. Log a
    compact `WARNING` with operation, attempted/succeeded/failed counts, failed
    symbols, and distinct exception class names. Do not attach `exc_info`.
19. Unexpected exceptions that reach the global Flask handler remain `ERROR`
    with `exc_info=True` and a full traceback.
20. Database write failures caught for best-effort import remain `WARNING` with
    `exc_info=True`, because they indicate a local persistence problem rather
    than expected bad market data. Include line number and request ID, never the
    imported row.
21. Confirmed data mutations emit one `INFO` audit event after the database
    reports success. Rejected, duplicate, missing, or rolled-back mutations do
    not emit a success event.
22. Docker uses the existing `json-file` driver with `max-size: "10m"` and
    `max-file: "3"`. This bounds retained local logs to approximately 30 MB plus
    Docker overhead.
23. No cache hit/miss telemetry, SQL statement logging, metrics backend,
    tracing system, health endpoint, alerting system, or frontend logging is in
    this feature.

## Event Vocabulary

Use the exact lower-snake-case event names below. Each log message starts with
`event=<name>` and then its required fields. Stable names make `docker compose
logs portfoliarr | grep 'event=...'` useful without a log platform.

### Process Events

1. `logging_level_invalid`
   Required fields: `configured_level`.
   Level: `WARNING`.
2. `database_initialization_failed`
   Required fields: none beyond `event`; include `exc_info=True`.
   Level: `CRITICAL`; re-raise after logging so the process fails fast.
3. `application_started`
   Required fields: `log_level`, `database=initialized`.
   Level: `INFO`; emit only after `db.init()` succeeds.

Process events have no request ID because no request exists yet.

### Request Events

1. `request_complete`
   Required fields: `request_id`, `method`, `path`, `status`, `duration_ms`.
   Level: `DEBUG` below 2000 ms, `WARNING` at or above 2000 ms.
2. `unhandled_error`
   Required fields: `request_id`, `method`, `path`.
   Level: `ERROR` with `exc_info=True`.

Use `%r` for `path`. The timing hook must tolerate a defensive missing start
time by defaulting to the current `perf_counter()`; normal Flask dispatch always
sets it, but error paths must not cause a second error while logging.

### Mutation Audit Events

1. `watchlist_added`: `request_id`, `symbol`.
2. `watchlist_removed`: `request_id`, `symbol`.
3. `transaction_created`: `request_id`, `tx_id`, `ticker`, `type`.
4. `transaction_updated`: `request_id`, `tx_id`, `ticker`, `type`.
5. `transaction_deleted`: `request_id`, `tx_id`.
6. `ticker_transactions_deleted`: `request_id`, `ticker`, `deleted_count`.
7. `transaction_import_completed`: `request_id`, `imported_count`,
   `failed_count`.

All mutation audit events are `INFO`. Do not add price, quantity, date,
currency, FX rate, or the original import line.

### Expected Rejection Events

Keep the currently useful typo and not-found diagnostics at `INFO`, converted to
stable events:

1. `watchlist_symbol_rejected`: `request_id`, `symbol`,
   `reason=unquotable`.
2. `transaction_ticker_rejected`: `request_id`, `ticker`,
   `reason=unquotable`.
3. `ticker_delete_rejected`: `request_id`, `ticker`,
   `reason=no_transactions`.
4. `historical_price_unavailable`: `request_id`, `symbol`, `date`.
5. `quote_unavailable`: `request_id`, `operation`, `symbol` for the existing
   endpoints that intentionally translate a quote miss to HTTP 404.

Do not add logs for generic validation 400s, duplicate watchlist 409s, missing
row 404s, or normal empty lists.

### Recovered Degradation Events

Use compact `WARNING` events without `exc_info` for expected upstream failures.
For operations that attempt multiple symbols, emit one aggregate record after
the loop or executor completes, only when at least one attempt failed:

1. `market_quotes_degraded`
   Required fields: `request_id`, `operation`, `attempted`, `succeeded`,
   `failed`, `symbols`, `error_types`.
   Allowed operation values: `indices`, `portfolio_summary`, `allocation`,
   `watchlist`, `transaction_list`, `import_preview`, `import_commit`.
   The indices form also includes `category`.
2. `market_history_degraded`
   Required fields: `request_id`, `operation`, `period`, `attempted`,
   `succeeded`, `failed`, `symbols`, `error_types`.
   Operation is `portfolio_history` or `comparison_history` as applicable.
3. `market_fx_degraded`
   Required fields: `request_id`, `operation`, `pair`, `error_type`.
4. `market_profile_degraded`
   Required fields: `request_id`, `operation=allocation`, `attempted`,
   `succeeded`, `failed`, `symbols`, `error_types`.
5. `stock_data_degraded`
   Required fields: `request_id`, `operation`, `symbol`, `error_type`.
   Use this for single-symbol name, stats, quote, profile, or history recovery
   where aggregate counts add no value.
6. `search_failed`
   Required fields: `request_id`, `query_length`, `error_type`.
7. `volume_leaders_failed`
   Required fields: `request_id`, `error_type`.
8. `import_database_write_failed`
   Required fields: `request_id`, `line`; include `exc_info=True`.
9. `market_currency_unsupported`
   Required fields: `request_id`, `operation`, `symbol`, `currency`.
   Use this where a portfolio route recovers from a Yahoo quote currency other
   than CAD or USD.

Name lookup failures are cosmetic because the symbol still identifies the
security. Preserve them at `DEBUG` without traceback as
`event=market_name_unavailable` with `request_id`, `operation`, `symbol`, and
`error_type`; do not promote them to `WARNING`.

For aggregate records:

1. Preserve configured or first-attempt order in `symbols`.
2. Deduplicate and alphabetically sort `error_types` so concurrency cannot make
   log assertions or production output nondeterministic.
3. Format `symbols` and `error_types` with `%r`.
4. Do not include exception messages. yfinance messages can contain URLs and
   other noisy implementation details; exception class names are sufficient for
   routine degradation.
5. A total failure produces the same single aggregate event with
   `succeeded=0`; do not emit a second all-failed warning.
6. Keep endpoint status and payload behavior unchanged. Logging must observe the
   existing recovery policy, not change it.

## Logging Configuration Contract

Implement one small configuration block near the top of `app.py`:

1. Import `logging`, `logging.config.dictConfig`, `os`, and `uuid` using the
   existing import style.
2. Read and normalize `LOG_LEVEL` before `Flask(__name__)` is called.
3. Validate against the exact five-level allowlist. Retain the invalid raw value
   only long enough to emit `logging_level_invalid` with `%r` after config is
   active.
4. Call `dictConfig` once with:
   - `version: 1`.
   - `disable_existing_loggers: False`.
   - One formatter: `%(asctime)s %(levelname)s %(name)s %(message)s`.
   - Date format: `%Y-%m-%dT%H:%M:%S%z`.
   - One `logging.StreamHandler` targeting `ext://sys.stderr`.
   - The validated level on both the handler and root logger.
5. Set `yfinance` and `peewee` loggers to `WARNING` only if they otherwise emit
   below-warning chatter during tests or the live smoke. Do not pre-emptively add
   a list of unrelated library loggers.
6. Construct the Flask app only after `dictConfig`; Flask then uses the already
   configured logging tree instead of installing its default handler.
7. Keep `app.logger` as the call site throughout the route layer.
8. Change the current logging comments so they describe explicit production
   configuration, stable events, privacy rules, and route-boundary ownership.
   Remove the inaccurate claim that no configuration is required.
9. Wrap only startup `db.init()` in a try/except that logs
   `database_initialization_failed` and re-raises. Do not add catch-and-log code
   inside `db.py`.
10. Emit `application_started` after successful initialization.

## Request Correlation And Timing Contract

1. In the existing `before_request` hook, assign `g.request_id =
   uuid.uuid4().hex` before assigning the timer start.
2. Keep `time.perf_counter()` as the duration clock.
3. In `after_request`, set `response.headers["X-Request-ID"]` from
   `g.request_id` before returning the response.
4. Calculate duration once and emit exactly one `request_complete` event.
5. Select `WARNING` when `duration_ms >= SLOW_REQUEST_MS`; otherwise select
   `DEBUG`.
6. Do not include the query string. `request.path` is the complete logged path.
7. Update the global unexpected-error record to `event=unhandled_error` and
   include request ID, method, and path with `exc_info=True`.
8. Preserve the existing `HTTPException` pass-through. Flask's 404/405 behavior
   must not become JSON 500.
9. `after_request` adds the request-ID header to ordinary responses, explicit
   route 4xx responses, Flask HTTP errors, and the handled JSON 500 response.
10. Do not add request IDs to JSON payloads; the contract is an HTTP response
    header only.

## Mutation Audit Contract

Add the success event immediately after each confirmed database operation:

1. Watchlist POST: after `db.add_symbol` returns, before the 201 response.
2. Watchlist DELETE: after `db.remove_symbol` returns true, before the 204.
3. Transaction POST: after `db.add_transaction` returns its ID, before the 201.
4. Transaction PUT: after `db.update_transaction` returns true and after the
   existing database re-read. Store the re-read row in a local variable, log
   from that stored truth, and return the same object. Do not add a second read.
5. Transaction DELETE: log only after `db.delete_transaction` returns true.
   Log `tx_id`; do not add a pre-delete read solely to recover ticker.
6. Ticker bulk DELETE: replace its prose-style success log with
   `ticker_transactions_deleted` and retain count plus ticker.
7. Import commit: replace its prose-style summary with
   `transaction_import_completed` and retain imported/failed counts.
8. Do not log one `transaction_created` event per imported row. The one import
   summary is the audit event, which avoids large batches flooding the stream.
9. Preview writes nothing and therefore emits no mutation audit event.

## Upstream Degradation Refactor

The implementation must preserve every endpoint response while reducing log
noise:

1. Where a route loops or uses `ThreadPoolExecutor`, collect each failure as a
   `(symbol, exception_class_name)` pair instead of logging inside the worker.
2. Emit one aggregate warning after all results are collected.
3. A worker returns or records enough failure metadata for the route thread to
   log. Do not call `app.logger`, read `request`, or read `g` inside a worker
   thread. Prefer logging once on the route thread.
4. Keep output ordering and all-success/partial-success/all-failed status rules
   unchanged.
5. For transaction import, change `_quote_unique_tickers` to return both the
   existing quote map and ordered failure metadata. Both preview and commit emit
   an operation-specific aggregate warning. Do not place a request-specific log
   in the helper.
6. For transaction listing, make the currently silent quote failures contribute
   to `operation=transaction_list`.
7. For single upstream calls, convert prose logs to the event vocabulary and
   record only exception class name, not traceback, except for the documented
   import database failure and global unhandled error.
8. Remove the raw query from the search warning. Compute `query_length` from the
   normalized query already used by the route.
9. Preserve `INFO` 404 translation events where the endpoint deliberately turns
   unavailable quote/history data into not-found behavior.
10. Do not broaden or narrow any exception catch in this feature unless needed
    to retain the exception object for its class name.

## Docker Retention Contract

In `docker-compose.yml`, add this exact service-level block to `portfoliarr`:

```yaml
logging:
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"
```

Keep it next to `restart` or `environment`, at the service indentation level.
Do not change image, ports, volume, timezone, restart policy, Gunicorn command,
worker count, or thread count. Add a short comment that rotation protects the
host during a repeated upstream outage.

## Files

Production:

- `app.py` - logging configuration, startup events, request IDs, timing level,
  stable event vocabulary, mutation audits, and aggregate degradation records.
- `docker-compose.yml` - bounded `json-file` retention.
- `project-brief.md` - durable logging and privacy design rule.

Tests:

- `tests/test_logging.py` - focused logging configuration, correlation,
  privacy, mutation, degradation, and slow-request behavior.
- `tests/test_error_handler.py` - preserve JSON 500 and HTTP exception behavior;
  move detailed log assertions to `test_logging.py` unless keeping them here is
  clearer.
- `tests/test_routes.py` - adapt existing indices log wording assertions to the
  stable aggregate event without weakening category/symbol/count coverage.
- `tests/test_docker.py` - lock rotation values and unchanged deployment
  process contract.
- `tests/test_import.py` and existing route suites - add only endpoint-specific
  assertions that are clearer beside current behavior; avoid duplicating the
  focused logging matrix.

Planning:

- `feature.md`
- `roadmap.md`

## Test-First Plan

Write sections A-F before changing production files. Run the focused red suite
and confirm failures are caused by missing logging behavior, not fixture or
syntax errors.

### A. Configuration And Startup Tests - `tests/test_logging.py`

Because `app` is imported once by pytest, test the configuration through a
small pure helper that accepts an environment value and returns the validated
level/config decision. Keep actual `dictConfig` application at import time.

1. Test missing `LOG_LEVEL` resolves to `INFO` with no invalid-level warning
   decision.
2. Parameterize lowercase and uppercase values for all five allowed levels and
   assert the normalized level.
3. Test an invalid value resolves to `INFO` and is marked for one warning.
4. Inspect the active formatter and assert it contains timestamp, level, logger
   name, and message in the approved order.
5. Assert the formatter date format is `%Y-%m-%dT%H:%M:%S%z`.
6. Assert the configured stream is stderr and the root/handler level equals the
   validated value.
7. Capture a normal formatted record and assert it begins with an ISO-like
   timestamp and contains `INFO app event=` in the expected order. Do
   not assert the current time.
8. Unit-test invalid-level event formatting with a value containing a newline;
   assert `%r` escapes it and the rendered event remains one physical line.
9. Monkeypatch `db.init` to raise in an isolated import/subprocess only if
   practical without destabilizing pytest imports; otherwise unit-test the
   startup wrapper directly. Assert one critical record with traceback and that
   the same exception is re-raised.
10. Test successful startup wrapper emits `application_started` only after init
    succeeds. Do not assert on the one real import-time startup record emitted
    during test collection.

### B. Request ID, Error, And Timing Tests - `tests/test_logging.py`

1. Request a successful endpoint and assert `X-Request-ID` is exactly 32
   lowercase hexadecimal characters.
2. Make two requests and assert their IDs differ.
3. Send an inbound `X-Request-ID` and assert the response does not reuse it.
4. Request an explicit route-level 400 and assert it still has the response
   header.
5. Request an unknown URL and assert the 404 remains 404 and has the header.
6. Force the existing global 500 path and assert the JSON body remains
   `{ "error": "internal server error" }`, the response has the header, and
   one `unhandled_error` record contains that same ID, method, and path.
7. Assert the unhandled record has exception information and includes the
   simulated exception in rendered traceback data.
8. Assert a Flask 404 does not emit `unhandled_error`.
9. With `SLOW_REQUEST_MS` monkeypatched very high, capture `DEBUG` and assert
   one `request_complete` event contains matching request ID, method, path,
   status, and a nonnegative duration.
10. With `SLOW_REQUEST_MS` monkeypatched to zero, assert the same event is
    `WARNING` and no duplicate `DEBUG` completion event exists.
11. Request a URL with a query string and assert the completion record contains
    the path but not the query key or value.
12. Ensure the after-request hook's defensive timer fallback can run in a Flask
    request context with no pre-set start value and still returns the response.

### C. Mutation Audit Tests - `tests/test_logging.py`

For each success case, capture at `INFO`, select records by exact event name,
and assert exactly one record:

1. Successful watchlist add logs `watchlist_added` with request ID and symbol.
2. Successful watchlist removal logs `watchlist_removed` with request ID and
   symbol.
3. Successful transaction creation logs `transaction_created` with request ID,
   ID, ticker, and BUY/SELL type.
4. Successful transaction edit logs `transaction_updated` from the re-read
   stored row.
5. Successful individual transaction delete logs `transaction_deleted` with
   ID only.
6. Successful ticker bulk delete logs `ticker_transactions_deleted` with ticker
   and exact deleted count.
7. Import commit logs one `transaction_import_completed` record with imported
   and failed counts, including the boundary cases of all imported and zero
   imported.
8. Import does not emit per-row `transaction_created` audit events.
9. Duplicate watchlist add, missing watchlist removal, invalid transaction,
   missing edit/delete ID, failed bulk delete, and preview produce no success
   audit event.
10. Force an ordinary transaction DB write to fail and assert no
    `transaction_created` event is emitted; the existing global error behavior
    handles the failure.
11. Force one best-effort import DB write to fail and assert
    `import_database_write_failed` includes request ID and line number, has
    exception information, and does not contain the row text.
12. Send distinctive values for price, quantity, date, FX rate, and import text;
    join all captured messages and assert none of those distinctive values are
    present. Choose values that do not overlap IDs, counts, durations, or status
    codes.

### D. Rejection And Privacy Tests - `tests/test_logging.py`

1. An unquotable watchlist symbol emits `watchlist_symbol_rejected` at `INFO`
   with request ID, escaped symbol, and `reason=unquotable`.
2. An unquotable transaction ticker emits `transaction_ticker_rejected` with
   the same constraints.
3. A bulk delete miss emits `ticker_delete_rejected` and no delete-success
   event.
4. Existing historical-price and quote-to-404 paths emit the approved event
   names with request ID.
5. Make a failed search with a distinctive raw query. Assert `search_failed`
   contains request ID, exact normalized query length, and exception type but
   not the raw query.
6. Use a symbol containing an encodable quote or control-like character and
   assert its rendered value uses repr-style escaping and cannot create a
   second physical log line.
7. Assert no captured message contains serialized JSON bodies or keys such as
   the distinctive private test values.

### E. Aggregate Degradation Tests - `tests/test_logging.py` And Existing Suites

1. Adapt the existing indices partial-failure test to assert exactly one
   `market_quotes_degraded` warning with request ID, `operation=indices`,
   selected category, attempted/succeeded/failed counts, failed symbols in
   configured order, and sorted exception types.
2. Adapt the indices all-failed test to assert the same single event has
   `succeeded=0`; assert there is no second all-failed warning.
3. Assert all-success indices emits no degradation warning.
4. For portfolio summary, fail two quote lookups with different exception
   classes and assert one aggregate quote warning with deterministic symbols
   and sorted error types while healthy holdings remain in the response.
5. Repeat one representative aggregate test for allocation and watchlist to
   prove sequential and executor-based collectors both work.
6. Add a transaction-list regression test for its formerly silent quote failure
   and assert one `operation=transaction_list` warning.
7. Preview an import with repeated rows for one failed ticker and one healthy
   ticker. Assert `attempted` counts unique quoted tickers, the failed symbol
   appears once, and no raw import text appears.
8. Commit the same shape and assert the operation changes to `import_commit`.
9. Test a portfolio-history partial failure and assert one
   `market_history_degraded` record with period and counts; assert worker order
   cannot alter configured/attempt order.
10. Test one FX failure, one profile failure, and one stock single-call failure
    for their exact event vocabulary and exception class field.
11. Test volume-leader failure emits `volume_leaders_failed` without traceback.
12. For every routine Yahoo degradation assertion, verify `record.exc_info` is
    absent.
13. Preserve all existing response payloads and status assertions beside the
    logging assertions. A logging refactor must not change user-visible recovery.

### F. Docker Tests - `tests/test_docker.py`

1. Inspect the `portfoliarr` service and assert logging driver is exactly
   `json-file`.
2. Assert option `max-size` is exactly string `10m`.
3. Assert option `max-file` is exactly string `3`.
4. Assert rotation is service-level, not accidentally placed under environment
   or volumes.
5. Keep the exact existing Gunicorn command assertion green; this feature does
   not enable access logging or change process/thread count.
6. Keep image, port, volume, timezone, and restart-policy tests green.

### G. Focused Red Run

After all new tests are written and before production edits, run:

```bash
source .venv/bin/activate
python -m pytest tests/test_logging.py tests/test_error_handler.py tests/test_routes.py tests/test_import.py tests/test_docker.py
```

Expected failures include no explicit logging config, no response request ID,
prose-style event messages, missing mutation events, multiple per-symbol
tracebacks, raw search query exposure, no slow-request promotion, and no Docker
rotation settings. Fix test syntax and fixture errors only; do not edit
production code until the failures prove these gaps.

## Implementation Sequence

1. Add the standard-library imports and `SLOW_REQUEST_MS = 2000`.
2. Add the pure log-level validation helper used by focused tests.
3. Build and apply the `dictConfig` before Flask construction.
4. Emit invalid-level warning after configuration when applicable.
5. Wrap startup database initialization, emit critical failure before re-raise,
   and emit success only after initialization.
6. Update the logging section's durable explanation.
7. Extend the existing before/after hooks with generated request ID, response
   header, stable completion event, and slow warning level.
8. Convert the global exception handler to `unhandled_error` with correlation.
9. Run configuration, request-ID, timing, and error-handler tests until green.
10. Add success audit events to watchlist and individual transaction routes.
11. Replace bulk-delete and import prose logs with stable audit events.
12. Run mutation and privacy tests until green.
13. Convert indices quote failures from worker logging to one route-thread
    aggregate record; preserve category and output order.
14. Apply the same collect-then-log pattern to portfolio history, portfolio
    summary, allocation, watchlist, and transaction listing.
15. Refactor `_quote_unique_tickers` to return ordered failure metadata and wire
    operation-specific preview/commit warnings.
16. Convert FX, profile, stock, search, volume-leader, rejection, and 404
    translation logs to the exact event vocabulary.
17. Search `app.py` for every `app.logger` call and verify each request-bound
    record contains request ID, user strings use `%r`, and only unexpected/local
    failures retain tracebacks.
18. Run all focused logging and affected route suites.
19. Add Docker Compose rotation and its tests; do not touch the Dockerfile CMD.
20. Add the durable design rule to `project-brief.md`.
21. Run the complete focused set again.
22. Run the full pytest suite as the final automated gate.
23. Perform the live Docker log smoke checks below and stop for user approval.

## Durable Documentation Update

After implementation, add one concise Design Rule to `project-brief.md` that
records:

1. Route-boundary logging ownership; pure data layers raise.
2. Console-only `key=value` output at production `INFO`.
3. Generated request IDs returned in `X-Request-ID`.
4. Mutation audits exclude financial amounts and bodies.
5. Routine upstream failure is aggregate warning data without tracebacks;
   unexpected bugs keep full tracebacks.
6. Normal reads are debug-only, requests at least two seconds are warnings.
7. Docker retains three 10 MB local log files.

Do not put the entire implementation inventory in the permanent brief. The
event list remains documented beside the code and in tests.

## Verification Gates

### Automated

Run focused suites during implementation:

```bash
source .venv/bin/activate
python -m pytest tests/test_logging.py tests/test_error_handler.py tests/test_routes.py tests/test_import.py tests/test_portfolio_summary.py tests/test_allocation.py tests/test_market_tabs.py tests/test_docker.py
```

Then the lead agent must run:

```bash
source .venv/bin/activate
python -m pytest
```

Do not report implementation complete unless the full suite passes.

### Live Console Smoke

Run the development server with `LOG_LEVEL=DEBUG` and inspect stderr:

1. Request `/api/indices`; confirm one `request_complete` line and a matching
   `X-Request-ID` response header.
2. Request an invalid URL; confirm 404, request-ID header, and no
   `unhandled_error`.
3. Add then remove a harmless temporary watchlist ticker; confirm exactly one
   success audit event for each action and no price/quantity/body data.
4. Search for a distinctive query while forcing or observing a Yahoo failure;
   confirm only query length is logged.
5. If practical, simulate one upstream failure and confirm one compact aggregate
   warning rather than one traceback per failed symbol.
6. Confirm ordinary fast reads are `DEBUG`, not `INFO` or `WARNING`.

### Production Container Smoke

After building through the normal CI path or using an approved equivalent test
environment:

1. Start the service and run `docker compose logs portfoliarr`.
2. Confirm `application_started` appears at `INFO` with database initialized.
3. Confirm normal polling does not create an INFO access line for every request.
4. Confirm a data mutation creates one readable audit line.
5. Inspect the container logging configuration and confirm `json-file`, `10m`,
   and `3` are active.
6. Do not wait to fill or rotate a 10 MB file as part of approval.

### User Approval

After automated and live checks pass, wait for the user to approve the logs.
Ask the user to confirm:

1. The lines are readable in `docker compose logs`.
2. A request ID makes a warning and completion event easy to correlate.
3. Mutation audit lines contain enough identity to be useful.
4. No portfolio amounts, quantities, pasted text, or search terms are exposed.
5. A Yahoo degradation is concise rather than a wall of tracebacks.
6. Normal polling is quiet at production `INFO`.

Only after approval ask whether to commit or push. Mark roadmap item #21 shipped
in that approved commit or PR.

## Out Of Scope

- External log aggregation, dashboards, alerts, email, or push notifications.
- OpenTelemetry, distributed tracing, metrics, Prometheus, or Sentry.
- Gunicorn access logs or reverse-proxy logs.
- Frontend JavaScript error collection.
- Android-native logging changes.
- Cache hit/miss or Yahoo-call latency telemetry.
- SQL query logging or database contents in logs.
- Request/response body logging, client IPs, or user-agent collection.
- User-configurable slow thresholds or retention settings in the web UI.
- A new health/readiness endpoint.
- Changes to endpoint payloads, status codes, cache policy, market calculations,
  transaction semantics, or database schema.
