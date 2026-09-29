# Android Biometric Unlock — roadmap #57

Status: in progress
Branch: `android-biometric` (branched from `main` at c853e19)
Date started: 2026-09-29

## HOW TO COMPLETELY REVERT THIS

`main` is untouched. Nothing here is merged. To throw the whole thing away:

```bash
git checkout main
git branch -D android-biometric
```

To keep the branch but back it out of the app later, every Kotlin change is
additive and gated: delete the four new Kotlin files and the new test file,
revert the eight changed ones, and the app returns to today's exact
behaviour. The web app, the database, and every Flask route are NOT modified
by this feature at all.

`VERSION` and `VERSION_CODE` are deliberately NOT bumped. That happens at APK
release time, per `AGENTS.md`, and nothing has been approved for release.

New files (5):
- `android/app/src/main/java/com/portfoliarr/app/CookieHeader.kt` (pure)
- `android/app/src/main/java/com/portfoliarr/app/StartGate.kt` (pure)
- `android/app/src/main/java/com/portfoliarr/app/SecretStore.kt`
- `android/app/src/main/java/com/portfoliarr/app/BiometricGate.kt`
- `android/app/src/test/java/com/portfoliarr/app/` — two JUnit suites
- `tests/test_android_biometric.py`

Changed (8):
- `MainActivity.kt`, `SettingsActivity.kt`, `activity_settings.xml`,
  `strings.xml`, `AndroidManifest.xml`, `libs.versions.toml`,
  `build.gradle.kts`, `.github/workflows/build-android.yml`

Plus docs: `feature.md`, `roadmap.md`, `project-brief.md`, `AGENTS.md`,
`README.md`.

To abandon it entirely and go back to a stock APK right now, install
`release/android-baseline-1.4` (that branch exists for exactly this).

## The problem this actually solves

The Android WebView ALREADY keeps a 30-day session cookie
(`PERMANENT_SESSION_LIFETIME`, `app.py:166`). So the app is already logged in
most of the time and the password is typed about once a month, not once per
open. A fingerprint therefore unlocks nothing that is currently locked.

What it buys is two real things:

1. PRIVACY. Today anyone who picks up the phone sees the whole portfolio.
2. NO MONTHLY RE-TYPING. The secret lives on the phone, released by a
   fingerprint.

So the honest description is: an app lock that also removes the monthly
password. It is NOT a server login feature.

## The account question, answered

The user asked how apps handle "several accounts, one fingerprint".

The industry answer is: the biometric is NOT the account. It is the key that
opens a locked box. Mac Touch ID says "Unlock keychain for <app>". Banking apps
open the vault with a fingerprint, then let you pick an account inside it.

Here that resolves itself for free: the saved session cookie IS the last-used
account's session. The app silently resumes it. To switch accounts the user
signs out in the app's own profile menu, and the next capture saves the new
account's cookie. So it is exactly "last account logged into", which is what the
user guessed, and it needs no account picker.

## Why the password stays

Decided: keep the password. The fallback is free. If there is no stored secret,
the user cancels, the fingerprint fails, or the restored cookie is rejected by
the server, the app simply loads the URL. The existing auth gate then redirects
to `/auth/login` and the user types the password as today. No new fallback code.

## Why passkeys / WebAuthn are NOT used

Researched and confirmed dead on arrival for this deployment. Three independent
blockers, all verified:

1. WebAuthn needs a secure context. `navigator.credentials` is `undefined` on
   plain HTTP. Portfoliarr is `http://<LAN-IP>:9967`, and `app.py:169` even
   turns `SESSION_COOKIE_SECURE` off for exactly this reason.
2. WebAuthn needs a registrable DOMAIN for the RP ID. Chrome rejects a bare IP
   with a `SecurityError`. The app is reached by IP.
3. The Android embedded WebView has no WebAuthn support by default. It needs
   `androidx.webkit` 1.12+ plus an explicit opt-in flag.

Even though `androidx.webkit:webkit:1.12.1` is already a dependency, blockers 1
and 2 are infrastructure work (HTTPS + a real hostname, e.g. Tailscale Serve or
a local CA) and are a separate future decision. NOT in this feature.

## Design (as built)

1. On a COLD START only, if a stored secret exists, the app calls
   `BiometricPrompt` (fingerprint, falling back to the device PIN/pattern/
   password).
2. On success it decrypts the secret with an AES-256-GCM key generated
   through `AndroidKeyStore`. That key is non-exportable, so the ciphertext
   in the app's data directory is worthless to anyone who copies it off the
   device.
3. It hands the cookie back to the WebView with `HttpOnly; SameSite=Lax` so
   the app never silently downgrades the server's session protections, then
   loads the dashboard FROM THE setCookie CALLBACK (see the race below).
4. In the background, `onPageFinished` samples the WebView cookie jar. If a
   `session` cookie is present, it is encrypted and stored. The stored value
   is compared by SHA-256, not read back, so sampling never triggers a
   prompt from the background.

### The key is NOT bound to user authentication — on purpose

The first draft used `setUserAuthenticationRequired(true)`, the stronger
primitive. Implementation killed it, and the reason is worth keeping:

That restriction applies to a key's ENCRYPT purpose as well as its decrypt
one. Capturing a newly logged-in cookie happens in the background right
after a login through the web form, and a web form login is NOT a keystore
authorization event. So every fresh login would have needed its own extra
fingerprint prompt, plus a "pending save" state machine to survive the gap
between auth windows.

The keystore's auth binding is not what protects the realistic threat here.
`BiometricPrompt` at cold start is. The keystore key's job is narrower and it
does it well: the at-rest bytes are unreadable without a non-exportable
hardware key. This is the same split real password managers use. See
`SecretStore.kt`'s header comment and `AGENTS.md` before "improving" it.

## Bugs this work caught (tests first, then code)

Recorded because each was found by a test rather than by reading, and each
would have shipped:

1. `StartGate.normalizeOrigin` stripped the scheme, so `http://host` and
   `https://host` compared equal. Keeping the scheme is safer: repointing the
   server from https to http must not replay a stored secret.
2. `extractSession` took the LAST of two same-named cookies, on a wrong
   reading of RFC 6265 ordering. Corrected to first-wins.
3. A bad test of my own: it asserted a header containing a valid `session`
   cookie returned null.
4. `SecretStore.kt` referenced a `KEY_ENABLED` constant that was never
   declared. Only a real compile caught this; see "How this was verified".
5. `CookieManager.setCookie` is asynchronous. The first draft loaded the page
   in the same breath, which races the cookie write and lands on the login
   form even after a successful fingerprint. The load is now issued from the
   callback.
6. **A sign-out would not have stuck.** Flask's session cookie is a stateless
   signed blob, so the server cannot revoke the copy the app already holds.
   Tapping "Sign out" expires the cookie in the WebView jar, but the stored
   secret survived it and the next cold start replayed it — signing the user
   straight back in. A sign-out that comes back on restart is worse than no
   sign-out at all. Now, landing on an auth page with no live cookie clears
   the stored secret. `StartGate.isAuthPath` does the matching and is unit
   tested against the near-misses ("author", "authsetup") that must NOT
   trigger a clear.

## How this was verified without an Android SDK

The dev machine has no Android SDK and only JDK 25, so `./gradlew` cannot run
here. Two local harnesses were built (in `/tmp`, deliberately NOT committed):

- `kotlinc` 2.0.21 + a downloaded JDK 17 compiles and runs the two PURE
  helpers and their JUnit suites: **36 tests, all green**. This is the same
  code CI will run under `./gradlew test`.
- Signature-accurate stubs for the `android.*` and `androidx.*` APIs let the
  WHOLE app source compile, which is what caught bug 4. CI's
  `assembleDebug` remains the authoritative build, and the on-device GUI
  check remains the authoritative behaviour test.

## Plan (as originally written)

The original design and the full test list are below. Where the
implementation corrected the design, the correction is recorded above and
the test list notes it.


## Deliberate non-goals

- No server change. No Flask route, no DB table, no new Python dependency.
- No web UI change. The login page is untouched.
- No background-timeout re-lock. Roadmap #16 covers that and STAYS on the
  roadmap; this feature only builds the plumbing #16 will reuse.
- No per-device revocation. A lost phone is handled by changing the password.
- No multi-server secret storage. One secret, bound to one server origin.

## Known limitations, stated up front

- If the phone is lost, the stored cookie is a full 30-day session that cannot
  be revoked individually. Options are "Forget this phone" before handing the
  device over, or changing the password (which also signs out the computer).
- A factory reset or a Google backup restore wipes the secret, because the
  Keystore key is not backed up while the ciphertext is. The app then falls
  back to the password form. This FAILS CLOSED, which is the safe direction.
  `allowBackup="true"` is left as is on purpose.
- Prompting is once per cold start. Rotating the screen does not re-prompt
  (a process-level flag distinguishes them).

## Test plan — written BEFORE implementation

### Kotlin JVM tests: `android/app/src/test/java/com/portfoliarr/app/`

Two suites, both on a plain JVM, because both files under test carry no
`android.*`/`androidx.*` imports (pinned by `tests/test_android_biometric.py`).

`CookieHeaderTest.kt` — Flask session cookies are itsdangerous
URLSafeBase64: they contain `.`, `-`, `_` and `=` padding. Cookie names are
case-sensitive. All three are real traps.

- T1 `extractSession` finds `session` among several cookies in one header
- T2 the value is returned VERBATIM, including `.`, `-`, `_` and trailing `=`
- T3 the split happens on the FIRST `=` only
- T4 `Session=` and `SESSION=` do NOT match, and return null
- T5/T6 null and empty headers return null
- T7 `session=` with an empty value is treated as absent
- T8 `session=` with only whitespace is treated as absent
- T9 the FIRST of two same-named cookies wins (RFC 6265 sends longest path
  first) — corrected during implementation
- T10 `buildRestoreCookieHeader` produces exactly
  `session=<v>; Path=/; Max-Age=2592000; HttpOnly; SameSite=Lax`
- T11 `buildRestoreCookieHeader` rejects an empty value
- T12 `SESSION_MAX_AGE_SECONDS` is 2_592_000, i.e. 30 days
- T13 the restore header never adds `Secure` (plain-HTTP LAN; CookieManager
  refuses a Secure cookie over http)
- T14 `sha256Hex` is stable, 64 lowercase hex chars, differs on a one-char
  change, and matches the published vectors for "abc" and ""

`StartGateTest.kt` — the one question MainActivity asks before prompting.

- T15 FALSE without a stored secret
- T16 FALSE when biometrics are unavailable
- T17 FALSE when the user turned the feature off
- T18 FALSE on a warm start
- T19 TRUE on a cold start with a secret, biometrics, and the feature on
- T20 FALSE when the secret belongs to a different server
- T21 FALSE when the secret or the current URL has no origin
- T22 "settings off" beats every other condition
- T23 origins match exactly, ports and scheme included
- T24 `normalizeOrigin` strips the trailing slash and surrounding space
- T25 `normalizeOrigin` maps blank/null to ""
- T26 `normalizeOrigin` refuses `javascript:` and `file:` URLs
- T27 `normalizeOrigin` lowercases scheme and host
- T28-T31 `isAuthPath` recognises /auth/login, /auth/setup, /auth/signup,
  and the real `?next=...` query shape, while rejecting the near-misses
  "author", "authsetup" and "authorisation", a bare host, and blank input

### Python string-lock tests: `tests/test_android_biometric.py`

pytest cannot compile Kotlin, so this file pins the contract the way
`tests/test_users_ui.py` and `tests/test_security_audit.py` already do. All
"must not appear" checks run against a comment-stripped copy of the file, so
the comment explaining a decision can never satisfy or defeat them.

- P1 `libs.versions.toml` pins `androidx-biometric` to an exact `x.y.z`, and
  declares the library alias
- P2 `libs.versions.toml` pins `junit` to an exact `x.y.z`
- P3 `app/build.gradle.kts` wires `libs.androidx.biometric` and `libs.junit`
- P4 the manifest declares `USE_BIOMETRIC`
- P5 the manifest declares `USE_FINGERPRINT` (needed on API 24-28)
- P6 `SecretStore.kt` generates through `AndroidKeyStore` at 256 bits
- P7 `SecretStore.kt` does NOT use `setUserAuthenticationRequired`, and the
  prompt with its `DEVICE_CREDENTIAL` fallback is present — pins the design
  decision above against a well-meaning regression
- P8 `SecretStore.kt` uses AES/GCM, never ECB, and reads the GCM tag
- P9 `SecretStore.kt` handles `AEADBadTagException` and
  `KeyPermanentlyInvalidatedException` rather than crashing
- P10 the restored cookie carries `HttpOnly` and `SameSite=Lax` and `Path=/`
- P11 its `Max-Age` matches `app.py`'s `PERMANENT_SESSION_LIFETIME`
- P12 `CookieHeader.kt` matches the cookie name case-sensitively
- P13 the gate runs BEFORE the first `webView.loadUrl` (index-order)
- P14 `onPageFinished` samples the cookie jar
- P15 `AppState` is declared OUTSIDE the Activity class, or a rotation
  re-prompts
- P16 the load is reachable from both the answer and a timeout, with two
  independent one-shot guards
- P17 the page load is issued from the `setCookie` callback, not before it
- P18 capture bails out when there is no session cookie, and is guarded by a
  hash comparison
- P19 `SettingsActivity` carries the toggle, the forget control, and
  `removeAllCookies`; the ids and strings line up with the layout
- P20 the Settings switch ignores changes it caused itself while populating
- P21 `build-android.yml` runs `./gradlew test` and still builds the APK
- P22 both pure helpers exist, have JVM unit tests, and import nothing from
  `android.*`/`androidx.*`

### Failure paths, each of which must fall through to the password login

- F1 user CANCELS the prompt: no crash, secret NOT cleared, plain load
- F2 too many attempts (`ERROR_LOCKOUT` / `ERROR_LOCKOUT_PERMANENT`): plain
  load, no toast storm
- F3 no biometric hardware: `canAuthenticate` != SUCCESS, never prompt
- F4 no fingerprint enrolled: never prompt
- F5 decrypt throws `AEADBadTagException` (tampered or stale ciphertext):
  clear the stored record, plain load
- F6 the server rejects the restored cookie (expired, or `password_version`
  bumped): the gate 302s to `/auth/login`; the app must NOT loop or re-prompt
- F7 capture finds no `session` cookie (user is still on the login page): store
  nothing, do NOT overwrite an existing good secret
- F8 the server URL changed: stored origin no longer matches, clear the secret
- F9 the keystore refuses the existing key: clear and start clean next time
- F10 a swallowed prompt callback would leave a blank screen forever, so a
  90s timeout forces the load; the load has its OWN one-shot guard so the
  timeout still works after the answer has already arrived
- F11 the Settings switch is populated from the stored value while the screen
  loads, which fires its change listener — acting on that would delete the
  secret just by opening Settings, so it must ignore non-user-driven changes

F6 is additionally protected by the existing pytest contract in
`tests/test_auth.py`; the new part is that the APP must not react to it.

## Test results

- `python -m pytest` → **1196 passed**, no regressions. Includes 24 new
  assertions in `tests/test_android_biometric.py`.
- Kotlin JVM suites (pure helpers) → **40 tests, all green**.
- Whole-app Kotlin compile against API stubs → clean.
- `assembleDebug` and on-device behaviour → **not run here**; see below.

## Not yet done

- `./gradlew assembleDebug` and `./gradlew test` (no Android SDK on this
  machine; CI runs both).
- The on-device GUI check, which is the only real test of the prompt, the
  keystore, and the cookie round trip.


## Implementation steps, in order

- I1  branch `android-biometric` (DONE)
- I2  roadmap item #57 + graph + order; correct #16's file list and the
     stale 4-char/no-rate-limit claims (DONE)
- I3  write the Kotlin and Python test suites; confirm they fail for the
     right reason (DONE — 18 pytest failures, each naming its missing file)
- I4  `CookieHeader.kt` and `StartGate.kt`, the two pure helpers (DONE —
     4 real failures found and fixed, then 36 green)
- I5  `SecretStore.kt` — keystore key, AES/GCM, prefs, clear/ignore (DONE)
- I6  `BiometricGate.kt` — availability, prompt, single-shot delivery (DONE)
- I7  `MainActivity.kt` — gate before first load, capture after page load,
     timeout safety net (DONE — the setCookie race found here)
- I8  `SettingsActivity.kt` + layout + strings (DONE)
- I9  gradle deps, manifest permissions, CI `./gradlew test` (DONE)
- I10 run pytest, the Kotlin suites, and the stub compile (DONE)
- I11 docs: project-brief.md, AGENTS.md, README.md, roadmap corrections (DONE)
- I12 commit on the branch (DONE)
- I13 ON-DEVICE CHECK — still owed by the user, see the checklist in the
     handover message. Nothing about the prompt, the keystore, or the cookie
     round trip has been proven on real hardware.

## Out of scope for the implementation agent

Do NOT touch any Flask route, `db.py`, `templates/`, or `static/`. Do NOT
merge to main. Do NOT push. Do NOT change the login page.
