package com.portfoliarr.app

import android.app.Activity
import android.app.KeyguardManager
import android.content.Context
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat

/** A native cover shared by the WebView and Settings. No web content is copied here. */
abstract class AppLockActivity : AppCompatActivity() {
    protected val lockPrefs by lazy { getSharedPreferences("portfoliarr", MODE_PRIVATE) }
    private var cover: FrameLayout? = null
    private var message: TextView? = null
    private var promptInFlight = false
    private var promptRequested = false
    private var testPrompt = false

    private val credentialResult = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        promptInFlight = false
        if (result.resultCode == Activity.RESULT_OK) unlock()
        else authenticationStopped(getString(R.string.lock_cancelled))
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        AppLockSession.initialize()
        updateScreenshotProtection()
    }

    override fun onStart() {
        super.onStart()
        if (lockEnabled()) showCover()
    }

    override fun onResume() {
        super.onResume()
        refreshLockGate()
    }

    override fun onPause() {
        // Cover the page before Android takes a task thumbnail or shows another app.
        if (lockEnabled()) showCover()
        super.onPause()
    }

    protected fun lockEnabled(): Boolean = lockPrefs.getBoolean("app_lock_enabled", false)

    protected fun updateScreenshotProtection() {
        if (lockEnabled()) window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        else window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
    }

    /** Call after setContentView when WebView renderer recovery replaces the root view. */
    protected fun ensureLockCover() {
        if (lockEnabled()) showCover()
    }

    protected fun refreshLockGate() {
        updateScreenshotProtection()
        val locked = AppLockSession.policy.requiresAuthentication(
            SystemClock.elapsedRealtime(), lockEnabled(),
            lockPrefs.getLong("app_lock_timeout_ms", AppLockPolicy.DEFAULT_TIMEOUT_MS)
        )
        if (locked || testPrompt) {
            showCover()
            if (!promptRequested && !promptInFlight) {
                promptRequested = true
                startAuthentication()
            }
        } else {
            promptRequested = false
            hideCover()
        }
    }

    protected fun testAppLock() {
        // A test of an enabled lock must guard the session too: Back from
        // Settings must not reveal MainActivity after the test is cancelled.
        if (lockEnabled()) AppLockSession.policy.authenticationFailed()
        testPrompt = true
        promptRequested = true
        showCover()
        startAuthentication()
    }

    protected fun canUseAppLock(): Boolean {
        val manager = BiometricManager.from(this)
        val strong = manager.canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_STRONG) ==
            BiometricManager.BIOMETRIC_SUCCESS
        val deviceSecure = (getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager).isDeviceSecure
        return strong || deviceSecure
    }

    protected fun openDeviceSecuritySettings() {
        startActivity(android.content.Intent(android.provider.Settings.ACTION_SECURITY_SETTINGS))
    }

    private fun showCover() {
        val root = findViewById<FrameLayout>(android.R.id.content)
        if (cover?.parent !== root) {
            (cover?.parent as? ViewGroup)?.removeView(cover)
            val panel = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                gravity = Gravity.CENTER
                setPadding(32, 32, 32, 32)
            }
            message = TextView(this).apply {
                text = getString(R.string.lock_message)
                textSize = 20f
                gravity = Gravity.CENTER
                setTextColor(ContextCompat.getColor(this@AppLockActivity, android.R.color.white))
            }
            panel.addView(message)
            panel.addView(Button(this).apply {
                text = getString(R.string.lock_retry)
                setOnClickListener {
                    if (!promptInFlight) {
                        promptRequested = true
                        startAuthentication()
                    }
                }
            })
            panel.addView(Button(this).apply {
                text = getString(R.string.lock_device_settings)
                setOnClickListener { openDeviceSecuritySettings() }
            })
            cover = FrameLayout(this).apply {
                setBackgroundColor(ContextCompat.getColor(this@AppLockActivity, android.R.color.background_dark))
                addView(panel, FrameLayout.LayoutParams(-1, -1))
            }
            root.addView(cover, FrameLayout.LayoutParams(-1, -1))
        }
        cover?.visibility = View.VISIBLE
        cover?.bringToFront()
    }

    private fun hideCover() {
        cover?.visibility = View.GONE
    }

    private fun startAuthentication() {
        if (promptInFlight) return
        if (!canUseAppLock()) {
            message?.text = getString(R.string.lock_no_credentials)
            authenticationStopped(getString(R.string.lock_no_credentials))
            return
        }
        promptInFlight = true

        // Android 10 and older cannot use STRONG | DEVICE_CREDENTIAL together
        // in BiometricPrompt. Offer the OS credential screen as the fallback.
        val strong = BiometricManager.from(this).canAuthenticate(
            BiometricManager.Authenticators.BIOMETRIC_STRONG
        ) == BiometricManager.BIOMETRIC_SUCCESS
        if (Build.VERSION.SDK_INT < 30 && !strong) {
            launchCredential()
            return
        }
        val authenticators = if (Build.VERSION.SDK_INT >= 30) {
            BiometricManager.Authenticators.BIOMETRIC_STRONG or
                BiometricManager.Authenticators.DEVICE_CREDENTIAL
        } else BiometricManager.Authenticators.BIOMETRIC_STRONG
        val info = BiometricPrompt.PromptInfo.Builder()
            .setTitle(getString(R.string.lock_prompt_title))
            .setAllowedAuthenticators(authenticators)
            .apply {
                if (Build.VERSION.SDK_INT < 30) {
                    setNegativeButtonText(getString(R.string.lock_use_device_credential))
                }
            }.build()
        BiometricPrompt(this, ContextCompat.getMainExecutor(this), object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                promptInFlight = false
                unlock()
            }

            override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                promptInFlight = false
                if (Build.VERSION.SDK_INT < 30 &&
                    (errorCode == BiometricPrompt.ERROR_NEGATIVE_BUTTON ||
                        errorCode == BiometricPrompt.ERROR_LOCKOUT ||
                        errorCode == BiometricPrompt.ERROR_LOCKOUT_PERMANENT)) {
                    launchCredential()
                } else {
                    authenticationStopped(getString(R.string.lock_cancelled))
                }
            }
        }).authenticate(info)
    }

    @Suppress("DEPRECATION")
    private fun launchCredential() {
        val keyguard = getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager
        val intent = keyguard.createConfirmDeviceCredentialIntent(
            getString(R.string.lock_prompt_title), getString(R.string.lock_message)
        )
        if (intent == null) {
            promptInFlight = false
            authenticationStopped(getString(R.string.lock_no_credentials))
        } else {
            promptInFlight = true
            credentialResult.launch(intent)
        }
    }

    private fun unlock() {
        AppLockSession.policy.authenticated()
        testPrompt = false
        promptRequested = false
        refreshLockGate()
    }

    private fun authenticationStopped(text: String) {
        promptInFlight = false
        if (testPrompt && !lockEnabled()) {
            testPrompt = false
            promptRequested = false
            hideCover()
            Toast.makeText(this, text, Toast.LENGTH_SHORT).show()
        } else {
            showCover()
            message?.text = text
        }
    }
}
