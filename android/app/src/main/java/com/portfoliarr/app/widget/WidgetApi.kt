package com.portfoliarr.app.widget

import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * The widget's two HTTP conversations (#51), kept in one small class:
 *
 *   * the CONNECT path, which speaks to the normal session-authenticated
 *     API using the app's saved cookie (list portfolios, mint a token) —
 *     only the config screen calls these;
 *   * the READ path, `fetchSummary`, which presents ONLY the scoped bearer
 *     token and touches /api/widget/summary and nothing else.
 *
 * HttpURLConnection + org.json on purpose: no new network dependency, the
 * same stack as the update checker. Every call has bounded timeouts so a
 * dead server cannot hang a worker. Nothing here logs the cookie or token.
 */
object WidgetApi {

    data class PortfolioRef(val id: Int, val name: String)

    data class CreatedToken(val id: Int, val token: String, val portfolioName: String)

    /** The server rejected the credential (401): expired session during
     * connect, or a revoked widget token during fetch. Never retryable. */
    class UnauthorizedException : Exception("unauthorized")

    /** Any other non-2xx reply. */
    class ApiException(val code: Int) : Exception("HTTP $code")

    private const val TIMEOUT_MS = 15_000
    private const val BEARER_PREFIX = "Bearer "

    fun listPortfolios(baseUrl: String, cookieHeader: String): List<PortfolioRef> {
        val body = get("${base(baseUrl)}/api/portfolios", cookieHeader)
        val array = JSONArray(body)
        return (0 until array.length()).map { index ->
            val item = array.getJSONObject(index)
            PortfolioRef(item.getInt("id"), item.getString("name"))
        }
    }

    fun createToken(
        baseUrl: String,
        cookieHeader: String,
        portfolioId: Int,
    ): CreatedToken {
        val json = post(
            "${base(baseUrl)}/api/widget/tokens",
            cookieHeader,
            JSONObject().put("portfolio_id", portfolioId).toString(),
        )
        return CreatedToken(
            json.getInt("id"),
            json.getString("token"),
            json.getString("portfolio_name"),
        )
    }

    fun fetchSummary(baseUrl: String, token: String): String {
        val connection = open("${base(baseUrl)}/api/widget/summary")
        connection.setRequestProperty("Accept", "application/json")
        connection.setRequestProperty("Authorization", BEARER_PREFIX + token)
        return read(connection)
    }

    private fun get(url: String, cookieHeader: String): String {
        val connection = open(url)
        connection.setRequestProperty("Accept", "application/json")
        connection.setRequestProperty("Cookie", cookieHeader)
        return read(connection)
    }

    private fun post(url: String, cookieHeader: String, body: String): JSONObject {
        val connection = open(url)
        connection.requestMethod = "POST"
        connection.doOutput = true
        connection.setRequestProperty("Accept", "application/json")
        connection.setRequestProperty("Content-Type", "application/json")
        connection.setRequestProperty("Cookie", cookieHeader)
        try {
            connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            return JSONObject(read(connection))
        } finally {
            connection.disconnect()
        }
    }

    private fun open(url: String): HttpURLConnection {
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.connectTimeout = TIMEOUT_MS
        connection.readTimeout = TIMEOUT_MS
        return connection
    }

    private fun read(connection: HttpURLConnection): String {
        try {
            val status = connection.responseCode
            when {
                status == HttpURLConnection.HTTP_UNAUTHORIZED ->
                    throw UnauthorizedException()
                status !in 200..299 -> throw ApiException(status)
            }
            return connection.inputStream.bufferedReader(Charsets.UTF_8).use {
                it.readText()
            }
        } finally {
            connection.disconnect()
        }
    }

    private fun base(baseUrl: String) = baseUrl.trimEnd('/')
}
