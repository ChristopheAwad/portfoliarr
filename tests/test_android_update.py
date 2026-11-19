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

# Public fingerprint of the old tracked android/app/debug.keystore. It must
# never sign a production release, no matter what release-cert.sha256 says.
DEBUG_CERT_SHA256 = (
    "83f98e8588eeb10de17aeb848e01ee35"
    "c3d3f1dda4594d9f7b403d8724871ab9"
)


def yaml_code(text):
    """Strip full-line YAML/shell comments so absence pins code, not prose.

    Inline text is preserved: `Signer #1` is code, not a comment.
    """
    return "\n".join(
        "" if line.lstrip().startswith("#") else line
        for line in text.splitlines()
    )


def run_blocks(text):
    """Return every indented `run: |` body in a workflow."""
    lines = text.splitlines()
    blocks = []
    index = 0
    while index < len(lines):
        match = re.match(r"^(\s*)run:\s*\|", lines[index])
        if not match:
            index += 1
            continue
        indent = len(match.group(1))
        body = []
        index += 1
        while index < len(lines):
            line = lines[index]
            if line.strip() and (len(line) - len(line.lstrip())) <= indent:
                break
            body.append(line)
            index += 1
        blocks.append("\n".join(body))
    return blocks


def test_release_workflow_is_manual_main_only():
    wf = source(WORKFLOW)
    on_block = wf.split("\non:", 1)[1].split("\npermissions:", 1)[0]
    assert "workflow_dispatch:" in on_block, \
        "release workflow needs a manual trigger"
    assert not re.search(r"^\s*(push|pull_request|schedule):", on_block, re.M), \
        "merging to main must never publish; only workflow_dispatch may start this"
    assert "github.ref == 'refs/heads/main'" in wf, \
        "workflow_dispatch on another branch must not build a release"
    assert "github.ref_type == 'branch'" in wf, \
        "a tag or other ref must not be treated as main"


def test_release_workflow_uses_protected_environment_and_serializes():
    wf = source(WORKFLOW)
    assert wf.count("environment: android-production") >= 2, \
        "both the signing build and the publisher need the protected environment"
    assert re.search(
        r"^concurrency:\s*\n\s+group:\s*android-production-release\s*\n"
        r"\s+cancel-in-progress:\s*false",
        wf, re.M,
    ), "publication must queue, never cancel or race another release run"


def test_release_workflow_scopes_release_write_to_the_publisher():
    wf = source(WORKFLOW)
    assert re.search(r"^permissions:\s*\n\s+contents:\s*read\s*$", wf, re.M), \
        "the default token must be read-only"
    assert not re.search(r"^permissions:\s*\n\s+contents:\s*write\s*$", wf, re.M), \
        "contents: write must not be a workflow-wide permission"
    jobs = wf.split("\njobs:", 1)[1]
    build = jobs.split("\n  publish:", 1)[0]
    publish = jobs.split("\n  publish:", 1)[1]
    assert re.search(r"^    permissions:\s*\n      contents:\s*read\s*$", build, re.M), \
        "the build job holds secrets and must stay read-only"
    assert re.search(r"^    permissions:\s*\n      contents:\s*write\s*$", publish, re.M), \
        "only the publisher may write releases"


def test_release_workflow_builds_tag_from_version_and_code():
    body = yaml_code(source(WORKFLOW))
    assert "VERSION_CODE" in body, "tag must include the Android version code"
    assert 'tag="android-${version}-${version_code}"' in body, \
        "tag must carry the android- prefix UpdateGate parses"
    assert 'asset="portfoliarr-${version}-${version_code}.apk"' in body, \
        "asset name must mirror the tag contract"
    assert "gh release create" in body, "workflow must create the release"
    assert '--target "$EXPECTED_SHA"' in body, \
        "the release tag must point at the exact commit this run built"


def test_release_workflow_validates_version_strictly():
    body = yaml_code(source(WORKFLOW))
    assert r"^[0-9]+\.[0-9]+(\.[0-9]+)?$" in body, \
        "VERSION must be a clean dotted number"
    assert r"^VERSION_CODE=([1-9][0-9]{0,9})$" in body, \
        "VERSION_CODE must be one positive integer with no leading zero"
    assert "2100000000" in body, \
        "VERSION_CODE must stay inside Android's maximum"
    assert "code_count" in body, \
        "duplicate or missing VERSION_CODE lines must fail closed"
    assert "positive integer" in body, \
        "the failure must explain why the version was rejected"


def test_release_workflow_rejects_lower_or_equal_codes():
    body = yaml_code(source(WORKFLOW))
    assert "max_code" in body, "the workflow must find the highest published code"
    assert '[ "$VERSION_CODE" -le "$max_code" ]' in body, \
        "a lower or equal VERSION_CODE must be rejected"
    assert "must be greater than published" in body, \
        "the failure must name the ordering rule"


def test_release_workflow_is_idempotent_and_fails_closed():
    body = yaml_code(source(WORKFLOW))
    assert "gh api --include" in body, \
        "the workflow must inspect the HTTP status instead of guessing"
    assert "unclear" in body, \
        "a response that is neither 200 nor 404 must fail the run"
    assert "gh release view" not in body, \
        "gh release view cannot tell a missing release from an API failure"
    assert "publish=false" in body and "publish=true" in body, \
        "the exact existing release must be an explicit no-op"
    assert '(.body | test("(?m)^SHA-256: [0-9a-fA-F]{64}$"))' in body, \
        "an existing release is exact only when it carries the SHA-256 note"
    assert "steps.state.outputs.publish == 'true'" in body, \
        "every build step must be guarded by the fail-closed decision"
    create = body.index("gh release create")
    assert body.index("releases/tags/${TAG}") < create, \
        "the release check must run before creating anything"
    assert body.index("git/ref/tags/${TAG}") < create, \
        "an orphan tag must be detected before creating anything"


def test_release_workflow_authenticates_gh():
    wf = source(WORKFLOW)
    assert wf.count("GH_TOKEN") >= 2, "both the build and publisher call gh"
    assert "secrets.GITHUB_TOKEN" in wf, \
        "gh needs a token in GitHub Actions or every call fails"
    assert not re.search(r"^env:\s*\n\s+GH_TOKEN:", wf, re.M), \
        "the token must not be exposed to every step in the workflow"


def test_release_workflow_publishes_a_final_release():
    body = yaml_code(source(WORKFLOW))
    assert "--draft" not in body, \
        "a draft release is invisible to releases/latest — the app would never see it"
    assert "--prerelease" not in body, \
        "a prerelease is never 'latest' — the app would never see it"


def test_release_workflow_builds_signed_release_without_caching_keys():
    body = yaml_code(source(WORKFLOW))
    assert "assembleRelease" in body, "the release must build the release variant"
    assert "assembleDebug" not in body, "a debug APK must never be published"
    assert "debug.keystore" not in body, "release signing must never use debug keys"
    for name in (
        "ANDROID_RELEASE_KEYSTORE_B64",
        "ANDROID_RELEASE_KEYSTORE_PATH",
        "ANDROID_RELEASE_STORE_PASSWORD",
        "ANDROID_RELEASE_KEY_ALIAS",
        "ANDROID_RELEASE_KEY_PASSWORD",
    ):
        assert name in body, f"the signing contract needs {name}"
    assert "base64 --decode" in body, "the keystore must be decoded at run time"
    assert body.index("android/release-cert.sha256") < body.index("base64 --decode"), \
        "certificate metadata must be checked before production secrets are used"
    assert "install -d -m 700" in body and "chmod 600" in body, \
        "the decoded keystore must live in a restricted directory"
    assert "--no-configuration-cache" in body, \
        "the configuration cache must stay off for signing state"
    assert "--no-build-cache" in body, "signed outputs must not come from a cache"
    assert "--no-daemon" in body, "no Gradle daemon may outlive the signing step"
    assert "cache-disabled: true" in body, \
        "the Gradle action must not cache signing inputs"
    assert "if: always()" in body, "cleanup must run after failure or cancellation"
    assert 'rm -rf "$RUNNER_TEMP/android-release-signing"' in body, \
        "the decoded keystore must be removed"


def test_release_workflow_keeps_signing_secrets_out_of_the_publisher():
    wf = source(WORKFLOW)
    publish = wf.split("\njobs:", 1)[1].split("\n  publish:", 1)[1]
    for name in (
        "ANDROID_RELEASE_KEYSTORE_B64",
        "ANDROID_RELEASE_KEYSTORE_PATH",
        "ANDROID_RELEASE_STORE_PASSWORD",
        "ANDROID_RELEASE_KEY_ALIAS",
        "ANDROID_RELEASE_KEY_PASSWORD",
    ):
        assert name not in publish, \
            f"the release-write job must not receive signing input {name}"


def test_release_workflow_verifies_signer_certificate_and_package():
    body = yaml_code(source(WORKFLOW))
    assert "apksigner" in body
    assert "verify --verbose --print-certs" in body, \
        "the APK signature and certificate must be inspected"
    assert "Number of signers:" in body, "the APK must have exactly one signer"
    assert "Signer #1 certificate SHA-256 digest:" in body
    assert "android/release-cert.sha256" in body, \
        "the expected owner-confirmed certificate lives in the repository"
    assert "git ls-files --error-unmatch" in body, \
        "a missing release certificate must fail closed"
    assert body.count(DEBUG_CERT_SHA256) == 2, \
        "pin the same exposed-debug digest everywhere it is checked"
    assert '[ "$signer_sha" = "$CERT_SHA256" ]' in body, \
        "the APK certificate must match the checked-in metadata"
    assert '[ "$signer_sha" != "$DEBUG_CERT_SHA256" ]' in body, \
        "the debug certificate must be rejected even if it matches the cert file"
    assert "application-debuggable" in body, "a debuggable APK must be rejected"
    assert "com.portfoliarr.app" in body, "the package name must be checked"
    assert "versionCode='${VERSION_CODE}' versionName='${VERSION}'" in body, \
        "the built APK must report the exact VERSION and VERSION_CODE"
    assert "aapt" in body, "package and version metadata must come from the APK"


def test_release_workflow_hashes_and_publishes_the_verified_file():
    body = yaml_code(source(WORKFLOW))
    assert "sha256sum" in body, "the workflow must hash the APK"
    assert "SHA-256:" in body, "the release notes must carry the SHA-256: line"
    assert "actions/upload-artifact@v4" in body
    assert "actions/download-artifact@v4" in body
    assert "path: release-dist" in body, \
        "only the verified release files may enter the artifact"
    assert "if-no-files-found: error" in body, \
        "a missing artifact must fail instead of publishing nothing"
    assert 'verified_sha="$(sha256sum "$apk"' in body, \
        "the APK that was verified must be the one hashed"
    assert 'publish_sha="$(sha256sum "$dist/$ASSET"' in body, \
        "the published copy must be hashed again"
    assert '[ "$verified_sha" = "$publish_sha" ]' in body, \
        "the published file must be byte-identical to the verified file"
    assert '[ "$actual_sha" = "$EXPECTED_SHA256" ]' in body, \
        "the publisher must re-check the verified hash"


def test_release_workflow_validates_the_exact_commit_and_ref():
    wf = source(WORKFLOW)
    assert "ref: ${{ github.sha }}" in wf, \
        "the build must check out the dispatch commit, not a moving ref"
    assert "persist-credentials: false" in wf, \
        "the build token must not be stored in git config"
    body = yaml_code(wf)
    assert '[ "$BUILD_SHA" = "$EXPECTED_SHA" ]' in body, \
        "the publisher must publish the commit the builder verified"
    assert '--repo "$REPO"' in body, \
        "the publisher has no checkout, so gh must be told which repository"
    assert '--target "$EXPECTED_SHA"' in body, \
        "the tag must be created at the verified commit"


def test_release_workflow_never_interpolates_expressions_into_shell():
    blocks = run_blocks(source(WORKFLOW))
    assert blocks, "expected shell run blocks in the release workflow"
    for block in blocks:
        assert "${{" not in block, \
            "put Actions expressions in env: and read environment variables in shell"


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
