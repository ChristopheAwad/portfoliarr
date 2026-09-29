// android/app/src/test/java/com/portfoliarr/app/CookieHeaderTest.kt
// JUnit tests for the pure cookie helpers — no Android framework, so these
// run on a plain JVM via `./gradlew test`.
//
// The traps this covers, all of them real:
//   * a Flask session cookie is itsdangerous URLSafeBase64, so the value
//     contains '.', '-', '_' AND '=' padding. Splitting on '=' naively
//     truncates it.
//   * cookie NAMES are case-sensitive. "Session=" is not our cookie.
//   * the cookie must be re-set with HttpOnly and SameSite=Lax, because the
//     app is re-injecting it by hand. Losing those flags would silently
//     downgrade the protections app.py sets on the real login response.

package com.portfoliarr.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CookieHeaderTest {

    // ── extractSession ────────────────────────────────────────────────

    @Test
    fun `finds the session cookie among several`() {
        val header = "theme=dark; session=abc123; locale=en"
        assertEquals("abc123", CookieHeader.extractSession(header))
    }

    @Test
    fun `returns a real flask session value verbatim`() {
        // itsdangerous output: base64url segments joined by '.', '=' padded.
        val value = "eyJ1c2VyX2lkIjoxfQ.Zx9-_Qw8=="
        val header = "session=$value; other=1"
        assertEquals(value, CookieHeader.extractSession(header))
    }

    @Test
    fun `splits on the first equals sign only`() {
        // A value containing '=' must survive intact.
        assertEquals("a=b=c", CookieHeader.extractSession("session=a=b=c"))
    }

    @Test
    fun `cookie name is case sensitive`() {
        assertNull(CookieHeader.extractSession("Session=abc123"))
        assertNull(CookieHeader.extractSession("SESSION=abc123"))
    }

    @Test
    fun `null header yields null`() {
        assertNull(CookieHeader.extractSession(null))
    }

    @Test
    fun `empty header yields null`() {
        assertNull(CookieHeader.extractSession(""))
        assertNull(CookieHeader.extractSession("   "))
    }

    @Test
    fun `header without a session cookie yields null`() {
        assertNull(CookieHeader.extractSession("theme=dark; locale=en"))
    }

    @Test
    fun `empty session value is treated as absent`() {
        assertNull(CookieHeader.extractSession("session="))
        assertNull(CookieHeader.extractSession("session=; theme=dark"))
    }

    @Test
    fun `whitespace only session value is treated as absent`() {
        assertNull(CookieHeader.extractSession("session=   "))
    }

    @Test
    fun `the first of two session cookies wins`() {
        // RFC 6265 sends cookies longest-path-first, so the first entry is
        // the most specific one. In practice Flask sets a single session
        // cookie at "/", so this only pins that we do not quietly take a
        // later value instead.
        assertEquals(
            "new",
            CookieHeader.extractSession("session=new; path=/; session=old")
        )
    }

    @Test
    fun `tolerates missing spaces and empty segments`() {
        assertEquals("v1", CookieHeader.extractSession(";;session=v1;;"))
        assertEquals("v1", CookieHeader.extractSession("session=v1"))
    }

    @Test
    fun `skips segments that carry no usable name`() {
        // Bare flags and empty names must be stepped over rather than
        // misread, and must not stop the scan from finding a real cookie
        // further along the header.
        assertNull(CookieHeader.extractSession("secure"))
        assertNull(CookieHeader.extractSession("=abc123"))
        assertNull(CookieHeader.extractSession("HttpOnly; Secure"))
        assertEquals("v1", CookieHeader.extractSession("secure; session=v1"))
    }

    // ── buildRestoreCookieHeader ──────────────────────────────────────

    @Test
    fun `restore header re-applies the server's cookie protections`() {
        assertEquals(
            "session=abc; Path=/; Max-Age=2592000; HttpOnly; SameSite=Lax",
            CookieHeader.buildRestoreCookieHeader("abc")
        )
    }

    @Test
    fun `restore header keeps a full value intact`() {
        val value = "eyJ1c2VyX2lkIjoxfQ.Zx9-_Qw8=="
        val header = CookieHeader.buildRestoreCookieHeader(value)!!
        assertTrue(header.startsWith("session=$value;"))
        assertTrue(header.contains("HttpOnly"))
        assertTrue(header.contains("SameSite=Lax"))
    }

    @Test
    fun `restore header refuses an empty value`() {
        assertNull(CookieHeader.buildRestoreCookieHeader(""))
        assertNull(CookieHeader.buildRestoreCookieHeader("   "))
    }

    @Test
    fun `max age is thirty days`() {
        // Must stay in step with PERMANENT_SESSION_LIFETIME in app.py.
        assertEquals(30 * 24 * 60 * 60, CookieHeader.SESSION_MAX_AGE_SECONDS)
        assertEquals(2_592_000, CookieHeader.SESSION_MAX_AGE_SECONDS)
    }

    @Test
    fun `restore header never marks the cookie secure on plain http`() {
        // The LAN server is http://, and CookieManager refuses a Secure
        // attribute over http. Its absence is deliberate, not an oversight.
        assertFalse(CookieHeader.buildRestoreCookieHeader("abc")!!.contains("Secure"))
    }

    // ── sha256Hex ─────────────────────────────────────────────────────

    @Test
    fun `sha256 is stable and lowercase hex`() {
        val first = CookieHeader.sha256Hex("abc")
        assertEquals(first, CookieHeader.sha256Hex("abc"))
        assertEquals(64, first.length)
        assertTrue(first, first.all { it in "0123456789abcdef" })
    }

    @Test
    fun `sha256 matches the known vector for abc`() {
        assertEquals(
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            CookieHeader.sha256Hex("abc")
        )
    }

    @Test
    fun `sha256 of the empty string matches its known vector`() {
        assertEquals(
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            CookieHeader.sha256Hex("")
        )
    }

    @Test
    fun `sha256 changes on a one character difference`() {
        assertTrue(
            CookieHeader.sha256Hex("abc") != CookieHeader.sha256Hex("abd")
        )
    }
}
