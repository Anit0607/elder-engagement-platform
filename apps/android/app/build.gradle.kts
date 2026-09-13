import java.util.Properties

plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
val localSettings = Properties().apply {
    val source = rootProject.file("amiko-local.properties")
    if (source.exists()) source.inputStream().use { load(it) }
}
fun setting(name: String, fallback: String = ""): String =
    System.getenv(name) ?: localSettings.getProperty(name, fallback)
fun quoted(value: String) = "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""

android {
    namespace = "com.eldercaresaathi.amiko"
    compileSdk = 36
    defaultConfig {
        applicationId = "com.eldercaresaathi.amiko"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0-ee009"
        buildConfigField("String", "FIREBASE_API_KEY", quoted(setting("AMIKO_FIREBASE_API_KEY")))
        buildConfigField("String", "FIREBASE_APP_ID", quoted(setting("AMIKO_FIREBASE_APP_ID")))
        buildConfigField("String", "FIREBASE_PROJECT", quoted(setting("AMIKO_FIREBASE_PROJECT")))
        buildConfigField("String", "API_ORIGIN", quoted(setting("AMIKO_API_ORIGIN", "http://127.0.0.1:8787")))
    }
    buildFeatures { buildConfig = true }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    buildTypes {
        release { isMinifyEnabled = false }
    }
    lint { abortOnError = true; checkReleaseBuilds = true }
}
kotlin { compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) } }
tasks.matching { it.name == "preReleaseBuild" }.configureEach {
    doFirst {
        check(setting("AMIKO_API_ORIGIN").startsWith("https://")) { "Release requires approved HTTPS API" }
        check(listOf("AMIKO_FIREBASE_API_KEY", "AMIKO_FIREBASE_APP_ID", "AMIKO_FIREBASE_PROJECT")
            .all { setting(it).isNotBlank() }) { "Release identity configuration is missing" }
    }
}
dependencies {
    // Firebase phone verification calls ContextCompat.registerReceiver (added in 1.9).
    // Its transitive dependencies alone resolve an older Core lacking that method.
    implementation("androidx.core:core:1.17.0")
    implementation(platform("com.google.firebase:firebase-bom:34.19.0"))
    implementation("com.google.firebase:firebase-auth")
    testImplementation("junit:junit:4.13.2")
}
