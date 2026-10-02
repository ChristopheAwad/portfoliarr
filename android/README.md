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

**Release APK:**
```
./gradlew assembleRelease
```
Output: `app/build/outputs/apk/release/app-release-unsigned.apk`

## Updates

The app checks GitHub Releases over HTTPS on each cold start, after the fingerprint gate resolves. If a release carries a strictly higher `versionCode`, the app offers to download it, verifies the file against the `SHA-256:` line in the release notes, and hands it to Android's installer. Android always keeps the final Install tap.

A release is visible to the app only when all of these hold:

- Tag `android-<VERSION>-<VERSION_CODE>`, for example `android-1.2-7`.
- One asset named `portfoliarr-<VERSION>-<VERSION_CODE>.apk`.
- A line `SHA-256: <64 hex chars>` in the release body.
- The release is final, not a draft and not a prerelease.

To ship a new version, bump root `VERSION` and `VERSION_CODE` in `android/gradle.properties` together on `main`. The `Publish Android release` workflow publishes the release, and phones on an update-aware build offer it on their next cold start. Android refuses a lower `versionCode`, so a downgrade needs an uninstall.

To test the update on a device, the phone must already run a build with the checker. Publish a higher-code build from a throwaway branch, test the in-app flow, then delete that release, tag, and branch. The header of `.github/workflows/release-android.yml` documents the exact contract.

## How It Works

- `MainActivity` — Fullscreen WebView that loads the saved server URL
- `SettingsActivity` — URL input form, saves to SharedPreferences
- Back button navigates WebView history, then exits
- Status bar color matches the web app's dark theme (`#1a1a2e`)

## Rollback

Delete this folder. The existing web app is completely unaffected.
