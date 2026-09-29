package com.portfoliarr.app

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.SwitchCompat

class SettingsActivity : AppCompatActivity() {

    // This screen is currently UNREACHABLE once a server URL is saved, and
    // that is deliberate, not an oversight. The route into it is the
    // action_settings menu item, but MainActivity.onCreate calls
    // supportActionBar?.hide(), so the menu is never shown. PR #75 made the
    // action bar visible to reach a lock's settings; the user rejected the
    // resulting app and asked for both the gear and the lock to be removed.
    //
    // So the fingerprint controls below are NOT the live path. The live path
    // is the one-time offer dialog in MainActivity, and the three-way
    // choice shown when a prompt is cancelled. Both are pinned by
    // tests/test_android_biometric.py (test_the_settings_gear_stays_gone).
    //
    // The switch and button are kept because they are the natural home for
    // these controls, and they cost nothing while unreachable. If the gear
    // ever comes back, delete this note rather than the comment.

    private lateinit var secretStore: SecretStore

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_settings)

        supportActionBar?.title = "Settings"
        supportActionBar?.setDisplayHomeAsUpEnabled(true)

        secretStore = SecretStore(this)

        val urlInput = findViewById<EditText>(R.id.urlInput)
        val saveButton = findViewById<Button>(R.id.saveButton)
        val biometricToggle = findViewById<SwitchCompat>(R.id.biometricToggle)
        val forgetButton = findViewById<Button>(R.id.forgetButton)

        // Pre-fill with saved URL
        val prefs = getSharedPreferences("portfoliarr", MODE_PRIVATE)
        val savedUrl = prefs.getString("server_url", "")
        urlInput.setText(savedUrl)

        saveButton.setOnClickListener {
            val url = urlInput.text.toString().trim()

            if (url.isBlank()) {
                Toast.makeText(this, "Please enter a URL", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            val lower = url.lowercase()
            if (lower.startsWith("javascript:")) {
                Toast.makeText(this, "That URL is not allowed", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            if (!lower.startsWith("http://") && !lower.startsWith("https://")) {
                Toast.makeText(this, "Start with http://", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            // Save and return to main
            prefs.edit().putString("server_url", url).apply()

            // A stored secret belongs to the server it was captured from. If
            // the user repoints the app at a different one, drop it rather
            // than leave a live session for a host that may not be theirs.
            if (secretStore.secretOrigin() != null &&
                secretStore.secretOrigin() != StartGate.normalizeOrigin(url)
            ) {
                secretStore.clear()
            }

            // Restart MainActivity so it picks up the new URL
            val intent = Intent(this, MainActivity::class.java)
            intent.flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK
            startActivity(intent)
            finish()
        }

        // The toggle defaults to OFF and stays off until the one-time offer
        // in MainActivity is accepted. Opening this screen is therefore
        // never enough on its own.
        biometricToggle.isChecked = secretStore.isEnabled
        biometricToggle.setOnCheckedChangeListener { button, isChecked ->
            if (!button.isPressed) {
                // Reached while the view is being populated from the stored
                // value, not by a tap: acting on it would let loading the
                // screen wipe the secret.
                return@setOnCheckedChangeListener
            }
            // Switching off also drops anything already stored, so turning
            // the feature off really does remove it from the phone. It does
            // NOT sign the user out — the current WebView session is left
            // alone until it expires on its own. The decline is recorded
            // too, or the one-time offer would return after the next
            // sign-in.
            if (!isChecked) secretStore.markDeclined()
            secretStore.setEnabled(isChecked)
        }

        forgetButton.setOnClickListener { confirmForget() }
    }

    /**
     * The one control that ends the session on this phone.
     *
     * Confirmed first, because the recovery is a password the user may have
     * to dig out. The actual wipe lives in SessionControl because
     * MainActivity's cancel dialog needs the identical behaviour, and two
     * copies of the step that actually matters is one too many.
     */
    private fun confirmForget() {
        AlertDialog.Builder(this)
            .setTitle(R.string.biometric_forget_confirm_title)
            .setMessage(R.string.biometric_forget_confirm_message)
            .setNegativeButton(R.string.cancel, null)
            .setPositiveButton(R.string.forget) { _, _ -> forgetSecret() }
            .show()
    }

    private fun forgetSecret() {
        SessionControl.forgetPhone(this, secretStore)

        Toast.makeText(this, R.string.biometric_forget_done, Toast.LENGTH_SHORT).show()

        val intent = Intent(this, MainActivity::class.java)
        intent.flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK
        startActivity(intent)
        finish()
    }

    override fun onSupportNavigateUp(): Boolean {
        finish()
        return true
    }
}
