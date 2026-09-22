plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

// The web app and APK expose the same human-readable release number.
val sharedVersion = rootProject.projectDir.parentFile.resolve("VERSION").readText().trim()
require(sharedVersion.matches(Regex("""[0-9]+\.[0-9]+(?:\.[0-9]+)?"""))) {
    "Invalid app version in root VERSION"
}

android {
    namespace = "com.portfoliarr.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.portfoliarr.app"
        minSdk = 24
        targetSdk = 34
        // versionCode is Android-specific; versionName is shared with Flask.
        versionCode = project.findProperty("VERSION_CODE")?.toString()?.toIntOrNull() ?: 1
        versionName = sharedVersion
    }

    // Shared debug keystore checked into the repo — both local and CI builds
    // use this same certificate so APK updates install over previous versions.
    // WITHOUT this, each machine's ~/.android/debug.keystore produces a
    // different certificate, and Android refuses the update ("app not installed").
    signingConfigs {
        // getByName, NOT create: AGP automatically pre-registers a signing
        // config named "debug" when the plugin applies, so create("debug")
        // fails with "Cannot add a SigningConfig with name 'debug' as a
        // SigningConfig with that name already exists" — a configuration-
        // phase error that kills every build before it compiles. We just
        // reconfigure the built-in one to point at the shared keystore.
        getByName("debug") {
            storeFile = file("debug.keystore")
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
    }

    buildTypes {
        debug {
            signingConfig = signingConfigs.getByName("debug")
        }
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("debug")
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
}
