# EE-011: Android saved sign-in and session controls

Status: implementation candidate in the native development test app, not the full
final application. EE-011 remains In progress until device/client results and
EE-010-dependent staff-session coverage are accepted.

## Implemented behavior

- Reopen: decrypt saved credentials with the existing Android Keystore key, then
  check current account/session state with the server before showing success.
- Expired access: renew once, preserving the same Member identifier. One
  process-wide lock prevents concurrent screens from reusing a refresh token.
- Clear saved credentials before sending renewal; process death or an uncertain
  renewal outcome cannot cause the old token to be resent after reopening.
  Save both replacement credentials together in one encrypted commit.
- Ordinary connection failure before renewal retains encrypted credentials but
  shows a retry message, not successful access. Failed/uncertain renewal returns
  to phone sign-in. Suspended/revoked/expired accounts cannot regain access.
- Sign-out requires confirmed server revocation before showing completion.
  Offline sign-out reports failure and requires reconnection, rather than
  claiming that the remote session was removed.
- List own devices and confirm removal. Removing this device signs it out;
  removing another device retains the current sign-in. The backend enforces
  ownership, and an unavailable target cannot be removed.
- Bengali/Hindi/English controls; no credentials in logs, screenshots, backups or Git.

Encryption uses the existing app-bound key and authenticated encryption, following
[Android's Keystore guidance](https://developer.android.com/privacy-and-security/keystore).
Local controller tests do not prove hardware key storage or real device behavior;
these need the phone checks below.

## Client phone checks (pending)

Use the approved connected development build, not a production/store release.
The project team enables the loopback relay's bounded session routes with:

`python -m tools.development_login_relay --project approved-development-project --region approved-region --session-controls --confirm TEST-EE-011-development`

The default EE-009 relay still accepts only phone-login exchange. Session mode
adds only renewal, logout, own-device listing/removal, uses separate cloud and
platform headers, and never sends the operator credential to the phone.

1. Open after the update: an existing valid sign-in should be restored without a
   new code. If it expired, use a fictional Google test identity and sign in.
2. Close/reopen Amiko, then force-stop/reopen: no new phone code should be needed
   while the saved session remains valid. Check Bengali, Hindi and English controls;
   the selected language should survive reopening without signing the Member out.
3. Wait over ten minutes with the valid sign-in, then check/reopen. Renewal should
   happen once without another phone code; the backend Member identifier stays
   unchanged. Do not record phone numbers, codes or tokens as evidence.
4. Briefly disconnect the network before checking sign-in: show failure, then
   reconnect and check again. Do not grant access from cached credentials alone.
5. Sign out and confirm: return to phone sign-in. Reopening must not restore the
   removed session. Sign back in with the fictional identity.
6. Cancel the sign-out/removal confirmation: remain signed in.
7. Remove this device and confirm: return to phone sign-in; reopening stays signed out.
8. Another-device removal needs a second synthetic session created by the project
   team. Remove only that designated test session; the current device stays signed
   in and the removed session fails its next protected request/renewal.

The project team also tests interrupted renewal and process restart without real
phone data. Unit simulations alone are not live Android lifecycle acceptance.
Record build commit, device/Android version, date, results and client approval.
Staff coverage waits for EE-010; production gateway/configuration, profiles and
the full final app remain separate planned items. No iOS application is built here.
