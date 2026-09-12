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
- a versioned Week 2 REST contract for identity, profiles and account controls.

The development container is deployed to private Cloud Run, and database migration `V0001` is applied to private Cloud SQL. The Member-session service now follows the approved immediate-access boundary: the repository atomically finds or creates an active Member for a verified phone identity, and `profileComplete=false` routes a new Member to self-service profile setup. The Google phone-token verifier, PostgreSQL Member resolver and initial secure-session issuer are implemented and tested, but they are not yet wired to the deployed endpoint because the Cloud SQL application connection and Google Secret Manager lifecycle are still pending. Refresh, logout and session-management operations remain EE-011 work. Contributors remain Administrator-created. Profiles, staff sign-in, circles, content, moderation, feeds, events, notifications and media providers are not yet implemented.

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

Do not copy `config/engagement/.env.example` into a staging or production deployment. It contains explicit non-operational development identifiers which secure-environment validation rejects.
