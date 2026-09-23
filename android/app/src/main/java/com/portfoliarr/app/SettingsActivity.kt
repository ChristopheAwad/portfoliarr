package com.portfoliarr.app

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.Spinner
import android.widget.ArrayAdapter
import android.widget.Switch
import android.widget.Toast

class SettingsActivity : AppLockActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_settings)
        ensureLockCover()

        supportActionBar?.title = "Settings"
        supportActionBar?.setDisplayHomeAsUpEnabled(true)

        val urlInput = findViewById<EditText>(R.id.urlInput)
        val saveButton = findViewById<Button>(R.id.saveButton)

        // Pre-fill with saved URL
        val prefs = getSharedPreferences("portfoliarr", MODE_PRIVATE)
        val savedUrl = prefs.getString("server_url", "")
        urlInput.setText(savedUrl)

        val enabled = findViewById<Switch>(R.id.lockEnabled)
        val timeout = findViewById<Spinner>(R.id.lockTimeout)
        val choices = listOf(
            getString(R.string.lock_immediately), getString(R.string.lock_one_minute),
            getString(R.string.lock_five_minutes), getString(R.string.lock_fifteen_minutes)
        )
        timeout.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, choices)
        timeout.setSelection(AppLockPolicy.TIMEOUTS.indexOf(
            AppLockPolicy.timeout(prefs.getLong("app_lock_timeout_ms", AppLockPolicy.DEFAULT_TIMEOUT_MS))
        ))
        enabled.isChecked = prefs.getBoolean("app_lock_enabled", false)
        timeout.isEnabled = enabled.isChecked
        enabled.setOnCheckedChangeListener { _, checked ->
            if (checked && !canUseAppLock()) {
                enabled.isChecked = false
                Toast.makeText(this, R.string.lock_no_credentials, Toast.LENGTH_LONG).show()
                return@setOnCheckedChangeListener
            }
            prefs.edit().putBoolean("app_lock_enabled", checked).apply()
            timeout.isEnabled = checked
            if (checked) AppLockSession.policy.authenticated()
            updateScreenshotProtection()
            refreshLockGate()
        }
        timeout.onItemSelectedListener = object : android.widget.AdapterView.OnItemSelectedListener {
            override fun onItemSelected(
                parent: android.widget.AdapterView<*>?, view: android.view.View?, position: Int, id: Long
            ) {
                prefs.edit().putLong("app_lock_timeout_ms", AppLockPolicy.TIMEOUTS[position]).apply()
            }
            override fun onNothingSelected(parent: android.widget.AdapterView<*>?) = Unit
        }
        findViewById<Button>(R.id.testLock).setOnClickListener {
            if (canUseAppLock()) testAppLock()
            else Toast.makeText(this, R.string.lock_no_credentials, Toast.LENGTH_LONG).show()
        }
        findViewById<Button>(R.id.deviceSecurity).setOnClickListener { openDeviceSecuritySettings() }

        saveButton.setOnClickListener {
            val url = urlInput.text.toString().trim()

            if (url.isBlank()) {
                Toast.makeText(this, "Please enter a URL", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            // Save and return to main
            prefs.edit().putString("server_url", url).apply()

            // Restart MainActivity so it picks up the new URL
            val intent = Intent(this, MainActivity::class.java)
            intent.flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK
            startActivity(intent)
            finish()
        }
    }

    override fun onSupportNavigateUp(): Boolean {
        finish()
        return true
    }
}
