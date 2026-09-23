# Android app-lock trial: scrapped

## Status

The user rejected the Android app-lock trial on 2026-09-23 and asked for a
replacement APK without the lock or the visible native Settings bar. PR #75
was closed without merging; its branch was deleted. `main` never contained
the app-lock changes. Roadmap item #16 records the reason and postmortem.

## Replacement build

Build the unmodified Android client from `main` with only a release-number
bump: root `VERSION` 1.4 and `android/gradle.properties` `VERSION_CODE=5`.
These values exceed the trial APK's 1.3 / 4, so Android can install the
replacement over it without an uninstall. Keep the checked-in signing key.
The native Android Settings bar stays hidden as before, and there is no app
lock. Wait for a green Build Android APK workflow and give the user the new
run's artifact, not the APK from closed PR #75.
