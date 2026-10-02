package com.portfoliarr.app.widget

import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Context
import androidx.work.Worker
import androidx.work.WorkerParameters
import com.portfoliarr.app.MainActivity
import com.portfoliarr.app.R
import com.portfoliarr.app.StartGate
import java.io.IOException

/**
 * One refresh pass for every configured watchlist widget (#59).
 *
 * Reads the stored server URL and each widget's scoped token from app-private
 * preferences; never touches the WebView session. Widgets sharing a token
 * share one fetch. A 401 means the token was revoked (or its owner deleted):
 * the config is cleared so the widget shows its connect state instead of
 * retrying a dead credential forever. Any other failure keeps the cached
 * numbers and asks WorkManager to retry. After a successful save the list
 * adapter is told the data changed.
 */
class WatchlistWidgetWorker(
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
            ComponentName(context, WatchlistWidgetProvider::class.java))
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
                val payload = WidgetApi.fetchWatchlist(serverUrl, token)
                val fetchedAt = System.currentTimeMillis()
                for (appWidgetId in ids) {
                    store.savePayload(appWidgetId, payload, fetchedAt)
                    store.saveAttemptFailed(appWidgetId, false)
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
            WatchlistWidgetRenderer.render(context, appWidgetId)
        }
        // The ListView items come from WatchlistWidgetFactory reading the
        // cached payload; re-rendering the main RemoteViews is not enough.
        manager.notifyAppWidgetViewDataChanged(
            widgetIds, R.id.widget_watchlist_list)
        return if (retry) Result.retry() else Result.success()
    }
}
