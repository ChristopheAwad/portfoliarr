package com.portfoliarr.app

/** Process-local session state. Never persist an unlocked session across process death. */
class AppLockPolicy {
    companion object {
        const val DEFAULT_TIMEOUT_MS = 300_000L
        val TIMEOUTS = listOf(0L, 60_000L, DEFAULT_TIMEOUT_MS, 900_000L)

        fun timeout(saved: Long): Long = saved.takeIf { it in TIMEOUTS } ?: DEFAULT_TIMEOUT_MS
    }

    private var unlocked = false
    private var leftAt: Long? = null

    fun authenticated() {
        unlocked = true
        leftAt = null
    }

    fun authenticationFailed() {
        unlocked = false
    }

    fun backgrounded(now: Long) {
        // A second lifecycle callback must not extend a background trip.
        if (leftAt == null) leftAt = now
    }

    fun requiresAuthentication(now: Long, enabled: Boolean, savedTimeout: Long): Boolean {
        if (!enabled) return false
        if (!unlocked) return true
        val departure = leftAt ?: return false
        if (now < departure || now - departure >= timeout(savedTimeout)) {
            unlocked = false
            return true
        }
        leftAt = null
        return false
    }
}
