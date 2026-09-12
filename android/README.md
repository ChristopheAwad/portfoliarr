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

To change the URL later, tap the gear icon in the toolbar.

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

## How It Works

- `MainActivity` — Fullscreen WebView that loads the saved server URL
- `SettingsActivity` — URL input form, saves to SharedPreferences
- Back button navigates WebView history, then exits
- Status bar color matches the web app's dark theme (`#1a1a2e`)

## Rollback

Delete this folder. The existing web app is completely unaffected.
