plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

// The web app and APK expose the same human-readable release number.
val sharedVersion = rootProject.projectDir.parentFile.resolve("VERSION").readText().trim()
require(sharedVersion.matches(Regex("""[0-9]+\.[0-9]+(?:\.[0-9]+)?"""))) {
    "Invalid app version in root VERSION"
}

// Debug builds may fall back to version code 1 for local JVM/debug work.
// Release packaging explicitly rejects that fallback (see validateReleaseSigning):
// a release must supply VERSION_CODE.
val versionCodeProperty = project.findProperty("VERSION_CODE")?.toString()
val versionCodeValue = versionCodeProperty?.toIntOrNull()
val hasValidVersionCode = versionCodeValue != null && versionCodeValue in 1..2_100_000_000

fun envValue(name: String): String? = System.getenv(name)?.takeIf { it.isNotEmpty() }

val releaseKeystorePath = envValue("ANDROID_RELEASE_KEYSTORE_PATH")
val releaseKeystoreFile = releaseKeystorePath?.let { file(it) }
val releaseStorePassword = envValue("ANDROID_RELEASE_STORE_PASSWORD")
val releaseKeyAlias = envValue("ANDROID_RELEASE_KEY_ALIAS")
val releaseKeyPassword = envValue("ANDROID_RELEASE_KEY_PASSWORD")

android {
    namespace = "com.portfoliarr.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.portfoliarr.app"
        minSdk = 24
        targetSdk = 34
        // versionCode is Android-specific; versionName is shared with Flask.
        versionCode = versionCodeValue ?: 1
        versionName = sharedVersion
    }

    // Debug builds use AGP's default signing config, which points at this
    // machine's ~/.android/debug.keystore. That key is local-only: it is never
    // committed, and it is never used for release builds.
    signingConfigs {
        // Release signing is a distinct config supplied only by the
        // environment. No keystore, password, alias, or fallback key is
        // committed to the repository. validateReleaseSigning fails packaging
        // when any of these inputs is absent, partial, or invalid.
        create("release") {
            storeFile = releaseKeystoreFile
            storePassword = releaseStorePassword
            keyAlias = releaseKeyAlias
            keyPassword = releaseKeyPassword
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // Never fall back to debug signing and never emit an unsigned
            // release. A missing or incomplete signing config fails below.
            signingConfig = signingConfigs.getByName("release")
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.material)
    implementation(libs.androidx.webkit)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.biometric)
    // #51 home-screen widget refresh scheduling.
    implementation(libs.androidx.work.runtime)

    // JVM unit tests for the pure helpers (CookieHeader, StartGate). They
    // carry no android.* imports precisely so these run here, on a plain
    // JVM, instead of needing a device.
    testImplementation(libs.junit)
}

// Release packaging must fail closed. Validation runs as a task and again at
// the start of every release APK, bundle, and install task, rejecting absent,
// partial, or obviously invalid inputs. It intentionally never opens the
// keystore: password and alias validity are left to AGP/signing so no key
// material is read here.
val releasePackagingTasks = setOf(
    "assembleRelease",
    "bundleRelease",
    "installRelease",
    "packageRelease",
    "packageReleaseBundle",
    "packageReleaseUniversalApk",
    "signReleaseBundle",
)

val validateReleaseInputs = Action<Task> {
    val problems = mutableListOf<String>()

    fun requireEnv(name: String, value: String?) {
        if (value.isNullOrBlank()) {
            problems += "$name is missing or empty"
        }
    }

    requireEnv("ANDROID_RELEASE_KEYSTORE_PATH", releaseKeystorePath)
    requireEnv("ANDROID_RELEASE_STORE_PASSWORD", releaseStorePassword)
    requireEnv("ANDROID_RELEASE_KEY_ALIAS", releaseKeyAlias)
    requireEnv("ANDROID_RELEASE_KEY_PASSWORD", releaseKeyPassword)

    if (releaseKeystoreFile != null) {
        if (!releaseKeystoreFile.isFile) {
            problems += "ANDROID_RELEASE_KEYSTORE_PATH is not a regular file"
        } else if (releaseKeystoreFile.length() == 0L) {
            problems += "ANDROID_RELEASE_KEYSTORE_PATH is empty"
        } else if (!releaseKeystoreFile.canRead()) {
            problems += "ANDROID_RELEASE_KEYSTORE_PATH is not readable"
        }
    }

    if (versionCodeProperty.isNullOrBlank()) {
        problems += "VERSION_CODE is not set; release builds must not fall back to a default"
    } else if (!hasValidVersionCode) {
        problems += "VERSION_CODE must be between 1 and 2100000000"
    }

    if (problems.isNotEmpty()) {
        throw GradleException(
            "Release signing is not configured safely:\n - " +
                problems.joinToString("\n - ")
        )
    }
}

val validateReleaseSigning = tasks.register("validateReleaseSigning") {
    group = "verification"
    description = "Fails unless production release signing and version inputs are complete."
    doFirst(validateReleaseInputs)
}

// Validate inside the packaging tasks too: a plain task dependency could be
// removed with --exclude-task, and that must not produce an unsigned release.
tasks.matching { it.name in releasePackagingTasks }.configureEach {
    doFirst(validateReleaseInputs)
}
