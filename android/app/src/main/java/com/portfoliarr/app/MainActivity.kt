package com.portfoliarr.app

import android.content.Intent
import android.os.Bundle
import android.os.SystemClock
import android.view.Menu
import android.view.MenuItem
import android.webkit.RenderProcessGoneDetail
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView

    // Renderer crash timestamps (elapsed-realtime ms): three crashes in
    // a minute means the PAGE is killing its own renderer, and reloading
    // the same URL just loops — fall back to the home URL instead.
    private var crashTimestamps = ArrayDeque<Long>()

    // Consecutive main-frame load failures. The app auto-opens Settings
    // once this reaches STUCK_LOAD_FAILURES: a URL that fails that many
    // times in a row is almost certainly wrong (not a blip), and without
    // an action bar the user has no other in-app path to fix it.
    // A single success resets it (see onPageFinished below).
    private var consecutiveLoadFailures = 0

    // Set to true when a MAIN-FRAME load fails (e.g. server unreachable,
    // network dropped). onResume() checks this and reloads the page so the
    // user doesn't have to force-kill the app after a network blip.
    // Subresource errors (fonts, CDN) do NOT set this — those are the web
    // app's JS-level problem, not a full-page recovery case.
    private var loadFailed = false

    // True when the CURRENT navigation errored. onPageFinished fires even
    // for error pages (an HTTP 500 still "finishes"), so the success reset
    // below must consult this instead of clearing blindly — otherwise an
    // HTTP error's own finish wipes the failure it just recorded and both
    // the resume recovery and the stuck-URL counter silently break.
    private var mainFrameErrored = false

    companion object {
        private const val STUCK_LOAD_FAILURES = 3
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Back navigation that survives API 33+: the platform
        // onBackPressed() override is deprecated — the dispatcher owns
        // back now. WebView history first, otherwise fall through to the
        // system (disable self so the event reaches the next handler).
        onBackPressedDispatcher.addCallback(
            this,
            object : OnBackPressedCallback(true) {
                override fun handleOnBackPressed() {
                    if (webView.canGoBack()) {
                        webView.goBack()
                    } else {
                        isEnabled = false
                        onBackPressedDispatcher.onBackPressed()
                    }
                }
            }
        )
        supportActionBar?.hide()

        // Build the WebView via the shared factory and put it on screen
        // directly — avoids inflating the XML layout's unconfigured
        // WebView, which would sit on screen as a blank white view while
        // the real one loads invisibly. This also matches the
        // onRenderProcessGone recovery path (which calls
        // setContentView(webView) after rebuilding), so both paths are
        // consistent and both WebViews get the same lifecycle calls.
        webView = createWebView()
        setContentView(webView)

        // Load saved URL or redirect to settings
        val prefs = getSharedPreferences("portfoliarr", MODE_PRIVATE)
        val url = prefs.getString("server_url", null)

        if (url.isNullOrBlank()) {
            startActivity(Intent(this, SettingsActivity::class.java))
        } else {
            webView.loadUrl(url)
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
                        consecutiveLoadFailures++
                        mainFrameErrored = true
                    }
                }

                override fun onPageFinished(view: WebView?, url: String?) {
                    // A finished navigation resets the failure state ONLY
                    // when the navigation itself did not error (an HTTP
                    // error page also "finishes" — clearing here would eat
                    // the error recorded above). No iframes exist in the
                    // app's templates, so this finish means the main frame.
                    if (view != null && url != null && !mainFrameErrored) {
                        loadFailed = false
                        consecutiveLoadFailures = 0
                    }
                    mainFrameErrored = false
                    super.onPageFinished(view, url)
                }

                override fun onReceivedHttpError(
                    view: WebView?, request: WebResourceRequest?,
                    errorResponse: WebResourceResponse?
                ) {
                    // Flask renders its own error pages (500/404) with HTTP
                    // status codes — without this the WebView shows a blank
                    // page, loadFailed stays false, and onResume never
                    // recovers. Only the main frame counts, same rule as
                    // onReceivedError above.
                    if (request?.isForMainFrame == true) {
                        loadFailed = true
                        consecutiveLoadFailures++
                        mainFrameErrored = true
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
                    this@MainActivity.recordCrashAndRebuild()
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
        //
        // STUCK ESCAPE: failures past STUCK_LOAD_FAILURES mean the saved
        // URL itself is wrong, and with no action bar there is no menu
        // path to Settings — so open Settings instead of reloading the
        // dead URL again. The counters reset, and saving an unchanged
        // (correct) URL there simply retries.
        if (loadFailed) {
            loadFailed = false
            if (consecutiveLoadFailures >= STUCK_LOAD_FAILURES) {
                consecutiveLoadFailures = 0
                startActivity(Intent(this, SettingsActivity::class.java))
                return
            }
            val url = webView.url
                ?: getSharedPreferences("portfoliarr", MODE_PRIVATE)
                    .getString("server_url", null)
            if (!url.isNullOrBlank()) {
                webView.loadUrl(url)
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

    // Count this crash and rebuild. A lone crash (background OOM kill)
    // reloads the page the user was on; three crashes within a minute
    // means the page itself is poison and would loop — go home instead.
    private fun recordCrashAndRebuild() {
        val now = SystemClock.elapsedRealtime()
        crashTimestamps.addLast(now)
        while (crashTimestamps.isNotEmpty()
            && now - crashTimestamps.first() > 60_000) {
            crashTimestamps.removeFirst()
        }
        rebuildWebView(fallbackToHome = crashTimestamps.size >= 3)
    }

    private fun rebuildWebView(fallbackToHome: Boolean) {
        // Prefer the page the user was actually on (a deep /stock link
        // survives a renderer crash); fall back to the saved home URL.
        // Captured BEFORE destroy() — afterwards the view is gone.
        // A crash loop (same page killing its renderer repeatedly) also
        // goes home instead of reloading the poison URL.
        val currentUrl = webView.url
        // Detach first so the dead view can never leak through the content
        // view; destroy() alone leaves it attached on some API levels.
        (webView.parent as? android.view.ViewGroup)?.removeView(webView)
        webView.clearHistory()
        webView.destroy()

        webView = createWebView()
        setContentView(webView)
        webView.onResume()

        val homeUrl = getSharedPreferences("portfoliarr", MODE_PRIVATE)
            .getString("server_url", null)
        val url = if (fallbackToHome) homeUrl else currentUrl ?: homeUrl
        if (!url.isNullOrBlank()) {
            webView.loadUrl(url)
        }
    }

    override fun onDestroy() {
        // The activity's own teardown path never destroyed the WebView —
        // only the crash path did — leaking the renderer on every rotate
        // (now rare with configChanges) and every back-out.
        (webView.parent as? android.view.ViewGroup)?.removeView(webView)
        webView.destroy()
        super.onDestroy()
    }

    // ── Menu ─────────────────────────────────────────────────────────

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
            else -> super.onOptionsItemSelected(item)
        }
    }
}
