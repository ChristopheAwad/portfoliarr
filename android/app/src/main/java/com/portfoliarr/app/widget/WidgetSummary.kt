package com.portfoliarr.app.widget

import org.json.JSONArray
import org.json.JSONObject

/**
 * The completeness contract for /api/widget/summary (#51).
 *
 * A 200 only means the request was accepted. Quotes or FX can fail, leaving
 * `unpriced` tickers and zero or partial sums in the body; painting that as a
 * fresh valuation is a lie. This helper is the ONE place that decides whether
 * a payload is complete, and both the network response and the cached payload
 * go through it so a legacy partial snapshot cannot be painted either.
 *
 * The decision itself is pure and JVM-testable. Only the tiny adapter at the
 * bottom touches org.json, and it hands back raw values so a string-typed
 * number cannot pass as a Double.
 */
object WidgetSummary {

    const val SUPPORTED_CURRENCY = "CAD"

    data class Snapshot(
        val totalValue: Double,
        val dayGain: Double,
        val dayGainPct: Double?,
        val totalGain: Double,
        val totalGainPct: Double?,
        val currency: String,
    )

    private val REQUIRED_KEYS = listOf(
        "total_value",
        "day_gain",
        "day_gain_pct",
        "total_gain",
        "total_gain_pct",
        "currency",
        "unpriced",
    )

    /**
     * Validate one payload's raw fields. Returns null when any part of the
     * contract is missing, mistyped, non-finite, or the portfolio is only
     * partly priced.
     */
    fun read(json: WidgetSummaryJson): Snapshot? {
        // Every key must be PRESENT: an absent percentage is not the same as
        // the explicit JSON null the server sends for a genuinely empty base.
        for (key in REQUIRED_KEYS) {
            if (!json.has(key)) return null
        }

        val totalValue = number(json.value("total_value")) ?: return null
        val dayGain = number(json.value("day_gain")) ?: return null
        val totalGain = number(json.value("total_gain")) ?: return null

        val rawDayPct = json.value("day_gain_pct")
        val dayGainPct: Double? =
            if (rawDayPct == null) null else (number(rawDayPct) ?: return null)
        val rawTotalPct = json.value("total_gain_pct")
        val totalGainPct: Double? =
            if (rawTotalPct == null) null else (number(rawTotalPct) ?: return null)

        val currency = json.value("currency") as? String ?: return null
        if (currency != SUPPORTED_CURRENCY) return null

        // Present, an array, and strictly empty: one unpriced ticker means the
        // total is a partial valuation, however plausible it looks.
        val unpricedLength = json.arrayLength("unpriced") ?: return null
        if (unpricedLength != 0) return null

        return Snapshot(
            totalValue = totalValue,
            dayGain = dayGain,
            dayGainPct = dayGainPct,
            totalGain = totalGain,
            totalGainPct = totalGainPct,
            currency = currency,
        )
    }

    /**
     * Parse and validate a raw response or cache body. Malformed JSON is
     * incomplete, never an exception the caller must handle.
     */
    fun readPayload(payloadJson: String?): Snapshot? {
        if (payloadJson.isNullOrBlank()) return null
        return try {
            read(JsonObjectSummary(JSONObject(payloadJson)))
        } catch (e: Exception) {
            null
        }
    }

    /** Accept only real finite JSON numbers; strings and booleans fail. */
    private fun number(value: Any?): Double? =
        (value as? Number)?.toDouble()?.takeIf { it.isFinite() }
}

/**
 * Raw field access for the contract. `has` keeps a missing key distinct from
 * an explicit JSON null, and `value` is deliberately untyped.
 */
interface WidgetSummaryJson {
    fun has(name: String): Boolean
    fun value(name: String): Any?
    fun arrayLength(name: String): Int?
}

/**
 * The only org.json-specific code. It reads raw values with `opt`, never a
 * coercing numeric getter, so a quoted number stays a String and fails the
 * contract.
 */
private class JsonObjectSummary(private val json: JSONObject) : WidgetSummaryJson {

    override fun has(name: String): Boolean = json.has(name)

    override fun value(name: String): Any? {
        val raw = json.opt(name)
        return if (raw == null || raw == JSONObject.NULL) null else raw
    }

    override fun arrayLength(name: String): Int? =
        (json.opt(name) as? JSONArray)?.length()
}
