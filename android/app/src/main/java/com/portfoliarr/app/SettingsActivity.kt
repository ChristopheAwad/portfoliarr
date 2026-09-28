package com.portfoliarr.app

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity

class SettingsActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_settings)

        supportActionBar?.title = "Settings"
        supportActionBar?.setDisplayHomeAsUpEnabled(true)

        val urlInput = findViewById<EditText>(R.id.urlInput)
        val saveButton = findViewById<Button>(R.id.saveButton)

        // Pre-fill with saved URL
        val prefs = getSharedPreferences("portfoliarr", MODE_PRIVATE)
        val savedUrl = prefs.getString("server_url", "")
        urlInput.setText(savedUrl)

        saveButton.setOnClickListener {
            val url = urlInput.text.toString().trim().trimEnd('/')

            if (url.isBlank()) {
                Toast.makeText(this, "Please enter a URL", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            // The server is plain HTTP on the home LAN or HTTPS remotely —
            // anything else (a bare host, a typo'd scheme) fails in
            // WebView.loadUrl and leaves the app in a reload loop.
            if (!url.startsWith("http://") && !url.startsWith("https://")) {
                Toast.makeText(this, "URL must start with http:// or https://",
                    Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            if (url.any { it.isWhitespace() }) {
                Toast.makeText(this, "URL must not contain spaces",
                    Toast.LENGTH_SHORT).show()
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
