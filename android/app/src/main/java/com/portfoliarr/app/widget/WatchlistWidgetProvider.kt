package com.portfoliarr.app.widget

import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.Context
import android.content.Intent
import android.os.Bundle
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import com.portfoliarr.app.R
import java.util.concurrent.TimeUnit

/**
 * The watchlist widget's system-facing shell (#59), sibling of
 * PortfolioWidgetProvider: repaints on update/resize, cleans up per-widget
 * state on delete, and owns the WorkManager schedule.
 *
 * WorkManager, not updatePeriodMillis: the system's own widget timer is
 * unreliable and will not run while the device is asleep. A periodic Worker
 * gets a bounded background window and survives reboots. The schedule only
 * exists while at least one widget is on the home screen.
 *
 * This provider, unlike #51's, backs a RemoteViews collection (a ListView):
 * after a fetch the list adapter must be told the data changed, which is what
 * notifyAppWidgetViewDataChanged does.
 *
 * exported="false" is deliberate: the system still delivers APPWIDGET_UPDATE,
 * and no other app can poke the provider.
 */
class WatchlistWidgetProvider : AppWidgetProvider() {

    override fun onUpdate(
        context: Context,
        appWidgetManager: AppWidgetManager,
        appWidgetIds: IntArray,
    ) {
        ensurePeriodic(context)
        for (appWidgetId in appWidgetIds) {
            WatchlistWidgetRenderer.render(context, appWidgetId)
        }
        appWidgetManager.notifyAppWidgetViewDataChanged(
            appWidgetIds, R.id.widget_watchlist_list)
        refreshNow(context)
    }

    override fun onAppWidgetOptionsChanged(
        context: Context,
        appWidgetManager: AppWidgetManager,
        appWidgetId: Int,
        newOptions: Bundle,
    ) {
        WatchlistWidgetRenderer.render(context, appWidgetId)
    }

    override fun onDeleted(context: Context, appWidgetIds: IntArray) {
        val store = WidgetStore(context)
        for (appWidgetId in appWidgetIds) {
            store.remove(appWidgetId)
        }
    }

    override fun onEnabled(context: Context) {
        ensurePeriodic(context)
    }

    override fun onDisabled(context: Context) {
        WorkManager.getInstance(context).cancelUniqueWork(PERIODIC_WORK)
    }

    override fun onReceive(context: Context, intent: Intent) {
        super.onReceive(context, intent)
        if (intent.action == ACTION_REFRESH) {
            refreshNow(context)
        }
    }

    companion object {
        const val ACTION_REFRESH =
            "com.portfoliarr.app.widget.action.WATCHLIST_REFRESH"

        private const val PERIODIC_WORK = "portfoliarr_watchlist_widget_periodic"
        private const val IMMEDIATE_WORK = "portfoliarr_watchlist_widget_now"
        private const val PERIOD_MINUTES = 30L

        @JvmStatic
        fun refreshNow(context: Context) {
            val request = OneTimeWorkRequestBuilder<WatchlistWidgetWorker>()
                .setConstraints(networkConstraints())
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork(
                IMMEDIATE_WORK, ExistingWorkPolicy.REPLACE, request)
        }

        private fun ensurePeriodic(context: Context) {
            val request = PeriodicWorkRequestBuilder<WatchlistWidgetWorker>(
                PERIOD_MINUTES, TimeUnit.MINUTES)
                .setConstraints(networkConstraints())
                .build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                PERIODIC_WORK, ExistingPeriodicWorkPolicy.KEEP, request)
        }

        private fun networkConstraints() = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
    }
}
