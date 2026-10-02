# tests/test_android_widget.py
# =============================
# Contract pins for the Android home-screen widget (roadmap #51).
#
# pytest cannot compile Kotlin, so these are source/meta-tests in the same
# spirit as test_android_update.py and test_android_biometric.py: they lock
# the pieces of the Kotlin/Gradle/manifest/resource wiring that the feature
# depends on. Runtime behaviour is the on-device GUI gate's job; the pure
# formatting helper additionally has real JVM tests in CI (WidgetFormatTest).
#
# What genuinely matters here, and why each pin exists:
#   * the widget's read path must present ONLY the scoped bearer token —
#     if it ever reached for the session cookie, one home-screen gadget
#     would hold the whole account;
#   * the bearer route is /api/widget/summary and nothing else;
#   * the connect screen is the only place the saved session may appear,
#     it must return the appWidgetId the launcher gave it, and it must
#     never log the session or the token;
#   * WorkManager (2.9.1, the last compileSdk-34 release) drives refresh,
#     and the widget declares both sizes;
#   * no new network library sneaks in: HttpURLConnection + org.json.
#
# `code()` strips comments before ABSENCE assertions: the comment
# explaining why a forbidden construct is not used must not satisfy the
# check that it is absent.

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KOTLIN = "android/app/src/main/java/com/portfoliarr/app"
WIDGET = f"{KOTLIN}/widget"
TEST_SRC = "android/app/src/test/java/com/portfoliarr/app"
MANIFEST = "android/app/src/main/AndroidManifest.xml"
RES = "android/app/src/main/res"
TOML = "android/gradle/libs.versions.toml"
GRADLE = "android/app/build.gradle.kts"

WIDGET_REFRESH_ACTION = "com.portfoliarr.app.widget.action.REFRESH"


def source(path):
    return (ROOT / path).read_text()


def code(path):
    text = source(path)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
    return text


# ── Gradle: exact WorkManager pin, no other library ──────────────────────

def test_work_dependency_is_pinned_exactly():
    toml = source(TOML)
    assert re.search(r'^work\s*=\s*"2\.9\.1"$', toml, re.MULTILINE), \
        "WorkManager must be pinned to 2.9.1 (the compileSdk 34 release)"
    assert re.search(
        r'^androidx-work-runtime\s*=\s*\{[^}]*name\s*=\s*"work-runtime"',
        toml, re.MULTILINE,
    ), "libs.versions.toml declares the version but never the library alias"
    assert "implementation(libs.androidx.work.runtime)" in source(GRADLE)


# ── Provider metadata: two sizes, WorkManager refresh ────────────────────

def test_widget_info_has_both_sizes():
    xml = source(f"{RES}/xml/widget_info.xml")
    for attr in (
        'android:minWidth="110dp"',
        'android:minHeight="40dp"',
        'android:minResizeWidth="110dp"',
        'android:minResizeHeight="40dp"',
        'android:targetCellWidth="2"',
        'android:targetCellHeight="1"',
        'android:resizeMode="horizontal"',
        'android:updatePeriodMillis="0"',
        'android:configure="com.portfoliarr.app.widget.WidgetConfigActivity"',
        'android:initialLayout="@layout/widget_small"',
    ):
        assert attr in xml, f"widget_info.xml is missing {attr}"


# ── Manifest: provider (private) + connect screen (exported) ─────────────

def test_manifest_declares_provider_and_config():
    manifest = source(MANIFEST)
    assert ".widget.PortfolioWidgetProvider" in manifest
    assert "android.appwidget.action.APPWIDGET_UPDATE" in manifest
    assert WIDGET_REFRESH_ACTION in manifest, \
        "the refresh tap broadcasts a custom action the provider must declare"
    assert "android.appwidget.provider" in manifest
    assert "@xml/widget_info" in manifest
    assert ".widget.WidgetConfigActivity" in manifest
    assert "android.appwidget.action.APPWIDGET_CONFIGURE" in manifest
    # The provider is private; the launcher-launched config screen must be
    # exported or the widget cannot be configured at all.
    provider_block = manifest[manifest.index("PortfolioWidgetProvider"):]
    provider_block = provider_block[:provider_block.index("</receiver>")]
    assert 'android:exported="false"' in provider_block
    config_block = manifest[manifest.index("WidgetConfigActivity"):]
    config_block = config_block[:config_block.index("</activity>")]
    assert 'android:exported="true"' in config_block


# ── Layouts: the ids each size owns ──────────────────────────────────────

def test_layouts_have_required_ids():
    small = source(f"{RES}/layout/widget_small.xml")
    for view_id in ("widget_root", "widget_value", "widget_asof", "widget_day"):
        assert f'@+id/{view_id}' in small, f"widget_small.xml lacks {view_id}"
    assert "widget_total" not in small, \
        "the small 2x1 layout has no room for the total-return column"

    wide = source(f"{RES}/layout/widget_wide.xml")
    for view_id in ("widget_root", "widget_name", "widget_asof",
                    "widget_value", "widget_day", "widget_total"):
        assert f'@+id/{view_id}' in wide, f"widget_wide.xml lacks {view_id}"


# ── Provider: scheduling and the refresh tap ─────────────────────────────

def test_provider_schedules_periodic_work():
    provider = code(f"{WIDGET}/PortfolioWidgetProvider.kt")
    assert "PeriodicWorkRequest" in provider
    assert "enqueueUniquePeriodicWork" in provider
    assert "30" in provider and "MINUTES" in provider, \
        "the roadmap fixes the refresh at about 30 minutes"
    assert "ExistingPeriodicWorkPolicy.KEEP" in provider
    assert "onDisabled" in provider and "cancelUniqueWork" in provider


def test_provider_handles_refresh_action():
    provider = code(f"{WIDGET}/PortfolioWidgetProvider.kt")
    assert WIDGET_REFRESH_ACTION in provider
    assert "OneTimeWorkRequest" in provider
    assert "ExistingWorkPolicy.REPLACE" in provider


# ── The read path: bearer only, never the session cookie ─────────────────

def test_worker_uses_bearer_and_never_the_cookie():
    api = code(f"{WIDGET}/WidgetApi.kt")
    assert "/api/widget/summary" in api
    assert '"Bearer ' in api
    worker_files = (code(f"{WIDGET}/WidgetWorker.kt")
                    + code(f"{WIDGET}/PortfolioWidgetProvider.kt")
                    + code(f"{WIDGET}/WidgetRenderer.kt"))
    for forbidden in ("CookieManager", "SecretStore", '"Cookie"', "LocalStorage"):
        assert forbidden not in worker_files, \
            f"the widget read path must not touch {forbidden}"


def test_widget_api_has_bounded_timeouts():
    assert "15_000" in code(f"{WIDGET}/WidgetApi.kt"), \
        "connect and read timeouts must be bounded"


# ── Connect screen: saved session, correct result hand-off, no logging ───

def test_config_uses_saved_session():
    config = code(f"{WIDGET}/WidgetConfigActivity.kt")
    assert "SecretStore" in config
    assert "CookieHeader" in config
    assert "SESSION_COOKIE_NAME" in config
    endpoints = config + code(f"{WIDGET}/WidgetApi.kt")
    assert "/api/portfolios" in endpoints
    assert "/api/widget/tokens" in endpoints


def test_config_sets_result_canceled_then_ok():
    config = code(f"{WIDGET}/WidgetConfigActivity.kt")
    assert "RESULT_CANCELED" in config, \
        "backing out must cancel the widget placement"
    cancel_pos = config.index("RESULT_CANCELED")
    ok_pos = config.index("RESULT_OK", cancel_pos + 1)
    assert 0 <= cancel_pos < ok_pos, \
        "RESULT_CANCELED must be set before any success path"
    assert "EXTRA_APPWIDGET_ID" in config, \
        "the success result must carry the launcher's appWidgetId"


def test_no_secret_logging_in_widget_code():
    for path in (ROOT / WIDGET).glob("*.kt"):
        assert "Log." not in path.read_text(), \
            f"{path.name} logs; the widget code must never log credentials"


# ── Purity and the JVM suite ─────────────────────────────────────────────

def test_widget_format_is_pure():
    fmt = code(f"{WIDGET}/WidgetFormat.kt")
    assert "android." not in fmt, "WidgetFormat must carry no android.* imports"
    assert "androidx." not in fmt, "WidgetFormat must carry no androidx.* imports"


def test_jvm_widget_suite_exists():
    suite_path = f"{TEST_SRC}/WidgetFormatTest.kt"
    suite = source(suite_path)
    assert "package com.portfoliarr.app" in suite
    assert "android." not in code(suite_path), "the suite must run on a plain JVM"
    for name in ("isWide", "formatMoney", "formatSignedMoney", "changeText",
                 "isUp", "status"):
        assert name in suite, f"the JVM suite must cover {name}"


# ── Store cleanup and 401 fail-closed ────────────────────────────────────

def test_store_removes_per_widget_keys():
    provider = source(f"{WIDGET}/PortfolioWidgetProvider.kt")
    assert "onDeleted" in provider and "remove(" in provider, \
        "removing a widget must delete its stored config"
    assert "portfoliarr_widget" in source(f"{WIDGET}/WidgetStore.kt"), \
        "widget config lives in its own app-private prefs file"


def test_worker_clears_config_on_unauthorized():
    worker = code(f"{WIDGET}/WidgetWorker.kt")
    assert "UnauthorizedException" in worker, \
        "a revoked token is a 401 and must not be retried forever"
    assert "remove(" in worker, \
        "a revoked token's config is cleared so the widget shows connect"


# ── Strings: every referenced widget string exists, ASCII only ───────────

def test_widget_strings_exist_and_are_ascii():
    strings = source(f"{RES}/values/strings.xml")
    used = set()
    for path in (ROOT / WIDGET).glob("*.kt"):
        used.update(re.findall(r"R\.string\.(widget_\w+)", path.read_text()))
    assert used, "no widget strings are referenced at all"
    for name in sorted(used):
        assert f'name="{name}"' in strings, f"strings.xml is missing {name}"
    for line in strings.splitlines():
        if 'name="widget_' in line:
            line.encode("ascii")  # raises on non-ASCII widget text


# ── Origin binding: a repointed server must not replay an old token ──────

def test_widget_read_path_is_origin_bound():
    combined = code(f"{WIDGET}/WidgetWorker.kt") + code(f"{WIDGET}/WidgetRenderer.kt")
    assert "normalizeOrigin" in combined, \
        "the server URL must be normalized before comparing origins"
    assert ".origin(" in combined, \
        "the stored token's origin must be compared before fetching or painting"
