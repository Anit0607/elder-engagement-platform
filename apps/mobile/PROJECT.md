# Amiko Android app (Sprint 5)

This is the production-app candidate, separate from the earlier native Android
phone-sign-in test harness in `apps/android`. Only Android is in scope; iOS is
developed by another team using the shared REST API.

The current shell provides Home, Circles and Profile navigation in English,
Bengali and Hindi. Text and colours are **provisional** until client branding
and translated wording are approved. Cards explicitly identify content that
is not yet connected. The shell does not claim that sign-in, profile editing,
circle membership or content delivery work in this app yet; those are EE-029
and EE-030 and later Sprint 5/6 integration tasks.

Run local checks from the workspace root with D-drive cache isolation:

```powershell
.\apps\mobile\tools\Verify-Android.ps1
.\apps\mobile\tools\Verify-Android.ps1 -BuildPackage
.\apps\mobile\tools\Verify-Android.ps1 -ClientTestPackage
```

Android package identifier: `com.eldercaresaathi.amiko`. Keep the app and its
Google/Firebase registration aligned when migrating from the phone-sign-in
test harness. No Firebase settings, account credentials or release signing
keys belong in this public repository. The generated debug signing key is
ignored. `clientTest` is a locally signed, self-contained phone-test package;
it is **not** a production release. Production signing must be configured
privately before release.
