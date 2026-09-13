# Amiko Android: EE-009 phone-login candidate

Native Kotlin Android application, permanent package `com.eldercaresaathi.amiko`.
This first build implements phone sign-in only, not the complete platform.
It is a small native test harness for the EE-009 backend acceptance checks.
The tracker still plans the complete React Native Android shell under EE-028;
this harness does not approve a change to that delivery stack or complete
EE-028/EE-029. Final app-screen integration remains in those planned items.
Minimum Android version is 8.0; this is a delivery assumption for device acceptance,
not evidence that the client's device fleet has been checked.

Toolchain: JDK 17, Android Gradle Plugin 8.13.2, Kotlin 2.3.10, Gradle 8.13,
compile/target SDK 36, Firebase Android BoM 34.19.0. These are pinned and based on
the official [Android build compatibility](https://developer.android.com/build/releases/agp-8-13-0-release-notes),
[Kotlin compatibility](https://kotlinlang.org/docs/gradle-configure-project.html) and
[Firebase phone authentication](https://firebase.google.com/docs/auth/android/phone-auth) documentation.

AndroidX Core is explicitly pinned to 1.17.0, compatible with this SDK 36/Kotlin
toolchain. Firebase phone verification requires the `ContextCompat.registerReceiver`
overload introduced in Core 1.9.0; its transitive dependencies alone can resolve
an older version and crash on code request. `PhoneAuthRuntimeTest` verifies that
the actual resolved library has the exact static method needed by the SDK.
See the [Core release notes](https://developer.android.com/jetpack/androidx/releases/core)
and [Firebase upstream report](https://github.com/firebase/firebase-android-sdk/issues/8505).

Build inputs belong only in ignored `amiko-local.properties` or environment:
`AMIKO_FIREBASE_API_KEY`, `AMIKO_FIREBASE_APP_ID`, `AMIKO_FIREBASE_PROJECT`,
`AMIKO_API_ORIGIN`. Do not publish actual project inputs, signing keys, test
verification codes or cloud-invocation credentials. The app contains no Google
administrator credentials. A build without identity inputs is deliberately
unable to sign in. Release builds reject missing identity inputs and non-HTTPS API.

Debug-only loopback HTTP exists for a local, authenticated development relay
accessed with Android Debug Bridge port reversal. The live Cloud Run service
remains private. Do not weaken that boundary or put an operator token in the APK.
Only the loopback hostname is allowed cleartext in debug; release forbids it.

Acceptance requires configured Firebase Android registration/signing fingerprints,
fictional-number device testing, final real phone/SMS testing, review of the
client's privacy/consent text and client sign-off. Fictional tests do not prove
Play Integrity or actual SMS delivery. No completed profile/feed is simulated.

Debug-only `AmikoLoginCheck` diagnostics contain stage names, HTTP status numbers
and exception class names only. They never include exception messages, stack
traces, phone numbers, verification codes, tokens, payloads or response bodies.
These distinguish Google-proof, backend and encrypted-storage failures during
device acceptance; they are disabled in release builds.

Narrow HTTPS browser and Custom Tab service queries enable Firebase's browser
discovery on Android 11+. No `QUERY_ALL_PACKAGES` permission is requested.
`VerificationBrowserManifestTest` guards these declarations; see Android's
[package-visibility guidance](https://developer.android.com/training/package-visibility/use-cases).
The real-number verification-page return path still requires device acceptance;
the declarations alone do not prove successful verification or SMS delivery.
