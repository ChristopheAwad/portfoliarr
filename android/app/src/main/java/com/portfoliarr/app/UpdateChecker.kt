// android/app/src/main/java/com/portfoliarr/app/UpdateChecker.kt
// The one network call the APK owns (roadmap #58): ask the GitHub releases
// API what the newest published phone build is.
//
// This class reports and never touches UI. Any failure — no network, a
// non-200 reply, garbage JSON, a tag that is not ours, no usable APK file —
// arrives at the caller as null, which MainActivity treats as "no update".
// A wrong null is a missed update found on the next cold start; a wrong
// release object would download a file onto the user's phone, so every
// uncertain condition answers null.
//
// Plain HttpURLConnection on a plain thread, parsed with org.json from the
// device runtime: no new Gradle dependency for one small GET.

package com.portfoliarr.app

import android.os.Handler
import android.os.Looper
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

class UpdateChecker {

    companion object {
        /** The only URL this class ever calls. Pinned by pytest. */
        const val RELEASES_URL =
            "https://api.github.com/repos/ChristopheAwad/portfoliarr/releases/latest"

        // A hung check must never hang the app: the whole call runs on a
        // background thread anyway, but bounded timeouts also stop a stalled
        // socket from holding that thread (and the user's patience) forever.
        const val CONNECT_TIMEOUT_MS = 15_000
        const val READ_TIMEOUT_MS = 15_000

        // GitHub rejects requests with no User-Agent. Android sends a default
        // one, but set ours so the API traffic is identifiable.
        const val USER_AGENT = "Portfoliarr-Android"
    }

    /**
     * Ask GitHub for the newest release, on a background thread. The
     * callback always runs on the main thread so the caller can touch UI
     * directly. Null means "no usable update", never an error to display —
     * the caller decides what (if anything) the user sees.
     */
    fun checkLatest(onResult: (UpdateGate.ReleaseRef?) -> Unit) {
        val main = Handler(Looper.getMainLooper())
        Thread {
            val release = try {
                fetchLatest()
            } catch (_: Exception) {
                // Airplane mode, DNS down, TLS failure, garbage bytes: all
                // of these are ordinary on a phone and all answer null.
                null
            }
            main.post { onResult(release) }
        }.start()
    }

    private fun fetchLatest(): UpdateGate.ReleaseRef? {
        val connection = (URL(RELEASES_URL).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            // Pin the API version: without this GitHub may one day answer a
            // differently shaped default and the parse below would misread it.
            setRequestProperty("Accept", "application/vnd.github+json")
            setRequestProperty("User-Agent", USER_AGENT)
            connectTimeout = CONNECT_TIMEOUT_MS
            readTimeout = READ_TIMEOUT_MS
        }
        try {
            if (connection.responseCode != 200) return null
            val body = connection.inputStream.bufferedReader().use { it.readText() }
            return parseRelease(JSONObject(body))
        } finally {
            connection.disconnect()
        }
    }

    private fun parseRelease(json: JSONObject): UpdateGate.ReleaseRef? {
        // optString/optJSONArray/optLong never throw on a missing key — a
        // half-shaped reply degrades to null instead of crashing the thread.
        val (versionName, versionCode) =
            UpdateGate.parseReleaseTag(json.optString("tag_name", "")) ?: return null
        val assets = json.optJSONArray("assets") ?: return null
        var bestCode = -1
        var bestUrl = ""
        var bestSize = 0L
        for (i in 0 until assets.length()) {
            val asset = assets.optJSONObject(i) ?: continue
            val code = UpdateGate.parseAssetCode(asset.optString("name", "")) ?: continue
            if (code > bestCode) {
                bestCode = code
                bestUrl = asset.optString("browser_download_url", "")
                bestSize = asset.optLong("size", 0L)
            }
        }
        // No usable APK, or an asset row without a download link: not ours.
        if (bestCode < 0 || bestUrl.isEmpty()) return null
        // The tag code and the APK code must agree. They always do for the
        // single-APK release workflow; a mismatch means the release is not
        // shaped the way this app expects, so fail closed rather than offer a
        // file whose version the tag does not describe.
        if (bestCode != versionCode) return null
        return UpdateGate.ReleaseRef(
            versionName = versionName,
            versionCode = versionCode,
            downloadUrl = bestUrl,
            sizeBytes = bestSize,
            sha256 = UpdateGate.extractSha256(json.optString("body", "")),
        )
    }
}
