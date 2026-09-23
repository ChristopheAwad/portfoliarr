# Android app lock (#16) plan

## Status and approval

Plan approved by the user on 2026-09-23. They then said "Proceed" and
implementation began. The user selected a five-minute default. Python tests
are green (899 passed). Android unit tests and the APK build are not yet
verified locally: the installed Java is 25, Gradle fails at configuration,
and SDK 34 is not installed. Android CI now runs `testDebugUnitTest` before
building the APK. The user explicitly authorized a branch push and PR so they
can download the CI APK and test it. Keep the PR open pending their device
approval; do not merge before that approval. The APK candidate bumps shared
VERSION to 1.2 and Android VERSION_CODE to 3 so it installs over older builds.

## Goal and limits

Give the Android APK an optional, phone-local lock. After the whole app has been
in the background for the configured delay, cover its content and ask Android to
authenticate with a strong biometric or the device PIN, pattern, or password.
Available delays are Immediately, 1 minute, 5 minutes, and 15 minutes; the
initial selection is 5 minutes. Disabled is the initial state. A cold start in
a new process requires authentication when the lock is enabled, regardless of
the last return time. A quick return within the delay must not reload the
WebView or dismiss open web forms. The lock applies to native Settings too.

This does not secure the Flask server, add login to the website, or store a
biometric template, PIN, or password in the app. Only a boolean enabled flag and
the selected timeout go in Android SharedPreferences. Authentication comes
from Android's `BiometricPrompt` with `BIOMETRIC_STRONG | DEVICE_CREDENTIAL`.

## Step 1. Write failing tests first

1. Add `android/app/src/test/java/com/portfoliarr/app/AppLockPolicyTest.kt`.
   Keep the policy independent of the Android UI. Inject the clock in elapsed
   milliseconds and pass saved settings and process-session state explicitly.
   Test disabled on first install, the enabled cold start, authentication
   success, quick returns, expiry at exactly 300000 ms, and a return at
   299999 ms. Test each selectable delay (0, 60000, 300000, 900000 ms), a
   negative or unknown saved delay falling back to 300000 ms, repeated
   background/foreground cycles, and monotonic elapsed time that is less than
   a previous stamp after a reboot (fail closed). Test cancellation and failed
   authentication do not unlock, and that success starts a fresh session.
2. Add `tests/test_android_app_lock.py` to inspect Android source/resources for
   wiring that Python can verify without an Android runtime: manifest permission
   and dependency, both activities sharing a lock controller/gate, both screens
   obscuring content while locked, Settings labels and selection values,
   default disabled/five-minute behavior, use of `BIOMETRIC_STRONG` and
   `DEVICE_CREDENTIAL`, no app-owned PIN or server-side auth, and no WebView
   destruction/reload on the ordinary unlock path. Check the renderer callback
   remains inside the WebViewClient. Keep these tests specific to meaningful
   contracts instead of matching whole source files or implementation comments.
3. Confirm `python -m pytest tests/test_android_app_lock.py` fails for the
   missing lock wiring. If Gradle is available, confirm
   `./gradlew testDebugUnitTest` fails for the missing policy. Do not accept a
   failure caused by a broken test or missing build tool as a product failure.

## Step 2. Implement the small, testable lock state machine

1. Add `AppLockPolicy.kt` with the delay constants, supported-value validation,
   and transitions for cold start, leave/return, success, cancellation, and
   rebooted monotonic time. Measure app background duration with
   `SystemClock.elapsedRealtime()`, never wall time. Treat a missing timestamp
   on cold process start as locked if enabled. Keep the decision about when
   authentication is required in this one policy, not in either Activity.
2. Add a small process-session owner (`AppLockSession.kt` or equivalent) to
   track unlock state across MainActivity/SettingsActivity transitions. Use
   `ProcessLifecycleOwner` to stamp when the application as a whole leaves
   the foreground. A transition from Main to Settings, a settings save, or an
   activity configuration change is not a trip to the background. Keep session
   state only in process memory: a restarted process authenticates again.
   Do not reset the clock on repeated resume events while the app is locked.
3. Share one lock gate between MainActivity and SettingsActivity, via a small
   base Activity/controller. Put a full-screen native covering view on top of
   each activity's content before showing a prompt, and before a background
   snapshot can show web or Settings content. Remove it only after the policy
   permits an unprompted return or authentication succeeds. Do not replace,
   destroy, or reload the WebView for a normal lock/unlock. Keep the existing
   `loadFailed` and renderer recovery paths; a renderer rebuild while locked
   must keep the cover in front of the new WebView.
4. Use `androidx.biometric:biometric` and the lifecycle-process dependency in
   `android/gradle/libs.versions.toml` and `android/app/build.gradle.kts`.
   Add Android's biometric permissions to the manifest as required by the
   AndroidX library/API levels. Build the prompt on the active foreground
   Activity; keep one prompt active at a time. Use an explicit Retry button
   after cancellation or terminal errors; do not immediately re-prompt in a
   loop. Treat an unsuccessful biometric attempt as still locked. On activity
   recreation, rebuild the cover and restore or retry the prompt without
   exposing content in an intermediate frame.

## Step 3. Add Settings controls and unavailable-device behavior

1. Update `activity_settings.xml` and `strings.xml` with an App lock section:
   enable/disable control, delay selector with the four exact options above,
   Test lock button, and short text that this protects the Android app only.
   Use resource strings for visible text and content descriptions.
2. Read/write only `app_lock_enabled` and `app_lock_timeout_ms` in the existing
   `portfoliarr` preferences. Initial enabled value is false and timeout is
   300000 ms. A changed timeout takes effect on the next background trip.
   Toggling off inside an already unlocked Settings session takes effect at
   once. Test lock prompts without changing the saved enable flag or delay.
3. Before enabling, call `BiometricManager.canAuthenticate` with the same
   authenticator mask as the prompt. If no enrolled biometric or device
   credential is available, leave the control off, explain what is needed,
   and offer a link to Android's security setup when possible. If credentials
   later disappear while the lock is enabled, keep content covered, explain
   the problem, and allow the user to open device security settings or retry.
   Do not silently turn the lock off or disclose content on error.
4. A locked Settings screen must not expose the saved server URL or the lock
   toggle. The system Back button may leave a locked screen but must not reveal
   another protected screen. Changing the server URL must retain the existing
   navigation behavior when unlocked.

## Step 4. Verify and ask for device approval

1. Run `python -m pytest tests/test_android_app_lock.py`.
2. From `android/`, run `./gradlew testDebugUnitTest` and
   `./gradlew assembleDebug` with JDK 17 and SDK 34. If the local Android SDK
   is unavailable, report that explicitly; the Android CI build still must
   pass before release.
3. The lead agent runs the final full `python -m pytest` suite. Review the
   source diff for lifecycle mistakes and inadvertent changes to the existing
   WebView, signing config, and version wiring.
4. Give the user an APK and ask for on-device checks: disabled launch; enable
   with a credential enrolled; return before five minutes; return at or after
   five minutes; cancel then retry; lock while Settings is visible; rotate or
   recreate; lose and restore the server connection; and renderer recovery.
   The user approved a branch push and PR to obtain the CI APK before the
   device check. Do not merge until they approve the phone behavior. Android's
   `Build Android APK` workflow must be green for any Android change.
5. Before the candidate APK, increase both root `VERSION` and `VERSION_CODE`
   in `android/gradle.properties`; do not change the shared signing key. Mark
   roadmap item #16 shipped only in the shipping commit, not in the candidate
   PR before approval.

## Files expected

`roadmap.md`, `feature.md`, `project-brief.md` (permanent lock-design rule),
`android/app/src/main/java/com/portfoliarr/app/MainActivity.kt`,
`android/app/src/main/java/com/portfoliarr/app/SettingsActivity.kt`, new
Android lock policy/session/gate classes, `android/app/src/main/res/layout/activity_settings.xml`,
Android lock overlay layout or programmatic cover, `android/app/src/main/res/values/strings.xml`,
`android/app/src/main/AndroidManifest.xml`, `android/gradle/libs.versions.toml`,
`android/app/build.gradle.kts`, `android/app/src/test/java/com/portfoliarr/app/AppLockPolicyTest.kt`,
and `tests/test_android_app_lock.py`.
