package com.portfoliarr.app

import com.portfoliarr.app.widget.WidgetFormat
import com.portfoliarr.app.widget.WidgetStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * JVM tests for the widget's pure presentation helpers. They run in CI
 * (`./gradlew test`) because WidgetFormat carries no android.* imports —
 * the rest of the widget is covered by pytest source pins and the
 * on-device gate.
 */
class WidgetFormatTest {

    @Test
    fun wideLayoutStartsAtTheFourCellWidth() {
        assertFalse(WidgetFormat.isWide(110))
        assertFalse(WidgetFormat.isWide(179))
        assertTrue(WidgetFormat.isWide(180))
        assertTrue(WidgetFormat.isWide(250))
    }

    @Test
    fun moneyIsGroupedAndAlwaysTwoDecimals() {
        assertEquals("12,345.60", WidgetFormat.formatMoney(12345.6))
        assertEquals("0.00", WidgetFormat.formatMoney(0.0))
        assertEquals("-1,234.50", WidgetFormat.formatMoney(-1234.5))
    }

    @Test
    fun signedMoneyCarriesThePlusForZeroAndUp() {
        assertEquals("+12.30", WidgetFormat.formatSignedMoney(12.3))
        assertEquals("-7.10", WidgetFormat.formatSignedMoney(-7.1))
        assertEquals("+0.00", WidgetFormat.formatSignedMoney(0.0))
    }

    @Test
    fun valueIsLabeledWithItsCurrency() {
        assertEquals("1,000.00 CAD",
            WidgetFormat.valueWithCurrency(1000.0, "CAD"))
    }

    @Test
    fun changeTextDropsThePercentWhenThereIsNoBase() {
        assertEquals("+123.45", WidgetFormat.changeText(123.45, null))
    }

    @Test
    fun changeTextMatchesTheDashboardsShape() {
        assertEquals("+123.45 (+1.02%)", WidgetFormat.changeText(123.45, 1.02))
        assertEquals("-123.45 (-1.02%)", WidgetFormat.changeText(-123.45, -1.02))
    }

    @Test
    fun zeroCountsAsUp() {
        assertTrue(WidgetFormat.isUp(0.0))
        assertFalse(WidgetFormat.isUp(-0.01))
    }

    @Test
    fun statusPicksTheFirstMissingPiece() {
        assertEquals(WidgetStatus.NO_SERVER,
            WidgetFormat.status(false, false, false))
        assertEquals(WidgetStatus.NO_TOKEN,
            WidgetFormat.status(true, false, false))
        assertEquals(WidgetStatus.NO_DATA,
            WidgetFormat.status(true, true, false))
        assertEquals(WidgetStatus.READY,
            WidgetFormat.status(true, true, true))
    }

    @Test
    fun asOfFormatsAsClockTime() {
        assertTrue(WidgetFormat.formatAsOf(0L).matches(Regex("""\d{2}:\d{2}""")))
    }
}
