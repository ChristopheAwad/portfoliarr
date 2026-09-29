// android/app/src/test/java/com/portfoliarr/app/StartGateTest.kt
// JUnit tests for the cold-start decision — the one question MainActivity
// asks before it does anything, plus the two pure string helpers that go
// with it.
//
// NO android.* / androidx.* imports on purpose; this runs on a plain JVM.
//
// The governing rule is that a wrong LOAD is cheap and a wrong PROMPT or
// OFFER is expensive. A needless fingerprint prompt is an annoyance, and a
// needless one-time OFFER is worse: the previous attempt at this feature
// (PR #75) was scrapped because the app kept interrupting the user. So
// every uncertain condition — no secret, no hardware, none enrolled,
// unknown URL, a different server, a declined offer — answers LOAD and lets
// the ordinary password login take over silently.

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
        enabledInSettings: Boolean = false,
        declinedOffer: Boolean = false,
        coldStart: Boolean = true,
        secretOrigin: String? = origin,
        currentOrigin: String? = origin,
    ) = StartGate.decideStartAction(
        hasStoredSecret = hasStoredSecret,
        biometricAvailable = biometricAvailable,
        enabledInSettings = enabledInSettings,
        declinedOffer = declinedOffer,
        coldStart = coldStart,
        secretServerOrigin = secretOrigin,
        currentServerOrigin = currentOrigin,
    )

    // ── the happy paths ───────────────────────────────────────────────

    @Test
    fun `prompts when enabled with a matching secret`() {
        assertEquals(StartGate.StartAction.PROMPT, decide(enabledInSettings = true))
    }

    @Test
    fun `offers the feature once when not enabled and not declined`() {
        assertEquals(StartGate.StartAction.OFFER, decide(enabledInSettings = false))
    }

    @Test
    fun `loads when enabled but no secret is stored`() {
        // The overwhelmingly common first launch: nothing has been saved, so
        // there is nothing to unlock and nothing to offer.
        assertEquals(
            StartGate.StartAction.LOAD,
            decide(hasStoredSecret = false, enabledInSettings = true)
        )
    }

    // ── everything must degrade to LOAD ───────────────────────────────

    @Test
    fun `loads without a stored secret`() {
        assertEquals(StartGate.StartAction.LOAD, decide(hasStoredSecret = false))
    }

    @Test
    fun `loads when biometrics are unavailable`() {
        // No hardware, nothing enrolled, or the sensor is busy. The gate
        // already collapses those; this obeys it. Note it suppresses the
        // OFFER too: asking someone to turn on a feature that cannot work
        // on this device is the definition of nagging.
        assertEquals(
            StartGate.StartAction.LOAD,
            decide(biometricAvailable = false, enabledInSettings = true)
        )
        assertEquals(
            StartGate.StartAction.LOAD,
            decide(biometricAvailable = false, enabledInSettings = false)
        )
    }

    @Test
    fun `loads on a warm start`() {
        // Rotating the screen or coming back from another app must neither
        // prompt nor re-offer.
        assertEquals(
            StartGate.StartAction.LOAD,
            decide(coldStart = false, enabledInSettings = true)
        )
        assertEquals(
            StartGate.StartAction.LOAD,
            decide(coldStart = false, enabledInSettings = false)
        )
    }

    @Test
    fun `loads once the offer has been declined`() {
        // "No thanks" must be permanent. Re-asking after every login is the
        // behaviour that got PR #75 scrapped.
        assertEquals(
            StartGate.StartAction.LOAD,
            decide(declinedOffer = true, enabledInSettings = false)
        )
    }

    @Test
    fun `a decline never suppresses an already enabled feature`() {
        // The flag only gates the OFFER. Someone who enabled it and later
        // declined the (already answered) offer must still get their prompt.
        assertEquals(
            StartGate.StartAction.PROMPT,
            decide(declinedOffer = true, enabledInSettings = true)
        )
    }

    @Test
    fun `loads when the secret belongs to a different server`() {
        assertEquals(
            StartGate.StartAction.LOAD,
            decide(secretOrigin = "http://10.0.0.9:9967", enabledInSettings = true)
        )
        assertEquals(
            StartGate.StartAction.LOAD,
            decide(secretOrigin = "http://10.0.0.9:9967", enabledInSettings = false)
        )
    }

    @Test
    fun `loads when either origin is unknown`() {
        assertEquals(
            StartGate.StartAction.LOAD,
            decide(secretOrigin = null, enabledInSettings = true)
        )
        assertEquals(
            StartGate.StartAction.LOAD,
            decide(secretOrigin = "", enabledInSettings = true)
        )
        assertEquals(
            StartGate.StartAction.LOAD,
            decide(currentOrigin = null, enabledInSettings = true)
        )
        assertEquals(
            StartGate.StartAction.LOAD,
            decide(currentOrigin = "   ", enabledInSettings = true)
        )
    }

    @Test
    fun `an exact origin match is required ports included`() {
        // A cookie is scoped to its host and port. "http://host" and
        // "http://host:9967" are different origins, so they must not
        // silently share a stored secret.
        for (other in listOf(
            "http://192.168.1.50",
            "http://192.168.1.50:5000",
            "https://192.168.1.50:9967",
        )) {
            assertEquals(
                "must not accept $other",
                StartGate.StartAction.LOAD,
                decide(secretOrigin = other, enabledInSettings = true)
            )
        }
    }

    // ── normalizeOrigin ───────────────────────────────────────────────

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
    fun `normalize refuses a bare host with no scheme`() {
        // MainActivity already requires an explicit scheme when saving a
        // URL, so reaching here without one means the value is not ours.
        // Reject rather than guess.
        assertEquals("", StartGate.normalizeOrigin("192.168.1.50:9967"))
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
