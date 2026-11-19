# Portfoliarr — Android App

A thin Android WebView wrapper around the Portfoliarr web app. Loads your self-hosted Flask server in a fullscreen WebView with native back button, settings screen, and app icon.

## Requirements

- Android Studio Ladybug (2024.2.1) or newer
- Android SDK 34
- JDK 17+

## Setup

1. Open this folder in Android Studio
2. Let Gradle sync (first build downloads dependencies)
3. Connect an Android device or start an emulator
4. Click **Run** (or `Shift+F10`)

## First Launch

The app opens to a **Settings** screen. Enter your server URL (e.g. `http://192.168.1.100:5000`) and tap **Save**. The WebView then loads your Portfoliarr instance.

To change the URL later, clear the app's storage in Android settings and enter it again. The action bar is hidden, so there is no reachable settings gear.

## Building an APK

**Debug APK:**
```
./gradlew assembleDebug
```
Output: `app/build/outputs/apk/debug/app-debug.apk`

Debug builds use the local Android debug key. An APK built on another machine may require a clean install. Do not distribute debug APKs as releases.

**Release APK:** Run `./gradlew :app:assembleRelease` in an environment configured with `ANDROID_RELEASE_KEYSTORE_PATH`, `ANDROID_RELEASE_STORE_PASSWORD`, `ANDROID_RELEASE_KEY_ALIAS`, and `ANDROID_RELEASE_KEY_PASSWORD`. Output: `app/build/outputs/apk/release/app-release.apk`. Release packaging requires signing inputs; it cannot fall back to a debug key.

## Updates

The app checks GitHub Releases over HTTPS on each cold start, after the fingerprint gate resolves. If a release carries a strictly higher `versionCode`, the app offers to download it, verifies the file against the `SHA-256:` line in the release notes, and hands it to Android's installer. Android always keeps the final Install tap.

A release is visible to the app only when all of these hold:

- Tag `android-<VERSION>-<VERSION_CODE>`, for example `android-1.2-7`.
- One asset named `portfoliarr-<VERSION>-<VERSION_CODE>.apk`.
- A line `SHA-256: <64 hex chars>` in the release body.
- The release is final, not a draft and not a prerelease.

## First release with the private key

Android cannot install the first production-signed APK over an older build signed with the retired key. Before uninstalling, note your server URL and make sure you know your login. Uninstall the old app, then download and install the production APK from the official [Portfoliarr releases page](https://github.com/ChristopheAwad/portfoliarr/releases). Enter the server URL, sign in, and reconnect your widgets. If you use the local fingerprint or PIN lock, enable it again. The server keeps your portfolio data. Later releases with the same production key install in place.

## Publishing a release

1. Generate a private production signing key with `keytool` outside the checkout. Keep an encrypted offline backup and verify you can open it. Never store the keystore or its passwords in Git.
2. Create a protected GitHub environment named `android-production` that permits deployments only from `main`. Set its `ANDROID_RELEASE_KEYSTORE_B64`, `ANDROID_RELEASE_STORE_PASSWORD`, `ANDROID_RELEASE_KEY_ALIAS`, and `ANDROID_RELEASE_KEY_PASSWORD` secrets. The first secret holds the entire keystore file, base64-encoded. Base64 does not encrypt it.
3. Get the SHA-256 fingerprint of the key's **public certificate** using `keytool -list -v -keystore <keystore-path> -alias <alias>`. Confirm the fingerprint independently and commit it in `android/release-cert.sha256` as one line of 64 hex digits without colons. The publisher checks the APK against this public fingerprint.
4. Verify a candidate on a test device before publication. Test a clean install as well as the expected refusal to update an old-key install. Do not use the public Releases page for temporary test APKs. For the next production release, verify that the same signer can update the app in place.
5. When ready to ship, bump root `VERSION` and `VERSION_CODE` in `android/gradle.properties` together. After the bump reaches `main`, use **Actions → Publish Android release → Run workflow** on `main`. A merge alone does not publish an APK.

## How It Works

- `MainActivity` — Fullscreen WebView that loads the saved server URL
- `SettingsActivity` — URL input form, saves to SharedPreferences
- Back button navigates WebView history, then exits
- Status bar color matches the web app's dark theme (`#1a1a2e`)

## Rollback

If a release stops the app from starting or working, build the last known good code with a higher `versionCode` and the same production key. Verify it restores normal sign-in, lock, and widget behavior on the device before publishing. Reverting the code does not downgrade an installed APK. If you lose the key, restore it from the offline backup. Without the backup, another signing change requires a new manual reinstall. Do not re-enable the retired key.
