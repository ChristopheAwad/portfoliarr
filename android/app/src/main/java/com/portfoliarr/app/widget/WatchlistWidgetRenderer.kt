package com.portfoliarr.app.widget

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.view.View
import android.widget.RemoteViews
import androidx.core.content.ContextCompat
import com.portfoliarr.app.MainActivity
import com.portfoliarr.app.R
import com.portfoliarr.app.StartGate
import org.json.JSONObject

/**
 * Paints the watchlist widget's main RemoteViews (#59).
 *
 * The scrollable rows are NOT painted here — they come from
 * WatchlistWidgetFactory/Service reading the cached payload. This renderer
 * owns the chrome: title, "as of" line, the refresh tap, the empty/blocked
 * message, and turning the collection on with setRemoteAdapter.
 *
 * Every state degrades honestly: "no server", "tap to connect", and a
 * "couldn't refresh" message. A failed refresh keeps the last good list and
 * tints the timestamp as stale.
 */
object WatchlistWidgetRenderer {

    fun render(context: Context, appWidgetId: Int) {
        val store = WidgetStore(context)
        val serverUrl = context
            .getSharedPreferences("portfoliarr", Context.MODE_PRIVATE)
            .getString("server_url", null)
        val hasServer = !serverUrl.isNullOrBlank() &&
            MainActivity.isAllowedUrl(serverUrl)
        val origin = if (serverUrl.isNullOrBlank()) "" else {
            StartGate.normalizeOrigin(serverUrl)
        }
        val hasToken = hasServer && store.origin(appWidgetId) == origin &&
            !store.token(appWidgetId).isNullOrEmpty()
        val payloadJson = store.payload(appWidgetId)
        val status = WidgetFormat.status(hasServer, hasToken, payloadJson != null)

        val views = RemoteViews(
            context.packageName, R.layout.widget_watchlist)
        views.setTextViewText(
            R.id.widget_watchlist_title,
            context.getString(R.string.widget_watchlist_title))

        when (status) {
            WidgetStatus.NO_SERVER -> showMessage(
                context, views, context.getString(R.string.widget_no_server))
            WidgetStatus.NO_TOKEN -> showMessage(
                context, views, context.getString(R.string.widget_no_token))
            WidgetStatus.NO_DATA -> showMessage(context, views, "—")
            WidgetStatus.READY -> try {
                showData(context, views, store, appWidgetId, payloadJson!!)
            } catch (e: Exception) {
                // A cached payload that cannot be parsed is treated like a
                // failed refresh: tell the truth, never crash the launcher.
                showMessage(context, views,
                    context.getString(R.string.widget_error))
            }
        }

        views.setInt(
            R.id.widget_watchlist_refresh, "setColorFilter",
            ContextCompat.getColor(context, R.color.widget_text_muted))
        views.setOnClickPendingIntent(
            R.id.widget_watchlist_refresh, refreshPending(context, appWidgetId))
        views.setOnClickPendingIntent(
            R.id.widget_watchlist_root,
            if (status == WidgetStatus.NO_TOKEN)
                configPending(context, appWidgetId)
            else openAppPending(context),
        )

        AppWidgetManager.getInstance(context)
            .updateAppWidget(appWidgetId, views)
    }

    private fun showMessage(
        context: Context,
        views: RemoteViews,
        message: String,
    ) {
        views.setTextViewText(
            R.id.widget_watchlist_empty, message)
        views.setViewVisibility(R.id.widget_watchlist_empty, View.VISIBLE)
        views.setViewVisibility(R.id.widget_watchlist_list, View.GONE)
        views.setViewVisibility(R.id.widget_watchlist_asof, View.GONE)
    }

    private fun showData(
        context: Context,
        views: RemoteViews,
        store: WidgetStore,
        appWidgetId: Int,
        payloadJson: String,
    ) {
        val json = JSONObject(payloadJson)
        val symbols = json.optJSONArray("symbols")
        if (symbols == null || symbols.length() == 0) {
            showMessage(context, views,
                context.getString(R.string.widget_watchlist_empty))
            return
        }

        views.setViewVisibility(R.id.widget_watchlist_empty, View.GONE)
        views.setViewVisibility(R.id.widget_watchlist_list, View.VISIBLE)
        // A unique data URI per widget: without it, two watchlist widgets
        // can be treated as the same collection and share one factory,
        // showing the first widget's appWidgetId (and data).
        val adapterIntent = Intent(
            context, WatchlistWidgetService::class.java)
            .putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, appWidgetId)
        adapterIntent.data = Uri.parse(
            "portfoliarr://watchlist-widget/$appWidgetId")
        views.setRemoteAdapter(R.id.widget_watchlist_list, adapterIntent)

        views.setViewVisibility(R.id.widget_watchlist_asof, View.VISIBLE)
        views.setTextViewText(
            R.id.widget_watchlist_asof,
            context.getString(
                R.string.widget_asof,
                WidgetFormat.formatAsOf(store.fetchedAt(appWidgetId))))
        // A failed refresh keeps the last good list and tints the timestamp
        // instead of blanking data the user already saw.
        views.setTextColor(
            R.id.widget_watchlist_asof,
            ContextCompat.getColor(
                context,
                if (store.attemptFailed(appWidgetId)) R.color.widget_stale
                else R.color.widget_text_muted))
    }

    private fun refreshPending(context: Context, appWidgetId: Int): PendingIntent {
        val intent = Intent(context, WatchlistWidgetProvider::class.java).apply {
            action = WatchlistWidgetProvider.ACTION_REFRESH
        }
        return PendingIntent.getBroadcast(
            context, appWidgetId, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }

    private fun configPending(context: Context, appWidgetId: Int): PendingIntent {
        val intent = Intent(context, WatchlistWidgetConfigActivity::class.java).apply {
            putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, appWidgetId)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        return PendingIntent.getActivity(
            context, appWidgetId, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }

    private fun openAppPending(context: Context): PendingIntent {
        val intent = Intent(context, MainActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        return PendingIntent.getActivity(
            context, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }
}
