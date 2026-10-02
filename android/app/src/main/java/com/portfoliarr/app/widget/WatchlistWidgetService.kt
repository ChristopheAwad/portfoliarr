package com.portfoliarr.app.widget

import android.content.Intent
import android.widget.RemoteViewsService

/**
 * Binds the watchlist widget's scrollable list to the cached payload (#59).
 *
 * A RemoteViews collection needs a service the launcher can bind to; the
 * system does not let the widget's RemoteViews build rows itself. This is
 * the standard half of the pattern, and the factory is the other half.
 */
class WatchlistWidgetService : RemoteViewsService() {

    override fun onGetViewFactory(intent: Intent): RemoteViewsFactory =
        WatchlistWidgetFactory(applicationContext, intent)
}
