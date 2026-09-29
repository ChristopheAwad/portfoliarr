// android/app/src/main/java/com/portfoliarr/app/BiometricGate.kt
// Asks Android for a fingerprint (or the device PIN/pattern/password) and
// reports the answer.
//
// One rule governs this file: NOTHING here is allowed to be fatal. A user who
// cancels, whose sensor is busy, who has enrolled nothing, or who has locked
// themselves out with too many attempts must all end up looking at the normal
// login page — never a crash, and never a prompt loop. Every callback
// therefore reports failure and lets the caller fall through.
//
// The pure yes/no decision of *whether* to prompt at all lives in StartGate,
// which has no Android imports and is unit tested on a plain JVM.

package com.portfoliarr.app

import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity

class BiometricGate(private val activity: FragmentActivity) {

    /**
     * Whether the device can actually service a prompt right now.
     *
     * [BiometricManager.BIOMETRIC_ERROR_NONE_ENROLLED] and
     * [BIOMETRIC_ERROR_NO_HARDWARE] are the two that matter: they are steady
     * states, so the caller skips prompting entirely rather than showing a
     * prompt that can only fail. A transient
     * [BIOMETRIC_ERROR_HW_UNAVAILABLE] is deliberately NOT treated as a
     * permanent "no", because the sensor is usually usable a moment later and
     * silently disabling the feature for the session would be worse than one
     * failed attempt.
     */
    fun isAvailable(): Boolean =
        when (BiometricManager.from(activity).canAuthenticate(AUTHENTICATORS)) {
            BiometricManager.BIOMETRIC_SUCCESS -> true
            BiometricManager.BIOMETRIC_ERROR_NONE_ENROLLED,
            BiometricManager.BIOMETRIC_ERROR_NO_HARDWARE,
            BiometricManager.BIOMETRIC_ERROR_SECURITY_UPDATE_REQUIRED,
            -> false
            else -> true
        }

    /**
     * Show the prompt and call [onResult] exactly once with true when the
     * user authenticated and false for every other ending.
     *
     * Must be called from the main thread (the caller is an Activity).
     */
    fun authenticate(title: String, subtitle: String, onResult: (Boolean) -> Unit) {
        // Every path below reaches onResult exactly once, so a caller cannot
        // be left waiting forever. Guard it anyway: a second call from a
        // duplicated callback would prompt the user twice.
        var delivered = false
        fun deliver(success: Boolean) {
            if (!delivered) {
                delivered = true
                onResult(success)
            }
        }

        val prompt = BiometricPrompt(
            activity,
            ContextCompat.getMainExecutor(activity),
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    deliver(true)
                }

                override fun onAuthenticationError(code: Int, message: CharSequence) {
                    // Covers the user tapping Cancel, a lockout after too many
                    // attempts, and every hardware error. All of them mean
                    // "not unlocked", and the caller falls through to the
                    // login page.
                    deliver(false)
                }

                // NOTE: onAuthenticationFailed is deliberately NOT handled as
                // a terminal result. It fires for each individual rejected
                // fingerprint while the prompt stays up, and the system then
                // shows "Too many attempts" and eventually calls
                // onAuthenticationError. Turning a single misread finger into
                // an immediate fall-through would abandon a prompt the user
                // can still succeed at.
            }
        )

        val info = BiometricPrompt.PromptInfo.Builder()
            .setTitle(title)
            .setSubtitle(subtitle)
            // WEAK admits Class 2 sensors so older fingerprint readers still
            // work; DEVICE_CREDENTIAL adds the PIN/pattern/password fallback
            // the user explicitly asked to keep. This mirrors the key's
            // accepted authenticators in SecretStore.
            .setAllowedAuthenticators(AUTHENTICATORS)
            .setConfirmationRequired(false)
            .build()

        try {
            // No CancellationSignal: androidx.biometric.BiometricPrompt
            // offers only authenticate(PromptInfo) and
            // authenticate(PromptInfo, CryptoObject). The overload that takes
            // a CancellationSignal belongs to the FRAMEWORK class,
            // android.hardware.biometrics.BiometricPrompt, which has a
            // different API. Cancellation is already covered by
            // onAuthenticationError, so nothing is lost.
            prompt.authenticate(info)
        } catch (e: Exception) {
            // A device that cannot even construct a prompt (odd OEM builds,
            // a locked-down profile) must still reach the login page.
            deliver(false)
        }
    }

    companion object {
        val AUTHENTICATORS: Int =
            BiometricManager.Authenticators.BIOMETRIC_WEAK or
                BiometricManager.Authenticators.DEVICE_CREDENTIAL
    }
}
