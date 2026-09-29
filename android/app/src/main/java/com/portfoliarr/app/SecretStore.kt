// android/app/src/main/java/com/portfoliarr/app/SecretStore.kt
// Holds the saved session cookie, encrypted under a key that lives in the
// phone's hardware keystore and is never exported to disk.
//
// Two separate protections, doing two separate jobs:
//
//   AT REST — AES-256-GCM under a non-exportable AndroidKeyStore key. Copying
//   the app's data directory off the device yields ciphertext and nothing
//   else, because the key material cannot leave the TEE.
//
//   IN USE — every read of that secret is gated behind BiometricPrompt (see
//   BiometricGate). This, not the keystore, is what stops the person who picks
//   up the phone.
//
// Why the key is NOT created with setUserAuthenticationRequired(true), even
// though that is the stronger primitive: that restriction applies to the key's
// ENCRYPT purpose as well as its decrypt one, so writing a newly-captured
// cookie would itself require an authentication. Capture happens in the
// background just after a login through the web form, which is not a keystore
// authorization event, so the feature would have to interrupt the user with an
// extra fingerprint prompt on every login and keep a "pending save" alive
// between auth windows. Trading a real, everyday cost for a marginal gain in
// a threat this app does not primarily have, is the wrong trade.
//
// Deliberately hand-rolled on the JCE + AndroidKeyStore rather than pulled
// from androidx.security:security-crypto, because the primitive that matters
// here is simply a non-exportable AES-GCM key, and that library adds an alpha
// dependency for it.

package com.portfoliarr.app

import android.content.Context
import android.content.SharedPreferences
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyPermanentlyInvalidatedException
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.GeneralSecurityException
import java.security.KeyStore
import javax.crypto.AEADBadTagException
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class SecretStore(context: Context) {

    private val prefs: SharedPreferences =
        context.applicationContext
            .getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    // ── Public state ───────────────────────────────────────────────────

    /** True when a secret is stored for some server. */
    fun hasSecret(): Boolean =
        !prefs.getString(KEY_CIPHERTEXT, null).isNullOrEmpty()

    /**
     * The server origin the stored secret belongs to, or null. Compared
     * against the configured server before every unlock, so a cookie is never
     * handed to a host it was not captured from.
     */
    fun secretOrigin(): String? = prefs.getString(KEY_ORIGIN, null)

    /**
     * SHA-256 of the cookie currently stored, or null. Lets the background
     * sampler notice "the live cookie changed" without decrypting — and
     * therefore without ever triggering a fingerprint prompt from the
     * background.
     */
    fun storedCookieHash(): String? = prefs.getString(KEY_HASH, null)

    /**
     * Whether the user has turned fingerprint unlock ON.
     *
     * Defaults to FALSE. This is a deliberate reversal of the obvious
     * choice: the previous attempt at this feature shipped enabled and was
     * scrapped after the user rejected it, because a lock that changes how
     * the app opens the moment it is installed is a surprise. A feature
     * that has to be asked for can never surprise anyone.
     */
    val isEnabled: Boolean
        get() = prefs.getBoolean(KEY_ENABLED, false)

    /**
     * True once the user has said "not now" to the one-time offer.
     *
     * Separate from [isEnabled] because they answer different questions. A
     * decline is permanent: re-asking after every login is precisely the
     * nagging that got PR #75 scrapped, and nothing about signing in again
     * should change the answer.
     */
    val declinedOffer: Boolean
        get() = prefs.getBoolean(KEY_DECLINED, false)

    /**
     * Turn the feature on or off. Turning it OFF also deletes the stored
     * login, so "off" really does remove the feature from the phone — but
     * it deliberately does NOT sign the user out, which is what
     * "Forget this phone" is for.
     */
    fun setEnabled(enabled: Boolean) {
        prefs.edit().putBoolean(KEY_ENABLED, enabled).apply()
        if (!enabled) clear()
    }

    /**
     * Record that the user does not want to be asked again.
     *
     * "Stop asking" calls this AND setEnabled(false). Both are needed:
     * setEnabled clears the secret, and without the decline the offer would
     * return the moment the user signs in again.
     */
    fun markDeclined() {
        prefs.edit().putBoolean(KEY_DECLINED, true).apply()
    }

    /**
     * Encrypt and store a session cookie for one server origin.
     *
     * [origin] must already be normalized by StartGate.normalizeOrigin.
     * Returns false when the keystore refused to produce a usable key, in
     * which case nothing is stored and the app simply keeps asking for a
     * password.
     *
     * Note the asymmetry with load(): a failure AFTER obtainKey succeeded
     * deliberately leaves any previous record alone. We know the key worked
     * in that call, so the stored secret is still readable and a transient
     * hiccup must not cost the user their saved login. load() clears,
     * because there the record is exactly what cannot be used.
     */
    fun save(sessionValue: String, origin: String): Boolean {
        val secretKey = obtainKey() ?: run {
            clear()
            return false
        }
        return try {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.ENCRYPT_MODE, secretKey)
            val cipherText = cipher.doFinal(sessionValue.toByteArray(Charsets.UTF_8))
            prefs.edit()
                .putString(KEY_CIPHERTEXT, encode(cipherText))
                .putString(KEY_IV, encode(cipher.iv))
                .putString(KEY_ORIGIN, origin)
                .putString(KEY_HASH, CookieHeader.sha256Hex(sessionValue))
                .apply()
            true
        } catch (e: GeneralSecurityException) {
            false
        }
    }

    /**
     * Decrypt the stored cookie, or null when there is nothing to return.
     *
     * Returns null — rather than throwing — in every recoverable case:
     *   * nothing stored
     *   * a half-written record (ciphertext without IV, and so on)
     *   * AEADBadTagException: the ciphertext was tampered with, or the key
     *     was regenerated
     *   * the keystore is unavailable
     *
     * In each case the unusable record is wiped, because leaving it in place
     * would mean failing the same way on every future launch.
     */
    fun load(): String? {
        val cipherText = prefs.getString(KEY_CIPHERTEXT, null) ?: return null
        val ivText = prefs.getString(KEY_IV, null) ?: run {
            clear()
            return null
        }
        val secretKey = obtainKey() ?: run {
            clear()
            return null
        }
        return try {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(
                Cipher.DECRYPT_MODE, secretKey,
                GCMParameterSpec(GCM_TAG_BITS, decode(ivText))
            )
            val plain = cipher.doFinal(decode(cipherText))
            String(plain, Charsets.UTF_8)
        } catch (e: AEADBadTagException) {
            clear()
            null
        } catch (e: GeneralSecurityException) {
            clear()
            null
        } catch (e: IllegalArgumentException) {
            // Base64 in prefs was corrupted by something outside our control.
            clear()
            null
        }
    }

    /**
     * Forget everything: the stored secret, its origin, and the key. Called
     * by the settings "forget" button, and by any failure that leaves the
     * record unreadable.
     */
    fun clear() {
        prefs.edit()
            .remove(KEY_CIPHERTEXT)
            .remove(KEY_IV)
            .remove(KEY_ORIGIN)
            .remove(KEY_HASH)
            .apply()
        try {
            val keyStore = KeyStore.getInstance(PROVIDER).apply { load(null) }
            if (keyStore.containsAlias(KEY_ALIAS)) {
                keyStore.deleteEntry(KEY_ALIAS)
            }
        } catch (e: GeneralSecurityException) {
            // Nothing useful to do: the ciphertext is already gone from prefs,
            // and a key we cannot delete will simply be replaced below.
        }
    }

    // ── Key management ─────────────────────────────────────────────────

    /**
     * The non-exportable hardware key, created on first use.
     *
     * No setUserAuthenticationRequired here, and no
     * setInvalidatedByBiometricEnrollment either — neither applies to a key
     * that is not bound to the user's authentication. The key simply lives
     * in the TEE and cannot be read back out.
     *
     * GCM, not ECB: this is authenticated encryption, so a tampered
     * ciphertext fails to decrypt instead of yielding garbage (see load()'s
     * AEADBadTagException path).
     */
    private fun obtainKey(): SecretKey? = try {
        val keyStore = KeyStore.getInstance(PROVIDER).apply { load(null) }
        (keyStore.getKey(KEY_ALIAS, null) as? SecretKey)
            ?: generateKey(keyStore)
    } catch (e: KeyPermanentlyInvalidatedException) {
        // Not reachable for a key with no auth binding, but a keystore that
        // refuses the existing key for any reason leaves us unable to read or
        // write, so drop the record rather than failing on every launch.
        clear()
        null
    } catch (e: GeneralSecurityException) {
        null
    }

    private fun generateKey(keyStore: KeyStore): SecretKey? {
        val generator = KeyGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_AES, PROVIDER
        )
        generator.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build()
        )
        // What keeps the key out of reach is the PROVIDER argument above —
        // a key generated through AndroidKeyStore is generated inside the
        // TEE and is non-exportable, so nothing this app (or a backup of its
        // data directory) can read ever yields the key itself.
        val key = generator.generateKey()
        keyStore.setEntry(KEY_ALIAS, KeyStore.SecretKeyEntry(key), null)
        return key
    }

    private fun encode(bytes: ByteArray): String =
        Base64.encodeToString(bytes, Base64.NO_WRAP)

    private fun decode(text: String): ByteArray =
        Base64.decode(text, Base64.NO_WRAP)

    companion object {
        // A private prefs file, separate from the "portfoliarr" one that
        // holds the server URL: the toggle lives next to the data it governs.
        private const val PREFS_NAME = "portfoliarr_biometric"
        private const val PROVIDER = "AndroidKeyStore"
        private const val KEY_ALIAS = "portfoliarr_session_secret"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
        private const val GCM_TAG_BITS = 128

        private const val KEY_CIPHERTEXT = "ciphertext"
        private const val KEY_IV = "iv"
        private const val KEY_ORIGIN = "origin"
        private const val KEY_HASH = "cookie_hash"
        private const val KEY_ENABLED = "enabled"
        private const val KEY_DECLINED = "declined_offer"
    }
}
