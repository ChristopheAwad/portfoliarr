package com.portfoliarr.app.widget

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.content.Context
import android.content.Intent
import android.util.TypedValue
import android.view.View
import android.widget.RemoteViews
import androidx.core.content.ContextCompat
import com.portfoliarr.app.MainActivity
import com.portfoliarr.app.R
import com.portfoliarr.app.StartGate
import org.json.JSONObject

/**
 * Paints one widget instance (#51).
 *
 * Two layouts: the 2x1 (value + day change) and the 4x1 (adds the portfolio
 * name, the fetch time, and total return). The wide/small decision comes
 * from the launcher's reported width. Every state degrades honestly:
 * "no server", "tap to connect", a placeholder while the first fetch is in
 * flight, and the cached numbers tinted as stale when the last refresh
 * failed. The view set is limited to what RemoteViews can inflate.
 */
object WidgetRenderer {

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
        // A token is only usable for the server it was issued for: a
        // repointed app must show "connect", never replay the old token.
        val hasToken = hasServer && store.origin(appWidgetId) == origin &&
            !store.token(appWidgetId).isNullOrEmpty()
        val payloadJson = store.payload(appWidgetId)
        val status = WidgetFormat.status(hasServer, hasToken, payloadJson != null)

        val manager = AppWidgetManager.getInstance(context)
        val widthDp = manager.getAppWidgetOptions(appWidgetId)
            .getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH)
        val wide = WidgetFormat.isWide(widthDp)
        val views = RemoteViews(
            context.packageName,
            if (wide) R.layout.widget_wide else R.layout.widget_small,
        )

        when (status) {
            WidgetStatus.NO_SERVER -> showMessage(
                context, views, wide, context.getString(R.string.widget_no_server))
            WidgetStatus.NO_TOKEN -> showMessage(
                context, views, wide, context.getString(R.string.widget_no_token))
            WidgetStatus.NO_DATA -> showMessage(context, views, wide, "—")
            WidgetStatus.READY -> try {
                showData(context, views, wide, store, appWidgetId, payloadJson!!)
            } catch (e: Exception) {
                // A cached payload that cannot be parsed is treated like a
                // failed refresh: tell the truth, never crash the launcher.
                showMessage(context, views, wide,
                    context.getString(R.string.widget_error))
            }
        }

        views.setInt(
            R.id.widget_refresh, "setColorFilter",
            ContextCompat.getColor(context, R.color.widget_text_muted))
        views.setOnClickPendingIntent(
            R.id.widget_refresh, refreshPending(context, appWidgetId))
        // Tapping the body opens the app; when there is no usable token the
        // tap goes to the connect screen instead, which is the one action
        // that fixes the state.
        views.setOnClickPendingIntent(
            R.id.widget_root,
            if (status == WidgetStatus.NO_TOKEN) configPending(context, appWidgetId)
            else openAppPending(context),
        )

        manager.updateAppWidget(appWidgetId, views)
    }

    private fun showMessage(
        context: Context,
        views: RemoteViews,
        wide: Boolean,
        message: String,
    ) {
        views.setTextViewTextSize(
            R.id.widget_value, TypedValue.COMPLEX_UNIT_SP, 11f)
        views.setTextViewText(R.id.widget_value, message)
        views.setViewVisibility(R.id.widget_asof, View.GONE)
        views.setViewVisibility(R.id.widget_day, View.GONE)
        if (wide) {
            views.setViewVisibility(R.id.widget_name, View.GONE)
            views.setViewVisibility(R.id.widget_total, View.GONE)
        }
    }

    private fun showData(
        context: Context,
        views: RemoteViews,
        wide: Boolean,
        store: WidgetStore,
        appWidgetId: Int,
        payloadJson: String,
    ) {
        val json = JSONObject(payloadJson)
        val totalValue = json.getDouble("total_value")
        val dayGain = json.getDouble("day_gain")
        val dayPct = if (json.isNull("day_gain_pct")) null
        else json.getDouble("day_gain_pct")
        val totalGain = json.getDouble("total_gain")
        val totalPct = if (json.isNull("total_gain_pct")) null
        else json.getDouble("total_gain_pct")
        val currency = json.optString("currency", "CAD")

        views.setTextViewTextSize(
            R.id.widget_value, TypedValue.COMPLEX_UNIT_SP, 15f)
        views.setTextViewText(
            R.id.widget_value,
            WidgetFormat.valueWithCurrency(totalValue, currency))

        views.setViewVisibility(R.id.widget_asof, View.VISIBLE)
        views.setTextViewText(
            R.id.widget_asof,
            context.getString(
                R.string.widget_asof,
                WidgetFormat.formatAsOf(store.fetchedAt(appWidgetId))))
        // A failed refresh keeps the last good numbers on screen and tints
        // the timestamp instead of blanking data the user already saw.
        views.setTextColor(
            R.id.widget_asof,
            ContextCompat.getColor(
                context,
                if (store.attemptFailed(appWidgetId)) R.color.widget_stale
                else R.color.widget_text_muted))

        views.setViewVisibility(R.id.widget_day, View.VISIBLE)
        views.setTextViewText(
            R.id.widget_day,
            context.getString(R.string.widget_today) + " " +
                WidgetFormat.changeText(dayGain, dayPct))
        views.setTextColor(
            R.id.widget_day,
            ContextCompat.getColor(
                context,
                if (WidgetFormat.isUp(dayGain)) R.color.widget_up
                else R.color.widget_down))

        if (wide) {
            views.setViewVisibility(R.id.widget_name, View.VISIBLE)
            views.setTextViewText(
                R.id.widget_name, store.portfolioName(appWidgetId) ?: "")
            views.setViewVisibility(R.id.widget_total, View.VISIBLE)
            views.setTextViewText(
                R.id.widget_total,
                context.getString(R.string.widget_total) + " " +
                    WidgetFormat.changeText(totalGain, totalPct))
            views.setTextColor(
                R.id.widget_total,
                ContextCompat.getColor(
                    context,
                    if (WidgetFormat.isUp(totalGain)) R.color.widget_up
                    else R.color.widget_down))
        }
    }

    private fun refreshPending(context: Context, appWidgetId: Int): PendingIntent {
        val intent = Intent(context, PortfolioWidgetProvider::class.java).apply {
            action = PortfolioWidgetProvider.ACTION_REFRESH
        }
        return PendingIntent.getBroadcast(
            context, appWidgetId, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }

    private fun configPending(context: Context, appWidgetId: Int): PendingIntent {
        val intent = Intent(context, WidgetConfigActivity::class.java).apply {
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
