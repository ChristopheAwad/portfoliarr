# Android In-App APK Update — roadmap #58 (fixed plan)

`Status: in progress` / `Branch: feature/58-android-in-app-update` / `Date started: 2026-09-29`

This file is the corrected plan. The first build pass shipped most of the
feature; a review found three blockers and three medium issues. This document
records what is done and what remains. Every remaining item below is small.

## 1. Problem (one paragraph)

Today every phone update is hand work: find the CI artifact, download it to the
phone, install it by hand. The app should do all of that itself: notice a newer
build, download it, check it arrived complete, and open the Android installer so
the user taps Install once. Android never allows a fully silent install, so one
tap stays. The update channel is HTTPS to GitHub Releases; the app polls the
public releases API. The deployment channel, tag contract, and the pure
`UpdateGate` were settled in the first pass and do not change here.

## 2. What the first pass already built (correct, do not rebuild)

- `UpdateGate.kt` — pure parser/decision object, no `android.*`.
- `UpdateChecker.kt` — one HTTPS GET to the pinned releases URL, bounded
  timeouts, `org.json`, no UI.
- `ApkDownloader.kt` — streams to the app-private cache, size check, then
  SHA-256; deletes on any failure.
- `ApkInstaller.kt` — `FileProvider` hand-off, MIME type, both intent flags,
  unknown-sources routing.
- `res/xml/file_paths.xml` — exposes only `cache/updates/`.
- Manifest permission + locked-down provider; menu item; strings.
- `UpdateGateTest.kt` — plain-JVM decision tests.
- `tests/test_android_update.py` — source/pytest contract pins.
- `.github/workflows/release-android.yml` — publishes `android-<VERSION>-<CODE>`
  with the APK and a `SHA-256:` line.

## 3. Fix pass (all items below were applied on the branch)

### A1 — the plain LOAD path must run the check
`MainActivity.kt`: `StartGate.StartAction.LOAD -> loadOnce(url)`.
The check lives in `loadOnce`. If LOAD calls `webView.loadUrl` directly, a phone
without biometrics, or one that declined the one-time offer, never sees updates.
Pytest pin: `test_plain_load_path_runs_the_update_check`.

### A2 — gh needs a token
`release-android.yml`: workflow-level
`env: GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}`.
GitHub requires it for every `gh` step.
Pytest pin: `test_release_workflow_authenticates_gh`.

### A3 — the existence skip must stop the job
`exit 0` only ends a step. The workflow now writes `already=true|false` to a
step output in `Check whether the release already exists`, and every later step
(`Build debug APK`, `Prepare asset and notes`, `Create release`) is guarded by
`if: steps.exists.outputs.already == 'false'`. The in-create race guard stays.
Pytest pin: `test_release_build_is_skipped_when_already_published`.

### B1 — hash the pending file off the main thread
`MainActivity.kt`: `maybeCheckForUpdates` now defers to a new `runUpdateCheck`;
`offerPendingUpdate` does only cheap checks on the main thread, then hashes the
cache file on a `Thread` and posts the result. A valid file shows Install; a
stale/altered/missing file clears and falls through to a fresh network check.

### B2 — bring the box back after rotation mid-download
`onDestroy` sets `AppState.updateChecked = false` when a download was in flight,
before cancelling it. A recreated Activity then runs the check again and shows
the update box.
Pytest pin: `test_rotation_reruns_the_check_after_cancelling_a_download`.

### C1 — drop the unused parameter
`ApkInstaller.buildInstallIntent(uri: Uri)` (no `context`); caller updated.

### C2 — throttle progress
`ApkDownloader.download` reports progress at most every 256 KB, plus one final
report so a determinate bar reaches 100%.

## 4. F1–F12 coverage map (honest)

`pytest` cannot compile Kotlin and this branch adds no Robolectric, so none of
these runtime paths is automated locally. Each row names where it is covered.

| Path | Covered by |
| --- | --- |
| F1 airplane mode → silent | device gate; null-on-exception pin in `test_checker_never_touches_ui_and_nulls_on_failure` |
| F2 zero releases (404) | device gate; non-200 pin in `UpdateChecker` test |
| F3 rate-limited (403) | same as F2 |
| F4 garbage `tag_name` | `UpdateGateTest` tag-rejection cases |
| F5 release with no `.apk` | `UpdateGateTest` `pickApkAsset` cases |
| F6 body without hash line | `test_missing_hash_fails_closed`; `UpdateGateTest` hash cases |
| F7 byte-flip mid-download | device gate; hash-order pin in `test_hash_is_verified_before_anything_installs` |
| F8 user cancels progress | device gate; cancel path pinned by `test_destroy_cancels_an_inflight_download` |
| F9 unknown-sources denied | `test_unknown_sources_flow_exists`; device gate for the return |
| F10 rotation mid-download | `test_rotation_reruns_the_check_after_cancelling_a_download` |
| F11 manual check on a skipped version | device gate; manual-ignores-skip source path |
| F12 size field lies | device gate; `SIZE_MISMATCH` delete in `ApkDownloader` |

No fake tests. The device gate is the only proof for F1, F2, F3, F7, F8, F9,
F11, F12.

## 5. Tests to run

1. `python -m pytest tests/test_android_update.py` — all pins.
2. `python -m pytest` — full suite (lead agent).
3. `Build Android APK` on the branch — the only real Kotlin compile; it runs
   `./gradlew test` (the `UpdateGateTest` suite).

## 6. Device gate using the real code-6 release (chosen method)

Do NOT bump `VERSION_CODE` on this branch. Use the real first release as the
upgrade target instead of a throwaway branch.

1. Install the code-5 APK from `release/android-baseline-1.4` on the phone.
2. Run `Publish Android release` by `workflow_dispatch` on this branch. Main
   already carries `VERSION=1.1` and `VERSION_CODE=6`, so it publishes the real
   `android-1.1-6`.
3. Open the app. It must offer 1.1-6. Test: Download → progress → hash check →
   Install prompt → tap Install. Confirm the version rises and the server URL
   and login survive.
4. Also exercise Later and Skip if reachable. The manual menu item is dormant
   (action bar hidden), so note it as dormant.
5. Merge #58. The workflow re-runs on main, sees the tag exists, and skips. The
   phone stays on the real 1.1-6. No code burned, no scratch cleanup.
6. If the test release is bad, delete it with
   `gh release delete android-1.1-6 --yes --cleanup-tag` before merging.

Fallback if a code-5 build cannot be installed: create a throwaway branch with
`VERSION_CODE=7`, dispatch the workflow, test, then delete that release. This
burns code 7 for the phone, so the next real release must be 7 or higher.

## 7. Revert path

All new Kotlin/XML/workflow/test files delete cleanly. `MainActivity.kt`,
manifest, menu, and strings revert by removing the marked `// #58` blocks.
Already-published releases stay published and are harmless — old code never
checks. Phone rollback: uninstall first, then install an older build.
