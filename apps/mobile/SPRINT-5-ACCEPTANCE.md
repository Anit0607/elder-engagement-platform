# Sprint 5 Android client check

This is a test of the Android app, not a production release. Use the approved
development environment and fictional account/content where possible. Do not
put personal photos, passwords or verification codes into a defect report.

Before starting, Codex must confirm that the test web address has a working
security certificate and provide a connected Amiko test build. The client
should approve the logo, colours and English/Bengali/Hindi wording separately.

| Sprint item | What the client does | Pass condition |
| --- | --- | --- |
| EE-028 | Install on the agreed Oppo phone; open Home, Circles and Profile; switch English, Bengali and Hindi; close and reopen the app. | All three areas open, labels change, chosen language survives reopening and the app does not close unexpectedly. |
| EE-029 | Sign in as a Member with the approved test method; reopen the app; sign out and sign in again. | Sign-in works, the account stays signed in until sign-out, and a signed-out account cannot view private profile data. |
| EE-029 | Create or edit a fictional Member profile: name, interests, state/city, language, optional `55+` choice and notification window. | Saved details reappear after reopening. Choosing no age group does not block the Member. Invalid or missing required details are explained clearly. |
| EE-029 | After saving the profile, choose a non-personal test image; cancel once and complete once. | Cancel leaves the profile unchanged. A valid image uploads privately and reappears. Unsupported/oversized files fail safely. |
| EE-029 | View signed-in devices; remove an approved fictional other device; then sign out. | Only this Member's devices appear; removing a device requires confirmation and does not expose credentials. |
| EE-030 | View predefined circles after sign-in; check suggestions; join and leave one test circle. | Suggestions reflect saved interests/language, membership changes are confirmed by a fresh server list, and leaving asks first. |
| EE-030 | Reach the Administrator-configured membership limit using fictional test circles. | The app explains the limit and does not falsely claim another circle was joined. |

For each row, record **Pass**, **Fail** or **Not tested**, the phone model and
Android version, and a short description of any failure. A screenshot is useful
only after checking it contains no personal information or codes. Codex keeps
EE-028 to EE-030 open until the relevant checks pass and the client accepts them.
