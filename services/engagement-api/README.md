# Elder Engagement API process foundation

Status: EE-002 dependency-free Pre-Sprint foundation. This is the current engagement-platform service. The top-level `backend/` directory is an inherited booking implementation and is not imported, renamed or extended here.

Implemented now:

- strict loading of the checked-in `config/engagement` contract;
- a minimal process-liveness `GET /health` route;
- fail-closed dependency-readiness `GET /ready` with injectable probes;
- structured redacted JSON application logs;
- validated request IDs and W3C trace correlation;
- safe response headers, explicit trusted hosts and CORS;
- a non-root, immutable-source container foundation for a later Cloud Run deployment;
- exact runtime/development dependency locks and automated checks.

Not implemented: authentication, profiles, circles, content, moderation, feeds, events, notifications, provider adapters, database models/migrations or cloud deployment.

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

The Cloud Run container definition is build-context independent of the legacy backend. Its pinned base image and root-owned, runtime-read-only source are statically tested. A real `docker build` remains pending until a Docker daemon is available.

Do not copy `config/engagement/.env.example` into a staging or production deployment. It contains explicit non-operational development identifiers which secure-environment validation rejects.
