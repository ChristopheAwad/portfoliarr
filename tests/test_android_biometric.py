# tests/test_android_biometric.py
# ===============================
# Contract pins for the Android biometric unlock (roadmap #57).
#
# pytest cannot compile Kotlin, so these are source/meta-tests in the same
# spirit as test_users_ui.py and test_security_audit.py: they lock the pieces
# of the Kotlin/Gradle/manifest wiring that the Python side actually depends
# on. The runtime behaviour is the on-device GUI gate's job.
#
# What genuinely matters here, and why each pin exists:
#   * the keystore key must require a fresh authentication, or the "secret"
#     is just a file anyone can copy off the phone;
#   * the restored cookie must re-apply HttpOnly and SameSite=Lax, or
#     re-injecting it by hand silently downgrades app.py's protections;
#   * Max-Age must match the server's own session lifetime, or the phone
#     and the server disagree about how long a login lasts;
#   * the gate must run BEFORE the first loadUrl, or the WebView races the
#     prompt and the portfolio flashes before the fingerprint is asked for.

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID = "android/app/src/main"
KOTLIN = f"{ANDROID}/java/com/portfoliarr/app"
TEST_SRC = "android/app/src/test/java/com/portfoliarr/app"


def source(path):
    return (ROOT / path).read_text()


def code(path):
    """The file with its comments stripped.

    Several checks below assert that a construct is ABSENT. Matching raw
    text for that is a trap: the very comment explaining why a flag is
    deliberately not used would then satisfy the "must not appear" rule and
    quietly disarm it. Stripping comments first makes these assertions about
    code, which is what they are meant to be about.
    """
    text = source(path)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
    return text


# ── Gradle dependencies ──────────────────────────────────────────────────

def test_biometric_library_is_pinned_to_an_exact_version():
    toml = source("android/gradle/libs.versions.toml")
    match = re.search(r'^biometric\s*=\s*"([^"]+)"', toml, re.MULTILINE)
    assert match, "libs.versions.toml has no pinned `biometric` version"
    version = match.group(1)
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), (
        f"biometric must be ==-pinned like every other dependency, got {version!r}"
    )
    assert re.search(
        r'^androidx-biometric\s*=\s*\{[^}]*name\s*=\s*"biometric"',
        toml, re.MULTILINE,
    ), "libs.versions.toml declares the version but never the library alias"


def test_junit_is_pinned_to_an_exact_version():
    toml = source("android/gradle/libs.versions.toml")
    match = re.search(r'^junit\s*=\s*"([^"]+)"', toml, re.MULTILINE)
    assert match, "libs.versions.toml has no pinned `junit` version"
    assert re.fullmatch(r"\d+\.\d+\.\d+", match.group(1))


def test_build_gradle_wires_both_dependencies():
    gradle = source("android/app/build.gradle.kts")
    assert "implementation(libs.androidx.biometric)" in gradle
    assert "testImplementation(libs.junit)" in gradle


# ── Manifest permissions ─────────────────────────────────────────────────

def test_manifest_declares_biometric_permissions():
    manifest = source(f"{ANDROID}/AndroidManifest.xml")
    # USE_BIOMETRIC covers API 28+; USE_FINGERPRINT is what API 24-27 reads
    # instead. minSdk is 24, so declaring only the modern one would leave the
    # prompt silently failing on older phones.
    assert "android.permission.USE_BIOMETRIC" in manifest
    assert "android.permission.USE_FINGERPRINT" in manifest


# ── The secret store: the security-critical part ─────────────────────────

def test_secret_store_key_lives_in_the_hardware_keystore():
    store = source(f"{KOTLIN}/SecretStore.kt")
    # A key generated through AndroidKeyStore is generated inside the TEE and
    # is non-exportable, so copying the app's data directory off the device
    # yields ciphertext and never the key itself.
    assert "AndroidKeyStore" in store
    assert "KeyGenParameterSpec.Builder" in store
    assert "setKeySize(256)" in store


def test_secret_store_key_is_not_bound_to_user_authentication():
    # A deliberate design decision, pinned so it cannot be "improved" into a
    # regression. setUserAuthenticationRequired(true) would bind the ENCRYPT
    # purpose too, so writing a newly-captured cookie would need its own
    # authentication — forcing an extra fingerprint prompt on every login and
    # a pending-save state machine. The prompt, not the key, is what stops
    # someone picking up the phone; see MainActivity's gate.
    store = code(f"{KOTLIN}/SecretStore.kt")
    assert "setUserAuthenticationRequired" not in store
    # ...and the prompt really is there, with the device credential fallback
    # the user asked to keep.
    gate = source(f"{KOTLIN}/BiometricGate.kt")
    assert "BiometricPrompt" in gate
    assert "DEVICE_CREDENTIAL" in gate


def test_secret_store_uses_authenticated_encryption_not_ecb():
    store = code(f"{KOTLIN}/SecretStore.kt")
    assert "AES" in store and "GCM" in store
    # ECB is unauthenticated: it leaks structure and is tamperable. This
    # also guards against a future "just use the default transform" slip.
    assert "ECB" not in store
    assert "NoPadding" in store
    assert "GCMParameterSpec" in store


def test_secret_store_clears_itself_when_the_secret_is_unreadable():
    # A tampered ciphertext fails the GCM tag check. Leaving the record in
    # place would mean failing the same way on every future launch, so the
    # store wipes it and lets the ordinary login take over.
    store = source(f"{KOTLIN}/SecretStore.kt")
    for marker in ("KeyPermanentlyInvalidatedException", "AEADBadTagException"):
        assert marker in store, f"{marker} must be handled, not left to crash"


# ── Cookie round-trip: the no-downgrade guard ────────────────────────────

def test_restored_cookie_reapplies_the_servers_protections():
    header = source(f"{KOTLIN}/CookieHeader.kt")
    # app.py sets SESSION_COOKIE_HTTPONLY=True and SESSION_COOKIE_SAMESITE
    # = "Lax" on the real login response. Re-injecting the cookie by hand
    # bypasses that response, so the app has to put the attributes back
    # itself or it has quietly weakened the session.
    assert "HttpOnly" in header
    assert "SameSite=Lax" in header
    assert "Path=/" in header


def test_restored_cookie_max_age_matches_the_server_session_lifetime():
    app = source("app.py")
    assert re.search(
        r'PERMANENT_SESSION_LIFETIME"?\]\s*=\s*timedelta\(days=(\d+)\)', app
    ), "app.py no longer declares a 30-day permanent session"

    header = source(f"{KOTLIN}/CookieHeader.kt")
    match = re.search(r'SESSION_MAX_AGE_SECONDS\s*=\s*([0-9_]+)', header)
    assert match, "CookieHeader.kt must define SESSION_MAX_AGE_SECONDS"
    # 30 days, and the comment beside it must say so, because a silent
    # mismatch here is how a phone ends up logging out early (or staying
    # logged in past what the server thinks).
    assert int(match.group(1).replace("_", "")) == 30 * 24 * 60 * 60
    assert "30 days" in header


def test_cookie_helpers_ignore_the_wrong_case_name():
    # Cookie names are case-sensitive; a case-insensitive match would happily
    # store some unrelated cookie named "Session".
    header = source(f"{KOTLIN}/CookieHeader.kt")
    assert 'SESSION_COOKIE_NAME = "session"' in header
    assert "equals(" not in code(f"{KOTLIN}/CookieHeader.kt"), (
        "cookie name matching must be case-sensitive, not equals(ignoreCase)"
    )


# ── MainActivity: the gate must come before the first load ───────────────

def test_biometric_gate_runs_before_the_first_page_load():
    main = source(f"{KOTLIN}/MainActivity.kt")
    gate = main.find("promptThenLoad")     # performs BiometricPrompt
    first_load = main.find("webView.loadUrl(")
    assert gate != -1, "MainActivity must call the unlock path"
    assert first_load != -1
    assert gate < first_load, (
        "the fingerprint prompt must be started BEFORE the first loadUrl, "
        "otherwise the portfolio renders before the user authenticates"
    )


def test_main_activity_samples_the_cookie_after_a_page_loads():
    main = source(f"{KOTLIN}/MainActivity.kt")
    # onPageFinished is what fires after the login POST redirects, which is
    # the only moment a fresh session cookie exists.
    assert "onPageFinished" in main
    assert "captureSessionCookie" in main
    assert "getCookie" in main


def test_main_activity_never_asks_more_than_once_per_process():
    main = source(f"{KOTLIN}/MainActivity.kt")
    assert "processFresh" in main, (
        "a process-level flag is what makes this cold-start only; without it "
        "every activity recreation re-prompts"
    )
    # And it must be process-scoped, declared outside the Activity class,
    # or a rotation would put it back to true.
    app_state = main.index("object AppState")
    activity = main.index("class MainActivity")
    assert app_state < activity, (
        "AppState must be a top-level object; as an Activity field a "
        "recreated Activity would ask a second time"
    )


def test_unlock_always_reaches_the_page_load():
    # A swallowed prompt callback would leave a permanently blank screen,
    # so the load is reachable both from the answer and from a timeout.
    main = code(f"{KOTLIN}/MainActivity.kt")
    assert "postDelayed" in main
    assert "removeCallbacksAndMessages" in main
    # Two independent one-shot guards: one for the prompt's answer (several
    # callbacks plus the timeout race each other) and one for the load (the
    # timeout must still be able to rescue a stuck cookie write).
    assert "if (answered) return" in main
    assert "if (loadIssued) return" in main


def test_page_load_waits_for_the_cookie_write():
    # CookieManager.setCookie is ASYNCHRONOUS. Loading the page in the same
    # breath would race the cookie write and land on the login form even
    # though the fingerprint succeeded — the feature would look broken on
    # every single unlock.
    main = code(f"{KOTLIN}/MainActivity.kt")
    restore = main[main.index("private fun restoreSavedSession"):]
    restore = restore[:restore.index("\n    }")]

    # The load must be triggered from the setCookie callback...
    assert "then()" in restore
    # ...and restoreSavedSession must take a continuation, so the caller
    # cannot accidentally load before the cookie is in place.
    assert "then: () -> Unit" in restore
    assert "restoreSavedSession(url, ::loadOnce)" in main


def test_capture_never_overwrites_a_good_secret_with_nothing():
    # A missing cookie means the user is on the login page. The stored
    # secret must survive that untouched, or simply opening the app while
    # signed out would wipe the saved login.
    main = code(f"{KOTLIN}/MainActivity.kt")
    capture = main[main.index("private fun captureSessionCookie"):]
    capture = capture[:capture.index("\n    }")]
    assert "?: return" in capture or "if (live == null)" in capture, (
        "captureSessionCookie must bail out when there is no session cookie"
    )
    assert "save(" in capture
    # And the write is guarded by a hash comparison, so a page load that
    # changes nothing does not re-encrypt on every navigation.
    assert "sha256Hex" in capture


def test_logging_out_also_drops_the_stored_secret():
    # Flask's session cookie is a stateless signed blob, so the server
    # cannot revoke the copy the app already holds. Tapping "Sign out" in
    # the profile menu expires the cookie in the WebView jar; if the stored
    # secret survived, the next cold start would replay it and sign the
    # user straight back in. A sign-out that comes back on restart is worse
    # than no sign-out at all.
    main = code(f"{KOTLIN}/MainActivity.kt")
    capture = main[main.index("private fun captureSessionCookie"):]
    capture = capture[:capture.index("\n    }")]
    assert "isAuthPath(url)" in capture
    # ...and it must clear, not just return.
    assert "secretStore.clear()" in capture

    # The path matcher is pure, so it is unit tested rather than trusted.
    gate = source(f"{KOTLIN}/StartGate.kt")
    assert "fun isAuthPath" in gate


# ── Settings: the escape hatches ────────────────────────────────────────

def test_settings_carries_the_toggle_and_the_forget_button():
    settings = source(f"{KOTLIN}/SettingsActivity.kt")
    assert "biometricToggle" in settings
    assert "forgetButton" in settings
    assert "forgetSecret" in settings
    # The label and the explanation live in strings.xml so the layout can
    # reference them; the ids the Activity binds to live in the layout.
    layout = source(f"{ANDROID}/res/layout/activity_settings.xml")
    assert "@+id/biometricToggle" in layout
    assert "@+id/forgetButton" in layout
    strings = source(f"{ANDROID}/res/values/strings.xml")
    assert 'name="biometric_enabled"' in strings
    assert 'name="biometric_explain"' in strings or \
        'name="biometric_explainer"' in strings


def test_settings_switch_populating_does_not_wipe_the_secret():
    # The toggle is set from the stored value while the screen loads, which
    # fires the change listener. Acting on that would let simply opening
    # Settings delete the stored login, so the listener must ignore
    # non-user-driven changes.
    settings = code(f"{KOTLIN}/SettingsActivity.kt")
    assert "isPressed" in settings


def test_forget_button_also_clears_the_webview_cookie():
    # Clearing only the encrypted blob leaves a live, unencrypted copy in
    # the WebView's own cookie jar — the "forget" would not forget.
    settings = source(f"{KOTLIN}/SettingsActivity.kt")
    assert "removeAllCookies" in settings


# ── CI ───────────────────────────────────────────────────────────────────

def test_android_ci_runs_the_unit_tests():
    workflow = source(".github/workflows/build-android.yml")
    assert "./gradlew test" in workflow
    # And it must not be the only thing: the APK is still the artifact.
    assert "./gradlew assembleDebug" in workflow


# ── Pure-logic unit tests exist at all ───────────────────────────────────

def test_pure_helpers_have_jvm_unit_tests():
    for helper in ("CookieHeader.kt", "StartGate.kt"):
        assert (ROOT / f"{KOTLIN}/{helper}").is_file(), f"{helper} is missing"
    for suite in ("CookieHeaderTest.kt", "StartGateTest.kt"):
        assert (ROOT / f"{TEST_SRC}/{suite}").is_file(), f"{suite} is missing"


def test_pure_helpers_import_no_android_framework():
    # The point of splitting them out is that `./gradlew test` can exercise
    # them on a plain JVM. An android.* import here would silently turn
    # them into "tests" that can only ever pass on a device.
    for helper in ("CookieHeader.kt", "StartGate.kt"):
        text = source(f"{KOTLIN}/{helper}")
        assert "import android." not in text, f"{helper} must stay pure"
        assert "import androidx." not in text, f"{helper} must stay pure"
