# Amiko Android: EE-009 phone-login candidate

Native Kotlin Android application, permanent package `com.eldercaresaathi.amiko`.
This first build implements phone sign-in only, not the complete platform.
Minimum Android version is 8.0; this is a delivery assumption for device acceptance,
not evidence that the client's device fleet has been checked.

Toolchain: JDK 17, Android Gradle Plugin 8.13.2, Kotlin 2.3.10, Gradle 8.13,
compile/target SDK 36, Firebase Android BoM 34.19.0. These are pinned and based on
the official [Android build compatibility](https://developer.android.com/build/releases/agp-8-13-0-release-notes),
[Kotlin compatibility](https://kotlinlang.org/docs/gradle-configure-project.html) and
[Firebase phone authentication](https://firebase.google.com/docs/auth/android/phone-auth) documentation.

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
