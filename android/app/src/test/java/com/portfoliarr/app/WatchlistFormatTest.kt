package com.portfoliarr.app

import com.portfoliarr.app.widget.WatchlistFormat
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * JVM tests for the watchlist widget's pure presentation helpers (#59).
 * They run in CI (`./gradlew test`) because WatchlistFormat carries no
 * android.* imports — the rest of the widget is covered by pytest source
 * pins and the on-device gate.
 */
class WatchlistFormatTest {

    @Test
    fun priceTextIsLabeledWithItsNativeCurrency() {
        assertEquals("182.50 USD", WatchlistFormat.priceText(182.5, "USD"))
        assertEquals("1,234.00 CAD",
            WatchlistFormat.priceText(1234.0, "CAD"))
    }

    @Test
    fun changePercentIsSignedAndTwoDecimals() {
        assertEquals("+1.30%", WatchlistFormat.changePercentText(1.3012))
        assertEquals("-0.50%", WatchlistFormat.changePercentText(-0.5))
        assertEquals("+0.00%", WatchlistFormat.changePercentText(0.0))
    }

    @Test
    fun changePercentIsEmptyWhenThereIsNoBase() {
        assertEquals("", WatchlistFormat.changePercentText(null))
    }

    @Test
    fun signComesFromTheMoneyValueAndZeroCountsAsUp() {
        assertTrue(WatchlistFormat.isUp(0.0))
        assertTrue(WatchlistFormat.isUp(0.01))
        assertFalse(WatchlistFormat.isUp(-0.01))
    }
}
