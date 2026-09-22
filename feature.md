# Feature #22: In-App Version Display

## Status

IMPLEMENTED 2026-09-22. Automated Flask and browser-source verification is
green. The local Android build is blocked before project evaluation because the
machine has only JDK 25 (`25.0.4.1`), while this project requires JDK 17; the
Build Android APK workflow must provide that gate. Browser GUI and on-device
approval remain pending.

Verification completed:

- Red test-first run: 15 expected failures.
- `python -m pytest tests/test_app_version.py`: 15 passed.
- Preferences regression run: 23 passed.
- `python -m pytest`: 888 passed.
- `git diff --check`: passed.
- `./gradlew assembleDebug`: locally blocked by the installed JDK 25 before
  Gradle evaluated the project (`IllegalArgumentException: 25.0.4.1`).

This file is the complete test-first implementation handoff. Write all failing
tests before production edits. After implementation and a green full pytest
suite, stop for the user's browser GUI approval. Do not commit or push before
that approval.

## User Goal

Make the installed or deployed Portfoliarr release easy to identify inside the
app. Show the release number in a small About card at the bottom of Preferences.
The web app and Android APK must report the same human-readable version instead
of maintaining duplicate values that can drift.

## Approved Product Decisions

1. Put the visible version on `/preferences`, not in the navbar, profile menu,
   bottom tabs, or every-page footer.
2. Add an `About` card after the existing Ledger card.
3. Show one read-only row with the label `Version` and the release text. The
   initial shared release is `1.1`.
4. Keep the display visually quiet. It is release metadata, not a control or a
   primary action.
5. Use a root `VERSION` text file as the one source for the human-readable app
   version. It must contain only the release value and a trailing newline.
6. Flask reads the root file and supplies that value to the Preferences Jinja
   template. Do not hardcode `1.1` in Python or HTML.
7. Android Gradle reads the same root file for `versionName`. Do not retain a
   second `VERSION_NAME` value in `android/gradle.properties`.
8. Keep Android `VERSION_CODE` in `android/gradle.properties`. It serves a
   different Android installation contract and must still increase before each
   APK release.
9. Accept release values with two or three numeric components, such as `1.1`
   and `1.1.0`. Reject empty values, arbitrary words, `v1.1`, and suffixes.
10. A missing or malformed shared version is a packaging error. Flask startup
    and Android Gradle configuration must fail clearly instead of using a
    fallback that could hide version drift.
11. Do not add an API endpoint, database setting, browser storage key, network
    request, or JavaScript for static release metadata.
12. Do not change the release number in this feature. The first displayed value
    is the existing Android `VERSION_NAME=1.1`.

## Architecture And Data Flow

1. Root `VERSION` contains `1.1`.
2. `app.py` resolves it relative to `app.py`, not the process working directory.
3. A small pure loader reads, trims, and validates the complete value. Missing
   files keep their clear `FileNotFoundError`; malformed values raise a clear
   `ValueError`.
4. `APP_VERSION` loads once when `app.py` imports. A running release does not
   need repeated disk reads.
5. `preferences_page()` passes `app_version=APP_VERSION` to the template.
6. `preferences.html` renders the escaped value as plain text.
7. Android Gradle resolves the same file from `rootProject.projectDir.parentFile`,
   validates it during configuration, and assigns it to `versionName`.
8. `android/gradle.properties` keeps `VERSION_CODE=2` but removes
   `VERSION_NAME=1.1`.
9. Docker requires no special copy rule: `COPY . .` includes root `VERSION`.

## Test-First Work

Create `tests/test_app_version.py` before production edits. Keep tests focused
on observable behavior and the single-source contract.

### Shared File Tests

1. Assert root `VERSION` exists.
2. Assert its exact trimmed value is `1.1`.
3. Assert it matches the approved full numeric format with two or three parts.
4. Assert it has no `v` prefix or release suffix.

### Flask Loader Tests

1. Verify a temporary file containing `2.3\n` returns `2.3`.
2. Verify valid surrounding whitespace is trimmed.
3. Parameterize invalid content: empty text, whitespace, `v1.1`, `1`, `1.`,
   `.1`, `1.x`, `1.2.3.4`, and `1.2-beta`.
4. Assert each invalid value raises `ValueError` with a message that identifies
   an invalid app version.
5. Pass a nonexistent path and assert `FileNotFoundError` is not hidden by a
   fallback.
6. Assert `app.APP_VERSION` equals root `VERSION` after trimming.

### Preferences Route Tests

1. Request `/preferences` and assert HTTP 200.
2. Assert the About card occurs after the Ledger card.
3. Assert the card includes a `Version` label and exact `APP_VERSION` value.
4. Assert the version is static text, not an input, select, checkbox, button,
   or link.
5. Preserve existing theme, default-sort, direction, and show-closed controls.

### Android Single-Source Tests

1. Assert `android/app/build.gradle.kts` resolves root `VERSION`.
2. Assert `versionName` is assigned from the shared loaded value.
3. Assert Gradle trims and validates it without a fallback.
4. Assert `android/gradle.properties` retains `VERSION_CODE=2`.
5. Assert `android/gradle.properties` no longer defines `VERSION_NAME`.
6. Assert release comments name root `VERSION` and Android `VERSION_CODE`.

### Docker Packaging Test

1. Extend Docker source tests only if needed to lock that `.dockerignore` does
   not exclude `VERSION` and `Dockerfile` retains `COPY . .`.
2. Do not require Docker locally; Docker is unavailable on this machine.

## Implementation Steps

1. Write all `tests/test_app_version.py` tests above.
2. Run `python -m pytest tests/test_app_version.py`; confirm failures cover the
   missing root file, loader, About card, and Gradle wiring.
3. Add root `VERSION` with exactly `1.1` and a trailing newline.
4. In `app.py`, import `Path` and `re` using the existing style.
5. Add `_load_app_version(path=None)` near application constants. Its default
   path is `Path(__file__).with_name("VERSION")`.
6. Validate with a full match for two or three dot-separated integer parts.
   Raise `ValueError` for invalid content and do not catch missing files.
7. Assign `APP_VERSION = _load_app_version()` at module import.
8. Pass `app_version=APP_VERSION` only from `preferences_page()`. Do not use a
   global Jinja context because other pages do not display it.
9. Add the About card after Ledger in `templates/preferences.html`. Reuse the
   existing card and preference-row classes.
10. Add only one small CSS class if needed for subdued, right-aligned version
    text. Use existing color tokens and do not change layout widths.
11. Update `android/app/build.gradle.kts` to read parent root `VERSION`, trim and
    validate it with the same format, and set `versionName` from it.
12. Use a clear Gradle `require(...)` message for invalid content. Let a missing
    file fail naturally. Remove the old version-name fallback.
13. Remove `VERSION_NAME=1.1` from `android/gradle.properties`, retain
    `VERSION_CODE=2`, and correct the release comments.
14. Add a Design Rule to `project-brief.md`: root `VERSION` is shared by web and
    Android; Android `VERSION_CODE` stays separate; invalid values fail.
15. Correct `AGENTS.md` so APK release instructions say to bump root `VERSION`
    and Android `VERSION_CODE`, not two Gradle properties.

## Verification

1. Run `python -m pytest tests/test_app_version.py`.
2. Run `python -m pytest tests/test_dark_mode.py tests/test_show_closed_pref.py tests/test_routes.py::test_preferences_page_renders_200`.
3. Run `python -m pytest tests/test_docker.py` if packaging tests change.
4. Run `android/gradlew assembleDebug` from `android/` with JDK 17 and SDK 34.
5. Run the final full suite: `python -m pytest`.
6. Record command results in this file's status section.
7. Stop for browser approval. The user checks Preferences at desktop and narrow
   widths in light and dark themes and confirms `Version 1.1` is readable and
   visually quiet.
8. A green Build Android APK workflow and on-device approval are required before
   merge. If local Android tools are unavailable, state that limitation.
9. Only after approvals, ask whether to commit/push. Never do so automatically.

## Files Expected To Change

- `VERSION`
- `app.py`
- `templates/preferences.html`
- `static/style.css` only if needed
- `android/app/build.gradle.kts`
- `android/gradle.properties`
- `tests/test_app_version.py`
- `project-brief.md`
- `AGENTS.md`
- `roadmap.md`
- `feature.md`

## Explicit Non-Goals

- No Git-tag or package-version generation.
- No commit SHA, build date, updater, changelog, or release notes UI.
- No version API endpoint.
- No version outside Preferences.
- No database migration or stored preference.
- No Android `VERSION_CODE` change for this UI feature.
- No fallback release number in Flask or Gradle.
