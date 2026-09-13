# EE-009: Member phone sign-in acceptance

Status: implementation candidate; do not mark the sprint item Done until device
results and client approval are recorded. This is the Week 2 sign-in slice, not a
production release of the full app.

## Checks the project team can automate

- Compile the Android app, run phone/code/cooldown policy tests and Android lint.
- Verify the Google identity-to-private-database-to-Member-session path.
- Verify that simultaneous session creation cannot bypass five new sessions per
  Member in ten minutes. Revoking a session or changing device identifiers does
  not reset this limit. The limit is stored in existing database session records
  and works across processes/instances; no new personal-data table is added.
- Verify that the default local Android test relay accepts only the development
  login route, never returns the operator's cloud token and does not expose other
  APIs. Explicit EE-011 mode adds only the bounded session-control routes described
  in `EE-011-ACCEPTANCE.md`.

Google's official phone SDK provides app verification, code checks and provider
limits. Local resend/wrong-code controls are usability guards, not a claim that
an altered app cannot bypass them. Real SMS delivery and Play Integrity are not
proved by fictional numbers. Overall SMS spend must also be watched in Google
quotas/billing; the backend session cap alone cannot cap Google SMS charges.

## Client device checklist

Use a configured, privately supplied debug build on an approved Android phone.
The project team starts the loopback relay and links it with Android Debug Bridge;
no Google administrator password or token is typed into the app.

1. Open Amiko. Check readable Bengali and Hindi labels; switch language before sign-in.
2. Reject an incomplete/invalid phone number without sending a request.
3. Require the phone-verification consent checkbox before requesting a code.
4. Use a fictional number and its test code from the client-owned Google console,
   not a code posted in chat, source or reports. No actual SMS is expected.
5. Enter an incorrect code: sign-in must fail, and a corrected code must work.
6. Confirm resend is unavailable during the countdown, then request a new code.
7. Repeat wrong codes: the screen must ask for a new code rather than retry forever.
8. Test a brief network outage: show a clear retry message, not a successful login.
9. Correct code and connection: show successful Member sign-in. The profile screen
   belongs to the next sprint task and is not simulated here.
10. Finally test one consenting real phone: receive and verify a real message,
    check Google app-verification behavior and confirm the login in the backend.

Record device/model, Android version, build revision, date, pass/fail results and
reproducible defects. Do not record the actual phone, verification code or tokens.
Client language/privacy wording review and acceptance remain required.

The debug relay is local test plumbing only. Direct production mobile access
requires the planned authenticated public entry point and separate production
configuration; developer cloud credentials must never be placed in the release app.
