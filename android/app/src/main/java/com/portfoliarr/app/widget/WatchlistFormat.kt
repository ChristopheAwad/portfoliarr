package com.portfoliarr.app.widget

/**
 * The watchlist widget's presentation math (#59). PURE: no android.* /
 * androidx.* imports, so WatchlistFormatTest runs on a plain JVM in CI —
 * the only automated coverage this feature can have outside pytest source
 * pins.
 *
 * The sign rule mirrors the web app: the up/down color comes from the MONEY
 * change, never from the percentage, and zero counts as up (WidgetFormat).
 */
object WatchlistFormat {

    fun priceText(price: Double, currency: String): String =
        "${WidgetFormat.formatMoney(price)} $currency"

    /** "+1.30%", "-0.50%", or "" when the server sent no base (null). */
    fun changePercentText(pct: Double?): String {
        if (pct == null) return ""
        val sign = if (pct >= 0) "+" else ""
        return "$sign${WidgetFormat.formatMoney(pct)}%"
    }

    fun isUp(change: Double): Boolean = change >= 0
}
