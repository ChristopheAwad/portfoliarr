"""Contracts for the optional phone-local Android lock."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent / "android" / "app" / "src" / "main"
JAVA = ROOT / "java" / "com" / "portfoliarr" / "app"


def source(name):
    return (JAVA / name).read_text()


def test_both_activities_share_native_lock_gate():
    assert "AppLockActivity" in source("MainActivity.kt")
    assert "AppLockActivity" in source("SettingsActivity.kt")
    gate = source("AppLockActivity.kt")
    assert "BiometricPrompt" in gate
    assert "cover" in gate.lower()
    assert "onPause" in gate


def test_android_supports_device_credentials_and_biometrics():
    catalog = (ROOT.parents[2] / "gradle" / "libs.versions.toml").read_text()
    build = (ROOT.parents[1] / "build.gradle.kts").read_text()
    manifest = (ROOT / "AndroidManifest.xml").read_text()
    gate = source("AppLockActivity.kt")
    assert "androidx.biometric" in catalog
    assert "lifecycle-process" in catalog
    assert "libs.androidx.biometric" in build
    assert "USE_BIOMETRIC" in manifest
    assert "BIOMETRIC_STRONG" in gate and "DEVICE_CREDENTIAL" in gate


def test_settings_expose_local_lock_and_five_minute_default():
    settings = source("SettingsActivity.kt")
    layout = (ROOT / "res" / "layout" / "activity_settings.xml").read_text()
    strings = (ROOT / "res" / "values" / "strings.xml").read_text()
    policy = source("AppLockPolicy.kt")
    assert "app_lock_enabled" in settings
    assert "app_lock_timeout_ms" in settings
    assert "300_000" in policy
    assert "lockEnabled" in layout and "lockTimeout" in layout and "testLock" in layout
    for text in ("Immediately", "1 minute", "5 minutes", "15 minutes"):
        assert text in strings
    assert "server_url" not in policy


def test_renderer_rebuild_and_unlock_keep_lock_cover():
    main = source("MainActivity.kt")
    gate = source("AppLockActivity.kt")
    assert "onRenderProcessGone" in main
    assert "ensureLockCover" in main
    assert "webView.destroy()" not in gate
    assert "webView.loadUrl" not in gate


def test_android_ci_runs_lock_policy_tests_before_uploading_apk():
    workflow = (ROOT.parents[3] / ".github" / "workflows" / "build-android.yml").read_text()
    assert "./gradlew testDebugUnitTest assembleDebug" in workflow
