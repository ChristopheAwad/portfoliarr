# Password recovery + owner-controlled open sign-up (roadmap #27)
Status: in progress

Two parts, both following #26's shape (plain form pages for auth, JSON APIs
for signed-in management, hashing/trimming stays route policy in `app.py`,
`db.py` only stores finished facts). Write every failing test named below
FIRST, then implement, then run the FULL `python -m pytest` suite. Never
commit.

## Part 1 — `python app.py reset-password`

### Code contract
1. New module-level function in `app.py`, placed next to the auth routes:
   `perform_password_reset(username, new_password)` returning `(ok, message)`
   with `ok` a bool:
   - `username = (username or "").strip()` (same trim as setup/login/forms).
   - `user = db.get_user_by_username(username)`; if `None` →
     `(False, "No account with that name on this server.")`
   - password length outside `PASSWORD_MIN..PASSWORD_MAX` (4..128) →
     `(False, "Passwords are 4 to 128 characters.")` — SAME words as setup.
   - else `db.set_password(user["id"], generate_password_hash(new_password))`
     and log with NO request_id (CLI has one):
      `"event=password_reset user_id=%d username=%r", user["id"], username`
      and no password text ever. Return `(True, "Password updated for "
      + username)`.
2. New function `run_reset_password_command(relative_username)`:
   - Uses `getpass.getpass("New password: ")` and
     `getpass.getpass("Confirm password: ")` twice-typed entry.
   - Mismatch → print `Passwords do not match.` to stderr, return 1.
   - Otherwise call `perform_password_reset`, print the returned `message`
     to stdout (when ok) or stderr (when not), return 0 or 1.
3. Extend the `if __name__ == "__main__":` block ONLY:
   - `python app.py reset-password <username>` (one extra arg) →
     `sys.exit(run_reset_password_command(arg))`.
   - `python app.py` alone → unchanged dev server (`app.run(debug=True,
     host="0.0.0.0")`).
   - Wrong arity (0 or 2+ args after the command) → stderr
     `usage: python app.py reset-password <username>` and exit 1.
   - No argparse dependency; just inspect `sys.argv`. Keep the existing
     comment explaining the guard.
4. NO Docker change. Docker runs `gunicorn app:app`, so the command block
   is unreachable in the container; comfy. `tests/test_docker.py` must stay
   green untouched.

### db.py: NO changes at all. All helpers exist
(`get_user_by_username`, `set_password`).

### tests/test_auth.py — NEW tests (write first, all fail)
Import `app` already done at top; add imports `from app import
perform_password_reset, run_reset_password_command` and `import re` not
needed.
1. `test_perform_password_reset_unknown_username(fresh_db)` →
   `(False, contains "No account")` for "ghost"; also
   different-casing " TestEr " trim still FINDS the seeded tester but for
   unknown find ghost first.
2. `test_perform_password_reset_rejects_short(fresh_db)` — seed_user
   ("tester"), call with password "abc" → `(False, "Passwords are 4 to 128
   characters.")`; also 129 "a"s → same.
3. `test_perform_password_reset_round_trip(fresh_db)` —
   seed_user("tester", TESTER_PASSWORD); `(ok, _) =
   perform_password_reset("tester", "brand-new-key-7")`; ok True; then
   `check_password_hash(db.get_user(uid)["password_hash"],
   "brand-new-key-7")` True and `check_password_hash(..., TESTER_PASSWORD)`
   False (import check_password_hash from werkzeug).
4. `test_perform_password_reset_logs_without_password(fresh_db, caplog)` —
   after a reset, upper/lowercase per app logger INFO, `event=password_reset`
   appears and no new password string appears anywhere in `caplog.text`.
5. `test_run_reset_password_command_mismatch(fresh_db, monkeypatch,
   capsys)` — monkeypatch `app.getpass.getpass` with a lambda returning each
   of two DIFFERENT strings (from a list: first call "pw-11", second
   "pw-99"); return code 1; stderr contains "Passwords do not match."
6. `test_run_reset_password_command_success(fresh_db, monkeypatch,
   capsys)` — both prompts return "brand-new-key-9"; return code 0; stdout
   contains "Password updated"; the record verifies via
   check_password_hash in db.
7. `test_main_dispatch_usage(fresh_db, monkeypatch, capsys)` — monkeypatch
   `app.sys` or set `sys.argv = ["app.py", "reset-password"]` guarded in a
   `with pytest.raises(SystemExit)` wrapper around a thin optional helper
   `main()`; simplest: wrap the dispatch into `def main(argv)` that returns
   an int when the dev-server branch is NOT taken. Implementation MUST
   provide `def main(argv=None)` so tests can call `app.main(["app.py",
   "reset-password", "tester"])` without touching Flask. Contract for
   `main(argv)`:
   - `len == 1` → dev server ONLY when argv is None (never in tests);
     when a list `["app.py"]` is passed, just return 0 WITHOUT calling
     app.run (tests never boot the server).
   - `["app.py", "reset-password", "x"]` → int code from
     run_reset_password_command.
   - `["app.py", "reset-password"]` or extra args → stderr usage lines,
     return 1.
   `__main__` block becomes `sys.exit(main());` ONLY when
   `sys.argv` is empty-conditional... simplest true implementation:
   in the `__name__` block, `if len(sys.argv) == 1: app.run(...)` else
   `sys.exit(main(sys.argv))` — and `main(argv)` treats `argv[1:]` list of
   length 0 as the impossible-except-tests branch returning 0.

## Part 2 — Owner-controlled open sign-up

### Code contract
1. `app.py` new constants/helpers next to auth routes:
   - `SIGNUP_KEY = "allow_signup"` (stored via existing
     `db.get_setting`/`db.set_setting`, values exactly "true"/"false").
   - `def signup_allowed(): return db.get_setting(SIGNUP_KEY) == "true"`.
2. `AUTH_EXEMPT_ENDPOINTS` gains `"auth_signup"` (frozenset add).
3. New route `@app.route("/auth/signup", methods=["GET", "POST"])` ->
   `auth_signup()`, behavior in EXACT order:
   a. `if db.count_users() == 0: return
      redirect(url_for("auth_setup"))` — setup mode wins.
   b. `if request.method == "GET" and g.user is not None: return
      redirect(_safe_next(url_for("index")))` (same as login page share).
   c. `if not signup_allowed():` POST →
      `(({"error": "sign-up is disabled"}), 409)` via jsonify; GET →
      `redirect(url_for("auth_login"))`.
   d. If POST, run the SAME validation ladder as setup:
      - `username = (request.form.get("username") or "").strip()`,
        `password = request.form.get("password") or ""`,
        `confirm = request.form.get("confirm_password") or ""`; messages:
        "Usernames are 1 to 30 characters." / "Passwords are 4 to 128
        characters." / "Passwords do not match." with 400 +
        `render_template("signup.html", error=error)`.
      - duplicate (IntegrityError case-insensitive) → "That username is
        taken."
      - success → `db.create_user(username, generate_password_hash(
        password))` DEFAULT seed (Main must exist) THEN `_stamp_session(
        user_id)`, log
        `"event=user_created source=signup user_id=%d username=%r"`,
        return redirect(_safe_next(url_for("index"))).
   e. GET renders `signup.html` with 200 and NO error.
4. Login page gets the link only when the toggle is on:
   - in `auth_login`'s final render: `render_template("login.html",
     error=error, signup_allowed=signup_allowed())`.
   - login.html gains below the form:
     `{% if signup_allowed %}<p class="auth-note">New here? <a href="{{
     url_for('auth_signup') }}">Create an account</a>{% endif %}` — keep
     plain anchor, no JS.
5. New templates/signup.html extends `_auth_head.html`, EXACT structure of
   setup.html minus the legacy-claim paragraph: blocks
   `{% block auth_title %}Create an account — Portfoliarr{% endblock %}`
   (one space before the dash), h1 "Create an account"; NO
   note paragraph (server is not brand new); same form ids (setup-*) may
   be reused? NO: use `signup-username`, `signup-password`,
   `signup-confirm`; `name` attributes MUST stay `username`,
   `password`, `confirm_password` (the route reads those). autocomplete =
   username / new-password / new-password; maxlength / minlength mirror
   the setup page. Comment mentions NO JavaScript.
6. `templates/login.html`: also needs the rendered context var name
   `signup_allowed`; source-visible link text "Create an account".
7. Toggle API `@app.route("/api/auth/signup-toggle",
   methods=["GET", "POST"])` (any signed-in user; People-card audience):
   - POST runs only with `g.user` (the gate guarantees a signed-in user).
   - GET → `jsonify({"allow": signup_allowed()})`, 200.
   - POST: `body = request.get_json(silent=True)`; demand
     `isinstance(body, dict) and isinstance(body["allow"], bool)`; wrong →
     `(jsonify({"error": "body must carry a boolean 'allow'"}), 400)`.
   - True/False → `db.set_setting(SIGNUP_KEY, "true" if body["allow"]
     else "false")`; log
     `"event=signup_toggled allow=%r user_id=%d"`, return `("", 204)`.
8. Preferences → People card:
   - templates/preferences.html, in the people card BETWEEN the error
     `<p id="people-error">` and `<ul id="people-list">`, add a
     `<label class="pref-row" for="allow-signup"><span>Allow open
     sign-up</span><input type="checkbox" id="allow-signup">`.
   - static/js/preferences.js inside the same IIFE `managePeople()`:
     - `const signupToggle = document.getElementById("allow-signup");`
     - `async function loadSignupSetting()`:
       GET `/api/auth/signup-toggle`; on ok set
       `signupToggle.checked = payload.allow`; on fail leave unchecked +
       silent (never block People list). Call it inside `loadPeople()` at
       its very top (same report-free path) so one flow boot runs it.
     - `signupToggle.addEventListener("change", async () => { const on =
       signupToggle.checked; const response = await request(
       "/api/auth/signup-toggle", {method: "POST", headers:
       {"Content-Type": "application/json"}, body: JSON.stringify({allow:
       on})}, reportPeople); if (response && response.ok) showToast(on ?
       "Open sign-up is on" : "Open sign-up is off", "success"); });`
       — revert the checkbox visually on failure via `signupToggle.checked
       = !on;` exactly when not ok.
9. Android: no file changes. common.js fetch hook stays the only 401
   wrapper.

### tests/test_auth.py — NEW tests (write first)
`signup_toggle(on=False)` helper: with a logged-in `client`-
supplied JSON post. Use `login()` from the module top.
10. `test_signup_toggle_defaults_off(fresh_db)` — seed_user tester,
    logged-in client GET `/api/auth/signup-toggle` →
    `200 {"allow": False}` (wordcount False, not None).
11. `test_signup_toggle_requires_session(fresh_db)` — signed-out fresh
    client POST and GET → 401 (gate reads users > 0 so the person is fully
    absent).
12. `test_signup_toggle_round_trip_and_boot_persistence(fresh_db)`,
    logged-in POST `{"allow": True}` → 204; GET → True; then a FRESH
    `app.test_client()` (no session) — `db.get_setting("allow_signup")`
    equals literal "true", proving the SQLite table; POST
    `{"allow": False}` again → 204; GET False.
13. `test_signup_toggle_rejects_bad_bodies(client)` — missing body, list
    body, `{"allow": 1}`, `{"allow": "yes"}` each → 400 + "must carry a
    boolean".
14. `test_signup_page_locked_by_default(fresh_db)` — seed any user, signed
    out GET `/auth/signup` → 302 to `/auth/login`; login page DOES NOT
    contain the string "Create an account".
15. `test_signup_page_unlocked(fresh_db)` — after a signed-in toggle to
    True (facilitate via `db.set_setting("allow_signup", "true")` direct
    helper for speed), signed out GET `/auth/signup` → 200; body contains
    `<form method="post"` and `name="username"`; login page DOES contain
    `href="/auth/signup"` AND "Create an account".
16. `test_signup_success_creates_main_and_signs_in(fresh_db)` — toggle on,
    signed out POST `/auth/signup` form {username:"neu", password:
    "pw-key-9", confirm_password: "pw-key-9"} → 302 Location `/`; the same
    test client GET `/api/portfolios` → 200 list length 1 name "Main"
    (the seeded default comes from `db.create_user` default); also
    `db.count_users() == 2`.
17. `test_signup_validation_ladder(fresh_db)` — toggle on, POST each:
    - 31-char username → 400 "Usernames are 1 to 30 characters."
    - password len 3 → 400 "Passwords are 4 to 128 characters."
    - confirm ≠ password → 400 "Passwords do not match."
    - username "TESTER" (seeded) → 400 "That username is taken."
18. `test_signup_refused_when_disabled(fresh_db)` — users exist but
    toggle off: signed out POST valid-looking form → 409 + json error
    "sign-up is disabled"; no user added (count unchanged); recycled
    browser stays signed out when GET `/` (302 to login).
19. `test_signup_setup_mode_redirect_to_setup(fresh_db)` — zero users,
    signed out GET `/auth/signup` → 302 ends `/auth/setup` (NOT login).
20. `test_signed_in_visitor_redirected_from_signup(client)` — signed in
    GET `/auth/signup` → 302 dashboard.
21. `test_signup_success_log_and_user_rows(fresh_db, caplog)` —
    `event=user_created` line; `source=signup` appears; username logged
    is the strips trims; password never appears in `caplog.text`.

### tests/test_users_ui.py — NEW tests
22. `test_login_page_links_signup_resource_source(fresh_db)` — the
    login.html template SOURCE contains `auth_signup` and
    "Create an account" (string test; the conditional visibility is
    already route-tested).
23. `test_signup_template_has_plain_form(fresh_db)` — signup.html source
    contains `type="password"`, `autocomplete="new-password"`, and
    `method="post"`, no `fetch(`.
24. `test_preferences_js_wires_signup_toggle(fresh_db)` —
    preferences.js source contains "/api/auth/signup-toggle", and toggles
    via "change", and reverts via `.checked`.
25. `test_preferences_html_has_signup_switch(fresh_db)` —
    preferences.html source contains id="allow-signup" bound with
    `for="allow-signup"`.

### UI gate
After green pytest, the user checks the GUI: toggle visible only in
Preferences, login link appears only when on, signup form works on the
phone-sized view, Android unchanged.

## Order
1. Write ALL failing tests (Part 1 + Part 2).
2. Implement `main(argv)` + `perform_password_reset` +
   `run_reset_password_command` + dispatch in app.py. Run the Part-1
   tests to green BEFORE touching Part 2.
3. Implement Part 2 app.py code, templates, preferences.js. Run full
   `python -m pytest`.
4. Report; GUI gate; then await commit approval.
