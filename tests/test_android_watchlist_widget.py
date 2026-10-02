# tests/test_android_watchlist_widget.py
# =======================================
# Contract pins for the Android watchlist widget (roadmap #59).
#
# pytest cannot compile Kotlin, so these are source/meta-tests in the same
# spirit as test_android_widget.py: they lock the pieces of the
# Kotlin/manifest/resource wiring the feature depends on. Runtime behaviour
# is the on-device GUI gate's job; the pure formatter has real JVM tests in
# CI (WatchlistFormatTest).
#
# What matters here, and why:
#   * the read path presents ONLY the scoped bearer token — never the
#     session cookie or the secret store;
#   * the bearer route is /api/widget/watchlist and nothing else;
#   * the connect screen is the only place the saved session appears, it
#     mints a watchlist-scoped token, returns the launcher's appWidgetId,
#     and never logs the session or the token;
#   * the widget is a RemoteViews collection (ListView), so its service is
#     declared and private and the provider notifies view-data changes;
#   * WorkManager drives refresh, exactly as #51.

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KOTLIN = "android/app/src/main/java/com/portfoliarr/app"
WIDGET = f"{KOTLIN}/widget"
TEST_SRC = "android/app/src/test/java/com/portfoliarr/app"
MANIFEST = "android/app/src/main/AndroidManifest.xml"
RES = "android/app/src/main/res"

WATCHLIST_REFRESH_ACTION = (
    "com.portfoliarr.app.widget.action.WATCHLIST_REFRESH")
WATCHLIST_LIST_REF = "R.id.widget_watchlist_list"


def source(path):
    return (ROOT / path).read_text()


def code(path):
    text = source(path)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
    return text


# ── Manifest: provider (private), service (private), config (exported) ───

def test_watchlist_provider_declared_in_manifest():
    manifest = source(MANIFEST)
    assert ".widget.WatchlistWidgetProvider" in manifest
    assert "android.appwidget.action.APPWIDGET_UPDATE" in manifest
    assert WATCHLIST_REFRESH_ACTION in manifest
    assert "@xml/widget_watchlist_info" in manifest
    block = manifest[manifest.index("WatchlistWidgetProvider"):]
    block = block[:block.index("</receiver>")]
    assert 'android:exported="false"' in block


def test_watchlist_service_declared_and_private():
    manifest = source(MANIFEST)
    assert ".widget.WatchlistWidgetService" in manifest
    assert "android.permission.BIND_REMOTEVIEWS" in manifest
    block = manifest[manifest.index(".widget.WatchlistWidgetService"):]
    block = block[:block.index("/>")]
    assert 'android:exported="false"' in block


def test_watchlist_config_activity_exported():
    manifest = source(MANIFEST)
    assert ".widget.WatchlistWidgetConfigActivity" in manifest
    assert "android.appwidget.action.APPWIDGET_CONFIGURE" in manifest
    block = manifest[manifest.index("WatchlistWidgetConfigActivity"):]
    block = block[:block.index("</activity>")]
    assert 'android:exported="true"' in block


# ── Provider metadata ────────────────────────────────────────────────────

def test_watchlist_info_metadata():
    xml = source(f"{RES}/xml/widget_watchlist_info.xml")
    for attr in (
        'android:minWidth=',
        'android:minHeight=',
        'android:targetCellWidth=',
        'android:targetCellHeight=',
        'android:updatePeriodMillis="0"',
        'android:configure="com.portfoliarr.app.widget.WatchlistWidgetConfigActivity"',
        'android:initialLayout="@layout/widget_watchlist"',
    ):
        assert attr in xml, f"widget_watchlist_info.xml is missing {attr}"
    assert "vertical" in xml, "the watchlist widget must resize vertically"


# ── Layouts ──────────────────────────────────────────────────────────────

def test_watchlist_main_layout_ids():
    layout = source(f"{RES}/layout/widget_watchlist.xml")
    assert "<ListView" in layout
    for view_id in ("widget_watchlist_root", "widget_watchlist_title",
                    "widget_watchlist_asof", "widget_watchlist_refresh",
                    "widget_watchlist_empty", "widget_watchlist_list"):
        assert f"@+id/{view_id}" in layout, f"widget_watchlist.xml lacks {view_id}"


def test_watchlist_item_layout_ids():
    item = source(f"{RES}/layout/widget_watchlist_item.xml")
    for view_id in ("watchlist_item_symbol", "watchlist_item_price",
                    "watchlist_item_change"):
        assert f"@+id/{view_id}" in item, f"widget_watchlist_item.xml lacks {view_id}"


# ── Provider: scheduling, refresh tap, view-data notification ────────────

def test_provider_schedules_and_notifies():
    provider = code(f"{WIDGET}/WatchlistWidgetProvider.kt")
    assert "PeriodicWorkRequest" in provider
    assert "enqueueUniquePeriodicWork" in provider
    assert "30" in provider and "MINUTES" in provider
    assert "ExistingPeriodicWorkPolicy.KEEP" in provider
    assert "onDisabled" in provider and "cancelUniqueWork" in provider
    assert "OneTimeWorkRequest" in provider
    assert "ExistingWorkPolicy.REPLACE" in provider
    assert WATCHLIST_REFRESH_ACTION in provider
    assert "notifyAppWidgetViewDataChanged" in provider
    assert WATCHLIST_LIST_REF in provider


# ── The read path: bearer watchlist only, never the session cookie ───────

def test_worker_uses_bearer_watchlist_and_never_cookie():
    api = code(f"{WIDGET}/WidgetApi.kt")
    assert "/api/widget/watchlist" in api
    assert '"Bearer ' in api
    worker = code(f"{WIDGET}/WatchlistWidgetWorker.kt")
    assert "fetchWatchlist" in worker
    read_path = (
        worker
        + code(f"{WIDGET}/WatchlistWidgetProvider.kt")
        + code(f"{WIDGET}/WatchlistWidgetRenderer.kt")
        + code(f"{WIDGET}/WatchlistWidgetFactory.kt")
        + code(f"{WIDGET}/WatchlistWidgetService.kt")
    )
    for forbidden in ("CookieManager", "SecretStore", '"Cookie"', "LocalStorage"):
        assert forbidden not in read_path, \
            f"the widget read path must not touch {forbidden}"


def test_worker_clears_config_on_unauthorized():
    worker = code(f"{WIDGET}/WatchlistWidgetWorker.kt")
    assert "UnauthorizedException" in worker
    assert "remove(" in worker


def test_factory_reads_only_cache():
    factory = code(f"{WIDGET}/WatchlistWidgetFactory.kt")
    assert "WidgetStore" in factory
    assert "payload" in factory
    for forbidden in ("HttpURLConnection", "fetch(", "CookieManager",
                      "SecretStore"):
        assert forbidden not in factory, \
            f"the factory must paint from cache only; found {forbidden}"


# ── Connect screen: saved session, watchlist scope, result hand-off ──────

def test_config_uses_saved_session_and_watchlist_scope():
    config = code(f"{WIDGET}/WatchlistWidgetConfigActivity.kt")
    assert "SecretStore" in config
    assert "CookieHeader" in config
    assert "SESSION_COOKIE_NAME" in config
    assert "createWatchlistToken" in config


def test_config_sets_result_canceled_then_ok():
    config = code(f"{WIDGET}/WatchlistWidgetConfigActivity.kt")
    assert "RESULT_CANCELED" in config
    cancel_pos = config.index("RESULT_CANCELED")
    ok_pos = config.index("RESULT_OK", cancel_pos + 1)
    assert 0 <= cancel_pos < ok_pos
    assert "EXTRA_APPWIDGET_ID" in config


# ── Purity, JVM suite, logging, strings ──────────────────────────────────

def test_watchlist_format_is_pure():
    fmt = code(f"{WIDGET}/WatchlistFormat.kt")
    assert "android." not in fmt
    assert "androidx." not in fmt


def test_jvm_watchlist_suite_exists():
    suite_path = f"{TEST_SRC}/WatchlistFormatTest.kt"
    suite = source(suite_path)
    assert "package com.portfoliarr.app" in suite
    assert "android." not in code(suite_path)
    for name in ("priceText", "changePercentText", "isUp"):
        assert name in suite, f"the JVM suite must cover {name}"


def test_no_secret_logging_in_watchlist_code():
    for path in (ROOT / WIDGET).glob("Watchlist*.kt"):
        assert "Log." not in path.read_text(), \
            f"{path.name} logs; the widget code must never log credentials"


def test_watchlist_strings_exist_and_are_ascii():
    strings = source(f"{RES}/values/strings.xml")
    used = set()
    for path in (ROOT / WIDGET).glob("Watchlist*.kt"):
        used.update(re.findall(r"R\.string\.(widget_\w+)", path.read_text()))
    assert used, "no widget strings are referenced by the watchlist code"
    for name in sorted(used):
        assert f'name="{name}"' in strings, f"strings.xml is missing {name}"
    for line in strings.splitlines():
        if 'name="widget_watchlist' in line:
            line.encode("ascii")
