package com.portfoliarr.app

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertEquals
import org.junit.Test

class AppLockPolicyTest {
    @Test fun disabledByDefault() {
        val policy = AppLockPolicy()
        assertFalse(policy.requiresAuthentication(0, false, AppLockPolicy.DEFAULT_TIMEOUT_MS))
        assertEquals(300_000L, AppLockPolicy.DEFAULT_TIMEOUT_MS)
    }

    @Test fun enabledColdStartRequiresAuthentication() {
        assertTrue(AppLockPolicy().requiresAuthentication(0, true, AppLockPolicy.DEFAULT_TIMEOUT_MS))
    }

    @Test fun fiveMinuteBoundaryAndRepeatedReturns() {
        val policy = AppLockPolicy()
        policy.authenticated()
        policy.backgrounded(1000)
        assertFalse(policy.requiresAuthentication(300_999, true, 300_000))
        assertFalse(policy.requiresAuthentication(300_999, true, 300_000))
        // Once back in the foreground, the old deadline no longer applies.
        assertFalse(policy.requiresAuthentication(301_000, true, 300_000))
        policy.backgrounded(400_000)
        assertTrue(policy.requiresAuthentication(700_000, true, 300_000))
        assertTrue(policy.requiresAuthentication(700_001, true, 300_000))
    }

    @Test fun everySelectableDelayHasAnExactBoundary() {
        for (delay in listOf(0L, 60_000L, 300_000L, 900_000L)) {
            val policy = AppLockPolicy()
            policy.authenticated()
            policy.backgrounded(500)
            if (delay > 0) assertFalse(policy.requiresAuthentication(500 + delay - 1, true, delay))
            // The exact-boundary case is a separate trip; the early return
            // above ended the first background trip.
            val boundary = AppLockPolicy()
            boundary.authenticated()
            boundary.backgrounded(500)
            assertTrue(boundary.requiresAuthentication(500 + delay, true, delay))
        }
    }

    @Test fun unknownSavedTimeoutFallsBackToFiveMinutes() {
        for (delay in listOf(-1L, 1L, 120_000L)) {
            val policy = AppLockPolicy()
            policy.authenticated()
            policy.backgrounded(100)
            assertFalse(policy.requiresAuthentication(300_099, true, delay))
            val boundary = AppLockPolicy()
            boundary.authenticated()
            boundary.backgrounded(100)
            assertTrue(boundary.requiresAuthentication(300_100, true, delay))
        }
    }

    @Test fun clockRebootLocksAndSuccessStartsNewSession() {
        val policy = AppLockPolicy()
        policy.authenticated()
        policy.backgrounded(400_000)
        assertTrue(policy.requiresAuthentication(100, true, 300_000))
        policy.authenticated()
        assertFalse(policy.requiresAuthentication(100, true, 300_000))
        policy.backgrounded(200)
        assertFalse(policy.requiresAuthentication(201, true, 300_000))
    }

    @Test fun failureAndCancellationNeverUnlock() {
        val policy = AppLockPolicy()
        policy.authenticationFailed()
        assertTrue(policy.requiresAuthentication(0, true, 300_000))
        policy.authenticated()
        policy.backgrounded(0)
        policy.authenticationFailed()
        assertTrue(policy.requiresAuthentication(1, true, 300_000))
    }

    @Test fun eachNewBackgroundTripStartsAtItsOwnTime() {
        val policy = AppLockPolicy()
        policy.authenticated()
        policy.backgrounded(100)
        assertFalse(policy.requiresAuthentication(59_999, true, 60_000))
        policy.backgrounded(60_000)
        assertFalse(policy.requiresAuthentication(119_999, true, 60_000))
        policy.backgrounded(120_000)
        assertTrue(policy.requiresAuthentication(180_000, true, 60_000))
    }
}
