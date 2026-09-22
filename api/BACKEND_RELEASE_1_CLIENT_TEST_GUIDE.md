# Amiko Backend Release 1 client test guide

Status: protected development test address available at
`https://api-test.eldercaresaathi.com`. Begin the eight acceptance journeys only
after Codex supplies the matching build/package revision and fictional test
identities through the agreed secure channel. Passing the gateway check is not
the same as passing the client journeys.

## Before testing

The client names one acceptance owner and the Member, Contributor and
Administrator testers. Never place a password, one-time code, authenticator key,
session token, phone number, signed media address or personal information in a
defect report.

Use the generated files from the Project Manager's D-drive test folder:

- `amiko-synthetic-upload-sample.mp4`
- `amiko-synthetic-upload-sample.mp3`
- `amiko-synthetic-upload-sample.pdf`

They contain no client material and are marked not for publication outside the
test environment.

## Acceptance journeys

Record Pass or Fail for every numbered journey.

1. **Member access and profile** — sign in using the approved test method;
   confirm immediate access; create/update the detailed profile; select English,
   Bengali and Hindi in separate checks; reopen the client and confirm the login
   remains saved; sign out and confirm protected information is no longer shown.
2. **Staff access** — confirm Contributor sign-in works with Administrator-issued
   credentials; confirm Administrator sign-in requires both password and the
   changing authenticator-app code; confirm each role sees only its permitted
   operations.
3. **Circles** — view predefined circles and suggestions; join and leave as a
   Member; create/update and assign/remove as an Administrator; confirm a
   Contributor cannot perform Administrator circle actions.
4. **Contributor uploads** — upload the generated MP4, MP3 and PDF with the rights
   confirmation selected; confirm each becomes pending rather than public;
   confirm a request without rights confirmation is rejected.
5. **Administrator moderation** — preview pending items privately; approve one
   and reject another using an approved reason; confirm the Contributor cannot
   moderate their own submission and approval alone does not publish it.
6. **Publication and feed** — publish an approved item to all Members, then a
   different item to one circle; confirm the correct Members see each item and a
   Member removed from that circle immediately loses access.
7. **Events and preferences** — create an information-only future event for all
   Members and another for one circle; confirm audience visibility; save and
   reload event/content notification preferences and an optional delivery window.
   No actual reminder is expected in this release.
8. **Account controls and recovery behaviour** — suspend and restore a fictional
   account; confirm suspension blocks access; change a fictional role and confirm
   an already-open session does not keep the removed permission; retry after a
   temporary connection interruption without creating duplicate content.

## How to report a failure

Create one issue per reproducible problem containing only:

- journey number and short title;
- test date/time and test role;
- device/application or REST-client version;
- steps performed;
- expected result;
- actual result;
- safe screenshot with identifiers and credentials removed;
- severity: release blocker, major, normal or minor.

A release blocker means a required journey cannot be completed, data is exposed
to the wrong role/audience, data is lost/corrupted, or the service cannot recover
through its documented path. Wording, spacing and cosmetic issues are recorded
but do not automatically block the backend release.

## Acceptance result

The acceptance owner records one outcome: Accepted; Accepted with listed
non-blocking issues; or Rejected with reproducible release blockers. Silence or
an incomplete checklist is not acceptance.
