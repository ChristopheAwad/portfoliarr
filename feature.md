# Multi-User Accounts (Login + Ownership) — roadmap #26

**Status: in progress — build complete; full pytest suite green (1040 tests);
waiting on the GUI gate and then commit/PR approval.** User-confirmed request
(2026-09-26): "multi account" means
multiple users. Real multi-user wins over the roadmap's old "single-user by
design" stance; the roadmap bullet was rewritten and item #26 added.

The plan below is written for an implementer who must not make design calls.
Every decision, signature, status code, reply body, error string, and log event
is fixed here. Tests are written FIRST and fail; then the implementation makes
them pass; then the full suite runs.

## Goal

The server asks who you are and gives each person their own data:

- Nobody sees anything until they sign in. Pages redirect to a login page;
  `/api/*` answers 401 JSON.
- A first-run setup page creates the first account and adopts any data an old
  database already holds (portfolios, transactions, watchlist rows).
- More people are created from the Preferences People card. Each person owns
  only their own portfolios, transactions, and watchlist.
- Portfolio math contracts from #23 keep working, now scoped per user: per-user
  portfolio names, per-user "cannot delete last portfolio", per-user default
  selection for omitted IDs, and a hard ownership check on every
  `portfolio_id` (requesting somebody else's ID is 404, never fallback).

## Locked decisions

1. **Auth is a session cookie over a real user table.** No magic links, no
   tokens in APIs, no third-party identity.
2. **No roles.** Any signed-in person can create users and delete OTHER users
   from Preferences. Rationale: home-LAN trust model; avoids an admin layer.
   Rules that bound the power: you cannot delete the account you are signed
   in as, the last user cannot be deleted, deleting a user requires typing
   the username exactly (same confirmation pattern as portfolio delete), and
   deletion cascades their portfolios + transactions + watchlist rows in one
   transaction.
3. **No open registration.** The only entry points are the setup page (runs
   only while zero users exist) and creating users from Preferences.
4. **Password policy: 4–128 characters**, measured on the raw typed value
   (no trim), hashed with `werkzeug.security.generate_password_hash`
   (Werkzeug ships inside Flask — no new dependency), stored as
   `password_hash`. Usernames: 1–30 characters after strip, stored trimmed,
   unique case-insensitively via SQLite `COLLATE NOCASE`.
5. **Login failure message is uniform**: "Wrong username or password."
   Never name which half was wrong.
6. **Sessions**: Flask signed cookies. `app.secret_key` is generated once
   (`secrets.token_hex(32)`) and persisted in the DB table `app_settings`
   (key `secret_key`) so container restarts do not log everyone out.
   `session.permanent = True` at login with
   `PERMANENT_SESSION_LIFETIME = 30 days`; `SESSION_COOKIE_SAMESITE = "Lax"`
   (the CSRF stance: Lax plus JSON-only POST bodies on the mutating API routes
   equals adequate for a home server; no CSRF token machinery).
   `session.clear()` before stamping `user_id` (fixation hygiene).
   Password change does NOT invalidate other sessions (accepted, documented;
   rework trigger: a remote-exposure deployment).
7. **Ownership model**: portfolios carry `user_id`; transactions stay owned
   THROUGH their portfolio's existing FK. The watchlist becomes per-user
   (`user_id` + symbol). Stock-detail "watched" stamps are per user.
8. **The single enforcement point** for portfolio identity stays the
   `resolve_portfolio_request` hook, which now also verifies ownership:
   `db.get_portfolio(id, g.user["id"])`. An unknown ID AND somebody else's ID
   both answer exactly `404 {"error": "portfolio not found"}`. Omitted
   `portfolio_id` resolves to the session user's first portfolio
   (`db.default_portfolio_id(g.user["id"])`); if a user somehow owns none
   (only reachable by corrupting the DB), the hook answers 409
   `{"error": "no portfolio for user"}` + one `event=user_without_portfolio`
   warning. New route rule: hook registration order is
   `start_request_timer` → `require_authentication` → `resolve_portfolio_request`
   (Flask runs `before_request` hooks in definition order).
9. **Redirect discipline**: unauthenticated page (non-`/api/`) requests get
   `302 → /auth/login?next=<path>`; unauthenticated `/api/*` requests get
   `401 {"error": "authentication required"}`. `static` endpoint is always
   exempt. `auth_login` and `auth_setup` are exempt (the routes police
   themselves: login redirects to setup when zero users exist, setup answers
   `409 {"error": "setup already complete"}` to a POST once a user exists and
   redirects a GET to login).
10. **`next` safety**: the redirect target is honored only if it is a string
    starting with `/` that does not start with `//` (open-redirect guard);
    everything else falls back to `/`. Tests sweep the drilled unsafe
    cases (`//evil.com`, empty, `http://evil.com`) and the one safe case
    (`/ledger`).
11. **The one frontend auth hook**: common.js wraps `window.fetch` once at
    the top of the file. Any 401 navigates the browser to `/auth/login` —
    except when the page itself is an `/auth/*` path (loop guard). Every
    later call site (existing and future) inherits the redirect for free.
    No other frontend file learns about auth.
12. **Login/setup pages are plain server-rendered HTML forms** (no JS, no
    fetch, no base.html/Navbar inheritance on purpose — the navbar's common.js
    would fire portfolio fetches that 401-loop). Each is a minimal standalone
    page sharing style.css, the favicon, fonts, and the dark-mode FOUC
    head script. Logout is a `<form method="post">` button in the profile
    dropdown (also no-JS).
13. **Logging** (route boundary only, mutation audits carry NO amounts and NO
    passwords): `event=login_success username=%r user_id=%d`, `event=login_failed
    username=%r` (warning), `event=logout`, `event=user_created new_user_id=%d
    username=%r`,     `event=user_deleted deleted_user_id=%d username=%r`,
    `event=password_changed user_id=%d`,
    `event=password_change_failed user_id=%d`
    (info), `event=user_without_portfolio` (warning, see 8). Setup success logs
    `event=user_created ... username=%r user_id=%d` like any creation.
14. **Out of scope (documented, not built here)**: login rate limiting /
    lockout (home-LAN trust model; rework trigger: first public exposure),
    password reset by another user, remembering "who created what" on
    transactions, admin dashboards, API keys.
15. **Android**: zero code changes. The WebView is a thin client: the login
    page loads inside it and the WebView's cookie store persists the session
    across app restarts. No `android/` edits, so no Android CI/GUI gate for
    this feature.
16. **Watchlist is per-user now**, replacing the old "one shared watchlist"
    design rule. Owning the SAME ticker at once is allowed for two users.
    A user's portfolios are invisible to everyone else; performing stock
    detail "Add to watchlist" works exactly as before (the route scopes).

## Test coverage (write these FIRST, they must fail before implementation)

Conventions: `client` (conftest) = signed-in test user "tester" for single-user
tests (see the conftest change below). `app.test_client()` = fresh browser.
Rediscover nothing: tests use real forms/statuses; no network is ever touched.

### NEW `conftest.py` changes (support, part of the failing phase)

- `client` fixture: after `fresh_db`, create user via
  `db.create_user("tester", generate_password_hash("test-password-1234"))`
  and then FORGE the session (fast; login itself is covered by its own tests):
  `with client.session_transaction() as session: session["user_id"] = uid`.
  Rationale: the suite has ~100 route tests; hashing on each would add
  ~10 s of scrypt cost for zero extra coverage.
- Add plain helper `seed_user(username, password="pw-1234")` returning the id
  (hashes via `generate_password_hash`), imported by multiuser tests the way
  `make_quote` already is.
- Keep `fresh_db`/`fresh_market_caches`/`fake_market`/`make_quote` untouched
  otherwise.

### NEW `tests/test_users.py` — db layer (users, settings, claim, cascade)

1. `test_init_creates_settings_and_empty_users` — after `db.init()` on a new
   DB: `db.count_users() == 0`; portfolios table exists but owns nothing
   `db.get_portfolios(uid)` is `[]` for a not-yet-existing id (empty).
2. `test_create_user_hashes_and_seeds_main_portfolio` — create alice;
   `db.get_user(alice_id)` returns `{"id", "username": "alice",
   "password_hash"}` whose hash verifies via `check_password_hash`;
   `db.get_portfolios(alice_id)` is exactly one `{"id": 1, "name": "Main",
   "sort_order": 0}`; `db.get_users()` shows her; `db.count_users() == 1`.
3. `test_create_user_duplicate_username_case_insensitive` — "amy" then
   "AMY" raises `sqlite3.IntegrityError`; no second row (`count_users`).
4. `test_create_user_rejects_bad_usernames` — parametrize
   ["", "   ", "x"*31]: `IntegrityError` (CHECK constraint). Boundary:
   "x"*30 accepted; "x"*1 accepted.
5. `test_get_user_by_username_is_case_insensitive` — stored "amy", lookup
   "  AMY ".strip()->"AMY" finds the row; unknown names get None.
6. `test_set_password_round_trip` — `set_password` returns True, old
   password no longer verifies, new one does; unknown id returns False.
7. `test_get_setting_round_trip_and_overwrite` — missing key None; set/get;
   overwrite replaces (settings upsert idempotent).
8. `test_default_portfolio_id_scopes_to_user_and_returns_none_without_one` —
   two users each with Main: default? first ordered for THAT user ✔ (ids
   1 and 2 map respectively); a user with zero portfolios → None (create a
   user row directly via db, then delete their portfolio through
   db.delete_portfolio to reach the state).
9. `test_claim_unowned_data_adopts_and_backfills_main` — build a LEGACY DB with
   conftest's `make_legacy_db`, run
   `db.init()` twice (idempotence), then `uid = create_user("owner", ...)` +
   `db.claim_unowned_data(uid)`: the legacy portfolio row now shows
   `user_id = uid`, `db.get_symbols(uid) == ["AAPL"]`, and 'Main' was NOT
   duplicated because a portfolio already exists. STILL TRUE with the
   settled design: `create_user` carries a `seed_main=True` flag; the setup
   route passes seed_main=False and ALWAYS ends with
   `db.claim_unowned_data(uid)` — adoption for legacy rows, Main-seeding
   for fresh ones (People-created users keep the default seed_main=True).
10. `test_claim_gives_main_when_nothing_to_claim` — fresh DB path:
    create user + claim → owns exactly one Main.
11. `test_delete_user_requires_exact_username_confirmation` — confirmation
    "Alice " or "alice" (case differs) → "mismatch"; unknown id → "missing";
    exact → "deleted".
12. `test_delete_user_cascades_owned_data_atomically` — alice with two
    portfolios + transactions + watchlist rows; bob signs... (route-free:
    no session concept at db layer) delete alice → returns "deleted";
    assert: `db.get_portfolios(alice_id) == []`, every alice transaction
    gone (via raw sqlite SELECT count on transactions joined to portfolios),
    `db.get_symbols(alice_id) == []`... (watchlist table no longer has her
    symbols — verify via raw rowid SELECT user_id IS NULL count == 0),
    bob's portfolio + watchlist untouched.
13. `test_delete_user_never_removes_last_user` — single user + exact
    confirmation → "last"; still countable afterwards.
14. `test_users_survive_reinit` — `db.init()` twice: users, Main portfolio
    and settings rows still one-each (no re-seed, no dup).

### NEW `tests/test_auth.py` — the gate, setup, login, logout, people, password (route level)

Gate:

1. `test_signed_out_page_redirects_with_next` — fresh `app.test_client()`:
   GET `/ledger` → 302 to a Location ending `/auth/login?next=/ledger`
   (Werkzeug keeps "/" unencoded in queries); GET `/stock/AAPL` with
   `next=/stock/AAPL`; GET `/` with `next=/` — redirect, never data.
2. `test_signed_out_api_is_401_json` — GET `/api/watchlist` → 401
   `{"error": "authentication required"}`; same for POST
   `/api/transactions` and GET `/api/portfolios`.
3. `test_static_bypasses_the_gate_and_login_renders_with_users` — signed
   out with a user existing: GET `/static/style.css` → 200 and GET
   `/auth/login` → 200 (a normal form page; the setup-mode redirect is
   test 8).
4. `test_unknown_url_while_signed_out_redirects_instead_of_404` — GET
   `/definitely-not-a-route` signed out → 302 (harmless default),
   while the SAME request signed in stays Flask's 404 (existing
   test_http_errors path keeps passing under `client`).
5. `test_deleted_user_session_is_rejected_not_leaked` — tester's client
   creates "third"; a third browser forges/markers
   session; its GET `/api/watchlist` → 200; tester deletes third →
   204; the SAME third browser then GETs `/api/watchlist` → 401 JSON
   `{"error": "authentication required"}` (its cookie names a user who
   no longer exists; no 500, no data, and no redirect — /api/* answers
   401).

Setup:

6. `test_setup_page_redirects_to_login_when_users_exist` — GET `/auth/setup`
   with `client` (a user exists) → 302 `/auth/login`.
7. `test_setup_post_completed_setup_rejected` — POST `/auth/setup` form when
   users exist → 409 `{"error": "setup already complete"}`.
8. `test_login_redirects_to_setup_when_no_users` — fresh client: GET
   `/auth/login` → 302 `/auth/setup`; POST `/auth/login` also bounces
   (following the redirect target semantics of 6).
9. `test_setup_success_redirects_and_is_signed_in` — legacy-DB build (the
   `make_legacy_db(path)` helper lives in conftest next to `seed_user`,
   shared by test_users.py and test_multiuser_scoping.py) → full flow: raw
   legacy db + `db.init()`; fresh
   `app.test_client()`; POST `/auth/setup` form {username "owner",
   password "owner-pass-1", confirm_password "owner-pass-1"} →
   302 `/`; then GET `/api/portfolios` (same client) shows ONE portfolio
   named from the legacy DB; GET `/api/watchlist` lists the legacy symbol;
   `db.count_users() == 1`.
10. `test_setup_validation_each_error_re_renders_400` — parametrize:
    (missing username) → 400 + "Usernames are 1 to 30 characters.",
    (username 31 chars) → same, (password 3 chars) → 400 + "Passwords are
    4 to 128 characters.", (password 129 chars) → same, (mismatched
    confirms) → 400 + "Passwords do not match.". HTML contains the message
    AND no user was created (`db.count_users() == 0` after all).
11. `test_setup_duplicate_username_re_renders_taken_message` — legacy flow,
    then POST setup again?? — blocked by 409; so duplicate-taken belongs to
    the users API instead; SETUP's try/except IntegrityError re-renders
    "That username is taken." — reach it ONLY through the race where
    `count_users() == 0` but create collides... unreachable via routes;
    cover the IntegrityError branch as a UNIT test inside test_users.py? No:
    route-level duplication of the pattern is meaningless. FINAL: setup
    duplicate branch is defense-in-depth, NOT route-tested; the users API
    duplicate case IS tested (test_auth 24).

Login/logout:

12. `test_login_success_redirects_and_cookie_works` — POST `/auth/login`
    form {"username": "tester", "password": "test-password-1234"} on a
    fresh client → 302 `/` (no next param); GET `/api/watchlist` now 200.
13. `test_login_honors_safe_next` — `?next=/ledger` redirects to
    `/ledger`.
14. `test_login_rejects_wrong_password_and_unknown_user_identically` —
    nonexistent username → 400 with "Wrong username or password."; right
    username + wrong password → the SAME page/status/message; in both
    cases the browser stays unauthenticated (the next `/api/*` call is
    401). Both replies are equal; the retrying user knows which half
    hurt, an attacker learns nothing.
15. `test_login_redirects_signed_in_users_home` — GET `/auth/login`
    while signed in → 302 `/` (a logged-in person never sees the online
    form again).
16. `test_logout_clears_session` — `client` (signed in) POST `/auth/logout`
    → 302 to `/auth/login`; afterwards `/api/watchlist` → 401 (logged
    out).

People API (any signed-in user):

17. `test_list_users_returns_id_username_only` — GET `/api/users` (signed
    tester + one more user) → list of {"id", "username"} WITHOUT
    password_hash keys; ordered by id; message: password hashes must never
    leave the server.
18. `test_create_user_via_api_validates_and_seeds` — POST `/api/users`
    {"username": "kid", "password": "kid-key-1"} → 201 {"id", "username"};
    kid owns exactly one Main portfolio (db.get_portfolios(kid_id)); bad
    bodies → 400: (no body dict) {"error": "expected JSON body with
    username and password"}, (username "") → "username must contain 1 to
    30 characters", (31 chars) → same, (password "abc") → "password must
    contain 4 to 128 characters", (128+1 chars) → same; duplicate
    "TESTER" (case-insensitive with tester) → 409 "username is already
    taken".
19. `test_delete_user_rules` — DELETE `/api/users/<own id>` → 400
    "you cannot delete the account you are signed in as"; DELETE
    nonexistent id → 404 "user not found"; no body/wrong typed name → 409
    "typed username does not match" (400 "type the username to confirm"
    when body lacks the string); LAST user: create zero-extra users and
    delete → 409 "cannot delete the last user"; happy path: create "kid",
    DELETE `/api/users/<kid>` {"username": "kid"} → 204; cascade: kid's
    portfolio gone from `db.get_portfolios(kid_id)`.
20. `test_delete_user_cascade_via_api_isolates_others` — users A (client) +
    B; B's portfolio has a transaction + B watched a symbol; A deletes B
    (typed confirm) → 204; A's `/api/portfolios` unchanged; B's id gone
    from `/api/users`; the B transaction row is gone (db check); A's
    watchlist rows intact.
21. `test_change_own_password_via_api` — POST `/api/auth/password`
    {"current_password": "test-password-1234", "new_password": "new-key-9"}
    → 204; old password now fails `/auth/login` (fresh client, 400); new
    one succeeds; wrong current → 400 "current password does not match";
    invalid new (3 chars) → 400 "password must contain 4 to 128
    characters"; non-dict body → 400 "expected JSON body with
    current_password and new_password".

Setup-mode + auth-changed logging:

22. `test_auth_events_are_logged` — caplog around: failed login warns
    `event=login_failed` WITHOUT any password text in the message;
    successful one infos `event=login_success ... username='tester'`;
    user create/delete/password-change emit their events (ids + usernames,
    no amounts/hashes).

### NEW `tests/test_multiuser_scoping.py` — the ownership wall

Helpers: `seed_user` from conftest; a `client2()` plain helper building + signing a second session
(POST form login; follow_redirects False).

1. `test_portfolios_list_create_are_per_user` — A(client) sees own list;
   A POSTs "Holiday" → owned by A; B's `/api/portfolios` child does NOT
   contain Holiday; B creates "Holiday" too → SUCCEEDS (names collide only
   within a user now).
2. `test_every_portfolio_scoped_route_404s_on_foreign_id` — parametrized
   sweep signing A(client) and B(client2); B's Main id = foreign pid for A:
     - GET `/api/portfolio/summary?portfolio_id=<B>` → 404
     - GET `/api/portfolio/history?portfolio_id=<B>` → 404
     - GET `/api/portfolio/allocation?portfolio_id=<B>` → 404
     - GET `/api/portfolio/realized?portfolio_id=<B>` → 404
     - GET `/api/transactions?portfolio_id=<B>` → 404
     - POST `/api/transactions?portfolio_id=<B>` (valid body + fake_market
       quote) → 404 (no row written: `db.get_transactions(B) == []`)
     - PUT `/api/transactions/<tx-id-of-B>?portfolio_id=<B>` → 404
     - DELETE `/api/transactions/<tx-id-of-B>?portfolio_id=<B>` → 404
     - DELETE `/api/transactions/ticker/AAPL?portfolio_id=<B>` → 404
     - POST `/api/transactions/import/preview?portfolio_id=<B>` → 404
     - POST `/api/transactions/import/commit?portfolio_id=<B>` → 404
     - PATCH `/api/portfolios/<B>` (rename, valid name) → 404
     - DELETE `/api/portfolios/<B>` (typed correct name) → 404
     - PATCH `/api/portfolios/<B>/move` → 404
   B's data bit-identical afterwards (counts + content).
3. `test_omitted_portfolio_id_resolves_within_the_caller` — A and B both
   hold separate Main portfolios; A omits portfolio_id on /api/transactions
   GET → A's rows; B same → B's rows; each list is exact (fixture
   identifiers requested separately by each client with explicit ids first,
   then deleted... no: JUST use distinct tickers: A logged AAPL, B logged
   MSFT with fake_market quotes; omitted-id GETs return exactly their own
   ticker).
4. `test_watchlist_is_per_user` — A(client) POST AAPL; B(client2) GET
   `/api/watchlist` shows "symbols": [] and cannot... B can ALSO POST AAPL
   (own copy allowed); DELETE `/api/watchlist/AAPL` by B removes only B's;
   A still has it; A's DELETE of B's... there is no cross-user DELETE to
   probe: same path, per-user outcome ✔ (assert A's row survived B's
   deletion of the same symbol).
5. `test_stock_page_watched_stamp_follows_the_session` — symbol AAPL: A
   watched (db.add_symbol("AAPL", A)); GET `/stock/AAPL` as A contains
   `data-watched="true"`; as B same page contains `data-watched="false"`
   (route reads the session user).
6. `test_watchlist_actions_scope_even_for_same_symbols` — A rows:
   add/remove via API paths still function identically for each user
   (already covered by 4 — merged there; no separate test).
7. `test_user_deletion_via_api_cannot_be_done_silently` — duplicates 19 →
   skip. (Listed only to keep the sweep complete.)
8. `test_foreign_watchlist_delete_404s_per_user` — B attempts DELETE
   `/api/watchlist/AAPL` when ONLY A watches AAPL → 404 (per-user row
   missing); A's row intact. (Merged with 4? It is complementary: keep.)

### NEW `tests/test_users_ui.py` — source pins (metadata, test_portfolios_ui style)

1. `test_base_carries_user_identity_and_logout` — templates/base.html
   contains `{{ g.user.username }}`, the logout `<form method="post"`,
   `url_for('auth_logout')`.
2. `test_preferences_carries_people_section` — preferences.html contains
   ids `people-card`, `people-create`, `people-list`, `people-error`,
   `password-change`, `data-current-uid`, and the copy "Each person owns
   only their own portfolios and watchlist".
3. `test_preferences_js_wires_people_and_password` — preferences.js
   contains "/api/users", "/api/auth/password", "showPrompt", and the
   self-delete suppression pattern (renders no delete control when
   `user.id === currentUid`).
4. `test_common_hooks_401_redirect` — common.js contains the fetch wrapper:
   "status === 401" and the '/auth/' pathname guard.
5. `test_auth_pages_are_no_js_forms` — templates/login.html AND
   templates/setup.html: `<form method="post"`, no `<script>` tags, and
   autocomplete attributes (`autocomplete="current-password"` in login,
   `autocomplete="new-password"` in setup).
6. `test_auth_pages_render_for_signed_out` — route behavior (GET 200
   logged out) already covered in test_auth; here assert the HTML contains
   `class="card auth-card"` and brand mark `logo-mark`.
7. `test_changed_page_scripts_parse_in_javascript_engine` — same MiniRacer
   parse loop as test_portfolios_ui (common.js + preferences.js).
8. `test_style_pins_auth_cards` — style.css contains `.auth-page`,
   `.auth-card`, `.auth-form`, `.profile-dropdown-user`, and a logout rule
   (`.profile-logout`).

### UPDATED existing tests (signature migration + fixture-owned data)

- `facts seed users`: every test file that calls the CHANGED db signatures
  gets a user id (via `seed_user` import) and passes it / the portfolio id
  explicitly:
  - `tests/test_db.py` — add_symbol/get_symbols/is_watched/remove_symbol
    gain (user); add/update/get/delete transactions gain explicit
    portfolio_id; plus the initusers assertions adapt (no auto-Main at
    init: empty until user; user creation seeds Main — covered by test_users).
  - `tests/test_portfolios.py` — legacy tests rewritten around claim
    (per decision 9 above), management tests unchanged because they go
    through `client` (add_assert: B clients see nothing: cross-user duplicate
    name case), db-level path stays explicit-owner.
  - `tests/test_import.py` — transactions seeded via explicit ids.
  - `tests/test_transaction_fees.py`, `tests/test_logging.py`,
    `tests/test_ledger_groups.py`, `tests/test_allocation.py`,
    `tests/test_ui_redesign.py`, `tests/test_compare.py`,
    `tests/test_twrr.py` — same signature migration.
  - `tests/test_stock.py` — db.add_symbol gains user; route-level client
    behavior stays.
  - `tests/test_error_handler.py` — `broken_get_symbols(user_id)` signature.
- Route tests that already go via `client` need no session work (the
  fixture signs them in), only db-level seeding fixes.

## Implementation steps (tests first)

### Step 1 — failing tests

Create/edit the four NEW test files + conftest + the signature migrations
above; `python -m pytest tests/test_users.py tests/test_auth.py
tests/test_multiuser_scoping.py tests/test_users_ui.py` shows failures
(import/signature errors at first), existing suite still green until the
new signatures land (the migrations happen together with them — that is
expected; the failing phase is the NEW files).

### Step 2 — db.py

1. imports none new (sqlite3/pathlib only).
2. `app_settings` + `users` tables in `init()` BEFORE portfolios/transactions
   creation; comment trail per house style.
3. portfolios:user_id column via the existing PRAGMA-table_info pattern
   (ALTER when missing; NULL for pre-multi-user rows until claim);
   `DROP INDEX IF EXISTS portfolio_name_unique`, then the per-user
   (user_id, name COLLATE NOCASE) unique index.
4. Remove the old 'Main'-auto-create block; create_user seeds it per user.
5. watchlist rebuild (PRAGMA table_info: no user_id column) → new table
   (user_id INTEGER REFERENCES users(id), symbol TEXT,
   PRIMARY KEY(user_id, symbol)), copy legacy rows with NULL user_id, drop
   old, rename, recreate no extra index (PK suffices).
6. new functions with EXACT signatures above (get_setting, set_setting,
   get_users, get_user, get_user_by_username, count_users, create_user —
   includes seeding a per-user 'Main' INSIDE the same connection block,
   set_password, delete_user with outcomes + atomic cascade, claim).
7. every portfolio/watchlist/transactions function gets the user/scope
   parameter; NO defaults for ownership inputs (ownership can never be
   forgotten silently); the ONLY retained Optional is `fee`.
8. `get_users()` deliberately omits password_hash (endpoint sanitizes via
   reconstruction — no leaking rule, enforced at the db boundary).

### Step 3 — app.py

1. imports: `secrets`, `timedelta`, `session`, `redirect`, `url_for`;
   `from werkzeug.security import generate_password_hash, check_password_hash`.
2. after `db.init()`: `app.secret_key` bootstrap via app_settings;
   config session keys (SameSite Lax, 30-day lifetime).
3. `AUTH_EXEMPT_ENDPOINTS` + `require_authentication` gate SOURCE-PLACED
   BETWEEN `start_request_timer` and `resolve_portfolio_request`.
4. `_safe_next(value)` helper (decision 10 exact rule).
5. routes `auth_setup` (GET/POST), `auth_login` (GET/POST), `auth_logout`
   (POST) — bodies per decisions; render failing forms with 400.
6. `/api/users` GET+POST, `/api/users/<int:user_id>` DELETE,
   `/api/auth/password` POST per the spec above.
7. rewrite `resolve_portfolio_request` body (ownership + per-user default
   + the 409 nobody-owns-anything branch).
  8. swap every db call in route bodies to pass `g.user["id"]` /
     `g.portfolio_id` explicitly (portfolios CRUD, every watchlist route,
     and stock_page's watched stamp). Transactions/import routes need NO
     body changes (they already take `g.portfolio_id`).
  9. error discipline: the door 401 JSON uses the shared shape; new logs per
     decision 13.

### Step 4 — templates + CSS + JS

1. templates/login.html, templates/setup.html (standalone; structure in
   the UI list above).
2. base.html profile dropdown: username line + logout form.
3. preferences.html: People card (ids/text above); update the Portfolios
   intro sentence to per-user language.
4. preferences.js: `managePeople()` IIFE (list/add/typed-confirm-
   delete/change-own-password; fetch patterns identical to managePortfolios;
   401s inherit the common.js hook).
5. common.js: the fetch wrapper FIRST (before portfolio code).
6. style.css: .auth-page/.auth-card/.auth-form/.auth-logo,
   .profile-dropdown-user + logout button rule.

### Step 5 — full suite + GUI gate

- `python -m pytest` green (fresh_db isolation, no network).
- Dev server `python app.py` manual GUI gate by the user afterwards:
  first-run setup → login/logout → two people in Preferences → ledger
  isolation → sign-out 401 behavior → Android WebView login (unchanged
  build).

## Files

`db.py`, `app.py`, `templates/base.html`, `templates/login.html` (new),
`templates/setup.html` (new), `templates/preferences.html`,
`static/js/common.js`, `static/js/preferences.js`, `static/style.css`,
`conftest.py`, `project-brief.md` (design rules + scope rewrite),
`roadmap.md` (done: item #26 in progress), tests: new `test_users.py`,
`test_auth.py`, `test_multiuser_scoping.py`, `test_users_ui.py`; updated
`test_db.py`, `test_portfolios.py`, `test_import.py`,
`test_transaction_fees.py`, `test_logging.py`, `test_ledger_groups.py`,
`test_allocation.py`, `test_ui_redesign.py`, `test_compare.py`,
`test_twrr.py`, `test_stock.py`, `test_error_handler.py`.

Docker files: UNTOUCHED (no compose/Dockerfile changes; secret lives in the
SQLite volume). `tests/test_docker.py` must stay green untouched.
