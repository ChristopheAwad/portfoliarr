// android/app/src/main/java/com/portfoliarr/app/StartGate.kt
// What the app does when it is opened, plus two pure string helpers.
//
// NO android.* / androidx.* imports on purpose — StartGateTest.kt runs this
// on a plain JVM.
//
// The governing rule is that a wrong LOAD is cheap and a wrong PROMPT or
// OFFER is expensive. A needless prompt is an annoyance; a needless
// one-time offer is worse, because the previous attempt at this feature
// (PR #75) was scrapped after the user rejected the on-device trial for
// changing how the app opens. So every uncertain condition answers LOAD and
// falls through to the ordinary password login, silently.

package com.portfoliarr.app

object StartGate {

    /**
     * What MainActivity should do on a cold start.
     *
     * Three outcomes, not a yes/no. A boolean could not express the
     * difference between "ask for a fingerprint" and "ask whether the user
     * WANTS a fingerprint", and collapsing them is how an opt-in turns into
     * a nag.
     */
    enum class StartAction {
        /** Load the page. Today's behaviour, exactly. */
        LOAD,

        /** Ask for a fingerprint, then restore the saved login. */
        PROMPT,

        /** Ask ONCE whether the user wants this feature at all. */
        OFFER,
    }

    /**
     * The one question MainActivity asks before doing anything.
     *
     * The ordering below is the whole design, and it is deliberately
     * conservative: every check that could produce an interruption is a
     * reason to answer LOAD. A wrong LOAD is invisible (the user types their
     * password, exactly as before). A wrong PROMPT is an unwanted
     * fingerprint scan. A wrong OFFER is the worst of the three, because
     * the previous attempt at this feature (PR #75) was scrapped when the
     * app kept interrupting the user — so OFFER additionally requires that
     * biometrics actually work on this device and that the user has not
     * already said no.
     */
    fun decideStartAction(
        hasStoredSecret: Boolean,
        biometricAvailable: Boolean,
        enabledInSettings: Boolean,
        declinedOffer: Boolean,
        coldStart: Boolean,
        secretServerOrigin: String?,
        currentServerOrigin: String?,
    ): StartAction {
        // Only a genuinely new process may ask anything. A rotation or a
        // return from another app must be invisible.
        if (!coldStart) return StartAction.LOAD
        // No hardware, nothing enrolled, sensor busy: nothing to ask with.
        if (!biometricAvailable) return StartAction.LOAD
        // No stored login means nothing to unlock and nothing to offer.
        if (!hasStoredSecret) return StartAction.LOAD
        // A secret belonging to some other server is useless here, and
        // offering a feature that could not then work would be a lie.
        if (!originMatches(secretServerOrigin, currentServerOrigin)) {
            return StartAction.LOAD
        }
        return when {
            // Already on: prompt. The decline flag cannot suppress this —
            // it only ever silenced the offer.
            enabledInSettings -> StartAction.PROMPT
            // Off, but never asked: ask once.
            !declinedOffer -> StartAction.OFFER
            // Off, and already declined: say nothing, forever.
            else -> StartAction.LOAD
        }
    }

    /**
     * True only when a stored secret provably belongs to the server we are
     * about to load. A cookie handed to the wrong origin would leak a live
     * session, so an unknown or mismatched origin is a hard no.
     */
    private fun originMatches(secretOrigin: String?, currentOrigin: String?): Boolean {
        if (secretOrigin.isNullOrBlank()) return false
        if (currentOrigin.isNullOrBlank()) return false
        return secretOrigin == currentOrigin
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
        // A cookie is scoped to host and port only, so drop the path, query,
        // fragment, and any userinfo. Credentials are stripped by taking what
        // comes AFTER the last '@', not before it: "user:pass@host" must
        // reduce to "host", and substringBefore would have kept the
        // credentials and thrown the host away.
        val hostPort = afterScheme.substringBefore('/')
            .substringBefore('?')
            .substringBefore('#')
            .substringAfterLast('@')
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
        // "auth" exactly, or anything beneath "auth/". The query and fragment
        // need no stripping: they sit after the prefix, so
        // "/auth/login?next=%2Fledger" and the bare "/auth/" both pass here.
        // Missing either shape would let a sign-out slip through and the
        // stored secret survive, signing the user back in on the next start.
        return path == "auth" || path.startsWith("auth/")
    }
}
