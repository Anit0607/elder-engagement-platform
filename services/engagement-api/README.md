# Elder Engagement API process foundation

## Week 2 staff enrollment foundation

`app/staff_enrollment.py` is a tested internal service, **not an enabled route,
an executable cloud bootstrap, or a completed enrollment/recovery workflow**.
It creates a Contributor only inside current Administrator authorization and
creates the first development Administrator only after a valid authenticator
confirmation. Administrator setup records that code as used: the next sign-in
must use a newly changing code. Passwords are hashed; authenticator seeds are
account-bound encrypted; neither is returned or written to audit metadata.
Creation, credentials, profile and audit commit together. A duplicate username
or existing Administrator is never overwritten. Uncertain commits are not
automatically retried. The first-Administrator check uses the same database
lock as role/status controls and is tested for concurrent attempts.

The development confirmation/environment arguments prevent operator mistakes;
they are **not access control**. Before cloud execution, provide a reviewed,
private operation with Google Cloud permissions, secure input transport, a
dedicated encryption key, an execution record and a verified backup. No public
endpoint may expose the first-Administrator method. Production bootstrap and
credential recovery require their own controlled workflow. Existing public
manual-profile request shapes and REST contracts are unchanged by this module.

`python -m app.development_staff_setup` is the fictional-only Cloud Run job
candidate. It refuses production, an unexpected job/project and missing private
input. It uses private IAM Cloud SQL access and the same credential/session
checks as the app. Both fictional accounts and their verification/audit records
share one outer transaction; a failed check rolls everything back. Its test
logins are signed out. Generated fixture codes do not count as client acceptance
of an authenticator app. The job, pinned secret versions, immutable image and
controlled execution are **not provisioned by this source change**. Never run
it against another environment or expose it through a public route.

Status: Sprint 1 foundation and the agreed Week 2 backend are deployed, verified and client-accepted in the private development environment. This remains a development release, not production readiness or final product acceptance. The acceptance boundary and evidence are recorded in [WEEK-2-ACCEPTANCE.md](WEEK-2-ACCEPTANCE.md). The top-level `backend/` directory is an inherited booking implementation and is not imported, renamed or extended here.

Implemented now:

- strict loading of the checked-in `config/engagement` contract;
- a minimal process-liveness `GET /health` route;
- fail-closed dependency-readiness `GET /ready` with injectable probes;
- structured redacted JSON application logs;
- validated request IDs and W3C trace correlation;
- safe response headers, explicit trusted hosts and CORS;
- a non-root, immutable-source container foundation for a later Cloud Run deployment;
- exact runtime/development dependency locks and automated checks.
- a tested Member identity-token exchange and session-service boundary;
- a Google Identity Platform/Firebase phone-token verifier that checks the
  signature, intended project, issuer, phone provider and verified phone claim;
- an atomic PostgreSQL Member resolver that prevents duplicate or crossed
  phone identities during concurrent sign-in;
- a secure session issuer that stores only a one-way refresh-token fingerprint
  and puts no phone or profile details in short-lived access tokens;
- an enabled-runtime, database-backed limit of five new Member sessions per ten
  minutes, serialized under a user-row lock across instances and device changes;
- rotating refresh, logout and owned-device revocation for Member and staff sessions;
- Contributor password sign-in and Administrator password plus authenticator-app sign-in;
- role-bound own-profile and Administrator account-control permissions;
- detailed English/Bengali/Hindi profiles with the non-restrictive `55+` label;
- private, short-lived profile-photo upload/view links and metadata-stripping image processing;
- Member-controlled event-reminder and content-update choices with an optional local delivery window;
- a versioned Sprint 3 REST contract containing the verified foundation, circles, private Contributor uploads, Administrator moderation, circle-filtered feed and basic events.

The development container is deployed to private Cloud Run, and checksum-locked migrations `V0001`–`V0009` are applied to private Cloud SQL. The Member-session service follows the approved immediate-access boundary: the repository atomically finds or creates an active Member for a verified phone identity, and `profileComplete=false` routes a new Member to self-service profile setup. Cloud SQL uses private IP and automatic IAM authentication. Cloud Run loads only pinned Secret Manager versions; missing, weak or equal keys prevent startup. Database commands and certificate requests are time-bounded, and pool, connector and certificate session resources close at shutdown. Contributors remain Administrator-created. Notification preferences, circles, Contributor uploads, Administrator moderation, the circle-filtered feed and basic events are deployed and verified. Media providers remain later work.

## Notification preferences (EE-022, verified in private development)

Authenticated accounts can read and completely replace only their own notification preferences. Event reminders and content updates are independent choices. The optional delivery window uses a validated time zone and supports windows that cross midnight. Missing saved preferences return safe defaults without changing the database. Each saved replacement and a minimal, non-personal audit record commit together. The internal delivery policy rejects unknown categories and times without a time zone. The private development deployment and fictional-Member save/read/restore trial passed without sending a real text message or notification.

## Predefined circles (EE-017, verified in private development)

Members can list active predefined circles, receive recommendations from saved interests or preferred language, and immediately join or leave their own circles. Administrators can create, list, update, deactivate/reactivate and assign/remove active Members. The initial limit is five active membership records and can be changed from one to twenty through an Administrator-only setting. Membership history and audited changes are retained. Contributors receive no Member-circle permission. V0006, private deployment and the repeatable live fictional-account proof passed.

## Contributor content uploads (EE-018, verified in private development)

Only a currently active Contributor can start or complete a content upload. The request requires a versioned ownership/permission declaration and enforces 250 MiB for MP4 video, 50 MiB for MP3/M4A audio and 25 MiB for PDF. A five-minute signed `PUT` sends the file directly to the private `content-quarantine/` prefix. Completion streams the object to check its declared type, exact size, SHA-256 fingerprint and file signature without loading the whole file into memory. A valid item is marked as having passed these current file checks and becomes pending for Administrator moderation; it is not copied to approved storage or published. This status does not claim advanced malware or artificial-intelligence screening. The synthetic MP4/MP3/PDF development proof passed. Administrator review and rejection reasons are EE-019; audience selection, promotion and Member delivery remain EE-020.

## Administrator content moderation (EE-019, verified in private development)

Only a currently authenticated Administrator can list the pending review queue,
request a two-minute private preview, or make a final decision. Contributors cannot
open this desk or decide their own material. Rejections use the client-approved
reason list; `other` requires a written explanation. Each decision, reason, actor
and time is committed with an audit event. A separate read-only preview identity
is restricted to `content-quarantine/`. Approval changes only the review state and
does not publish or select an audience; those remain EE-020.
V0008, the restricted preview identity, private deployment, GitHub health check
and live synthetic MP4/MP3/PDF workflow all passed.

## Approved-content feed (EE-020, verified in private development)

An Administrator can publish an approved clean item to all Members or to one-to-
twenty active circles. Publication copies the exact reviewed object from the
quarantine bucket to the private approved-content prefix, records the audience
and publication time, and writes an audit event. A dedicated read-only delivery
identity signs five-minute Member links. The bounded cursor feed and media route
both recheck current active-circle membership; unapproved, unpublished,
quarantined and out-of-audience items are excluded. The private deployment,
authenticated health check and live fictional audience-isolation proof passed.

## Basic events (EE-021, development verified)

An Administrator can create a future information-only event for all Members or
one-to-twenty active circles, with an optional end time and up to five unique
reminder offsets between five minutes and seven days. Members can list only
their visible upcoming or past events; every page checks current active-circle
membership. Each creation and its audience/reminder rules commit with a minimal
audit event. EE-021 records reminder timing but does not deliver notifications.
Google Meet and telephone joining remain later integrations. V0009, private
deployment and live fictional audience-isolation proof remain required.

## Staff sign-in (EE-010, verified in private development)

### Administrator account controls (EE-014, verified in private development)

Status and role PATCH handlers require connected staff authentication and
`EE_ACCOUNT_CONTROLS_ENABLED=true` (default false). Only a currently authenticated
Administrator may use them. Cross-account mutations share a transaction lock
before user-row locks, preventing reversed Administrator locks and concurrent
removal of the last usable active Administrator. Suspension revokes sessions;
reactivation does not resurrect them. Reasons and from/to values are recorded in
the private audit table in the same transaction, never ordinary request logs.

Invitation activation is separate. Member-to-Contributor changes create an
invited account requiring staff credential setup. Administrator promotion requires
an enrolled authenticator with a confirmed code. Staff-to-Member conversion needs
existing Google phone identity and removes staff credentials before changing role.
Role changes revoke old sessions. Staff creation/enrollment and the Administrator
console remain separate work; these source handlers do not claim live acceptance.

### Own profiles and photos (EE-013, verified in private development)

`EE_PROFILE_ENABLED=false` is the default. Enabled profiles require connected
identity and V0004 English preference support at startup. `GET/PATCH
/v1/me/profile` use server-verified current sessions and owner-bound transaction
locks. First creation requires display name and preferred language. Subsequent
updates preserve omitted fields; explicit null clears only age/broad location;
interest arrays and notification objects replace their previous contents.
Time-zone existence is checked against PostgreSQL's supported time-zone names.
Window times are local; a later start represents a midnight-crossing window.

English/Bengali/Hindi and the `55+` profile label are approved. Younger users are
not blocked. Future minimum-age enforcement is a separate extension requiring
an agreed age input, consent/verification and policy rollout, not just a label.
Profile audits store changed field names, not names/location/interest values.
Photo authorisation uses a five-minute signed upload restricted to the declared
type and exact size, with a five-mebibyte maximum. The server verifies the hash
and real image format, applies orientation, resizes oversized images, converts to
WebP and strips source metadata before attaching it. Both buckets and object keys
remain private; profiles receive only a five-minute view link. Synthetic live
development checks passed, but they do not substitute for client acceptance.

### Week 2 permissions (EE-012, verified in private development)

`app/authorization.py` defines own-profile/own-account permissions for active
users and Administrator-only staff creation/status/role controls. A verified
session is rechecked against current account, credential and session state.
Protected handlers must use the yielded connection: account and session locks
remain held until protected work and its audit record commit together. Unknown
permissions, unowned targets, suspended accounts, changed roles/credential
versions and revoked sessions are rejected. This library alone does not implement
profile or account-control endpoints and does not complete EE-012 acceptance.

### Shared runtime wiring candidate (not deployed)

`EE_STAFF_SESSION_ENABLED` defaults to `false`. Enabling it requires connected
Member sessions and a dedicated numeric
`EE_STAFF_AUTHENTICATOR_KEY_SECRET_REF`. Cloud Run injects that secret into
`AMIKO_STAFF_AUTHENTICATOR_KEY_BASE64`; it must decode to exactly 32 independent
bytes. Runtime startup checks staff columns, validated constraints and enabled
credential/role-change guards through metadata, without migration-ledger access.
The shared session adapter verifies signed claims before access-token routing;
refresh routing uses the stored credential-version marker and the selected
adapter revalidates authoritative state under its transaction locks.

Staff refresh responses retain Contributor/Administrator roles. Member sign-in
and the existing REST paths/payloads remain unchanged. Terraform wiring is also
off by default; this source change does not apply infrastructure or enable staff
login. Staff enrollment/recovery, the controlled live update, measured cloud
performance and client acceptance remain open. Earlier candidate descriptions
below record preceding implementation steps, not the current deployment status.

`POST /v1/auth/staff/session` now has validated username/password, optional
second-factor code, installation and Android/iOS/web inputs. Passwords and codes
use masked secret types in ordinary model diagnostics, following
[Pydantic secret-type guidance](https://docs.pydantic.dev/latest/api/types/#pydantic.types.SecretStr).
Validation failures use the existing safe problem response, never input values.
Client-supplied roles are rejected. Responses allow only active Contributors or
Administrators and omit credential fields.

**No real staff sign-in is enabled or deployed by this change.** With no real
adapter, the endpoint returns `503 DEPENDENCY_UNAVAILABLE` without issuing tokens.
Test fixtures are injected only in tests, never through a runtime flag or cloud
configuration. Password/code verification and transactional issuance/counters
are implemented as disabled candidates below. Secure activation, authenticator
enrollment/recovery, live database update, runtime wiring and staff session
renewal/controls remain EE-010/EE-011 work. Keep Member login unchanged.

The agreed policy is Administrator-created Contributor usernames/passwords and
Administrator password plus an authenticator-app code. Secure test-account
activation and client acceptance are required before enabling the real adapter.
There is no staff console in this interface change; console work remains in its
planned sprint. No iOS application is developed here.

### Credential verification candidate (not enabled)

`app/staff_credentials.py` implements actual salted Argon2id password hashing and
verification, encrypted account-bound authenticator seeds and six-digit,
30-second TOTP verification. The Argon2id policy uses 19 MiB, two iterations and
one lane, following the minimum in
[OWASP password-storage guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).
Stored hash parameters cannot select arbitrary work or memory costs. A
process-wide two-worker bound remains held until the hashing thread finishes,
even if its awaiting request is cancelled. Hashing is moved off the event loop.
Cloud worker performance still needs measurement before release.

Authenticator verification uses pinned PyOTP and
[RFC 6238](https://www.rfc-editor.org/rfc/rfc6238), with a one-step clock-drift
window. The checker rejects steps at or below the supplied last accepted step.
It returns a step number, never a sign-in token. The real database adapter **must
persist that step and failed attempts under account/credential locks in the same
transaction as session issuance**; these unit checks alone do not implement
durable replay prevention or failed-attempt counting. Seeds use account-bound
[AES-GCM authenticated encryption](https://cryptography.io/en/latest/hazmat/primitives/aead/#cryptography.hazmat.primitives.ciphers.aead.AESGCM).
Its dedicated 32-byte key must be securely injected and kept separate from
session signing/refresh keys when runtime is connected.

The credential policy rejects unknown/non-staff/inactive accounts, wrong
passwords and codes; suspended accounts and current locks are respected.
Administrator access never falls back to password-only if authenticator setup
is missing or damaged. Secret setup values are not in ordinary record
representations. Wrong keys and corrupted ciphertext fail closed.
The log redactor also masks staff password hashes, second-factor codes, encrypted
seeds and authenticator setup URLs in structured context and diagnostic text.

The credential primitives alone do not activate users, enroll authenticators or
issue sessions. The database-backed candidate below builds on these primitives.

### Transactional database candidate (not enabled or applied to the client database)

`app/postgres_staff_session.py` connects authoritative staff credentials to
password/code verification and session issuance in one PostgreSQL transaction.
It locks the user before the credential row and never accepts a client-supplied
role. The default route still uses the unavailable adapter; this candidate is
not wired into application startup or deployed.

- Incorrect passwords or incorrect/reused authenticator codes persist a failed
  attempt before the error is returned. Five failures pause that account for ten
  minutes; an expired pause starts a fresh window. Valid sign-in clears failures.
  Missing codes, suspended/invited accounts, capacity/outage errors and successful
  sign-in throttling do not count as incorrect credentials.
- An Administrator must have an enrolled/enabled authenticator. Password-only
  Contributor sign-in remains supported. Unknown accounts receive the bounded
  dummy password check without creating an account.
- Accepted authenticator step, cleared failures and new session are committed
  together. Concurrent use of one code allows only one success. A failed session
  insert rolls back code consumption; lost commit acknowledgement returns no
  tokens and must not automatically replay the submitted code.
- At most five new session families may be issued per account in ten minutes,
  including recently revoked sessions. This is an implementation-candidate
  protection, not a viewer or subscription limit. Unknown-username/IP throttling
  still requires the planned shared ingress protections before public release.
- Additive migration `V0002` stores only account-bound encrypted authenticator
  seeds, the accepted step and a credential version. Password/authenticator
  changes rotate the version and revoke existing sessions; password-only changes
  do not erase the previously accepted authenticator step. Unchanged authenticator
  counters cannot move backwards. Credential rows cannot transfer to another user.
- Staff tokens/session rows contain the server-selected role and credential
  version. Existing Member tokens are unchanged and Member controls reject staff
  tokens. The staff controls candidate below supplies current-version/role checks;
  runtime routing and secure enrollment must still be connected before activation.

Unit tests use synthetic rows. PostgreSQL integration tests accept only the
disposable local PostgreSQL 16 test database, test actual locking/rollback/state
and never connect to the client database. Keep the default unavailable adapter
until secure enrollment/recovery, a dedicated runtime encryption key, staff
session controls, deployment and client acceptance are ready. Before applying
`V0002`, verify a usable backup and use a reviewed immutable migration image/job.
The existing one-time `V0001` runner is pinned to its original source/image and
must not be repurposed through ad hoc overrides. Do not edit the applied baseline
or relax the private database boundary.

### Staff session controls candidate (not runtime-connected)

`app/staff_session_controls.py` checks signed staff tokens, the current account
role/status, current credential version and owned unrevoked session on each
list/sign-out/device-removal operation. Administrators without an enabled
authenticator are rejected. Device removal cancels that owned session family;
another account's device is indistinguishable from a missing device.

Refresh rotates the one-use token, retaining the family's original absolute
expiry. Reuse revokes the family before returning an error. Password changes
invalidate previous credentials/sessions. Additive `V0003` revokes sessions on
role changes: an old Contributor refresh token cannot gain Administrator access
after promotion. Outages, insert collisions and uncertain commits never
automatically replay refresh/removal. Fresh sign-in remains possible.

This is backend testing, not client acceptance or a deployed staff console. Both
`V0002` and `V0003` are required. HTTP controls remain Member-only; shared-role
routing, the refresh-response contract, runtime startup wiring, a dedicated
encryption key, secure enrollment/recovery and live acceptance remain planned
EE-010/EE-011 work. Do not enable staff login in isolation. Connected Android,
iOS and web clients must use the reviewed shared REST contract.

## Local verification

The service is independently installable and does not use the inherited `backend/.venv`. From a PowerShell prompt:

```powershell
cd services\engagement-api
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.lock -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pytest --cov=app --cov-branch --cov-report=term-missing
.\.venv\Scripts\python.exe -m ruff check app tests tools
node --test tests/config_parity.test.mjs
```

Run it locally with the checked-in non-secret development example:

```powershell
.\.venv\Scripts\python.exe -m tools.run_local
```

Then `GET http://127.0.0.1:8000/health`. The default `/ready` response is intentionally `503` because no real dependency adapters are implemented. Tests inject deterministic probes without credentials or network calls. Stop the service with Ctrl+C.

The Cloud Run container definition is build-context independent of the legacy backend. Its pinned base image, non-root user, runtime-read-only source, Open Container Initiative revision metadata and TCP health check are statically tested. The manual GitHub development-candidate workflow runs the complete backend gate, publishes one candidate to Artifact Registry, then starts that exact digest and verifies `/health` before reporting it. Publication never deploys Cloud Run; the digest must enter a separately reviewed Terraform plan first.

The current Cloud Run configuration is deliberately development-only. It supplies the complete non-secret startup contract, uses platform TCP startup/liveness probes and keeps `deploy_application=false` until the candidate workflow returns a lowercase SHA-256 digest. `/ready` remains unavailable until real dependency probes are implemented; it must not be used as the current startup probe.

A real local `docker build` remains pending until a Docker daemon is available.

## Private development phone-login trial

The operator-only trial reads fictional identities from the approved Google
configuration and refuses missing test entries or a country mismatch. It checks
wrong-code rejection, genuine Google phone proof, Android/iOS session exchange,
repeat-account reuse, fake-proof rejection and private-service access. It prints
only a credential-free result. It retains the fictional Member and development
sessions; it never exercises real text-message delivery, Android Play Integrity,
profile screens, refresh/logout or production acceptance.

From this service directory, an authorised operator can run:

```powershell
.\.venv\Scripts\python.exe -m tools.test_development_member_login --project approved-development-project --region approved-region --confirm TEST-EE-009-development
```

The command uses the existing D-drive Cloud CLI/configuration and the currently
authenticated operator's existing permission to invoke private development Cloud
Run. It does not impersonate the GitHub service account, grant roles or make the
service public. Do not paste tokens or codes into the terminal, chat or repository.
A phone/login screen for client acceptance comes later.

## Member session controls (EE-011, partial implementation)

The enabled Member runtime also supplies `GET /v1/me/sessions`,
`POST /v1/auth/logout` and `DELETE /v1/me/sessions/{sessionId}`. These operations
accept the platform access token in `Authorization: Bearer ...`, not the Google
phone identity token. They verify the configured signature, issuer, audience,
expiry, Member role and required identifier/time claims, then check current
account and session state in the database. Account and session locks serialize
same-user changes; removed, expired, replaced and suspended sessions cannot act.
Device removal is scoped to the authenticated owner and revokes the target token
family. Missing and foreign targets return the same not-found response. Logout
returns an empty 204 response; a subsequent use of the removed session is refused.

Member listing, logout, removal and refresh are deployed and verified in private
development. Staff
sessions are not implemented. The native Android device-list/session test app
exists, with partial client phone acceptance; it is not the full final app. Existing login
routes remain unchanged. A private
Cloud Run trial must send the cloud-invocation token in `X-Serverless-Authorization`
and the platform token in `Authorization`; otherwise the two authentication layers
would compete for one header. No cloud permissions or schema changes are required.
JWT verification follows the [PyJWT verification documentation](https://pyjwt.readthedocs.io/en/stable/api.html)
with a fixed allowed signing algorithm, never a token-selected algorithm.

### Single-use Member renewal (development verified)

`POST /v1/auth/refresh` accepts a refresh token in its request body; no still-valid
platform access token is required. Successful renewal replaces both credentials,
keeps the Member identifier and installation, and preserves the family's original
expiry (30 days with the default configuration). Access tokens last ten minutes
by default, capped by remaining family lifetime. Less than sixty seconds remaining
requires a fresh phone sign-in. Tokens are stored only as keyed hashes in the
database. Reusing a replaced refresh token commits revocation of the entire owned
family before returning `REFRESH_TOKEN_REUSED`. Removed, expired, suspended,
deleted and non-Member accounts cannot renew. All session writers lock the user
before session rows to avoid inconsistent concurrent renewals/removal. Renewal
rows do not consume the five-fresh-logins-per-ten-minutes allowance.

Clients must serialize renewal, atomically save both replacement credentials and
never retry the old token after an uncertain response or a dependency outage.
The refresh route deliberately does not advertise automatic outage retries.
This safety policy follows the rotation/reuse principles in
[RFC 9700, section 4.14](https://www.rfc-editor.org/rfc/rfc9700.html#section-4.14).
The thirty-day absolute expiry is this application's configured policy, not a
requirement imposed by that standard.

EE-011 remains in progress: Android encrypted restoration, serialized renewal
and sign-out/device controls are implemented in the test app, with partial client
acceptance. Confirmed phone checks include saved sign-in after reopening and a
full app restart, English-language persistence, sign-out, current-device removal,
cancellation, and connection-error/recovery behavior. Timed renewal, designated
other-device removal and interrupted-renewal device evidence remain pending. Staff-session
coverage depends on EE-010. Do not treat backend-only tests as full EE-011 acceptance.

Development verification on 13 September 2026: source commit
`83f095c578794da6bf046ecaefa141e2242bee0e`, container digest
`sha256:cf4ab097b8086b99964edd439ed6ece996b5c2e52ce54cc03f22469b9d3b4190`.
GitHub verification passed all 207 backend tests, including PostgreSQL 16
integration tests, with 96.80% branch-aware coverage. Candidate build and private
deployed-health checks passed. The fictional-account trial passed all seven live
checks below without real SMS. The reviewed cloud plan changed only the server
image; database structure, permissions, phone provider and country settings did
not change. This is development evidence, not a full production release or
Android/client acceptance. Subsequent operator-trial tests are separate from the
deployed image and do not change its source identity.

### Private development session trial

After verifying deployment of the reviewed refresh implementation, run
`python -m tools.test_development_member_sessions --project approved-development-project --region approved-region --confirm TEST-EE-011-development`
from this service directory. It uses only phone identities already allowlisted
as fictional test numbers by Google and requests only those configuration fields
and the client API key, not the full identity configuration. It creates three
test sessions, checks stable Android/iOS identity, renews one, exercises reuse
revocation, signs another out, and removes only its own newly created current
device. The service must remain private. No real text message is sent; secrets,
tokens, phone values and Member identifiers are never printed. Synthetic database
rows remain; a failed trial may leave its newly created test sessions active until
expiry or controlled removal. Existing user devices are not altered. This trial
does not replace Android phone testing or EE-010 staff acceptance.

## EE-009 Android development trial

The first native Android phone-login app lives in `apps/android`. Google verifies
codes in the official SDK; the app exchanges the resulting identity proof through
the shared REST endpoint. A local, loopback-only development relay may be started
with `python -m tools.development_login_relay --project approved-development-project
--region approved-region --confirm TEST-EE-009-development` (one line).
By default it proxies only Android Member login and acquires the operator's existing cloud
identity internally; it never gives that cloud identity to the phone. Developer
access stays out of the APK. Device testing uses Android Debug Bridge port reversal
for port 8787. This is not a public production gateway. See the app acceptance
checklist before declaring EE-009 complete.

The Android EE-011 candidate opts into bounded session routes with
`--session-controls --confirm TEST-EE-011-development`. This adds only refresh,
logout, own-device listing and UUID-scoped removal. Platform access travels in
`Authorization`, and the internally obtained cloud token travels only upstream
in `X-Serverless-Authorization`. Extra routes/queries/bodies, missing platform
authentication, redirects and oversized upstream responses are refused. The
relay remains loopback-only, carries no cloud credential in the APK and is not
a production entry point.

The first live development trial passed all eight checks against the deployed
Google identity service and private Cloud SQL. Both Android and iOS request shapes
returned one Member account. This is backend evidence, not an Android device test
or production acceptance.

## Live development profile trial

`python -m tools.test_development_profiles --project approved-development-project
--region approved-region --confirm TEST-EE-013-development` (one line) verifies
approved profile fields and English/Bengali/Hindi persistence through the shared
REST interface. It uses the second configured fictional phone identity, sends no
real text message, refuses to overwrite a non-fixture profile and signs out its
test session. Clearly labelled synthetic profile data is retained. The test checks
that age labels do not restrict access; this is not proof of a person's age or an
implemented future age-verification policy. Automated development evidence does
not replace client acceptance.

`python -m tools.test_development_profile_photos --project
approved-development-project --region approved-region --confirm
TEST-EE-013-PHOTO-development` verifies the separate photo path with the same
fictional Member and an in-memory synthetic PNG. It proves the upload restriction,
private direct upload, server-side WebP conversion, metadata removal, short-lived
profile view link and completed-upload replay rejection. It never prints a token,
phone number, Member identifier or signed URL, and sends no real text message.

For the final Week 2 client check, run `python -m
tools.development_week2_acceptance_page --project approved-development-project
--region approved-region --confirm CLIENT-TEST-EE-016-development` (one line),
then open `http://127.0.0.1:8790`. The loopback-only page presents the earlier
accepted checks and lets the client trigger the remaining four profile-photo
checks with one fictional login, without seeing cloud credentials or signed links.
Google's fictional sign-in proof is prepared before the page reports that it is
ready, and a successful result is cached so an accidental second click cannot
create another login.

Do not copy `config/engagement/.env.example` into a staging or production deployment. It contains explicit non-operational development identifiers which secure-environment validation rejects.
