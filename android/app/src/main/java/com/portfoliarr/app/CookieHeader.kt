// android/app/src/main/java/com/portfoliarr/app/CookieHeader.kt
// Pure string helpers for the session cookie. NO android.* / androidx.*
// imports on purpose: everything here is exercised by CookieHeaderTest.kt on
// a plain JVM, and an android import would turn that into a test that can
// only ever pass on a real device.
//
// The cookie we juggle is Flask's signed session: itsdangerous URLSafeBase64,
// so the value contains '.', '-', '_' and '=' padding, and the name is
// matched case-sensitively ("Session" is a different cookie).

package com.portfoliarr.app

import java.security.MessageDigest

object CookieHeader {

    const val SESSION_COOKIE_NAME = "session"

    // 30 days — must stay in step with PERMANENT_SESSION_LIFETIME in app.py.
    // tests/test_android_biometric.py fails if these two ever drift apart.
    const val SESSION_MAX_AGE_SECONDS = 2_592_000

    private val HEX = "0123456789abcdef".toCharArray()

    /**
     * Pull the session cookie's value out of a WebView `Cookie:` request
     * header, or null when it is not there.
     *
     * Cookie names are case-SENSITIVE, so this compares with `==` and never
     * with equals(ignoreCase = true): "Session" is some other cookie and must
     * not be stored as ours.
     *
     * A segment with no '=' (a bare flag such as "Secure") is skipped, as is
     * one whose name is empty.
     *
     * When the same name appears twice the FIRST occurrence wins, matching
     * RFC 6265's ordering: cookies are sent longest-path-first, so the first
     * is the most specific one. In practice Flask only ever sets one session
     * cookie at "/", so duplicates do not arise.
     */
    fun extractSession(cookieHeader: String?): String? {
        if (cookieHeader.isNullOrBlank()) return null
        for (raw in cookieHeader.split(';')) {
            val pair = raw.trim()
            if (pair.isEmpty()) continue
            // Only the FIRST '=' separates name from value. A base64 value is
            // padded with '=' and must survive intact.
            val split = pair.indexOf('=')
            if (split <= 0) continue
            if (pair.substring(0, split).trim() != SESSION_COOKIE_NAME) continue
            val value = pair.substring(split + 1).trim()
            // An empty or whitespace-only value is not a usable login.
            if (value.isEmpty()) continue
            return value
        }
        return null
    }

    /**
     * Build the `Set-Cookie` value used to hand the cookie back to the
     * WebView, or null when there is nothing worth setting.
     *
     * The attributes are NOT optional decoration. The server put HttpOnly and
     * SameSite=Lax on the real login response (app.py's SESSION_COOKIE_*
     * settings), but re-injecting a cookie by hand bypasses that response
     * entirely. Without re-applying them the restored cookie would be
     * readable from JavaScript and cross-site-riding — a silent downgrade of
     * the session's protections, on the one surface the user trusts most.
     *
     * There is deliberately NO `Secure` attribute: the LAN server is plain
     * HTTP, and CookieManager refuses a Secure cookie over http://, which
     * would break login on exactly the deployment this app targets.
     */
    fun buildRestoreCookieHeader(sessionValue: String): String? {
        val value = sessionValue.trim()
        if (value.isEmpty()) return null
        return "$SESSION_COOKIE_NAME=$value; Path=/; " +
            "Max-Age=$SESSION_MAX_AGE_SECONDS; HttpOnly; SameSite=Lax"
    }

    /**
     * Lowercase hex SHA-256 of a value, used to notice that the live cookie
     * has changed WITHOUT decrypting the stored one. Decrypting requires a
     * fresh fingerprint, and the background cookie sampler must never ask for
     * one, so the two are compared by hash instead.
     */
    fun sha256Hex(value: String): String {
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(value.toByteArray(Charsets.UTF_8))
        val out = CharArray(digest.size * 2)
        for (i in digest.indices) {
            val b = digest[i].toInt() and 0xFF
            out[i * 2] = HEX[b ushr 4]
            out[i * 2 + 1] = HEX[b and 0x0F]
        }
        return String(out)
    }
}
