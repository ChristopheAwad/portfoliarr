# Feature: Android WebView Wrapper

## Problem
Want a native Android app experience (launcher icon, full-screen, back button) for Portfoliarr without maintaining a separate native frontend. PWAs require HTTPS, which this project doesn't use.

## Solution
A thin WebView wrapper that loads the existing web app from a user-configurable server URL. All UI logic stays in Flask + vanilla JS. The wrapper adds: app icon, native back button, status bar theming, and a settings screen for URL entry.

## Rollback
Delete the `android/` folder. Zero changes to the existing codebase.

## Files to create (all inside `android/`)

| File | ~LoC | Notes |
|---|---|---|
| `settings.gradle.kts` | ~20 | Project settings |
| `gradle/libs.versions.toml` | ~15 | Version catalog |
| `build.gradle.kts` | ~10 | Root build |
| `gradle.properties` | ~5 | JVM args |
| `gradlew` + `gradlew.bat` | ~201 | Wrapper scripts |
| `gradle/wrapper/gradle-wrapper.properties` | ~3 | Gradle 8.11.1 |
| `app/build.gradle.kts` | ~30 | compileSdk 34, minSdk 24 |
| `app/src/main/AndroidManifest.xml` | ~20 | INTERNET perm, cleartext |
| `app/src/main/java/.../MainActivity.kt` | ~80 | WebView, back button, settings menu |
| `app/src/main/java/.../SettingsActivity.kt` | ~65 | URL input, save to SharedPreferences |
| `app/src/main/res/layout/activity_main.xml` | ~10 | Fullscreen WebView |
| `app/src/main/res/layout/activity_settings.xml` | ~30 | EditText + Save button |
| `app/src/main/res/menu/main_menu.xml` | ~12 | Settings gear icon |
| `app/src/main/res/values/themes.xml` | ~12 | Dark status bar |
| `app/src/main/res/values/colors.xml` | ~5 | #1a1a2e status bar |
| `app/src/main/res/values/strings.xml` | ~6 | App name "Portfoliarr" |
| `app/src/main/res/mipmap-*/ic_launcher.png` | binary | 5 densities from assets/logo |
| `README.md` | ~40 | Build instructions |

**Real code: ~220 LoC**

## Flow
```
First launch → no URL in SharedPreferences → SettingsActivity → save → load WebView
Return launch → URL exists → load WebView
Menu gear icon → open SettingsActivity to change URL
```

## Test plan
- Build the APK in Android Studio
- Install on device/emulator
- First launch shows settings screen, enter server URL
- WebView loads the web app
- Back button navigates WebView history, then exits
- Gear icon opens settings to change URL
- Status bar matches dark theme
