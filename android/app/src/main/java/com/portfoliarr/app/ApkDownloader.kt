// android/app/src/main/java/com/portfoliarr/app/ApkDownloader.kt
// Download a verified update file (roadmap #58): stream the APK into the
// app-private cache, then prove it arrived complete BEFORE anyone installs
// it. A file that fails any check is deleted, never kept.
//
// Ordering is the whole safety story and is pinned by pytest: the SHA-256
// verification textually precedes the verified-ready report, and a missing
// expected hash aborts instead of skipping the check.

package com.portfoliarr.app

import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

class ApkDownloader {

    /**
     * What the download produced. MainActivity shows progress itself; this
     * only reports the outcome on the thread the caller chooses via
     * onProgress/onDone callers (both invoked on the download thread — the
     * caller posts to main).
     */
    sealed interface DownloadResult {
        /** The file is fully downloaded AND hash-verified. Installable. */
        data class Verified(val file: File) : DownloadResult

        /** Anything else: failed fetch, size lie, hash mismatch. */
        data class Failed(val reason: FailReason) : DownloadResult
    }

    enum class FailReason {
        NETWORK,
        SIZE_MISMATCH,
        HASH_MISMATCH,
        CANCELLED,
    }

    companion object {
        /** App-private cache subdir; the FileProvider exposes only this. */
        const val UPDATES_DIR = "updates"

        /** The single verified-file name both runs of the flow agree on. */
        const val UPDATE_FILE = "portfoliarr-update.apk"

        fun updateFile(cacheDir: File): File = File(File(cacheDir, UPDATES_DIR), UPDATE_FILE)

        /** Lowercase hex SHA-256 of a file. Null when the file is unreadable. */
        fun sha256HexOf(file: File): String? {
            return try {
                val digest = MessageDigest.getInstance("SHA-256")
                file.inputStream().use { input ->
                    val buffer = ByteArray(8192)
                    while (true) {
                        val read = input.read(buffer)
                        if (read < 0) break
                        digest.update(buffer, 0, read)
                    }
                }
                digest.digest().joinToString("") { "%02x".format(it) }
            } catch (_: Exception) {
                null
            }
        }
    }

    @Volatile
    private var cancelled = false

    fun cancel() {
        cancelled = true
    }

    /**
     * Stream [release.downloadUrl] to the update file. Progress is
     * bytes-read / expected size, or -1 when the size is unknown.
     *
     * Runs on the calling thread — MainActivity calls this on a background
     * thread. Returns Verified ONLY after the size check (when the release
     * states one) and the SHA-256 check both pass; every other path deletes
     * any partial file and returns Failed.
     */
    fun download(
        release: UpdateGate.ReleaseRef,
        cacheDir: File,
        onProgress: (bytesRead: Long, expectedBytes: Long) -> Unit,
    ): DownloadResult {
        val target = updateFile(cacheDir)
        target.parentFile?.mkdirs()
        target.delete()
        var connection: HttpURLConnection? = null
        try {
            connection = (URL(release.downloadUrl).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = UpdateChecker.CONNECT_TIMEOUT_MS
                readTimeout = UpdateChecker.READ_TIMEOUT_MS
            }
            if (connection.responseCode != 200) {
                return DownloadResult.Failed(FailReason.NETWORK)
            }
            val expected = release.sizeBytes.takeIf { it > 0 }
                ?: connection.contentLengthLong.takeIf { it > 0 }
                ?: -1L
            var read = 0L
            // Report at most every 256 KB: posting one UI update per 8 KB
            // chunk would flood the main thread for a multi-megabyte APK.
            var lastReported = 0L
            connection.inputStream.use { input ->
                target.outputStream().use { output ->
                    val buffer = ByteArray(8192)
                    while (true) {
                        if (cancelled) {
                            target.delete()
                            return DownloadResult.Failed(FailReason.CANCELLED)
                        }
                        val count = input.read(buffer)
                        if (count < 0) break
                        output.write(buffer, 0, count)
                        read += count
                        if (read - lastReported >= 262144) {
                            lastReported = read
                            onProgress(read, expected)
                        }
                    }
                }
            }
            // Final report so a determinate bar lands on 100%.
            onProgress(read, expected)
            // A lying size (truncated or padded transfer) is a corrupt file,
            // not an update: delete it rather than hash-checking garbage.
            if (expected > 0 && read != expected) {
                target.delete()
                return DownloadResult.Failed(FailReason.SIZE_MISMATCH)
            }
            // THE gate: no expected hash, or a hash that does not match, or
            // an unreadable file — all three delete and abort. A Verified
            // result below this line means the bytes equal the release notes.
            val expectedHash = release.sha256
            val actualHash = sha256HexOf(target)
            if (expectedHash == null || actualHash == null || !actualHash.equals(expectedHash, ignoreCase = true)) {
                target.delete()
                return DownloadResult.Failed(FailReason.HASH_MISMATCH)
            }
            return DownloadResult.Verified(target)
        } catch (_: Exception) {
            target.delete()
            return if (cancelled) {
                DownloadResult.Failed(FailReason.CANCELLED)
            } else {
                DownloadResult.Failed(FailReason.NETWORK)
            }
        } finally {
            connection?.disconnect()
        }
    }
}
