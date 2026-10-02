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
import java.util.concurrent.TimeUnit

/**
 * The widget's system-facing shell (#51): repaints on update/resize, cleans
 * up per-widget state on delete, and owns the WorkManager schedule.
 *
 * WorkManager, not updatePeriodMillis: the system's own widget timer is
 * unreliable, will not run while the device is asleep, and gives the
 * receiver only a few seconds on the main thread. A periodic Worker gets a
 * bounded background window and survives reboots. The schedule only exists
 * while at least one widget is on the home screen (onEnabled/onDisabled).
 *
 * exported="false" in the manifest is deliberate: the system still delivers
 * APPWIDGET_UPDATE (the documented pattern), and no other app can poke the
 * provider.
 */
class PortfolioWidgetProvider : AppWidgetProvider() {

    override fun onUpdate(
        context: Context,
        appWidgetManager: AppWidgetManager,
        appWidgetIds: IntArray,
    ) {
        ensurePeriodic(context)
        for (appWidgetId in appWidgetIds) {
            WidgetRenderer.render(context, appWidgetId)
        }
        refreshNow(context)
    }

    override fun onAppWidgetOptionsChanged(
        context: Context,
        appWidgetManager: AppWidgetManager,
        appWidgetId: Int,
        newOptions: Bundle,
    ) {
        // A resize can cross the small/wide threshold: repaint from cache
        // immediately, then let the normal refresh keep it fresh.
        WidgetRenderer.render(context, appWidgetId)
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
        const val ACTION_REFRESH = "com.portfoliarr.app.widget.action.REFRESH"

        private const val PERIODIC_WORK = "portfoliarr_widget_periodic"
        private const val IMMEDIATE_WORK = "portfoliarr_widget_now"
        private const val PERIOD_MINUTES = 30L

        @JvmStatic
        fun refreshNow(context: Context) {
            val request = OneTimeWorkRequestBuilder<WidgetWorker>()
                .setConstraints(networkConstraints())
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork(
                IMMEDIATE_WORK, ExistingWorkPolicy.REPLACE, request)
        }

        private fun ensurePeriodic(context: Context) {
            val request = PeriodicWorkRequestBuilder<WidgetWorker>(
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
