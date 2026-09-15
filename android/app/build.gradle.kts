plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "com.portfoliarr.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.portfoliarr.app"
        minSdk = 24
        targetSdk = 34
        // Read from gradle.properties so versionCode/Name live in one place.
        // Falls back to 1 / "1.0" if the properties are missing.
        versionCode = project.findProperty("VERSION_CODE")?.toString()?.toIntOrNull() ?: 1
        versionName = project.findProperty("VERSION_NAME")?.toString() ?: "1.0"
    }

    // Shared debug keystore checked into the repo — both local and CI builds
    // use this same certificate so APK updates install over previous versions.
    // WITHOUT this, each machine's ~/.android/debug.keystore produces a
    // different certificate, and Android refuses the update ("app not installed").
    signingConfigs {
        create("debug") {
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
