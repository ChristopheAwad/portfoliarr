# tests/test_android_update.py
# ==============================
# Contract pins for the Android in-app APK update (roadmap #58).
#
# pytest cannot compile Kotlin, so these are source/meta-tests in the same
# spirit as tests/test_android_biometric.py: they lock the pieces of the
# Kotlin/Gradle/manifest/workflow wiring that the Python side actually
# depends on. The runtime behaviour is the on-device GUI gate's job.
#
# What genuinely matters here, and why each pin exists:
#   * CI and the app must agree on the release tag shape byte for byte, or
#     the phone silently never sees a release (a draft/prerelease is
#     invisible to the releases/latest API for the same silent reason);
#   * the SHA-256 must be verified BEFORE anything installs, or a damaged
#     download becomes a broken phone app;
#   * the FileProvider must expose exactly one directory, or the installer
#     hand-off becomes a wider file leak;
#   * the cold-start check must run once per process and only after the
#     #57 gate resolves, or the update box races the fingerprint prompt;
#   * no new Gradle library may sneak in — HttpURLConnection, a thread, and
#     org.json already on the phone are the whole stack.

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KOTLIN = "android/app/src/main/java/com/portfoliarr/app"
TEST_SRC = "android/app/src/test/java/com/portfoliarr/app"

API_URL = "https://api.github.com/repos/ChristopheAwad/portfoliarr/releases/latest"
AUTHORITY = "com.portfoliarr.app.fileprovider"


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


# ── Release workflow ─────────────────────────────────────────────────────

WORKFLOW = ".github/workflows/release-android.yml"


def test_release_workflow_exists_and_triggers_on_main():
    wf = source(WORKFLOW)
    assert "branches" in wf and "main" in wf, "release workflow must run on main"
    assert '"android/**"' in wf or "'android/**'" in wf, \
        "release workflow must trigger on android/**"
    assert '"VERSION"' in wf or "'VERSION'" in wf, \
        "release workflow must trigger on VERSION"
    assert "workflow_dispatch" in wf, "release workflow needs a manual trigger"


def test_release_workflow_has_contents_write():
    wf = source(WORKFLOW)
    assert re.search(r"permissions:\s*\n\s*contents:\s*write", wf), \
        "release workflow needs permissions: contents: write to publish"


def test_release_workflow_builds_tag_from_version_and_code():
    wf = source(WORKFLOW)
    assert "VERSION_CODE" in wf, "tag must include the Android version code"
    assert re.search(r"android-\$", wf) or "android-" in wf, \
        "tag must carry the android- prefix UpdateGate parses"
    assert "gh release create" in wf, "workflow must create the release"


def test_release_workflow_is_idempotent():
    wf = source(WORKFLOW)
    assert "gh release view" in wf, \
        "workflow must skip when the tag already exists (gh release view)"
    view_pos = wf.index("gh release view")
    create_pos = wf.index("gh release create")
    assert view_pos < create_pos, \
        "the existence check must run BEFORE creating anything"


def test_release_workflow_authenticates_gh():
    wf = source(WORKFLOW)
    assert "GH_TOKEN" in wf, \
        "gh needs GH_TOKEN in GitHub Actions or every gh call fails"


def test_release_build_is_skipped_when_already_published():
    wf = source(WORKFLOW)
    assert "steps.exists.outputs.already" in wf, \
        "the build must be guarded by the existence check; exit 0 in a step " \
        "only ends that step and the build would run anyway"
    guard_pos = wf.index("steps.exists.outputs.already")
    build_pos = wf.index("assembleDebug")
    assert guard_pos < build_pos, \
        "the skip decision must be made before the build starts"


def test_release_workflow_publishes_a_final_release():
    lines = []
    for line in source(WORKFLOW).splitlines():
        # YAML comments use #, not //: strip them so the explanatory comment
        # naming the forbidden flags cannot satisfy this pin by itself.
        stripped = line.split("#", 1)[0]
        # ...but never strip inside single quotes (the license hashes).
        if stripped.count("'") % 2 == 1:
            stripped = line
        lines.append(stripped)
    body = "\n".join(lines)
    assert "--draft" not in body, \
        "a draft release is invisible to releases/latest — the app would never see it"
    assert "--prerelease" not in body, \
        "a prerelease is never 'latest' — the app would never see it"


def test_release_workflow_uploads_apk_and_sha_notes():
    wf = source(WORKFLOW)
    assert "assembleDebug" in wf, "the release must build the APK first"
    assert re.search(r"portfoliarr-.*\.apk", wf), \
        "the uploaded asset must be named portfoliarr-<VERSION>-<CODE>.apk"
    assert "sha256sum" in wf, "the workflow must hash the APK"
    assert "SHA-256:" in wf, "the release notes must carry the SHA-256: line"


# ── Manifest and FileProvider ────────────────────────────────────────────

MANIFEST = "android/app/src/main/AndroidManifest.xml"
FILE_PATHS = "android/app/src/main/res/xml/file_paths.xml"


def test_manifest_has_request_install_packages():
    manifest = source(MANIFEST)
    assert "android.permission.REQUEST_INSTALL_PACKAGES" in manifest, \
        "installing an APK needs REQUEST_INSTALL_PACKAGES on API 26+"


def test_manifest_has_locked_down_file_provider():
    manifest = source(MANIFEST)
    assert "androidx.core.content.FileProvider" in manifest
    assert AUTHORITY in manifest, "provider authority must match ApkInstaller"
    assert 'android:exported="false"' in manifest
    assert 'android:grantUriPermissions="true"' in manifest
    assert "android.support.FILE_PROVIDER_PATHS" in manifest


def test_file_paths_exposes_only_the_update_cache():
    xml = source(FILE_PATHS)
    assert "cache-path" in xml, "updates must come from the app-private cache"
    assert 'path="updates/"' in xml, "only the updates/ directory is exposed"
    body = code(FILE_PATHS)
    assert "external-path" not in body, "no shared storage in the hand-off"
    assert "root-path" not in body, "never expose the filesystem root"


def test_cleartext_flag_is_untouched():
    manifest = source(MANIFEST)
    assert 'android:usesCleartextTraffic="true"' in manifest, \
        "the update channel is HTTPS to GitHub; the LAN flag stays as it was"


# ── Menu and strings ─────────────────────────────────────────────────────

MENU = "android/app/src/main/res/menu/main_menu.xml"
STRINGS = "android/app/src/main/res/values/strings.xml"
MAIN = f"{KOTLIN}/MainActivity.kt"


def test_menu_has_check_update_item():
    menu = source(MENU)
    assert "action_check_update" in menu, \
        "the manual trigger lives beside the Settings gear"


def test_menu_handler_runs_a_manual_check():
    main = code(MAIN)
    assert "action_check_update" in main, "MainActivity must handle the item"
    assert re.search(r"maybeCheckForUpdates\s*\(\s*manual\s*=\s*true", main), \
        "the menu path must run a manual check that always reports its result"


def test_every_update_string_exists_and_cancel_is_reused():
    main = source(MAIN)
    used = set(re.findall(r"R\.string\.(update_\w+)", main))
    assert used, "MainActivity references no update strings"
    strings = source(STRINGS)
    for name in sorted(used):
        assert f'name="{name}"' in strings, f"strings.xml is missing {name}"
    assert "update_cancel" not in strings, \
        "reuse the existing cancel string instead of duplicating it"


# ── UpdateGate purity and surface ────────────────────────────────────────

GATE = f"{KOTLIN}/UpdateGate.kt"
GATE_TEST = f"{TEST_SRC}/UpdateGateTest.kt"


def test_update_gate_is_pure_and_complete():
    gate = code(GATE)
    assert "android." not in gate, "UpdateGate must carry no android.* imports"
    assert "androidx." not in gate, "UpdateGate must carry no androidx.* imports"
    assert "org.json" not in gate, "JSON parsing stays in UpdateChecker"
    assert "java.net" not in gate, "networking stays in UpdateChecker"
    for fn in ("parseReleaseTag", "parseAssetCode", "pickApkAsset",
               "extractSha256", "decideCheck"):
        assert fn in gate, f"UpdateGate must expose {fn}"


def test_update_gate_tag_shape_matches_the_workflow():
    gate = source(GATE)
    assert "android-" in gate, "the tag regex must carry the android- prefix"
    assert re.search(r"android-.*VERSION.*VERSION_CODE|VERSION.*CODE", gate) or \
        ("[0-9]" in gate and "android-" in gate), \
        "the tag shape must mirror the workflow's TAG construction"


def test_update_gate_jvm_suite_exists():
    suite = source(GATE_TEST)
    assert "package com.portfoliarr.app" in suite
    assert "android." not in code(GATE_TEST), "the suite must run on a plain JVM"
    for name in ("parseReleaseTag", "pickApkAsset", "extractSha256", "decideCheck"):
        assert name in suite, f"the JVM suite must cover {name}"


# ── Checker: exact URL, timeouts, no UI ──────────────────────────────────

CHECKER = f"{KOTLIN}/UpdateChecker.kt"


def test_checker_hits_the_exact_releases_endpoint():
    checker = source(CHECKER)
    assert API_URL in checker, \
        "the checker must call releases/latest on this repo and no other URL"


def test_checker_has_bounded_timeouts():
    checker = code(CHECKER)
    assert "15_000" in checker or "15000" in checker, \
        "connect and read timeouts must be bounded so a hung check cannot hang the app"
    assert "vnd.github+json" in checker, "the Accept header keeps the API stable"


def test_checker_never_touches_ui_and_nulls_on_failure():
    checker = code(CHECKER)
    assert "AlertDialog" not in checker, "the checker reports; MainActivity dialogs"
    assert "Toast" not in checker, "the checker reports; MainActivity toasts"
    assert "!= 200" in checker or "!isSuccessful" in checker or \
        "responseCode" in checker, "non-200 replies must not proceed"


# ── Downloader/installer: verify before install ──────────────────────────

DOWNLOADER = f"{KOTLIN}/ApkDownloader.kt"
INSTALLER = f"{KOTLIN}/ApkInstaller.kt"


def test_hash_is_verified_before_anything_installs():
    combined = code(DOWNLOADER) + code(INSTALLER)
    assert "MessageDigest" in combined or "sha256" in combined.lower(), \
        "the downloaded file must be hashed"
    dl = code(DOWNLOADER)
    verify_pos = dl.lower().find("sha-256")
    if verify_pos == -1:
        verify_pos = dl.find("MessageDigest")
    ready_markers = ["InstallReady", "onVerified", "listener.on", "installIntent",
                     "buildInstallIntent", "contentUriFor"]
    ready_pos = min((dl.find(m) for m in ready_markers if m in dl),
                    default=len(dl))
    assert 0 <= verify_pos < ready_pos, \
        "verification must textually precede the install hand-off"


def test_missing_hash_fails_closed():
    dl = code(DOWNLOADER)
    assert "delete" in dl, "unverifiable files must be deleted, never kept"
    assert re.search(r"sha256\s*==\s*null|null.*sha256|expected.*null",
                     dl, re.IGNORECASE), \
        "a missing expected hash must abort the install"


def test_installer_uses_the_locked_down_provider():
    installer = source(INSTALLER)
    assert "FileProvider.getUriForFile" in installer
    assert AUTHORITY in installer, "installer authority must match the manifest"
    assert "application/vnd.android.package-archive" in installer
    assert "FLAG_GRANT_READ_URI_PERMISSION" in installer
    assert "FLAG_ACTIVITY_NEW_TASK" in installer


# ── Wiring: once per process, after the gate ─────────────────────────────

def test_cold_start_check_runs_once_after_the_gate():
    main = code(MAIN)
    assert "updateChecked" in main, \
        "AppState needs a process-scoped flag so the check runs once"
    assert re.search(r"maybeCheckForUpdates\s*\(\s*manual\s*=\s*false", main), \
        "the automatic path must be a non-manual check"
    load_once = main[main.index("fun loadOnce"):]
    load_once = load_once[:load_once.index("\n    }")]
    assert "maybeCheckForUpdates" in load_once, \
        "the check starts from loadOnce — after the #57 gate resolves, never before it"


def test_plain_load_path_runs_the_update_check():
    main = code(MAIN)
    assert re.search(r"StartAction\.LOAD\s*->\s*loadOnce\s*\(\s*url\s*\)", main), \
        "the plain LOAD path must call loadOnce; otherwise users without " \
        "biometrics, or who declined the offer, never get the automatic check"


def test_skip_and_pending_keys_are_used():
    main = source(MAIN)
    assert "skipped_update_code" in main, "Skip-this-version must be remembered"
    assert "pending_update_code" in main, \
        "a verified-but-uninstalled file must be offered again next start"


def test_unknown_sources_flow_exists():
    main = code(MAIN)
    assert "canInstallUnknownApps" in main, \
        "MainActivity must check the grant before firing the installer"
    assert "unknownSourcesSettingsIntent" in main, \
        "MainActivity must route to the system screen when the grant is missing"
    assert "ACTION_MANAGE_UNKNOWN_APP_SOURCES" in code(INSTALLER), \
        "the routing must land on the exact system screen for this app"
    assert "pendingInstallAfterPermission" in main, \
        "the grant must retry the install the user already tapped, not nag again"
    assert "fun onResume" in main, "the retry happens when the user returns"


def test_destroy_cancels_an_inflight_download():
    main = code(MAIN)
    assert "fun onDestroy" in main
    destroy = main[main.index("fun onDestroy"):]
    destroy = destroy[:destroy.index("\n    }")]
    assert "updateDownloader" in destroy and ".cancel()" in destroy, \
        "rotation mid-download must cancel it rather than leak into a dead Activity"


def test_rotation_reruns_the_check_after_cancelling_a_download():
    main = code(MAIN)
    destroy = main[main.index("fun onDestroy"):]
    destroy = destroy[:destroy.index("\n    }")]
    assert "AppState.updateChecked = false" in destroy, \
        "an interrupted download must let the recreated Activity offer the update again"


# ── Version source and dependency discipline ─────────────────────────────

def test_version_code_comes_from_package_info():
    main = code(MAIN)
    assert "getPackageInfo" in main, \
        "the running build's code comes from PackageManager"
    assert "BuildConfig" not in main, \
        "AGP 8 disables BuildConfig by default; do not widen the diff to get it"


def test_no_new_gradle_dependency():
    toml = source("android/gradle/libs.versions.toml")
    for lib in ("okhttp", "retrofit", "coroutine"):
        assert lib not in toml.lower(), \
            f"no {lib}: HttpURLConnection plus a thread is the whole stack"
    build = source("android/app/build.gradle.kts")
    assert "buildConfig" not in build, "BuildConfig stays off"


def test_version_code_floor_still_holds():
    props = source("android/gradle.properties")
    match = re.search(r"^VERSION_CODE=(\d+)$", props, re.MULTILINE)
    assert match, "VERSION_CODE missing from android/gradle.properties"
    assert int(match.group(1)) > 5, \
        "VERSION_CODE must exceed 5 (the release/android-baseline-1.4 APK) " \
        "or the update refuses to install over it"
