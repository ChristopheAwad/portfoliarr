package com.portfoliarr.app.widget

import android.app.Activity
import android.appwidget.AppWidgetManager
import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.portfoliarr.app.CookieHeader
import com.portfoliarr.app.MainActivity
import com.portfoliarr.app.R
import com.portfoliarr.app.SecretStore
import com.portfoliarr.app.StartGate
import java.io.IOException

/**
 * The watchlist widget connect screen (#59).
 *
 * Unlike #51's config screen there is no portfolio to pick: the watchlist
 * belongs to the signed-in person. It borrows the app's already-saved login
 * ONCE to mint a watchlist-scoped read-only token over the session API.
 * Only the token is stored, in this app's private widget preferences; the
 * session itself is never persisted here and never logged.
 *
 * There is deliberately no biometric prompt: a widget's numbers are on the
 * public home screen by design. The activity returns RESULT_CANCELED the
 * moment it starts (so backing out cancels the widget placement), then
 * RESULT_OK with the launcher's appWidgetId once a token is stored.
 */
class WatchlistWidgetConfigActivity : AppCompatActivity() {

    private var appWidgetId = AppWidgetManager.INVALID_APPWIDGET_ID
    private var serverUrl: String? = null
    private var cookieHeader: String? = null

    private lateinit var status: TextView
    private lateinit var connect: Button
    private lateinit var retry: Button
    private lateinit var openApp: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setResult(Activity.RESULT_CANCELED)
        appWidgetId = intent.getIntExtra(
            AppWidgetManager.EXTRA_APPWIDGET_ID,
            AppWidgetManager.INVALID_APPWIDGET_ID,
        )
        if (appWidgetId == AppWidgetManager.INVALID_APPWIDGET_ID) {
            finish()
            return
        }

        setContentView(R.layout.activity_widget_watchlist_config)
        status = findViewById(R.id.watchlist_config_status)
        connect = findViewById(R.id.watchlist_config_connect)
        retry = findViewById(R.id.watchlist_config_retry)
        openApp = findViewById(R.id.watchlist_config_open_app)

        connect.setOnClickListener { connectWidget() }
        retry.setOnClickListener { connectWidget() }
        openApp.setOnClickListener {
            startActivity(Intent(this, MainActivity::class.java))
            finish()
        }

        serverUrl = getSharedPreferences("portfoliarr", MODE_PRIVATE)
            .getString("server_url", null)
        if (serverUrl.isNullOrBlank() || !MainActivity.isAllowedUrl(serverUrl!!)) {
            showBlocked(R.string.widget_config_no_server)
            return
        }

        val sessionValue = SecretStore(this).load()
        if (sessionValue.isNullOrBlank()) {
            showBlocked(R.string.widget_config_no_session)
            return
        }
        // The widget API needs a Cookie header, and the cookie's name is
        // the one constant the server and app already agree on.
        cookieHeader = "${CookieHeader.SESSION_COOKIE_NAME}=$sessionValue"

        status.setText(R.string.widget_watchlist_config_explainer)
        connect.visibility = View.VISIBLE
        connect.isEnabled = true
    }

    private fun showBlocked(messageRes: Int) {
        status.setText(messageRes)
        connect.visibility = View.GONE
        retry.visibility = View.GONE
        openApp.visibility = View.VISIBLE
    }

    private fun connectWidget() {
        val url = serverUrl ?: return
        val cookie = cookieHeader ?: return

        connect.isEnabled = false
        retry.visibility = View.GONE
        status.setText(R.string.widget_watchlist_config_loading)
        Thread {
            try {
                val created = WidgetApi.createWatchlistToken(url, cookie)
                runOnUiThread {
                    if (isFinishing || isDestroyed) return@runOnUiThread
                    WidgetStore(this).saveConfig(
                        appWidgetId,
                        created.token,
                        created.id,
                        "Watchlist",
                        StartGate.normalizeOrigin(url),
                    )
                    // The system does NOT call onUpdate after a config
                    // screen closes; the first paint must be asked for.
                    WatchlistWidgetProvider.refreshNow(this)
                    val result = Intent().putExtra(
                        AppWidgetManager.EXTRA_APPWIDGET_ID, appWidgetId)
                    setResult(Activity.RESULT_OK, result)
                    finish()
                }
            } catch (e: WidgetApi.UnauthorizedException) {
                runOnUiThread {
                    if (!isFinishing && !isDestroyed) {
                        showBlocked(R.string.widget_config_no_session)
                    }
                }
            } catch (e: IOException) {
                runOnUiThread {
                    if (!isFinishing && !isDestroyed) {
                        status.setText(R.string.widget_config_error)
                        connect.isEnabled = true
                        retry.visibility = View.VISIBLE
                    }
                }
            } catch (e: WidgetApi.ApiException) {
                runOnUiThread {
                    if (!isFinishing && !isDestroyed) {
                        status.setText(R.string.widget_config_error)
                        connect.isEnabled = true
                        retry.visibility = View.VISIBLE
                    }
                }
            } catch (e: Exception) {
                runOnUiThread {
                    if (!isFinishing && !isDestroyed) {
                        status.setText(R.string.widget_config_error)
                        connect.isEnabled = true
                        retry.visibility = View.VISIBLE
                    }
                }
            }
        }.start()
    }
}
