# Elder Engage REST API change log

The contract remains controlled. Only operations named in a matching verified deployment record are claimed callable; contract-only operations remain unavailable.

## Backend Release 1 availability clarification — 0.3.5 draft — 21 September 2026

- Marked `GET` and `POST /v1/admin/users` as planned and not callable. These operations depend on the later Administrator workflow; no implemented route or promised release date changed.
- Marked the corresponding Postman requests as not callable and added a regression check comparing every documented operation with the application routes.
- This is a documentation and test clarification, not a public deployment, iOS handover or client acceptance.

## Basic events — 0.3.5 development verified — 16 September 2026

- Added Administrator creation of future information-only events for all Members or one-to-twenty active circles.
- Added zero-to-five unique reminder offsets from five minutes to seven days before an event. EE-021 records the schedule; notification delivery remains a later milestone.
- Added bounded upcoming/past Member event pages that recheck current active-circle membership on every request.
- Applied V0009 and passed the private development proof for Administrator-only creation, stored reminder rules, circle isolation and immediate access removal.
- Google Meet and telephone joining remain separate later integrations. Deployment and live fictional audience proof are still required; this source candidate is not a production release.

## Circle-filtered Member feed — 0.3.4 — 16 September 2026

- Added Administrator publication of an approved, clean item to either all Members or one-to-twenty active circles.
- Added a bounded, cursor-paginated Member feed that rechecks current active-circle membership on every page and every media request.
- Publication promotes the exact reviewed file from quarantine into private approved storage. Member media links expire after five minutes and use a dedicated read-only signer.
- Unapproved, unpublished, quarantined and out-of-audience items are never returned. Publication and audience choice are audited.
- The locked package, private Cloud Run deployment, authenticated health check and live fictional Member/circle audience-isolation proof passed. Production acceptance remains part of the later release gate.

## Administrator content moderation — 0.3.3 — 16 September 2026

- Added an Administrator-only pending queue, two-minute private previews, and final approve/reject decisions.
- Rejection uses the approved reason list; `other` requires an explanation. Every decision records the Administrator, time, reason and audit event.
- Approval does not publish content. Audience selection and Member feed publication remain EE-020.
- Added checksum-locked V0008 and a separate read-only preview identity restricted to the private content-quarantine area.
- V0008, the separate preview identity, private Cloud Run deployment, GitHub health check and live synthetic MP4/MP3/PDF proof passed. Production acceptance remains part of the later release gate.

## Contributor uploads — 0.3.2 — 16 September 2026

- Added Contributor-only start/complete operations for private MP4, MP3/M4A and PDF uploads.
- Added mandatory ownership/permission confirmation and separate 250 MiB video, 50 MiB audio and 25 MiB PDF limits.
- Completion verifies the stored content type, exact size, SHA-256 fingerprint and file signature before recording that the current file checks passed and placing the item in pending Administrator moderation. It never publishes the upload. This status does not claim advanced malware or artificial-intelligence screening.
- Added checksum-locked V0007, a restricted `content-quarantine/` storage permission, Android/iOS examples and synthetic-media generation recipe.
- Explicitly type the rights-statement audit value so PostgreSQL can commit a valid upload authorisation.
- V0007, the private Cloud Run deployment, authenticated health check and live fictional MP4/MP3/PDF proof passed. Production acceptance remains part of the later release gate.

## Predefined-circle candidate — 0.3.1 draft — 15 September 2026

- Added Member circle discovery, interest/language suggestions, immediate join/leave and the client-approved initial five-circle limit.
- Added Administrator create/list/update/deactivate, Member assignment/removal and a changeable one-to-twenty membership-limit setting.
- Circle and membership changes use current account permissions, retain membership history and create minimal audit records. Contributors do not receive Member circle access.
- Added checksum-locked V0006 for the single circle-limit setting, Android/iOS contract examples and disposable PostgreSQL coverage.
- V0006, the private development deployment and a repeatable fictional-account live proof passed. Client production acceptance remains a later release activity.

## Notification-preference candidate — 0.3.0 draft — 15 September 2026

- Added authenticated read and complete-replacement operations for an account's own notification preferences.
- Event reminders and content updates are independent choices. The optional local-time delivery window supports overnight ranges and validates its time zone before saving.
- A replacement and its minimal audit record commit together. Missing saved preferences return safe defaults without writing data.
- Added Android/iOS request and response examples, negative contract checks and a generated Sprint 3 Postman collection.
- The source, private development deployment and fictional-Member save/read/restore trial passed under EE-022. No real text message or notification was sent.

## Week 2 private development verification — 15 September 2026

- Deployed and verified Google phone identity exchange, Member/staff sessions,
  refresh/logout/device revocation, own profiles, private profile-photo handling,
  and Administrator status/role controls in the private development environment.
- Applied checksum-locked database migrations through `V0005` using recorded
  one-time jobs after a fresh successful backup. GitHub's authenticated private
  health check and live fictional Member/profile/photo checks passed.
- The photo trial used a synthetic image and no real text message. It verified a
  restricted upload, WebP conversion, metadata removal, short-lived viewing and
  completed-upload replay rejection without printing tokens or signed links.
- The client-triggered final acceptance page reported Success on 15 September
  2026. All four outstanding photo checks passed with a fictional Member and a
  generated picture; no real text message or personal photo was used. The agreed
  Week 2 development scope is accepted.
- Administrator user creation/listing, the production Administrator console,
  real staff invitation/recovery, staging/production release and direct iOS
  handoff remain outstanding. This is not a production release.

## Account-control candidate — 0.2.2 draft — 14 September 2026

- Implemented disabled-by-default status/role PATCH handlers at the existing
  paths. Added explicit profile/account outage responses and profile forbidden
  responses; no success-payload changes.
- Current Administrator permissions, serialized mutations, last-Administrator
  protection, session revocation and atomic audit apply. Invitations cannot be
  activated through status changes; Administrator promotion requires confirmed
  MFA. Role conversion never converts an existing saved login's privileges.
- Staff creation/enrollment, profile photos, controlled cloud release and client
  acceptance remain open. This source increment is not a production release.

## Staff sign-in interface candidate — 14 September 2026

### Profile implementation and language extension — 0.2.1 draft

- Added approved English profile preference alongside Bengali/Hindi to profile,
  staff creation and session-summary schemas. Existing fields/paths unchanged;
  clients with closed language lists must add English before using this choice.
- Added disabled-by-default own-profile GET/PATCH implementation with current
  session/owner checks, omission versus explicit-null rules, notification-window
  validation and atomic minimal audit records. Creation requires name/language.
- The age label is `55+`, not an age restriction; younger users are not blocked.
  Future age gating requires an agreed age input/verification policy and rollout.
- V0004 extends only profile language; released V0001–V0003 bytes stay unchanged.
  Live migration/deployment, photo workflow and client acceptance remain pending.

### Shared runtime implementation candidate (not deployed)

- Connected the existing staff sign-in handler and shared refresh, logout and
  device operations behind an off-by-default staff switch. Signed access proofs
  determine routing; each adapter rechecks current account and session state.
- Staff startup requires the recorded staff schema changes and a separate pinned
  authenticator encryption secret. The application does not read the migration
  ledger. No path or success-payload changes; staff refresh preserves staff role.
- Enrollment/recovery, controlled live database update and client acceptance
  remain outstanding. This entry is not a production release or iOS handover.

- Validated the existing staff-sign-in request/response interface for Android,
  iOS and web. No path or success-payload changes. Added the unavailable response.
- Administrator password plus authenticator-app code is approved; Contributors
  remain Administrator-created username/password accounts. Actual credential
  activation, verification and staff-session controls still need implementation.
- The endpoint remains unavailable without a real adapter. Test fixtures cannot
  be enabled through cloud/runtime configuration. This is not deployed staff
  login, production acceptance or an external iOS handover.

## Member refresh development verification — 13 September 2026

- The Member refresh implementation from commit `83f095c578794da6bf046ecaefa141e2242bee0e` is deployed and verified in the private development environment. GitHub passed 207 backend tests, including PostgreSQL 16 integration checks; the deployed private-health check also passed.
- Seven live fictional-account checks passed: stable Android/iOS Member identifier, replacement credentials, old-access rejection, reuse-family revocation with another family unaffected, logout blocking renewal, own-device removal blocking renewal, and private-service access. No real SMS was sent.
- This does not make every operation in this draft callable. Android persistent-session acceptance and EE-010 staff support remain outstanding. No public/production origin or iOS handover is included.

## Member refresh implementation note — 13 September 2026

- Implemented single-use Member refresh at the existing `/v1/auth/refresh` path: stable user identifier, new credentials, unchanged session-family expiry, and committed family revocation on token reuse.
- Added the dependency-outage response. Clients must not replay a refresh token after an uncertain outcome or an outage response; sign in again instead. This operation does not advertise automatic outage retries.
- Renewals do not consume the fresh phone-sign-in allowance. Logout, removed-device, suspended-account and expired-session protections apply to renewal.
- No success-payload or path changes. Candidate is not yet deployed. Android persistence/renewal and EE-010 staff-session acceptance remain outstanding; EE-011 is not complete.

## Member session-control implementation note — 12 September 2026

- Added explicit suspension and dependency-outage responses for Member device listing, logout and device removal, plus invalid-path validation for device removal.
- Clarified owner isolation, token-family revocation and rejection of a removed session.
- No path or success-payload changes. Backend candidate remains undeployed; staff sessions and refresh rotation are not included in this implementation step.

## 0.2.0-draft — 12 September 2026

- Replaced Administrator-pre-provisioned Member sign-in with the approved immediate-access self-registration journey.
- Added `profileComplete` and a new-Member response example so Android and iOS can route incomplete profiles to self-service setup.
- Kept Contributor creation under Administrator control.

## 0.1.3-draft — 12 September 2026

- Added the documented retryable dependency-unavailable response to Member session creation.
- Began the callable Member-session foundation while keeping external phone verification, persistent member lookup and secure token storage fail-closed until their production adapters are connected.

## 0.1.2-draft — 9 September 2026

- Added distinct safe problem codes for unexpected internal errors, oversized request bodies and unsupported methods.
- Added health/readiness documentation for safe 413 and 500 responses to align the current EE-002 process foundation.
- Retained dependency outages as retryable 503 responses; unexpected application failures are not classified as dependency outages.

## 0.1.1-draft — 9 September 2026

- Established the engagement-platform contract as the current source and marked inherited booking interfaces legacy.
- Closed strict Profile composition and response-token direction defects.
- Added manual role-specific profile onboarding and profile-photo upload lifecycle.
- Added stable authentication/session error actions and HTTP-status mappings.
- Defined manual Member pre-provisioning, invited staff state, serialized refresh recovery, profile patch and notification-window semantics.
- Added eight synthetic examples, repeatable JSON Schema checks and a matching 16-request Postman companion.

No staging origin, implementation, deployment, iOS receipt or client acceptance is included in this draft release.

## Change rules

- Additive, optional version-one fields require OpenAPI, example, contract-test, Postman and change-log updates in the same pull request.
- Removing or changing a field, or making optional input mandatory, requires `/v2` plus a documented migration window unless the client and iOS developer explicitly approve a recorded exception before merge.
- Each shared draft records its Git commit, contract checksum, recipient, date, questions and acknowledgement in the notification log.
