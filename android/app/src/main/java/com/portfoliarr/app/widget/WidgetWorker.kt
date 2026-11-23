package com.portfoliarr.app.widget

import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Context
import androidx.work.Worker
import androidx.work.WorkerParameters
import com.portfoliarr.app.MainActivity
import com.portfoliarr.app.StartGate
import java.io.IOException

/**
 * One refresh pass for every configured widget (#51).
 *
 * Reads the stored server URL and each widget's scoped token from
 * app-private preferences; never touches the WebView session. Widgets that
 * share a portfolio share one fetch. A 401 means the token was revoked (or
 * its portfolio/user deleted): the config is cleared so the widget shows
 * its connect state instead of retrying a dead credential forever. A 200
 * whose body fails the completeness contract (an unpriced ticker, a failed
 * quote or FX rate) is NOT saved as fresh data: the attempt is marked failed
 * so the last good snapshot stays tinted stale, and it is not retried, since
 * another immediate request would fail the same way. Any other failure keeps
 * the cached numbers and asks WorkManager to retry.
 */
class WidgetWorker(
    appContext: Context,
    params: WorkerParameters,
) : Worker(appContext, params) {

    override fun doWork(): Result {
        val context = applicationContext
        val serverUrl = context
            .getSharedPreferences("portfoliarr", Context.MODE_PRIVATE)
            .getString("server_url", null)
        if (serverUrl.isNullOrBlank() || !MainActivity.isAllowedUrl(serverUrl)) {
            return Result.success()
        }
        val origin = StartGate.normalizeOrigin(serverUrl)

        val manager = AppWidgetManager.getInstance(context)
        val widgetIds = manager.getAppWidgetIds(
            ComponentName(context, PortfolioWidgetProvider::class.java))
        val store = WidgetStore(context)

        val idsByToken = LinkedHashMap<String, MutableList<Int>>()
        for (appWidgetId in widgetIds) {
            val token = store.token(appWidgetId) ?: continue
            if (store.origin(appWidgetId) != origin) continue
            idsByToken.getOrPut(token) { mutableListOf() }.add(appWidgetId)
        }

        var retry = false
        for ((token, ids) in idsByToken) {
            try {
                val payload = WidgetApi.fetchSummary(serverUrl, token)
                if (WidgetSummary.readPayload(payload) != null) {
                    val fetchedAt = System.currentTimeMillis()
                    for (appWidgetId in ids) {
                        store.savePayload(appWidgetId, payload, fetchedAt)
                        store.saveAttemptFailed(appWidgetId, false)
                    }
                } else {
                    // A 200 is not proof of a complete valuation. Keep the
                    // last good snapshot and timestamp untouched.
                    for (appWidgetId in ids) {
                        store.saveAttemptFailed(appWidgetId, true)
                    }
                }
            } catch (e: WidgetApi.UnauthorizedException) {
                for (appWidgetId in ids) {
                    store.remove(appWidgetId)
                }
            } catch (e: IOException) {
                for (appWidgetId in ids) {
                    store.saveAttemptFailed(appWidgetId, true)
                }
                retry = true
            } catch (e: WidgetApi.ApiException) {
                for (appWidgetId in ids) {
                    store.saveAttemptFailed(appWidgetId, true)
                }
            }
        }

        for (appWidgetId in widgetIds) {
            WidgetRenderer.render(context, appWidgetId)
        }
        return if (retry) Result.retry() else Result.success()
    }
}
