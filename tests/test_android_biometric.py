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
#   * the keystore key must NOT be bound to user authentication, and the
#     prompt is what gates access instead. Binding it would also gate
#     encryption and force a prompt on every login.
#   * the restored cookie must re-apply HttpOnly and SameSite=Lax, or
#     re-injecting it by hand silently downgrades app.py's protections;
#   * Max-Age must match the server's own session lifetime, or the phone
#     and the server disagree about how long a login lasts;
#   * the gate must run BEFORE the first loadUrl, or the WebView races the
#     prompt and the portfolio flashes before the fingerprint is asked for.
#
# The androidx.biometric pins exist because hand-written stubs cannot see the
# real library. Two mistakes there shipped a red CI build, and both are
# invisible without a compiler.

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


def test_secret_store_does_not_reinsert_the_generated_key():
    # KeyGenerator.generateKey() on the AndroidKeyStore provider ALREADY
    # creates the entry under the alias. Calling setEntry on top of that
    # throws KeyStoreException on a real device, which obtainKey() swallows as
    # a GeneralSecurityException, so save() fails silently, hasSecret() stays
    # false, and the one-time offer can never fire. The feature would be dead
    # on arrival with nothing on screen to explain it.
    store = code(f"{KOTLIN}/SecretStore.kt")
    assert "generateKey()" in store
    assert "setEntry" not in store, (
        "do not re-store a key the provider already registered under the alias"
    )


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
    gate = main.find("decideStartAction")   # picks PROMPT / OFFER / LOAD
    first_load = main.find("webView.loadUrl(")
    assert gate != -1, "MainActivity must consult the start decision"
    assert first_load != -1
    assert gate < first_load, (
        "the start decision must be made BEFORE the first loadUrl, otherwise "
        "the portfolio renders before the user authenticates"
    )


# ── the three-way decision ───────────────────────────────────────────────

def test_start_gate_decides_between_load_prompt_and_offer():
    gate = code(f"{KOTLIN}/StartGate.kt")
    assert "enum class StartAction" in gate
    for action in ("LOAD", "PROMPT", "OFFER"):
        assert action in gate
    assert "fun decideStartAction" in gate


def test_feature_is_off_until_the_user_turns_it_on():
    # Off by default on purpose: PR #75 added a lock that the user rejected
    # on the on-device trial, and a feature that changes how the app opens
    # the moment it is installed is exactly that mistake again.
    store = code(f"{KOTLIN}/SecretStore.kt")
    assert 'getBoolean(KEY_ENABLED, false)' in store, (
        "the feature must default to OFF, not ON"
    )


def test_offers_the_feature_exactly_once():
    store = code(f"{KOTLIN}/SecretStore.kt")
    assert "KEY_DECLINED" in store
    assert "declinedOffer" in store
    main = code(f"{KOTLIN}/MainActivity.kt")
    # "Stop asking" must record the decline as well as switching off, or
    # clearing the secret would let the offer return after the next login.
    assert "markDeclined" in main


def test_login_is_saved_even_while_the_feature_is_off():
    # The one-time offer is only possible because there is a saved login to
    # restore. Capture must therefore NOT consult the enabled flag AT ALL —
    # otherwise the offer can never fire and the feature is unreachable.
    #
    # Deliberately asserts the absence of ANY mention of the flag, not one
    # particular phrasing: a test that only banned the string it happened to
    # be written against would pass on `if (!isEnabled) return`.
    main = code(f"{KOTLIN}/MainActivity.kt")
    capture = main[main.index("private fun captureSessionCookie"):]
    capture = capture[:capture.index("\n    }")]
    for reference in ("isEnabled", "enabledInSettings", "declinedOffer"):
        assert reference not in capture, (
            f"captureSessionCookie must not consult {reference}; the one-time "
            "offer needs a stored secret to exist"
        )


def test_stale_callbacks_cannot_act_on_a_dead_activity():
    # A 90s timeout and a posted dialog can both outlive the Activity if the
    # user rotates or the system reclaims it. Firing either at that point is a
    # crash (BadTokenException) or a load into a destroyed WebView.
    main = code(f"{KOTLIN}/MainActivity.kt")
    assert "onDestroy" in main, "the timeout handler must be cancelled"
    assert "removeCallbacksAndMessages" in main
    assert "isFinishing" in main or "isDestroyed" in main


def test_the_settings_gear_stays_gone():
    # Hard-won: PR #75 made the action bar visible to reach the lock's
    # settings, the user rejected the resulting app, and asked for both the
    # gear and the lock to be removed. The controls are reachable from the
    # cancel dialog instead. Nothing may reintroduce a visible gear.
    main = code(f"{KOTLIN}/MainActivity.kt")
    assert "supportActionBar?.hide()" in main, (
        "the action bar must stay hidden; the user rejected it being shown"
    )
    # No new layout may add a settings button to the main screen.
    layout = source(f"{ANDROID}/res/layout/activity_settings.xml")
    assert "action_settings" not in layout


def test_cancelling_offers_the_three_way_choice():
    main = code(f"{KOTLIN}/MainActivity.kt")
    for name in ("biometric_use_my_password", "biometric_stop_asking",
                 "biometric_forget"):
        assert f"R.string.{name}" in main, f"{name} must be offered on cancel"
    # Stop asking must both disable AND record the decline; disabling alone
    # clears the secret, which lets the one-time offer return after the next
    # sign-in.
    assert "markDeclined" in main
    assert "setEnabled(false)" in main
    # Forget must go through the shared action, not a second copy.
    assert "forgetPhone" in main


def test_settings_screen_is_documented_as_unreachable():
    # Honest bookkeeping: the switch and Forget button live on a screen the
    # user cannot open, because the only route is an action-bar item in a
    # hidden action bar. The dialog is the live path. A future change that
    # makes the gear reachable should remove this note, not forget it.
    settings = source(f"{KOTLIN}/SettingsActivity.kt")
    assert "unreachable" in settings.lower() or "hidden action bar" in settings


# ── release hygiene ──────────────────────────────────────────────────────

def test_version_code_is_high_enough_to_install_over_the_baseline_apk():
    # The scrapped PR #75 trial build and the replacement baseline APK on
    # branch release/android-baseline-1.4 are VERSION_CODE 5. Android
    # refuses a DOWNGRADE, so a build from this branch would fail to install
    # with "App not installed" unless the code is strictly higher.
    props = source("android/gradle.properties")
    match = re.search(r"^VERSION_CODE=(\d+)$", props, re.MULTILINE)
    assert match, "VERSION_CODE missing from android/gradle.properties"
    assert int(match.group(1)) > 5, (
        "VERSION_CODE must exceed 5 (the release/android-baseline-1.4 APK) "
        f"or Android rejects the update; found {match.group(1)}"
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


def test_dialogs_cannot_block_the_load():
    # The offer and the cancel choice are dialogs standing between the user
    # and the page. Neither may ever prevent the load: a dialog that cannot
    # be dismissed would leave a blank screen, which is the one failure mode
    # with no user-visible workaround.
    main = code(f"{KOTLIN}/MainActivity.kt")

    # A dismissal listener is the guarantee: back button, tap-outside, or a
    # button all converge on the load.
    assert "setOnDismissListener" in main, (
        "the dialogs must load the page on dismissal, not only on a button"
    )

    # All three outcomes of the decision must be handled in onCreate.
    on_create = main[main.index("override fun onCreate"):]
    on_create = on_create[:on_create.index("\n    private fun")]
    for action in ("StartAction.PROMPT", "StartAction.OFFER"):
        assert action in on_create, f"{action} is never handled"
    # And the plain LOAD path is still there as the default. Since roadmap
    # #58 it goes through loadOnce — which performs the load AND runs the
    # automatic update check — so that a phone without biometrics still
    # reaches both.
    assert "StartGate.StartAction.LOAD" in on_create, \
        "the plain LOAD path is never handled"
    assert re.search(r"StartAction\.LOAD\s*->\s*loadOnce\s*\(\s*url\s*\)", on_create), \
        "the plain LOAD path must route through loadOnce"


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
    assert "restoreSavedSession(url) { loadOnce(url) }" in main


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
    # Clearing only the encrypted blob leaves a live copy in the WebView's
    # own cookie jar — the "forget" would not forget. Worse, because Flask's
    # session cookie is a stateless signed blob, the stored copy stays valid
    # and the next cold start would sign the user straight back in.
    #
    # The wipe lives in SessionControl so the cancel dialog and the Settings
    # button cannot drift apart, and BOTH must call it.
    control = code(f"{KOTLIN}/SessionControl.kt")
    assert "removeAllCookies" in control
    assert "flush()" in control
    assert "clear()" in control

    for caller in ("MainActivity.kt", "SettingsActivity.kt"):
        assert "SessionControl.forgetPhone" in code(f"{KOTLIN}/{caller}"), (
            f"{caller} must go through the shared forget action"
        )


# ── CI ───────────────────────────────────────────────────────────────────

def test_android_ci_runs_the_unit_tests():
    workflow = source(".github/workflows/build-android.yml")
    assert "./gradlew test" in workflow
    # And it must not be the only thing: the APK is still the artifact.
    assert "./gradlew assembleDebug" in workflow


# ── androidx.biometric API contract ──────────────────────────────────────
# Pinned because hand-written stubs cannot see the real library. Two mistakes
# here shipped a red CI build: the constructors take a FragmentActivity (there
# is no Context overload) and authenticate() has no CancellationSignal
# overload (that one belongs to the framework class, not the androidx one).
# Both are cheap to write and impossible to notice without compiling.

def test_biometric_prompt_is_built_from_a_fragment_activity():
    gate = code(f"{KOTLIN}/BiometricGate.kt")
    assert "FragmentActivity" in gate, (
        "androidx.biometric.BiometricPrompt only accepts a FragmentActivity or "
        "a Fragment; there is no Context constructor"
    )
    assert "import androidx.fragment.app.FragmentActivity" in gate
    # And it must not reach for the framework class, whose API differs.
    assert "android.hardware.biometrics" not in gate


def test_biometric_prompt_is_started_without_a_cancellation_signal():
    gate = code(f"{KOTLIN}/BiometricGate.kt")
    # androidx has exactly two authenticate() overloads:
    #   (PromptInfo) and (PromptInfo, CryptoObject)
    # No CancellationSignal. The one that takes a CancellationSignal belongs
    # to android.hardware.biometrics.BiometricPrompt.
    assert "authenticate(info)" in gate
    assert "CancellationSignal" not in gate, (
        "androidx BiometricPrompt has no CancellationSignal overload"
    )


def test_biometric_prompt_still_answers_exactly_once():
    # Whatever the API shape, the one guarantee that matters is that every
    # ending reaches the caller. A second callback would double-load the page.
    gate = code(f"{KOTLIN}/BiometricGate.kt")
    assert "delivered" in gate
    assert "onAuthenticationSucceeded" in gate
    assert "onAuthenticationError" in gate


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
