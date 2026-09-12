# Amiko Elder Engagement Platform

[![Verify](https://github.com/Anit0607/elder-engagement-platform/actions/workflows/verify.yml/badge.svg)](https://github.com/Anit0607/elder-engagement-platform/actions/workflows/verify.yml)

Public engineering repository for Amiko. It contains the current backend foundation, versioned REST contract, applied database baseline, configuration contract, Google Cloud infrastructure and technical architecture.

## Current status

Sprint 1's development foundation is deployed in the client-owned Google Cloud project. The private Cloud Run health service, private PostgreSQL database, storage, service identities, secrets, immutable database migration, logging, uptime monitoring, error alerts and budget alerts are in place and verified. Alert-email delivery still requires a client-approved recipient.

This is not the final production release. A separate production environment, completed application functions and client acceptance remain later milestones. Week 2's Member-session code and REST draft exist, but the production identity-provider connection, self-registration flow, profiles and staff access are not yet complete.

## Repository contents

- `services/engagement-api/` — FastAPI process, configuration, health/readiness and safety foundation.
- `api/` — OpenAPI contract, examples, contract tests and Postman companion.
- `database/` — checksum-locked PostgreSQL migration image, runner, manifest and safety tests.
- `architecture/` — current architecture, permission mapping and deployment runbook.
- `config/engagement/` — non-secret local configuration example and validation.
- `infrastructure/` — parameterised Google Cloud foundation, keyless GitHub identity and plan-first deployment controls.
- `tools/` — contract, configuration and public-repository checks.

## Local checks

```powershell
node tools\validate_engagement_openapi.mjs
node tools\validate_engagement_config.mjs
node tools\validate_engagement_schema.mjs
node --test config\engagement\validation.test.mjs

cd api\contract-tests
npm ci
npm test

cd ..\..\services\engagement-api
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock -r requirements-dev.lock
.\.venv\Scripts\python.exe -m ruff check app tests tools
.\.venv\Scripts\python.exe -m pytest --cov=app --cov-branch --cov-fail-under=90
```

## Public-repository rule

Credentials, personal data, confidential client documents, commercial material, internal delivery tracking, local runtime data and inherited legacy implementations are deliberately excluded. Run `powershell -ExecutionPolicy Bypass -File tools\check_public_repository.ps1` after staging and before every push.

See [SECURITY.md](SECURITY.md) before reporting a vulnerability or handling configuration.
