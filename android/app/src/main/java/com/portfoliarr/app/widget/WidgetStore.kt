package com.portfoliarr.app.widget

import android.content.Context
import android.content.SharedPreferences

/**
 * Per-widget configuration and cache (#51).
 *
 * The Android launcher can host several widget instances, each bound to its
 * own portfolio, so every value is keyed by appWidgetId. The token is a
 * scoped, revocable, read-only credential — not the session — and it must be
 * readable by a background worker with no prompt, so it lives in this
 * app-private preferences file (the OS sandbox is the at-rest protection;
 * encrypting it under the biometric keystore would make the widget unable to
 * refresh while the phone is locked).
 *
 * The cached payload is what lets a widget paint instantly on add/resize/
 * reboot, before the network answers; fetchedAt feeds the "as of" line and
 * attemptFailed tints it when the last refresh did not succeed.
 */
class WidgetStore(context: Context) {

    private val prefs: SharedPreferences =
        context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun saveConfig(
        appWidgetId: Int,
        token: String,
        tokenId: Int,
        portfolioName: String,
        origin: String,
    ) {
        prefs.edit()
            .putString(key("token", appWidgetId), token)
            .putInt(key("token_id", appWidgetId), tokenId)
            .putString(key("name", appWidgetId), portfolioName)
            .putString(key("origin", appWidgetId), origin)
            // A reconfigured widget may now point at a different portfolio;
            // the previous portfolio's cached numbers must never be painted
            // under the new name (even tinted stale).
            .remove(key("payload", appWidgetId))
            .remove(key("fetched_at", appWidgetId))
            .remove(key("failed", appWidgetId))
            .apply()
    }

    fun token(appWidgetId: Int): String? = prefs.getString(key("token", appWidgetId), null)

    fun tokenId(appWidgetId: Int): Int = prefs.getInt(key("token_id", appWidgetId), -1)

    fun portfolioName(appWidgetId: Int): String? =
        prefs.getString(key("name", appWidgetId), null)

    /** The server origin this widget's token was issued for. A repointed
     * server therefore cannot be fetched with a stale token. */
    fun origin(appWidgetId: Int): String? =
        prefs.getString(key("origin", appWidgetId), null)

    fun savePayload(appWidgetId: Int, payloadJson: String, fetchedAtMillis: Long) {
        prefs.edit()
            .putString(key("payload", appWidgetId), payloadJson)
            .putLong(key("fetched_at", appWidgetId), fetchedAtMillis)
            .apply()
    }

    fun payload(appWidgetId: Int): String? =
        prefs.getString(key("payload", appWidgetId), null)

    fun fetchedAt(appWidgetId: Int): Long =
        prefs.getLong(key("fetched_at", appWidgetId), 0L)

    fun saveAttemptFailed(appWidgetId: Int, failed: Boolean) {
        prefs.edit().putBoolean(key("failed", appWidgetId), failed).apply()
    }

    fun attemptFailed(appWidgetId: Int): Boolean =
        prefs.getBoolean(key("failed", appWidgetId), false)

    /** Drop every key for one widget when it is removed from the home screen. */
    fun remove(appWidgetId: Int) {
        val editor = prefs.edit()
        for (name in KEYS) {
            editor.remove(key(name, appWidgetId))
        }
        editor.apply()
    }

    private fun key(name: String, appWidgetId: Int) = "${name}_$appWidgetId"

    companion object {
        const val PREFS_NAME = "portfoliarr_widget"
        private val KEYS = listOf(
            "token", "token_id", "name", "origin", "payload", "fetched_at", "failed",
        )
    }
}
