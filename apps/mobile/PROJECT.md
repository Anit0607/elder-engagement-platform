# Amiko Android app (Sprint 5)

This is the production-app candidate, separate from the earlier native Android
phone-sign-in test harness in `apps/android`. Only Android is in scope; iOS is
developed by another team using the shared REST API.

The app provides Home, Circles and Profile navigation in English, Bengali and
Hindi. Text and colours are **provisional** until client branding and translated
wording are approved. Member phone sign-in, profile editing, device controls
and predefined-circle selection are connected through the existing secure
native account layer. Account tokens remain in Android's protected storage,
not JavaScript. The Home feed, profile-photo upload and live content are not
connected yet. These screens have local automated tests and Android build
checks, but **not** final phone/client acceptance. The test API address must
have a working security certificate before connected client-device checks.

Run local checks from the workspace root with D-drive cache isolation:

```powershell
.\apps\mobile\tools\Verify-Android.ps1
.\apps\mobile\tools\Verify-Android.ps1 -BuildPackage
.\apps\mobile\tools\Verify-Android.ps1 -ClientTestPackage
.\apps\mobile\tools\Verify-Android.ps1 -BuildPackage -ConnectedDevelopment
.\apps\mobile\tools\Verify-Android.ps1 -ClientTestPackage -ConnectedDevelopment -ApiOrigin https://api-test.eldercaresaathi.com
```

Android package identifier: `com.eldercaresaathi.amiko`. Keep the app and its
Google/Firebase registration aligned when migrating from the phone-sign-in
test harness. No Firebase settings, account credentials or release signing
keys belong in this public repository. The generated debug signing key is
ignored. `clientTest` is a locally signed, self-contained phone-test package;
it is **not** a production release. Production signing must be configured
privately before release.

The connected debug build reads the ignored Google configuration already used
by the earlier phone-sign-in test. It targets the local protected test relay;
the self-contained connected package must instead use the approved HTTPS test
address once its certificate is active. No secrets are printed or committed.
