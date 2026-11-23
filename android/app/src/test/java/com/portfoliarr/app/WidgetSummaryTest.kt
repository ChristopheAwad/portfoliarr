// android/app/src/test/java/com/portfoliarr/app/WidgetSummaryTest.kt
// JVM tests for the portfolio widget's completeness gate. The decision is a
// pure function of raw field values, so these run on a plain JVM. The small
// org.json adapter is pinned from pytest instead: the JVM stub cannot parse
// real JSON, but it must still inspect raw types rather than coerce them.
//
// The governing rule is that a wrong "complete" is expensive: it paints a
// partial valuation as fresh. A wrong "incomplete" only shows "Prices
// unavailable" until the next refresh. So every uncertain shape fails closed.

package com.portfoliarr.app

import com.portfoliarr.app.widget.WidgetSummary
import com.portfoliarr.app.widget.WidgetSummaryJson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class WidgetSummaryTest {

    private class FakeJson(
        private val values: Map<String, Any?>,
    ) : WidgetSummaryJson {
        override fun has(name: String): Boolean = values.containsKey(name)
        override fun value(name: String): Any? = values[name]
        override fun arrayLength(name: String): Int? =
            (values[name] as? List<*>)?.size
    }

    private fun complete(): MutableMap<String, Any?> = mutableMapOf(
        "total_value" to 1234.5,
        "day_gain" to 12.3,
        "day_gain_pct" to 1.02,
        "total_gain" to 234.5,
        "total_gain_pct" to 5.5,
        "currency" to "CAD",
        "unpriced" to emptyList<String>(),
    )

    private fun read(values: Map<String, Any?>) =
        WidgetSummary.read(FakeJson(values))

    @Test
    fun completeSnapshotWithNullPercentagesIsAccepted() {
        val fields = complete()
        fields["day_gain_pct"] = null
        fields["total_gain_pct"] = null

        val summary = read(fields)

        assertNotNull(summary)
        assertEquals(1234.5, summary!!.totalValue, 0.0)
        assertEquals(12.3, summary.dayGain, 0.0)
        assertEquals(234.5, summary.totalGain, 0.0)
        assertNull(summary.dayGainPct)
        assertNull(summary.totalGainPct)
        assertEquals("CAD", summary.currency)
    }

    @Test
    fun genuinelyEmptyPortfolioIsComplete() {
        val fields = complete()
        fields["total_value"] = 0
        fields["day_gain"] = 0
        fields["day_gain_pct"] = null
        fields["total_gain"] = 0
        fields["total_gain_pct"] = null

        val summary = read(fields)

        assertNotNull(summary)
        assertEquals(0.0, summary!!.totalValue, 0.0)
        assertEquals(0.0, summary.dayGain, 0.0)
        assertEquals(0.0, summary.totalGain, 0.0)
    }

    @Test
    fun everyMissingKeyIsIncomplete() {
        for (key in complete().keys) {
            val fields = complete()
            fields.remove(key)
            assertNull("missing $key must be incomplete", read(fields))
        }
    }

    @Test
    fun explicitNullPercentagesAreCompleteButNullNumbersAreNot() {
        val withNullPercentages = complete()
        withNullPercentages["day_gain_pct"] = null
        withNullPercentages["total_gain_pct"] = null
        assertNotNull(read(withNullPercentages))

        for (key in listOf(
            "total_value", "day_gain", "total_gain", "currency", "unpriced",
        )) {
            val broken = complete()
            broken[key] = null
            assertNull("explicit null $key must be incomplete", read(broken))
        }
    }

    @Test
    fun stringTypedNumbersAreRejected() {
        for (key in listOf(
            "total_value", "day_gain", "day_gain_pct",
            "total_gain", "total_gain_pct",
        )) {
            val fields = complete()
            fields[key] = "12.5"
            assertNull("string $key must be incomplete", read(fields))
        }
    }

    @Test
    fun nonFiniteNumbersAreRejected() {
        val bad = listOf(
            Double.NaN,
            Double.POSITIVE_INFINITY,
            Double.NEGATIVE_INFINITY,
        )
        for (key in listOf(
            "total_value", "day_gain", "day_gain_pct",
            "total_gain", "total_gain_pct",
        )) {
            for (value in bad) {
                val fields = complete()
                fields[key] = value
                assertNull("$value $key must be incomplete", read(fields))
            }
        }
    }

    @Test
    fun anyUnpricedTickerOrNonArrayIsIncomplete() {
        val nonEmpty = complete()
        nonEmpty["unpriced"] = listOf("CM")
        assertNull(read(nonEmpty))

        val notAnArray = complete()
        notAnArray["unpriced"] = "CM"
        assertNull(read(notAnArray))
    }

    @Test
    fun malformedJsonIsIncomplete() {
        // Null and blank never reach the adapter. The text cases must fail
        // closed whether the parser rejects the text or the shape; the
        // adapter's raw-type reads are pinned from pytest.
        assertNull(WidgetSummary.readPayload(null))
        assertNull(WidgetSummary.readPayload(""))
        assertNull(WidgetSummary.readPayload("not json"))
        assertNull(WidgetSummary.readPayload("{}"))
    }

    @Test
    fun onlyTheSupportedCurrencyIsAccepted() {
        for (currency in listOf("USD", "cad", "EUR", "", 1)) {
            val fields = complete()
            fields["currency"] = currency
            assertNull("currency $currency must be incomplete", read(fields))
        }
    }
}
