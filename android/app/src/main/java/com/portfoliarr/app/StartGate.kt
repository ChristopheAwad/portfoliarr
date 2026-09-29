// android/app/src/main/java/com/portfoliarr/app/StartGate.kt
// The one question MainActivity asks before deciding to show a fingerprint
// prompt, plus the server-origin comparison that goes with it.
//
// NO android.* / androidx.* imports on purpose — StartGateTest.kt runs this
// on a plain JVM.
//
// The governing rule is that a wrong `true` is much worse than a wrong
// `false`. A needless prompt is an annoyance; a prompt that reappears after a
// failure is a loop the user cannot escape. So every uncertain condition — no
// secret, no hardware, none enrolled, unknown URL, a different server, a
// disabled setting, a warm start — answers false and falls through to the
// ordinary password login.

package com.portfoliarr.app

object StartGate {

    /**
     * True only when there is a stored secret to unlock, the user has
     * switched the feature on, biometrics are actually usable, this is a
     * genuine cold start, and the secret belongs to the server we are about
     * to load.
     */
    fun shouldPromptOnStart(
        hasStoredSecret: Boolean,
        biometricAvailable: Boolean,
        enabledInSettings: Boolean,
        coldStart: Boolean,
        secretServerOrigin: String?,
        currentServerOrigin: String?,
    ): Boolean {
        // Cheapest and most absolute first: the user turned it off.
        if (!enabledInSettings) return false
        // Cold start only. A rotation or a return from another app must not
        // ask again.
        if (!coldStart) return false
        // Nothing to unlock.
        if (!hasStoredSecret) return false
        // No hardware, nothing enrolled, or the sensor is busy.
        if (!biometricAvailable) return false
        // A secret with no recorded origin, or a server we cannot compare it
        // against, is not safe to offer. Handing a cookie to the wrong origin
        // would leak a live session to another host.
        if (secretServerOrigin.isNullOrBlank()) return false
        if (currentServerOrigin.isNullOrBlank()) return false
        if (secretServerOrigin != currentServerOrigin) return false
        return true
    }

    /**
     * Reduce a user-typed server URL to the value a stored secret is bound
     * to: lowercase scheme, host and port, no trailing slash, no path.
     *
     * The SCHEME IS KEPT even though a cookie is technically shared between
     * http and https on the same host. Keeping it is the safer choice: if the
     * user edits the server from `https://` to `http://`, the stored secret
     * must not be replayed to a different transport.
     *
     * The user may type "http://192.168.1.50:9967" with or without a trailing
     * slash, and both mean the same server. Anything that is not http(s)
     * returns "" so a `javascript:` or `file:` URL can never become a stored
     * secret's origin. A bare "host:port" is also rejected rather than
     * guessed at: MainActivity already requires an explicit scheme when
     * saving a URL, so reaching here without one means the value is not ours.
     */
    fun normalizeOrigin(rawUrl: String?): String {
        val url = rawUrl?.trim() ?: return ""
        if (url.isEmpty()) return ""
        val lower = url.lowercase()
        val scheme = when {
            lower.startsWith("http://") -> "http"
            lower.startsWith("https://") -> "https"
            else -> return ""
        }
        val afterScheme = lower.substringAfter("://")
        // Cut the path, query, fragment and any credentials. A cookie is
        // scoped to host and port only.
        val hostPort = afterScheme.substringBefore('/')
            .substringBefore('?')
            .substringBefore('#')
            .substringBefore('@')
        if (hostPort.isEmpty()) return ""
        return "$scheme://$hostPort"
    }

    /**
     * True when a URL is one of the server's own auth pages (/auth/login,
     * /auth/setup, /auth/signup).
     *
     * This is how the app recognises a LOGOUT. Flask's session cookie is a
     * stateless signed blob, so the server has no way to revoke the copy the
     * app already holds: replaying it would sign the user straight back in.
     * So a stored secret is only dropped when we land on an auth page with no
     * live cookie — that pairing is exactly what tapping "Sign out" produces,
     * and without it a sign-out would last only until the app was closed.
     *
     * "author" and "authsetup" are NOT auth pages. The path must be "auth"
     * exactly, or "auth/" followed by something.
     */
    fun isAuthPath(url: String): Boolean {
        val afterScheme = url.substringAfter("://", "")
        if (afterScheme.isEmpty()) return false
        // Everything after the first "/" of the authority; an authority with
        // no path leaves this empty.
        val path = afterScheme.substringAfter('/', "")
        if (path.isEmpty()) return false
        if (path == "auth") return true
        if (!path.startsWith("auth/")) return false
        // Strip the query and fragment before matching the segment, so
        // "/auth/login?next=%2Fledger" is still recognised.
        val segment = path.removePrefix("auth/").substringBefore('?')
            .substringBefore('#')
        return segment.isNotEmpty()
    }
}
