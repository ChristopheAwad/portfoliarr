// android/app/src/main/java/com/portfoliarr/app/SessionControl.kt
// The actions that end a login on this phone, in one place.
//
// Two callers need the "forget this phone" behaviour — MainActivity (the
// cancel dialog, which is the only reachable route in the shipped UI) and
// SettingsActivity (the switch and button on a screen the user cannot
// currently open). Duplicating it would mean two copies of the step that
// actually matters, and a fix applied to only one of them.

package com.portfoliarr.app

import android.content.Context
import android.webkit.CookieManager

object SessionControl {

    /**
     * Forget the saved login on this phone.
     *
     * Two things must go, and clearing only one of them is a silent no-op:
     *
     *   * the encrypted secret in the app's own prefs, and
     *   * the live cookie in the WebView's jar.
     *
     * Clear only the first and a working session is left behind, which then
     * quietly re-saves itself on the next page load. Clear only the second
     * and the next cold start replays the stored copy — and because Flask's
     * session cookie is a stateless signed blob, that copy is still valid,
     * so the user would be signed straight back in.
     *
     * This does NOT switch the feature off. That is what "Stop asking" is
     * for; keeping the two separate means "forget" is a re-login, not a
     * settings change.
     */
    fun forgetPhone(context: Context, store: SecretStore) {
        store.clear()
        val cookies = CookieManager.getInstance()
        cookies.removeAllCookies(null)
        cookies.flush()
    }
}
