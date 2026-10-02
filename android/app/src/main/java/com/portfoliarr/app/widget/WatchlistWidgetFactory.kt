package com.portfoliarr.app.widget

import android.appwidget.AppWidgetManager
import android.content.Context
import android.content.Intent
import android.widget.RemoteViews
import android.widget.RemoteViewsService
import androidx.core.content.ContextCompat
import com.portfoliarr.app.R
import org.json.JSONArray
import org.json.JSONObject

/** One painted row: the symbol, its price text, its change text, and up/down. */
private data class WatchlistRow(
    val symbol: String,
    val price: String,
    val change: String,
    val up: Boolean,
)

/**
 * Builds the watchlist widget's scrollable rows (#59) from the CACHED
 * payload only. It never performs network calls and never touches the
 * session — the Worker fetched and cached the data; this factory just
 * paints it. A symbol whose quote failed renders as "—" and stays in the
 * list, so the row set always matches the stored watchlist.
 */
class WatchlistWidgetFactory(
    private val context: Context,
    intent: Intent,
) : RemoteViewsService.RemoteViewsFactory {

    private val appWidgetId: Int = intent.getIntExtra(
        AppWidgetManager.EXTRA_APPWIDGET_ID,
        AppWidgetManager.INVALID_APPWIDGET_ID,
    )

    private var rows: List<WatchlistRow> = emptyList()

    override fun onCreate() {
        // Nothing to allocate; onDataSetChanged loads the cached payload.
    }

    override fun onDataSetChanged() {
        rows = parse(WidgetStore(context).payload(appWidgetId))
    }

    private fun parse(payloadJson: String?): List<WatchlistRow> {
        if (payloadJson.isNullOrBlank()) return emptyList()
        return try {
            val json = JSONObject(payloadJson)
            val symbols = json.optJSONArray("symbols") ?: return emptyList()
            val bySymbol = HashMap<String, JSONObject>()
            val quotes: JSONArray = json.optJSONArray("quotes") ?: JSONArray()
            for (i in 0 until quotes.length()) {
                val quote = quotes.optJSONObject(i) ?: continue
                bySymbol[quote.optString("symbol")] = quote
            }
            (0 until symbols.length()).mapNotNull { i ->
                val symbol = symbols.optString(i)
                if (symbol.isEmpty()) return@mapNotNull null
                val quote = bySymbol[symbol]
                if (quote == null) {
                    WatchlistRow(symbol, "—", "", true)
                } else {
                    WatchlistRow(
                        symbol,
                        WatchlistFormat.priceText(
                            quote.optDouble("price", 0.0),
                            quote.optString("currency", "")),
                        WatchlistFormat.changePercentText(
                            if (quote.isNull("change_pct")) null
                            else quote.optDouble("change_pct", 0.0)),
                        WatchlistFormat.isUp(quote.optDouble("change", 0.0)),
                    )
                }
            }
        } catch (e: Exception) {
            // A corrupt cache is treated as "no data"; never crash the launcher.
            emptyList()
        }
    }

    override fun getCount(): Int = rows.size

    override fun getViewAt(position: Int): RemoteViews {
        val views = RemoteViews(
            context.packageName, R.layout.widget_watchlist_item)
        val row = rows.getOrNull(position) ?: return views
        views.setTextViewText(R.id.watchlist_item_symbol, row.symbol)
        views.setTextViewText(R.id.watchlist_item_price, row.price)
        views.setTextViewText(R.id.watchlist_item_change, row.change)
        views.setTextColor(
            R.id.watchlist_item_change,
            ContextCompat.getColor(
                context,
                if (row.up) R.color.widget_up else R.color.widget_down))
        return views
    }

    override fun getLoadingView(): RemoteViews? = null

    override fun getViewTypeCount(): Int = 1

    override fun getItemId(position: Int): Long = position.toLong()

    override fun hasStableIds(): Boolean = false

    override fun onDestroy() {
        rows = emptyList()
    }
}
