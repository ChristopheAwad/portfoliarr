// android/app/src/test/java/com/portfoliarr/app/StartGateTest.kt
// JUnit tests for the cold-start decision — the one question MainActivity
// asks before it decides to show a fingerprint prompt.
//
// Every false case here matters as much as the true one. If any of them
// returned true, the phone would prompt the user for no reason, or — worse —
// keep prompting in a loop after a failure. The rule is simple: when in
// doubt, do NOT prompt; just load the page and let the normal password
// login handle it.

package com.portfoliarr.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class StartGateTest {

    private val origin = "http://192.168.1.50:9967"

    private fun decide(
        hasStoredSecret: Boolean = true,
        biometricAvailable: Boolean = true,
        enabledInSettings: Boolean = true,
        coldStart: Boolean = true,
        secretOrigin: String? = origin,
        currentOrigin: String? = origin,
    ) = StartGate.shouldPromptOnStart(
        hasStoredSecret = hasStoredSecret,
        biometricAvailable = biometricAvailable,
        enabledInSettings = enabledInSettings,
        coldStart = coldStart,
        secretServerOrigin = secretOrigin,
        currentServerOrigin = currentOrigin,
    )

    @Test
    fun `prompts on a cold start with everything in place`() {
        assertTrue(decide())
    }

    @Test
    fun `no prompt without a stored secret`() {
        assertFalse(decide(hasStoredSecret = false))
    }

    @Test
    fun `no prompt when biometrics are unavailable`() {
        // No hardware, none enrolled, or the sensor is busy. canAuthenticate
        // already collapses those; the gate just obeys it.
        assertFalse(decide(biometricAvailable = false))
    }

    @Test
    fun `no prompt when the user turned the feature off`() {
        assertFalse(decide(enabledInSettings = false))
    }

    @Test
    fun `no prompt on a warm start`() {
        // Rotating the screen or coming back from another app must not ask
        // again — the user chose cold start only.
        assertFalse(decide(coldStart = false))
    }

    @Test
    fun `no prompt when the secret belongs to a different server`() {
        assertFalse(decide(secretOrigin = "http://10.0.0.9:9967"))
    }

    @Test
    fun `no prompt when the secret has no recorded origin`() {
        assertFalse(decide(secretOrigin = null))
        assertFalse(decide(secretOrigin = ""))
    }

    @Test
    fun `no prompt when the current server url is unknown`() {
        assertFalse(decide(currentOrigin = null))
    }

    @Test
    fun `settings off wins over everything else`() {
        assertFalse(
            decide(enabledInSettings = false, hasStoredSecret = true,
                biometricAvailable = true, coldStart = true)
        )
    }

    @Test
    fun `an http origin is matched exactly, ports included`() {
        // A cookie is scoped to its host and port. "http://host" and
        // "http://host:9967" are different origins, so they must not
        // silently share a stored secret.
        assertFalse(decide(secretOrigin = "http://192.168.1.50"))
        assertFalse(decide(secretOrigin = "http://192.168.1.50:5000"))
        assertFalse(decide(secretOrigin = "https://192.168.1.50:9967"))
    }

    @Test
    fun `a trailing slash difference still matches`() {
        // The user may type the URL with or without a trailing slash; the
        // stored origin is normalized on save, so both forms must resolve.
        assertTrue(
            StartGate.normalizeOrigin("http://192.168.1.50:9967/") ==
                StartGate.normalizeOrigin("http://192.168.1.50:9967")
        )
    }

    @Test
    fun `normalize strips the trailing slash and surrounding space`() {
        assertEquals(
            "http://192.168.1.50:9967",
            StartGate.normalizeOrigin("  http://192.168.1.50:9967/  ")
        )
    }

    @Test
    fun `normalize maps blank input to an empty string`() {
        assertEquals("", StartGate.normalizeOrigin(null))
        assertEquals("", StartGate.normalizeOrigin("   "))
    }

    @Test
    fun `normalize refuses a non http url`() {
        // A javascript: or file: URL must never become a secret origin.
        assertEquals("", StartGate.normalizeOrigin("javascript:alert(1)"))
        assertEquals("", StartGate.normalizeOrigin("file:///etc/passwd"))
        assertEquals("", StartGate.normalizeOrigin("ftp://host/"))
    }

    @Test
    fun `normalize lowercases the scheme and host`() {
        assertEquals(
            "http://192.168.1.50:9967",
            StartGate.normalizeOrigin("HTTP://192.168.1.50:9967")
        )
    }

    // ── isAuthPath: how a logout is recognised ─────────────────────────

    @Test
    fun `recognises the auth pages`() {
        assertTrue(StartGate.isAuthPath("http://192.168.1.50:9967/auth/login"))
        assertTrue(StartGate.isAuthPath("http://192.168.1.50:9967/auth/setup"))
        assertTrue(StartGate.isAuthPath("http://192.168.1.50:9967/auth/signup"))
        assertTrue(StartGate.isAuthPath("https://host/auth"))
    }

    @Test
    fun `recognises an auth page with a query or fragment`() {
        // This is the real shape: the gate redirects to /auth/login?next=...
        assertTrue(
            StartGate.isAuthPath("http://host:9967/auth/login?next=%2Fledger")
        )
        assertTrue(StartGate.isAuthPath("http://host:9967/auth/login#top"))
    }

    @Test
    fun `does not treat a lookalike path as an auth page`() {
        // The dangerous near-misses: clearing the stored secret on a normal
        // page would be harmless, but MISSING a real auth page means a
        // sign-out silently does not stick.
        assertFalse(StartGate.isAuthPath("http://host:9967/"))
        assertFalse(StartGate.isAuthPath("http://host:9967/ledger"))
        assertFalse(StartGate.isAuthPath("http://host:9967/author"))
        assertFalse(StartGate.isAuthPath("http://host:9967/authsetup"))
        assertFalse(StartGate.isAuthPath("http://host:9967/authorisation"))
    }

    @Test
    fun `rejects a bare host and a schemeless string`() {
        assertFalse(StartGate.isAuthPath("http://192.168.1.50:9967"))
        assertFalse(StartGate.isAuthPath(""))
        assertFalse(StartGate.isAuthPath("   "))
    }
}
