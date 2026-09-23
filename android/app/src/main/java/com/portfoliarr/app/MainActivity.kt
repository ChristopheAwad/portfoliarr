package com.portfoliarr.app

import android.content.Intent
import android.os.Bundle
import android.view.Menu
import android.view.MenuItem
import android.webkit.RenderProcessGoneDetail
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient

class MainActivity : AppLockActivity() {

    private lateinit var webView: WebView

    // Set to true when a MAIN-FRAME load fails (e.g. server unreachable,
    // network dropped). onResume() checks this and reloads the page so the
    // user doesn't have to force-kill the app after a network blip.
    // Subresource errors (fonts, CDN) do NOT set this — those are the web
    // app's JS-level problem, not a full-page recovery case.
    private var loadFailed = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Keep the native bar visible. Its gear opens the URL and app-lock
        // controls even after the server URL has already been saved.

        // Build the WebView via the shared factory and put it on screen
        // directly — avoids inflating the XML layout's unconfigured
        // WebView, which would sit on screen as a blank white view while
        // the real one loads invisibly. This also matches the
        // onRenderProcessGone recovery path (which calls
        // setContentView(webView) after rebuilding), so both paths are
        // consistent and both WebViews get the same lifecycle calls.
        webView = createWebView()
        setContentView(webView)
        ensureLockCover()

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

    private fun rebuildWebView() {
        webView.destroy()

        webView = createWebView()
        setContentView(webView)
        ensureLockCover()
        webView.onResume()

        val url = getSharedPreferences("portfoliarr", MODE_PRIVATE)
            .getString("server_url", null)
        if (!url.isNullOrBlank()) {
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
