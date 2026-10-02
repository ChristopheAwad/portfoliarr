package com.portfoliarr.app.widget

import android.app.Activity
import android.appwidget.AppWidgetManager
import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.Spinner
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.portfoliarr.app.CookieHeader
import com.portfoliarr.app.MainActivity
import com.portfoliarr.app.R
import com.portfoliarr.app.SecretStore
import com.portfoliarr.app.StartGate
import java.io.IOException

/**
 * The widget connect screen (#51).
 *
 * The launcher starts this when a widget is added (android:configure in
 * widget_info.xml). It borrows the app's already-saved login ONCE to list
 * portfolios over the session API, then asks the server to mint a scoped
 * read-only token for the chosen portfolio. Only the token is stored, in
 * this app's private widget preferences; the session itself is never
 * persisted here and never logged.
 *
 * There is deliberately no biometric prompt: a widget's numbers are on the
 * public home screen by design, so adding one is already an explicit choice
 * to show totals. The saved session is only used to create the token.
 *
 * The activity always returns: RESULT_CANCELED the moment it starts (so
 * backing out cancels the widget placement), then RESULT_OK with the
 * launcher's appWidgetId once a token is stored. That contract is what
 * makes the launcher actually place the widget.
 */
class WidgetConfigActivity : AppCompatActivity() {

    private var appWidgetId = AppWidgetManager.INVALID_APPWIDGET_ID
    private var serverUrl: String? = null
    private var cookieHeader: String? = null
    private var portfolios: List<WidgetApi.PortfolioRef> = emptyList()

    private lateinit var status: TextView
    private lateinit var spinner: Spinner
    private lateinit var connect: Button
    private lateinit var retry: Button
    private lateinit var openApp: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Cancel first: if anything below returns early or the user backs
        // out, the launcher must not place a half-configured widget.
        setResult(Activity.RESULT_CANCELED)
        appWidgetId = intent.getIntExtra(
            AppWidgetManager.EXTRA_APPWIDGET_ID,
            AppWidgetManager.INVALID_APPWIDGET_ID,
        )
        if (appWidgetId == AppWidgetManager.INVALID_APPWIDGET_ID) {
            finish()
            return
        }

        setContentView(R.layout.activity_widget_config)
        status = findViewById(R.id.config_status)
        spinner = findViewById(R.id.config_portfolio)
        connect = findViewById(R.id.config_connect)
        retry = findViewById(R.id.config_retry)
        openApp = findViewById(R.id.config_open_app)

        connect.setOnClickListener { connectWidget() }
        retry.setOnClickListener { loadPortfolios() }
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

        loadPortfolios()
    }

    private fun showBlocked(messageRes: Int) {
        status.setText(messageRes)
        spinner.visibility = View.GONE
        connect.visibility = View.GONE
        retry.visibility = View.GONE
        openApp.visibility = View.VISIBLE
    }

    private fun loadPortfolios() {
        val url = serverUrl ?: return
        val cookie = cookieHeader ?: return
        retry.visibility = View.GONE
        connect.isEnabled = false
        status.setText(R.string.widget_config_loading)
        Thread {
            try {
                val loaded = WidgetApi.listPortfolios(url, cookie)
                runOnUiThread {
                    if (isFinishing || isDestroyed) return@runOnUiThread
                    portfolios = loaded
                    if (loaded.isEmpty()) {
                        status.setText(R.string.widget_config_error)
                        retry.visibility = View.VISIBLE
                        return@runOnUiThread
                    }
                    status.setText(R.string.widget_config_explainer)
                    spinner.adapter = ArrayAdapter(
                        this,
                        android.R.layout.simple_spinner_item,
                        loaded.map { it.name },
                    ).apply {
                        setDropDownViewResource(
                            android.R.layout.simple_spinner_dropdown_item)
                    }
                    spinner.visibility = View.VISIBLE
                    connect.visibility = View.VISIBLE
                    connect.isEnabled = true
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
                        retry.visibility = View.VISIBLE
                    }
                }
            } catch (e: WidgetApi.ApiException) {
                runOnUiThread {
                    if (!isFinishing && !isDestroyed) {
                        status.setText(R.string.widget_config_error)
                        retry.visibility = View.VISIBLE
                    }
                }
            } catch (e: Exception) {
                // A malformed reply (e.g. an HTML login page JSON cannot
                // parse) is a failure, not a crash.
                runOnUiThread {
                    if (!isFinishing && !isDestroyed) {
                        status.setText(R.string.widget_config_error)
                        retry.visibility = View.VISIBLE
                    }
                }
            }
        }.start()
    }

    private fun connectWidget() {
        val url = serverUrl ?: return
        val cookie = cookieHeader ?: return
        val index = spinner.selectedItemPosition
        if (index !in portfolios.indices) return
        val portfolio = portfolios[index]

        connect.isEnabled = false
        status.setText(R.string.widget_config_loading)
        Thread {
            try {
                val created = WidgetApi.createToken(url, cookie, portfolio.id)
                runOnUiThread {
                    if (isFinishing || isDestroyed) return@runOnUiThread
                    WidgetStore(this).saveConfig(
                        appWidgetId,
                        created.token,
                        created.id,
                        created.portfolioName,
                        StartGate.normalizeOrigin(url),
                    )
                    // The system does NOT call onUpdate after a config
                    // screen closes; the first paint must be asked for.
                    PortfolioWidgetProvider.refreshNow(this)
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
                // Same fail-safe as the list load: report, never crash.
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
