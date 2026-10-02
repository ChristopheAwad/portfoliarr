package com.portfoliarr.app

import android.content.ActivityNotFoundException
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Menu
import android.view.MenuItem
import android.webkit.CookieManager
import android.webkit.RenderProcessGoneDetail
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.ProgressBar
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity

/**
 * Process-scoped flag, deliberately NOT an Activity field.
 *
 * The fingerprint prompt is for a COLD START only. Android destroys and
 * recreates an Activity for an ordinary rotation or a low-memory kill while
 * the process keeps running, and prompting again for those would be
 * maddening. A top-level object's state lives as long as the process, so it
 * is still true in a recreated Activity and false after the first unlock of
 * that process. Only a genuinely new process — the app fully closed, or
 * killed — starts it over at true.
 */
object AppState {
    var processFresh: Boolean = true

    // #58: the cold-start update check runs once per process. Set the first
    // time loadOnce fires (which is after the #57 gate resolves), so neither
    // a rotation nor a second load path can ask twice.
    var updateChecked: Boolean = false
}

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var secretStore: SecretStore
    private lateinit var biometricGate: BiometricGate

    // Set to true when a MAIN-FRAME load fails (e.g. server unreachable,
    // network dropped). onResume() checks this and reloads the page so the
    // user doesn't have to force-kill the app after a network blip.
    // Subresource errors (fonts, CDN) do NOT set this — those are the web
    // app's JS-level problem, not a full-page recovery case.
    private var loadFailed = false

    // The cold-start page load, issued at most once. See loadOnce().
    private var loadIssued = false

    // The pending unlock-timeout handler, so onDestroy can cancel it.
    private var unlockTimeout: Handler? = null

    // #58 in-app update state. The downloader runs on its own thread holding
    // no Activity reference beyond posted callbacks, but the progress dialog
    // is window-bound: onDestroy cancels the download and drops the dialog so
    // neither can fire into a dead Activity. A rotation mid-download is caught
    // there too, and lets the recreated Activity offer the update again.
    private var updateDownloader: ApkDownloader? = null
    private var updateProgressDialog: AlertDialog? = null

    // #58: set when the user is sent to system settings to grant
    // install-unknown-apps. onResume retries the install they already tapped
    // if — and only if — the grant is now present.
    private var pendingInstallAfterPermission = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        supportActionBar?.hide()

        secretStore = SecretStore(this)
        biometricGate = BiometricGate(this)
        // Build the WebView via the shared factory and put it on screen
        // directly — avoids inflating the XML layout's unconfigured
        // WebView, which would sit on screen as a blank white view while
        // the real one loads invisibly. This also matches the
        // onRenderProcessGone recovery path (which calls
        // setContentView(webView) after rebuilding), so both paths are
        // consistent and both WebViews get the same lifecycle calls.
        webView = createWebView()
        setContentView(webView)

        // Saved URL, or straight to settings if there isn't a usable one.
        val prefs = getSharedPreferences("portfoliarr", MODE_PRIVATE)
        val url = prefs.getString("server_url", null)

        if (url.isNullOrBlank() || !isAllowedUrl(url)) {
            startActivity(Intent(this, SettingsActivity::class.java))
            return
        }

        // THE GATE. This must run before the first loadUrl: the whole point
        // is that the portfolio is not on screen until the user has
        // authenticated. Three outcomes, and two of them are interruptions,
        // so decideStartAction answers LOAD unless every condition for
        // asking is genuinely met.
        val action = StartGate.decideStartAction(
            hasStoredSecret = secretStore.hasSecret(),
            biometricAvailable = biometricGate.isAvailable(),
            enabledInSettings = secretStore.isEnabled,
            declinedOffer = secretStore.declinedOffer,
            coldStart = AppState.processFresh,
            secretServerOrigin = secretStore.secretOrigin(),
            currentServerOrigin = StartGate.normalizeOrigin(url),
        )
        // Whatever we are about to do, this process has asked its one
        // question. Flipped before any dialog or prompt, so an Activity
        // rebuilt while either is up cannot ask a second time.
        AppState.processFresh = false

        when (action) {
            StartGate.StartAction.PROMPT -> promptThenLoad(url)
            StartGate.StartAction.OFFER -> offerThenLoad(url)
            // #58: the plain LOAD path must go through loadOnce too. If it
            // calls webView.loadUrl directly, the automatic update check —
            // which lives in loadOnce — never runs for a phone without
            // biometrics, or after the one-time offer is declined. Those are
            // the common cases.
            StartGate.StartAction.LOAD -> loadOnce(url)
        }
    }

    /**
     * The page load, issued at most once per Activity instance.
     *
     * Three different things want to trigger it — the prompt's answer, the
     * offer's dismissal, and a timeout rescue — and they race each other.
     * Without this guard a double trigger would reload the page underneath
     * the user, discarding whatever they were doing.
     */
    private fun loadOnce(url: String) {
        if (loadIssued) return
        loadIssued = true
        webView.loadUrl(url)
        // #58: the cold-start update check starts here — after the #57 gate
        // has resolved (prompt answered, offer dismissed, timeout, or plain
        // load). Renderer-crash rebuilds bypass loadOnce, and
        // AppState.updateChecked keeps this to once per process.
        maybeCheckForUpdates(manual = false)
    }

    /**
     * Ask ONCE whether the user wants fingerprint unlock at all, then load.
     *
     * This is the only way the feature turns itself on, because the
     * Settings screen that carries the switch is unreachable in the shipped
     * UI (MainActivity hides the action bar, and the gear lived in it — the
     * user rejected having it shown). So the question has to be asked where
     * the user already is, which is nowhere more intrusive than this.
     *
     * The dismissal listener is a guarantee, not a nicety: back button, tap
     * outside, or either button all converge on the load. A dialog that
     * could be dismissed without ever loading would leave a blank screen.
     */
    private fun offerThenLoad(url: String) {
        val dialog = AlertDialog.Builder(this)
            .setTitle(R.string.biometric_offer_title)
            .setMessage(R.string.biometric_offer_message)
            .setPositiveButton(R.string.biometric_offer_accept) { _, _ ->
                // The saved login is already there (capture runs whether or
                // not the feature is on), so this is all it takes to arm it.
                secretStore.setEnabled(true)
            }
            .setNegativeButton(R.string.biometric_offer_decline) { _, _ ->
                // Permanent. Re-asking after every sign-in is the nagging
                // that got PR #75 scrapped.
                secretStore.markDeclined()
            }
            .create()

        dialog.setOnDismissListener { loadOnce(url) }
        dialog.show()
    }

    /**
     * The prompt was cancelled, refused, or errored. Put the login page up
     * immediately — someone who cancelled wants their password, not another
     * wait — and float the ways out of this on top of it.
     *
     * The page is loaded before the dialog appears, so the dialog's own
     * dismissal needs no load: loadOnce has already fired and a second call
     * is a no-op.
     */
    private fun showCancelChoice() {
        AlertDialog.Builder(this)
            .setTitle(R.string.biometric_cancel_title)
            .setMessage(R.string.biometric_cancel_message)
            .setPositiveButton(R.string.biometric_use_my_password, null)
            .setNeutralButton(R.string.biometric_stop_asking) { _, _ ->
                // Both parts, deliberately. setEnabled(false) clears the
                // stored secret; without the decline the one-time offer
                // would come straight back after the next sign-in.
                secretStore.setEnabled(false)
                secretStore.markDeclined()
            }
            .setNegativeButton(R.string.biometric_forget) { _, _ ->
                SessionControl.forgetPhone(this, secretStore)
                Toast.makeText(
                    this, R.string.biometric_forget_done, Toast.LENGTH_SHORT
                ).show()
            }
            .show()
    }

    /**
     * Ask for the fingerprint, then load the page.
     *
     * Two one-shot guards, because there are two ways this could go wrong:
     *
     *   * [answered] makes the unlock a one-shot. BiometricPrompt reports
     *     through several callbacks and the timeout below races them, and
     *     without it a double answer would load twice and restore twice.
     *   * [loadOnce] makes the LOAD a one-shot, independently. The cookie
     *     write is asynchronous, so the page load is issued from inside its
     *     callback; if that callback were ever swallowed, only the timeout
     *     could still rescue the screen, and it must not be blocked by
     *     [answered] already being true.
     *
     * The timeout itself is a safety net, not a UX decision. A system prompt
     * always ends in onAuthenticationError, but if some OEM build or a
     * bizarre lifecycle state ever swallowed that, the user would otherwise
     * stare at a blank screen forever. Loading anyway degrades to the login
     * page, which is always a working answer.
     */
    private fun promptThenLoad(url: String) {
        val timeout = Handler(Looper.getMainLooper())
        // Kept so onDestroy can cancel it; see UNLOCK_TIMEOUT_MS.
        unlockTimeout = timeout

        var answered = false
        fun answer(unlocked: Boolean) {
            if (answered) return
            answered = true
            if (unlocked) {
                restoreSavedSession(url) { loadOnce(url) }
            } else {
                // Cancelled, refused, or the sensor failed. The login page
                // goes up now and the ways out of this float on top of it.
                loadOnce(url)
                // Posted rather than shown inline: BiometricPrompt pauses the
                // Activity and its callback is delivered around the resume.
                // Showing a dialog in the same breath can beat the window
                // token and throw BadTokenException, which on this path would
                // be a crash on the exact tap the user made to escape the
                // prompt. One message later is invisible and cannot lose the
                // race.
                Handler(Looper.getMainLooper()).post {
                    // ...and the Activity may be gone by then, if the user
                    // rotated or the system reclaimed it while the prompt was
                    // up. A dialog on a dead Activity is the same crash.
                    if (!isFinishing && !isDestroyed) showCancelChoice()
                }
            }
        }

        timeout.postDelayed({
            answer(false)
            // Belt and braces: answer(false) normally issues the load
            // itself, but if a cookie write is stuck this is what still
            // gets the page on screen.
            loadOnce(url)
        }, UNLOCK_TIMEOUT_MS)

        biometricGate.authenticate(
            getString(R.string.biometric_unlock_title),
            getString(R.string.biometric_unlock_subtitle),
        ) { unlocked ->
            timeout.removeCallbacksAndMessages(null)
            answer(unlocked)
        }
    }

    /**
     * Cancel anything that could fire into an Activity that is going away.
     *
     * The unlock timeout runs for up to 90 seconds. If the user rotates the
     * screen or the system reclaims the Activity while it is pending, the
     * callback would land on a destroyed instance and try to load a dead
     * WebView.
     */
    override fun onDestroy() {
        unlockTimeout?.removeCallbacksAndMessages(null)
        unlockTimeout = null
        // #58: a download outlives nothing — cancel it and drop its dialog
        // so neither touches this Activity after it is gone.
        if (updateDownloader != null) {
            // A download in flight dies with the Activity. Let a recreated
            // Activity run the check again so the update box and its Download
            // button come back; otherwise updateChecked would suppress it
            // until the next cold start.
            AppState.updateChecked = false
        }
        updateDownloader?.cancel()
        updateDownloader = null
        updateProgressDialog?.dismiss()
        updateProgressDialog = null
        super.onDestroy()
    }

    /**
     * Hand the stored cookie back to the WebView, then run [then].
     *
     * The cookie is re-set with HttpOnly and SameSite=Lax, which the server
     * applied to the original login response but which are lost when a cookie
     * is injected by hand. Skipping them would silently downgrade the session
     * on the one screen the user trusts most.
     *
     * [then] runs from the setCookie callback, NOT synchronously:
     * CookieManager.setCookie is asynchronous, and loading the page in the
     * same breath would race the write and land on the login form even though
     * the unlock succeeded. [then] also runs when there is nothing to
     * restore, so the caller has a single path either way.
     *
     * If the stored secret cannot be read, [then] still runs — the page then
     * simply lands on the login form, which is the intended fallback.
     */
    private fun restoreSavedSession(url: String, then: () -> Unit) {
        val header = secretStore.load()?.let { CookieHeader.buildRestoreCookieHeader(it) }
        if (header == null) {
            then()
            return
        }
        val cookies = CookieManager.getInstance()
        cookies.setCookie(url, header) {
            // Persist so the value survives the app process being killed.
            cookies.flush()
            then()
        }
    }

    /**
     * Keep the stored secret in step with the live one.
     *
     * Runs after every page load, which is the only moment a fresh session
     * cookie exists: the login POST redirects, onPageFinished fires, and the
     * jar now holds it.
     *
     * Deliberately NOT gated on the enabled flag. The one-time offer can
     * only happen if a login is already saved, and the user can only arm the
     * feature from that offer — so gating capture on the flag would make the
     * feature unreachable. What is stored is a cookie the app already holds
     * in memory, encrypted under a non-exportable key, and "Stop asking"
     * and "Forget this phone" both delete it.
     *
     * The stored value is compared by SHA-256, not read back, so sampling
     * never prompts from the background.
     */
    private fun captureSessionCookie(url: String) {
        val origin = StartGate.normalizeOrigin(url)
        if (origin.isEmpty()) return

        val live = CookieHeader.extractSession(
            CookieManager.getInstance().getCookie(url)
        )

        if (live == null) {
            // Landing on an auth page with no session cookie is what a logout
            // looks like from here — and a logout MUST stay logged out.
            //
            // Flask's session cookie is a stateless signed blob, so the server
            // cannot revoke the copy we already hold: replaying it would sign
            // the user straight back in. The stored secret therefore has to go
            // when the live cookie does, or tapping "Sign out" in the profile
            // menu would only last until the app was closed.
            if (StartGate.isAuthPath(url) && secretStore.hasSecret()) {
                secretStore.clear()
            }
            // Anything else with no cookie is just the login page before a
            // first sign-in: leave any stored secret completely alone.
            return
        }

        // A secret captured from a different server is never reused: handing
        // a cookie to a host it was not issued for would leak a live session.
        if (secretStore.hasSecret() &&
            secretStore.secretOrigin() != null &&
            secretStore.secretOrigin() != origin
        ) {
            secretStore.clear()
        }

        if (secretStore.storedCookieHash() ==
            CookieHeader.sha256Hex(live)
        ) {
            return
        }
        secretStore.save(live, origin)
    }

    // ── #58 in-app update ────────────────────────────────────────────
    // The single entry point for BOTH triggers. Automatic (from loadOnce,
    // once per process) shows a dialog ONLY when there is a newer build the
    // user has not skipped; every other outcome is silent. Manual (from the
    // menu) ignores the skip and always reports: up-to-date box, available
    // box, or failure toast. Neither path ever blocks the dashboard — the
    // network call runs on its own thread.

    private fun updatePrefs() = getSharedPreferences("portfoliarr", MODE_PRIVATE)

    @Suppress("DEPRECATION")
    private fun localVersionCode(): Int {
        // PackageManager, not BuildConfig: AGP 8 generates no BuildConfig by
        // default and enabling it would widen this diff for one integer.
        return packageManager.getPackageInfo(packageName, 0).versionCode
    }

    private fun clearPendingUpdate() {
        updatePrefs().edit()
            .remove("pending_update_code")
            .remove("pending_update_sha")
            .remove("pending_update_name")
            .apply()
    }

    private fun maybeCheckForUpdates(manual: Boolean) {
        if (manual) {
            runUpdateCheck(manual = true)
            return
        }
        if (AppState.updateChecked) return
        AppState.updateChecked = true
        // A verified-but-uninstalled file from a previous run: offer it
        // without downloading again. offerPendingUpdate owns the whole
        // outcome, including a fresh network check when the file is stale.
        if (offerPendingUpdate()) return
        runUpdateCheck(manual = false)
    }

    private fun runUpdateCheck(manual: Boolean) {
        UpdateChecker().checkLatest { release ->
            if (isFinishing || isDestroyed) return@checkLatest
            val skipped = if (updatePrefs().contains("skipped_update_code")) {
                updatePrefs().getInt("skipped_update_code", -1)
            } else {
                null
            }
            when (val decision = UpdateGate.decideCheck(
                localCode = localVersionCode(),
                remote = release,
                // Manual checks answer the true question; the skip is an
                // auto-check courtesy only.
                skippedCode = if (manual) null else skipped,
            )) {
                is UpdateGate.UpdateDecision.Available ->
                    showUpdateAvailable(decision.release)
                is UpdateGate.UpdateDecision.UpToDate ->
                    if (manual) {
                        if (release == null) {
                            showUpdateToast(R.string.update_check_failed)
                        } else {
                            showUpToDateBox()
                        }
                    }
                // else: silent on auto, unreachable on manual (skip is null
                // there, so Skipped cannot occur).
                is UpdateGate.UpdateDecision.Skipped -> Unit
            }
        }
    }

    /**
     * Offer a previously verified file, if one is still valid. Returns true
     * when a pending key existed; this method then owns the outcome — it
     * shows the install box, or, when the file is stale, clears it and falls
     * through to a fresh network check. Returns false when nothing is pending.
     *
     * The SHA-256 runs on a background thread: hashing a full APK on the main
     * thread at cold start would freeze the dashboard.
     */
    private fun offerPendingUpdate(): Boolean {
        val prefs = updatePrefs()
        if (!prefs.contains("pending_update_code")) return false
        val code = prefs.getInt("pending_update_code", -1)
        val expectedHash = prefs.getString("pending_update_sha", null)
        val name = prefs.getString("pending_update_name", null)
        val file = ApkDownloader.updateFile(cacheDir)
        // Cheap staleness checks on the main thread first. A wrong offer here
        // is worse than a redundant download, so anything uncertain clears.
        if (code <= localVersionCode() || name == null || !file.exists() ||
            expectedHash == null
        ) {
            clearPendingUpdate()
            runUpdateCheck(manual = false)
            return true
        }
        Thread {
            val actual = ApkDownloader.sha256HexOf(file)
            runOnUiThread {
                if (isFinishing || isDestroyed) return@runOnUiThread
                if (actual != null && actual == expectedHash.lowercase()) {
                    showInstallReady(file, name)
                } else {
                    clearPendingUpdate()
                    runUpdateCheck(manual = false)
                }
            }
        }.start()
        return true
    }

    private fun showUpToDateBox() {
        if (isFinishing || isDestroyed) return
        AlertDialog.Builder(this)
            .setMessage(R.string.update_up_to_date)
            .setPositiveButton(android.R.string.ok, null)
            .show()
    }

    private fun showUpdateToast(messageRes: Int) {
        Toast.makeText(this, messageRes, Toast.LENGTH_LONG).show()
    }

    private fun showUpdateAvailable(release: UpdateGate.ReleaseRef) {
        if (isFinishing || isDestroyed) return
        val sizeMb = if (release.sizeBytes > 0) {
            String.format(java.util.Locale.US, "%.1f", release.sizeBytes / 1048576.0)
        } else {
            "?"
        }
        AlertDialog.Builder(this)
            .setTitle(R.string.update_available_title)
            .setMessage(getString(
                R.string.update_available_message, release.versionName, sizeMb
            ))
            .setPositiveButton(R.string.update_download) { _, _ ->
                startUpdateDownload(release)
            }
            .setNeutralButton(R.string.update_later, null)
            .setNegativeButton(R.string.update_skip) { _, _ ->
                // Permanent for exactly this build. A still newer build
                // later is a different question and is asked normally.
                updatePrefs().edit()
                    .putInt("skipped_update_code", release.versionCode)
                    .apply()
            }
            .show()
    }

    private fun startUpdateDownload(release: UpdateGate.ReleaseRef) {
        if (isFinishing || isDestroyed) return
        val downloader = ApkDownloader()
        updateDownloader = downloader
        val progressBar = ProgressBar(
            this, null, android.R.attr.progressBarStyleHorizontal
        ).apply {
            isIndeterminate = true
            max = 100
        }
        val density = resources.displayMetrics.density
        val container = FrameLayout(this).apply {
            val horizontal = (24 * density).toInt()
            setPadding(horizontal, (12 * density).toInt(), horizontal, 0)
            addView(progressBar)
        }
        updateProgressDialog = AlertDialog.Builder(this)
            .setTitle(R.string.update_downloading_title)
            .setView(container)
            .setNegativeButton(R.string.cancel) { _, _ -> downloader.cancel() }
            .setCancelable(false)
            .create()
        updateProgressDialog?.show()
        Thread {
            val result = downloader.download(release, cacheDir) { read, expected ->
                runOnUiThread {
                    // A late progress post can land after onDestroy; touching
                    // the dead dialog's bar then would crash.
                    if (isFinishing || isDestroyed) return@runOnUiThread
                    if (expected > 0) {
                        progressBar.isIndeterminate = false
                        progressBar.progress =
                            ((read * 100) / expected).toInt().coerceIn(0, 100)
                    }
                }
            }
            runOnUiThread {
                updateDownloader = null
                updateProgressDialog?.dismiss()
                updateProgressDialog = null
                if (isFinishing || isDestroyed) return@runOnUiThread
                when (result) {
                    is ApkDownloader.DownloadResult.Verified -> {
                        // Remembered so the next cold start can offer the
                        // install without re-downloading.
                        updatePrefs().edit()
                            .putInt("pending_update_code", release.versionCode)
                            .putString("pending_update_sha", release.sha256)
                            .putString("pending_update_name", release.versionName)
                            .apply()
                        showInstallReady(result.file, release.versionName)
                    }
                    is ApkDownloader.DownloadResult.Failed -> when (result.reason) {
                        ApkDownloader.FailReason.CANCELLED ->
                            showUpdateToast(R.string.update_download_cancelled)
                        ApkDownloader.FailReason.HASH_MISMATCH ->
                            showUpdateToast(R.string.update_hash_mismatch)
                        else ->
                            showUpdateToast(R.string.update_download_failed)
                    }
                }
            }
        }.start()
    }

    private fun showInstallReady(file: java.io.File, versionName: String) {
        if (isFinishing || isDestroyed) return
        AlertDialog.Builder(this)
            .setTitle(R.string.update_install_ready_title)
            .setMessage(getString(
                R.string.update_install_ready_message, versionName
            ))
            .setPositiveButton(R.string.update_install) { _, _ ->
                tryInstallUpdate(file)
            }
            // Declining keeps the pending keys: the next cold start offers
            // the install again without re-downloading.
            .setNegativeButton(R.string.update_later, null)
            .show()
    }

    private fun tryInstallUpdate(file: java.io.File) {
        if (!file.exists()) {
            clearPendingUpdate()
            showUpdateToast(R.string.update_download_failed)
            return
        }
        if (!ApkInstaller.canInstallUnknownApps(this)) {
            // API 26+: without the grant the install intent would die
            // silently, so route to the exact system screen instead and
            // retry from onResume when the user returns.
            pendingInstallAfterPermission = true
            AlertDialog.Builder(this)
                .setTitle(R.string.update_unknown_sources_title)
                .setMessage(R.string.update_unknown_sources_message)
                .setPositiveButton(R.string.update_open_settings) { _, _ ->
                    startActivity(ApkInstaller.unknownSourcesSettingsIntent(this))
                }
                .setNegativeButton(R.string.cancel) { _, _ ->
                    pendingInstallAfterPermission = false
                }
                .show()
            return
        }
        launchInstaller(file)
    }

    private fun launchInstaller(file: java.io.File) {
        val uri = ApkInstaller.contentUriFor(this, file)
        try {
            startActivity(ApkInstaller.buildInstallIntent(uri))
        } catch (_: ActivityNotFoundException) {
            // No installer on the device: report it instead of crashing.
            showUpdateToast(R.string.update_download_failed)
        }
    }

    companion object {
        // Generous enough for a deliberate, unhurried unlock, short enough
        // that a swallowed callback is not a permanently blank screen.
        private const val UNLOCK_TIMEOUT_MS = 90_000L

        // LAN WebView may only load http(s) URLs. A value saved before
        // validation existed (or edited outside the settings form) must
        // never reach loadUrl — notably javascript: URLs.
        fun isAllowedUrl(url: String): Boolean {
            val lower = url.trim().lowercase()
            if (lower.startsWith("javascript:")) return false
            return lower.startsWith("http://") || lower.startsWith("https://")
        }
    }

    // ── WebView factory ────────────────────────────────────────────────
    // Extracted from onCreate so onRenderProcessGone can rebuild a fresh
    // WebView without duplicating the client/settings setup. Every call
    // returns a NEW instance — the old one must be destroyed first.

    private fun createWebView(): WebView {
        return WebView(this).apply {
            settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true
                allowFileAccess = false
                allowContentAccess = false
            }

            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(
                    view: WebView?, request: WebResourceRequest?
                ): Boolean {
                    // Keep all navigation inside the WebView
                    return false
                }

                override fun onReceivedError(
                    view: WebView?, request: WebResourceRequest?, error: WebResourceError?
                ) {
                    // Only flag main-frame errors — subresource failures
                    // (fonts, CDN, analytics) must not trigger a full page
                    // reload. The web app's JS handles its own per-fetch
                    // error toasts ("Could not reach the server").
                    if (request?.isForMainFrame == true) {
                        loadFailed = true
                    }
                }

                // The session cookie only exists once a login has completed,
                // and the login POST redirects — so onPageFinished is the
                // moment there is something worth saving. Errors never reach
                // here, which is why a failed load cannot overwrite a good
                // stored secret.
                override fun onPageFinished(view: WebView, url: String) {
                    super.onPageFinished(view, url)
                    if (isAllowedUrl(url)) {
                        captureSessionCookie(url)
                    }
                }

                // Renderer crash recovery. This callback belongs to the
                // WebViewClient, NOT the Activity — Kotlin's `override`
                // only compiles here (AppCompatActivity has no such
                // method, so a class-level override fails with
                // "overrides nothing"). After hours in the background
                // Android may reclaim the WebView's renderer process
                // (OOM, memory pressure), leaving a dead blank screen
                // that can never recover on its own. Requires API 26;
                // on older devices it simply never fires.
                override fun onRenderProcessGone(
                    view: WebView, detail: RenderProcessGoneDetail
                ): Boolean {
                    this@MainActivity.rebuildWebView()
                    // Return true = we handled it (don't kill the activity).
                    return true
                }
            }
        }
    }

    // ── Lifecycle ──────────────────────────────────────────────────────

    override fun onResume() {
        super.onResume()
        webView.onResume()

        // If the page failed to load while we were backgrounded (Doze cut
        // the network, Wi-Fi slept, etc.), reload now that we're back in
        // the foreground. Only reload on failure — an unconditional reload
        // would wipe open dialogs and edit forms every time the user
        // alt-tabs back; instant-freshness-on-return is the JS layer's
        // job (common.js's setupAutoRefresh).
        if (loadFailed) {
            loadFailed = false
            val url = webView.url
                ?: getSharedPreferences("portfoliarr", MODE_PRIVATE)
                    .getString("server_url", null)
            if (!url.isNullOrBlank() && isAllowedUrl(url)) {
                webView.loadUrl(url)
            }
        }

        // #58: the user returns from the system unknown-sources screen. The
        // flag is cleared on EVERY return; the installer fires only when the
        // grant is genuinely present now. No grant, no loop, no nag.
        if (pendingInstallAfterPermission) {
            pendingInstallAfterPermission = false
            if (ApkInstaller.canInstallUnknownApps(this)) {
                val file = ApkDownloader.updateFile(cacheDir)
                if (file.exists()) {
                    launchInstaller(file)
                } else {
                    clearPendingUpdate()
                }
            }
        }
    }

    override fun onPause() {
        // Pause the WebView's JS timers while backgrounded. Without this,
        // setInterval continues firing in the background, generating a
        // storm of failed-fetch toasts when the network drops during Doze.
        webView.onPause()
        super.onPause()
    }

    // ── Renderer crash recovery ────────────────────────────────────────
    // The actual rebuild the WebViewClient's onRenderProcessGone asks
    // for: destroy the dead WebView, build a fresh one, put it on
    // screen, and reload. Kept as an Activity method (not inside the
    // client) because it mutates the activity's webView field and
    // content view.

    private fun rebuildWebView() {
        webView.destroy()

        webView = createWebView()
        setContentView(webView)
        webView.onResume()

        val url = getSharedPreferences("portfoliarr", MODE_PRIVATE)
            .getString("server_url", null)
        if (!url.isNullOrBlank() && isAllowedUrl(url)) {
            webView.loadUrl(url)
        }
    }

    // ── Menu & back ────────────────────────────────────────────────────

    override fun onCreateOptionsMenu(menu: Menu?): Boolean {
        menuInflater.inflate(R.menu.main_menu, menu)
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        return when (item.itemId) {
            R.id.action_settings -> {
                startActivity(Intent(this, SettingsActivity::class.java))
                true
            }
            // #58: dormant while the action bar is hidden (see
            // main_menu.xml), but wired and tested for the day it returns.
            R.id.action_check_update -> {
                maybeCheckForUpdates(manual = true)
                true
            }
            else -> super.onOptionsItemSelected(item)
        }
    }

    @Suppress("DEPRECATION")
    override fun onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack()
        } else {
            super.onBackPressed()
        }
    }
}
