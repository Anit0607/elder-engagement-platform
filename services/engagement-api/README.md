# Elder Engagement API process foundation

Status: Sprint 1 development foundation deployed; Week 2 identity work started but not production-ready. This is the current Amiko service. The top-level `backend/` directory is an inherited booking implementation and is not imported, renamed or extended here.

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
- a versioned Week 2 REST contract for identity, profiles and account controls.

The development container is deployed to private Cloud Run, and database migration `V0001` is applied to private Cloud SQL. The Member-session service follows the approved immediate-access boundary: the repository atomically finds or creates an active Member for a verified phone identity, and `profileComplete=false` routes a new Member to self-service profile setup. `EE_MEMBER_SESSION_ENABLED=true` connects the verifier, repository and session issuer through the application lifespan. Cloud SQL uses private IP, automatic IAM authentication and a four-connection pool; it never loads the password-style database URL secret. Cloud Run injects the two pinned Secret Manager values as base64 into `AMIKO_SESSION_SIGNING_KEY_BASE64` and `AMIKO_REFRESH_PEPPER_BASE64`. Missing, weak or equal keys prevent startup. Disabling the flag preserves the unavailable login boundary. Database commands and certificate requests are time-bounded, and pool, connector and certificate session resources close at shutdown. Refresh, logout and session-management operations remain EE-011 work. Contributors remain Administrator-created. Profiles, staff sign-in, circles, content, moderation, feeds, events, notifications and media providers are not yet implemented.

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

Member listing, logout and removal are already deployed in development. The new
refresh implementation described below remains an undeployed candidate. Staff
sessions and the client device-list screen are not implemented. Existing login
routes remain unchanged. A private
Cloud Run trial must send the cloud-invocation token in `X-Serverless-Authorization`
and the platform token in `Authorization`; otherwise the two authentication layers
would compete for one header. No cloud permissions or schema changes are required.
JWT verification follows the [PyJWT verification documentation](https://pyjwt.readthedocs.io/en/stable/api.html)
with a fixed allowed signing algorithm, never a token-selected algorithm.

### Single-use Member renewal candidate

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

EE-011 remains in progress: this candidate needs the real PostgreSQL test gate and
deployment verification; Android encrypted restoration, serialized renewal,
sign-out/device controls and client acceptance remain outstanding. Staff-session
coverage depends on EE-010. Do not treat backend-only tests as full EE-011 acceptance.

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
It proxies only Android Member login and acquires the operator's existing cloud
identity internally; it never gives that cloud identity to the phone. Developer
access stays out of the APK. Device testing uses Android Debug Bridge port reversal
for port 8787. This is not a public production gateway. See the app acceptance
checklist before declaring EE-009 complete.

The first live development trial passed all eight checks against the deployed
Google identity service and private Cloud SQL. Both Android and iOS request shapes
returned one Member account. This is backend evidence, not an Android device test
or production acceptance.

Do not copy `config/engagement/.env.example` into a staging or production deployment. It contains explicit non-operational development identifiers which secure-environment validation rejects.
