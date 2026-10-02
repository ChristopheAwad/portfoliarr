// android/app/src/main/java/com/portfoliarr/app/UpdateGate.kt
// The in-app update decision for roadmap #58: parsing the release tag CI
// publishes, picking the APK out of a release, reading the SHA-256 out of
// the release notes, and deciding whether the phone should offer anything.
//
// NO android.* / androidx.* imports on purpose — UpdateGateTest.kt runs this
// on a plain JVM.
//
// The governing rule is that a wrong "up to date" is cheap and a wrong
// "update available" is expensive. A missed update is found on the next cold
// start. A bogus offer downloads and installs a file the user did not need
// and teaches them to tap through the update box without reading it. So
// every uncertain condition — an unparseable tag, no APK file, no hash line,
// an older or equal build, a skipped version — answers UpToDate or Skipped,
// silently.

package com.portfoliarr.app

object UpdateGate {

    /**
     * A usable update release, as read off the GitHub releases API.
     *
     * versionName is display text only and never a comparison input; only
     * versionCode decides newness. sha256 is null when the release notes
     * carry no hash line — and a null hash means "do not install".
     */
    data class ReleaseRef(
        val versionName: String,
        val versionCode: Int,
        val downloadUrl: String,
        val sizeBytes: Long,
        val sha256: String?,
    )

    /**
     * What MainActivity should do about updates.
     *
     * Three outcomes, not a yes/no. A boolean could not express the
     * difference between "there is nothing newer" and "there is something
     * newer but the user asked not to hear about this one", and collapsing
     * them is how a skip turns into a nag.
     */
    sealed interface UpdateDecision {
        /** Offer this release to the user. */
        data class Available(val release: ReleaseRef) : UpdateDecision

        /** Nothing newer, or nothing usable. Stay silent. */
        data object UpToDate : UpdateDecision

        /** Newer, but the user skipped exactly this build. Stay silent. */
        data object Skipped : UpdateDecision
    }

    // Must match the tag the Publish Android release workflow creates:
    // android-<VERSION>-<VERSION_CODE>, e.g. android-1.2-7. The same shape
    // is pinned in tests/test_android_update.py so CI and the app cannot
    // drift apart unnoticed.
    private val TAG_REGEX = Regex("""^android-([0-9]+\.[0-9]+(?:\.[0-9]+)?)-([0-9]+)$""")

    // The trailing -<CODE>.apk of portfoliarr-<VERSION>-<CODE>.apk.
    private val ASSET_CODE_REGEX = Regex("""-([0-9]+)\.apk$""")

    // The verification line CI writes into the release notes, e.g.
    // "SHA-256: cdcd...cd". Multiline: the notes carry human text too.
    private val SHA_REGEX = Regex("""(?m)^SHA-256:\s*([0-9a-fA-F]{64})\s*$""")

    /**
     * Split a release tag into (versionName, versionCode), or null when the
     * tag is not ours. Surrounding whitespace is trimmed before matching;
     * anything else malformed is a hard no rather than a guess.
     */
    fun parseReleaseTag(tag: String?): Pair<String, Int>? {
        val match = TAG_REGEX.matchEntire(tag?.trim().orEmpty()) ?: return null
        val code = match.groupValues[2].toIntOrNull() ?: return null
        return match.groupValues[1] to code
    }

    /**
     * Read the version code out of an asset file name, or null when the
     * name does not fit the contract. Extension match is case-sensitive:
     * "Foo.APK" is not our file.
     */
    fun parseAssetCode(assetName: String?): Int? {
        if (assetName.isNullOrEmpty()) return null
        if (!assetName.endsWith(".apk")) return null
        return ASSET_CODE_REGEX.find(assetName)?.groupValues?.get(1)?.toIntOrNull()
    }

    /**
     * Pick the APK file out of a release's asset names. Highest parsed code
     * wins when several qualify; unparseable names are ignored; no usable
     * APK means null, which the caller treats as "no update".
     */
    fun pickApkAsset(names: List<String>): String? {
        return names
            .mapNotNull { name -> parseAssetCode(name)?.let { code -> code to name } }
            .maxByOrNull { (code, _) -> code }
            ?.second
    }

    /**
     * Read the expected SHA-256 out of release notes, lowercase, or null
     * when no hash line is present. Null means "do not install", never
     * "skip the check".
     */
    fun extractSha256(body: String?): String? {
        if (body.isNullOrEmpty()) return null
        return SHA_REGEX.find(body)?.groupValues?.get(1)?.lowercase()
    }

    /**
     * The one question MainActivity asks about updates.
     *
     * The ordering is the whole design, and it is deliberately
     * conservative: every uncertain input answers UpToDate. A null remote —
     * failed check, 404, garbage JSON, unparseable tag, no APK — is silent.
     * An equal or older build is silent. Only a strictly newer build the
     * user has not skipped earns an offer.
     */
    fun decideCheck(
        localCode: Int,
        remote: ReleaseRef?,
        skippedCode: Int?,
    ): UpdateDecision {
        if (remote == null) return UpdateDecision.UpToDate
        if (remote.versionCode <= localCode) return UpdateDecision.UpToDate
        if (skippedCode == remote.versionCode) return UpdateDecision.Skipped
        return UpdateDecision.Available(remote)
    }
}
