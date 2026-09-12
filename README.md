# Elder Engagement Platform

[![Verify](https://github.com/Anit0607/elder-engagement-platform/actions/workflows/verify.yml/badge.svg)](https://github.com/Anit0607/elder-engagement-platform/actions/workflows/verify.yml)

Public engineering repository for the Elder Engagement Platform. It contains the current backend foundation, REST contract, database draft, configuration contract and technical architecture.

## Current status

This is a dependency-free Pre-Sprint foundation, not a production release. The health/readiness service and local contracts are tested, but authentication, profiles, circles, content, moderation, events, notifications, broadcasting, mobile applications and cloud deployment are not yet implemented unless a later release explicitly says otherwise.

## Repository contents

- `services/engagement-api/` — FastAPI process, configuration, health/readiness and safety foundation.
- `api/` — OpenAPI contract, examples, contract tests and Postman companion.
- `database/` — checksum-locked PostgreSQL migration candidate, runner, and safety tests.
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
