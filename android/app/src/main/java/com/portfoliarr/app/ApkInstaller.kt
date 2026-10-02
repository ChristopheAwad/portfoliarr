// android/app/src/main/java/com/portfoliarr/app/ApkInstaller.kt
// Hand a VERIFIED update file to Android's own installer (roadmap #58).
//
// Two deliberate limits. First, this class never decides WHAT to install —
// MainActivity only calls it with a file ApkDownloader reported Verified, so
// an unverified file cannot reach this code by accident. Second, there is no
// signature pre-check here: Android's installer refuses a wrongly-signed APK
// itself ("App not installed"), which is the authoritative backstop; the
// SHA-256 is the tripwire before it.
//
// Unknown sources (API 26+): the app cannot install until the user grants
// "install unknown apps" for Portfoliarr in system settings. Launching the
// install intent without it does nothing visible, so the caller must check
// first and route to settings instead. API 24–25 has no per-app gate — the
// old global switch covers it, and the toast in MainActivity points there.

package com.portfoliarr.app

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import java.io.File

class ApkInstaller {

    companion object {
        /** Must match the provider authorities in AndroidManifest.xml. */
        const val FILE_PROVIDER_AUTHORITY = "com.portfoliarr.app.fileprovider"

        const val APK_MIME_TYPE = "application/vnd.android.package-archive"

        fun contentUriFor(context: Context, file: File): Uri {
            return FileProvider.getUriForFile(context, FILE_PROVIDER_AUTHORITY, file)
        }

        fun buildInstallIntent(uri: Uri): Intent {
            return Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(uri, APK_MIME_TYPE)
                // The installer is a separate app: it needs a new task and
                // an explicit grant to read our private file, or the install
                // dies with a permission denial.
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
        }

        /** True on API 26+ once the user granted install-unknown-apps. */
        fun canInstallUnknownApps(context: Context): Boolean {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return true
            return context.packageManager.canRequestPackageInstalls()
        }

        /** The exact system screen that grants the permission, for this app. */
        fun unknownSourcesSettingsIntent(context: Context): Intent {
            return Intent(
                Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                Uri.parse("package:${context.packageName}"),
            )
        }
    }
}
