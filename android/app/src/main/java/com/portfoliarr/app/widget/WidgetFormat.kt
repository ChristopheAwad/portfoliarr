package com.portfoliarr.app.widget

import java.math.RoundingMode
import java.text.DecimalFormat
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Which message the widget should paint. Integer-free on purpose: the
 * decision is a pure function of what the renderer knows, so it is JVM
 * testable and the renderer cannot invent a state.
 */
enum class WidgetStatus { READY, NO_SERVER, NO_TOKEN, NO_DATA }

/**
 * The widget's presentation math and layout choice. PURE: no android.* /
 * androidx.* imports, so WidgetFormatTest runs on a plain JVM in CI — the
 * only automated coverage this feature can have outside pytest source pins.
 *
 * The sign rules mirror the web app's paintChange (static/js/common.js):
 * the sign comes from the MONEY value, never from the percentage, and zero
 * counts as up. That is what keeps the widget and the dashboard strip
 * reading the same way.
 */
object WidgetFormat {

    // 2 launcher cells is ~110dp, 4 cells ~250dp; the midpoint switches to
    // the layout that also carries the total-return column.
    const val WIDE_MIN_WIDTH_DP = 180

    // Formatters are created per call: DecimalFormat and SimpleDateFormat
    // are NOT thread-safe, and a widget repaint can come from the main
    // thread (onUpdate) and a WorkManager thread at the same time. These
    // calls are rare, so the small allocation is the cheap correct answer.
    private fun money(): DecimalFormat = DecimalFormat("#,##0.00").apply {
        roundingMode = RoundingMode.HALF_UP
    }

    fun isWide(minWidthDp: Int): Boolean = minWidthDp >= WIDE_MIN_WIDTH_DP

    fun formatMoney(value: Double): String = money().format(value)

    fun formatSignedMoney(value: Double): String =
        (if (value >= 0) "+" else "") + formatMoney(value)

    fun valueWithCurrency(value: Double, currency: String): String =
        "${formatMoney(value)} $currency"

    /**
     * "+123.45 (+1.02%)" — the dollar amount always, the percentage only
     * when a base exists (the server sends null otherwise). The percent's
     * sign follows the dollar sign, matching the web.
     */
    fun changeText(value: Double, pct: Double?): String {
        val sign = if (value >= 0) "+" else ""
        val amount = formatSignedMoney(value)
        return if (pct == null) amount
        else "$amount ($sign${money().format(pct)}%)"
    }

    fun isUp(value: Double): Boolean = value >= 0

    fun formatAsOf(epochMillis: Long): String =
        SimpleDateFormat("HH:mm", Locale.US).format(Date(epochMillis))

    fun status(
        hasServerUrl: Boolean,
        hasToken: Boolean,
        hasPayload: Boolean,
    ): WidgetStatus = when {
        !hasServerUrl -> WidgetStatus.NO_SERVER
        !hasToken -> WidgetStatus.NO_TOKEN
        !hasPayload -> WidgetStatus.NO_DATA
        else -> WidgetStatus.READY
    }
}
