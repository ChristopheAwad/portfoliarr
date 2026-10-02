// android/app/src/test/java/com/portfoliarr/app/UpdateGateTest.kt
// JUnit tests for the in-app update decision (roadmap #58): parsing the
// release tag the CI publishes, picking the APK file out of the release,
// reading the SHA-256 out of the release notes, and deciding whether the
// phone should offer anything at all.
//
// NO android.* / androidx.* imports on purpose; this runs on a plain JVM.
//
// The governing rule is that a wrong "up to date" is cheap and a wrong
// "update available" is expensive. A missed update is found on the next cold
// start. A bogus offer downloads and installs a file the user did not need,
// interrupts them, and — worst of all — teaches them to tap through the
// update box without reading it. So every uncertain condition — an
// unparseable tag, no APK file, no hash line, an older or equal build, a
// skipped version — answers UpToDate or Skipped, silently.

package com.portfoliarr.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class UpdateGateTest {

    private fun ref(code: Int) = UpdateGate.ReleaseRef(
        versionName = "1.2",
        versionCode = code,
        downloadUrl = "https://example.invalid/portfoliarr-1.2-$code.apk",
        sizeBytes = 1024,
        sha256 = "ab".repeat(32),
    )

    // ── parseReleaseTag ────────────────────────────────────────────────

    @Test
    fun `parses a two-part version tag`() {
        assertEquals("1.2" to 7, UpdateGate.parseReleaseTag("android-1.2-7"))
    }

    @Test
    fun `parses a three-part version tag`() {
        assertEquals("1.2.3" to 10, UpdateGate.parseReleaseTag("android-1.2.3-10"))
    }

    @Test
    fun `trims whitespace before matching`() {
        // Pasted or re-serialised tags may carry padding; the shape is what
        // matters, so surrounding whitespace is forgiven and documented here.
        assertEquals("1.2" to 7, UpdateGate.parseReleaseTag("  android-1.2-7\n"))
    }

    @Test
    fun `rejects a bare version without the android prefix`() {
        assertNull(UpdateGate.parseReleaseTag("v1.2"))
    }

    @Test
    fun `rejects a tag without a version code`() {
        assertNull(UpdateGate.parseReleaseTag("android-1.2"))
    }

    @Test
    fun `rejects a non-numeric version code`() {
        assertNull(UpdateGate.parseReleaseTag("android-1.2-x"))
    }

    @Test
    fun `rejects a missing version`() {
        assertNull(UpdateGate.parseReleaseTag("android--7"))
    }

    @Test
    fun `rejects empty blank and null tags`() {
        assertNull(UpdateGate.parseReleaseTag(""))
        assertNull(UpdateGate.parseReleaseTag("   "))
        assertNull(UpdateGate.parseReleaseTag(null))
    }

    @Test
    fun `tag prefix is case-sensitive`() {
        assertNull(UpdateGate.parseReleaseTag("Android-1.2-7"))
    }

    // ── parseAssetCode ─────────────────────────────────────────────────

    @Test
    fun `parses the code out of an asset name`() {
        assertEquals(7, UpdateGate.parseAssetCode("portfoliarr-1.2-7.apk"))
    }

    @Test
    fun `rejects an asset name without a code`() {
        assertNull(UpdateGate.parseAssetCode("portfoliarr-1.2.apk"))
    }

    @Test
    fun `rejects a non-apk asset name`() {
        assertNull(UpdateGate.parseAssetCode("portfoliarr-1.2-7.sha256"))
    }

    @Test
    fun `rejects a null asset name`() {
        assertNull(UpdateGate.parseAssetCode(null))
    }

    // ── pickApkAsset ───────────────────────────────────────────────────

    @Test
    fun `picks the single apk out of a mixed release`() {
        val names = listOf("notes.txt", "portfoliarr-1.2-7.apk", "portfoliarr-1.2-7.sha256")
        assertEquals("portfoliarr-1.2-7.apk", UpdateGate.pickApkAsset(names))
    }

    @Test
    fun `answers null when the release carries no apk`() {
        assertNull(UpdateGate.pickApkAsset(listOf("notes.txt", "portfoliarr-1.2-7.sha256")))
        assertNull(UpdateGate.pickApkAsset(emptyList()))
    }

    @Test
    fun `picks the highest code when several apks are attached`() {
        val names = listOf("portfoliarr-1.2-7.apk", "portfoliarr-1.2-9.apk")
        assertEquals("portfoliarr-1.2-9.apk", UpdateGate.pickApkAsset(names))
    }

    @Test
    fun `ignores an unparseable apk name in favour of a good one`() {
        val names = listOf("portfoliarr-latest.apk", "portfoliarr-1.2-7.apk")
        assertEquals("portfoliarr-1.2-7.apk", UpdateGate.pickApkAsset(names))
    }

    @Test
    fun `answers null when every apk name is unparseable`() {
        assertNull(UpdateGate.pickApkAsset(listOf("portfoliarr-latest.apk")))
    }

    // ── extractSha256 ──────────────────────────────────────────────────

    @Test
    fun `finds the hash line in release notes`() {
        val hex = "cd".repeat(32)
        val body = "Android 1.2 (7)\n\nSHA-256: $hex\n"
        assertEquals(hex, UpdateGate.extractSha256(body))
    }

    @Test
    fun `normalises an uppercase hash to lowercase`() {
        val hex = "EF".repeat(32)
        assertEquals(hex.lowercase(), UpdateGate.extractSha256("SHA-256: $hex"))
    }

    @Test
    fun `answers null when the hash line is missing`() {
        assertNull(UpdateGate.extractSha256("Android 1.2 (7)\nNo hash here.\n"))
        assertNull(UpdateGate.extractSha256(null))
    }

    @Test
    fun `rejects a short hash`() {
        assertNull(UpdateGate.extractSha256("SHA-256: " + "ab".repeat(31)))
    }

    // ── decideCheck ────────────────────────────────────────────────────

    @Test
    fun `offers a strictly newer build`() {
        assertEquals(
            UpdateGate.UpdateDecision.Available(ref(7)),
            UpdateGate.decideCheck(localCode = 6, remote = ref(7), skippedCode = null),
        )
    }

    @Test
    fun `stays quiet when the build is current or older`() {
        assertEquals(
            UpdateGate.UpdateDecision.UpToDate,
            UpdateGate.decideCheck(localCode = 7, remote = ref(7), skippedCode = null),
        )
        assertEquals(
            UpdateGate.UpdateDecision.UpToDate,
            UpdateGate.decideCheck(localCode = 8, remote = ref(7), skippedCode = null),
        )
    }

    @Test
    fun `stays quiet when there is no usable release`() {
        // A failed check, a 404, garbage JSON, an unparseable tag — all of
        // these arrive here as null, and all of them are silent.
        assertEquals(
            UpdateGate.UpdateDecision.UpToDate,
            UpdateGate.decideCheck(localCode = 6, remote = null, skippedCode = null),
        )
        assertEquals(
            UpdateGate.UpdateDecision.UpToDate,
            UpdateGate.decideCheck(localCode = 6, remote = null, skippedCode = 7),
        )
    }

    @Test
    fun `honours a skipped version`() {
        assertEquals(
            UpdateGate.UpdateDecision.Skipped,
            UpdateGate.decideCheck(localCode = 6, remote = ref(7), skippedCode = 7),
        )
    }

    @Test
    fun `a different skip does not suppress a newer build`() {
        assertEquals(
            UpdateGate.UpdateDecision.Available(ref(8)),
            UpdateGate.decideCheck(localCode = 6, remote = ref(8), skippedCode = 7),
        )
    }
}
