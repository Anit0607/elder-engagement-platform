# Elder Engagement Platform deployment runbook

Status: Sprint 1 controlled runbook under EE-008
Target: client-owned Google Cloud development, staging, and production environments
Production readiness: not yet verified

## Purpose and boundary

This runbook describes how the approved engagement-platform backend and web consoles will be built, migrated, deployed, verified, and rolled back from GitHub. It does not authorise deployment and contains no project identifier, domain, credential, secret, or personal data.

The runbook becomes acceptance evidence for EE-008 only after its steps are executed successfully in the client-owned environments created under EE-001 through EE-007. Until then it is a repeatable plan, not proof of production readiness.

## Required inputs

| Input | Owner | Gate |
|---|---|---|
| Project Manager-owned public GitHub repository, default branch, required reviewers | Project Manager | Before pipeline connection |
| Google Cloud project(s), billing, region, named access | Client | Before infrastructure work |
| Development, staging, and production isolation model | Client and Lead | Before resource creation |
| Application name, domains and Android package identifier | Client | Before permanent naming and public routing |
| Identity, YouTube, Meet, Firebase Cloud Messaging and Agora accounts | Client | Before the corresponding integration sprint |
| Privacy, retention, deletion/export and broad-location decisions | Client | Before real personal data or production retention jobs |

If any gate is missing, use only local mocks and synthetic data. Never substitute a personal account or an invented permanent value.

## Target topology

Each environment has its own Cloud Run service, Cloud SQL PostgreSQL database, private Cloud Storage buckets, Secret Manager values, service identities, encryption context, logs, alert destinations and provider credentials. Staging contains synthetic data only. Production personal data is never copied to development or staging.

Traffic follows this path:

```text
Android / iOS / web console
        -> HTTPS load-managed Cloud Run origin
        -> versioned REST API /v1
        -> private Cloud SQL and Cloud Storage
        -> explicitly enabled external providers
```

The version-one backend remains a modular monolith. Database migration runs as a separately authorised job; application startup never changes the schema.

## Release sequence

### 1. Confirm the release candidate

- Select the reviewed Git commit from the protected release branch.
- Confirm that the OpenAPI version, migrations, application version, change log and rollback target refer to the same commit.
- Confirm that required automated checks passed and no release-blocking defect is open.
- Confirm that environment-specific client decisions and approvals are recorded in the tracker.

### 2. Build once

- GitHub builds an immutable container image from the selected commit.
- Dependency versions come from the committed lock file.
- The pipeline performs linting, unit tests, coverage, security scanning, dependency auditing and contract checks before publishing.
- The resulting image is identified by digest. The same digest moves from development to staging to production; production is not rebuilt separately.

### 3. Provision or reconcile infrastructure

- Reconcile only the approved environment and region using reviewed infrastructure definitions.
- Create or update Cloud Run, Cloud SQL, private buckets, service identities, Secret Manager references, log sinks, uptime checks, alerts and budget thresholds.
- Deny public database and bucket access.
- Bind the minimum Google Cloud roles to the runtime, migration and deployment identities separately.
- Record the change plan before application and the resulting resource identifiers after application.

### 4. Validate configuration safely

- Validate presence, type and environment rules for every required configuration key.
- Confirm that no secret value is printed in logs, command output, GitHub Actions output or evidence attachments.
- Confirm that development, staging and production reference different databases, buckets, secrets, provider applications and encryption contexts.
- Confirm that mocks, fixed one-time passwords and synthetic-only flags cannot start in production.

### 5. Back up and migrate

- Confirm a recent usable Cloud SQL backup and record its identifier and retention.
- Run the immutable migration through the dedicated migration identity and job.
- Verify the expected migration version and schema checksum.
- Stop the release if migration verification fails. Do not allow the application process to repair or create tables automatically.

### First development database setup

1. Record the client's approval of the database, schema names and one-time access method.
2. Confirm PostgreSQL 16 is running with private addressing, automatic backups and point-in-time recovery.
3. Create an on-demand backup and wait for `SUCCESSFUL`; an asynchronous request by itself is not evidence of a usable backup.
4. Using PowerShell 7, run `Invoke-DatabaseBootstrap.ps1` in its default plan mode with the ignored backend file. The runner reads the exact target, database accounts and approved repository identity from protected Terraform state.
5. Merge the reviewed bootstrap template, tests and steady-state Data API disabled control. Live bootstrap is allowed only from a clean `main` branch.
6. Run the guarded apply once with the exact reviewed 40-character `origin/main` revision and confirmation. It verifies the repository address before contacting it, temporarily registers the active named operator, opens the authenticated Data API and creates the two empty schemas in one checked transaction. It rejects database errors carried inside an otherwise successful Google Cloud response, rejects partial results and requires the final database/schema checks to all be true. It then closes the Data API, removes the operator and verifies cleanup. It does not use or store a database password.
7. Confirm Terraform has no unplanned change and Cloud SQL still has no public address.
8. Create the dormant immutable migration job from a reviewed saved plan, grant one named operator job-only execution permission, run once without overrides and verify `V0001` plus its checksum, table count, ownership and permissions.
9. Remove job execution permission and destroy the dormant job using another reviewed saved plan. Retain the migration identity, immutable image, backup and private evidence.

The guarded migration runner must compare the live job with the reviewed saved plan and use organization-scoped Cloud Asset Inventory analysis to reject unexpected inherited `run.jobs.run` access. It must create a durable ignored recovery marker before adding job-level invocation permission, remove that permission even after a normal failure, and support explicit Cleanup after interruption. Never rerun Apply when a marker or execution record exists. Verify the exact execution resource, one successful task, zero failed tasks and one execution-scoped `V0001` success record before accepting the migration.

Only one Plan, Apply or Cleanup process may run at a time; the protected exclusive lock must be held through final cleanup, and an existing recovery marker must never be overwritten. The lock coordinates only this workstation, so the release owner must prohibit concurrent execution from any second computer. If the runner or computer is interrupted, do not repeat Apply. Use the explicit guarded Cleanup action; it reads the ignored recovery marker, closes the Data API first, removes only the recorded temporary operator and deletes the protected temporary SQL. A different authorised named human may perform this recovery. After successful cleanup, make and verify a new on-demand backup before retrying. If any bootstrap preflight or cleanup check fails, stop. Do not run the table migration and do not attempt an improvised repair.

### 6. Deploy the service

- Deploy the approved image digest as a new Cloud Run revision without sending production traffic immediately.
- Attach only the runtime identity and approved Secret Manager references.
- Enforce encrypted database connectivity, bounded concurrency, request timeout, minimum/maximum instances and resource limits defined for that environment.
- Send test traffic to the new revision and verify `/health` and `/ready` without exposing configuration.

### 7. Smoke-test before traffic

Use synthetic identities and the version-matched contract to verify:

- process health and dependency readiness;
- Member identity-token exchange through the approved test provider;
- Contributor and Administrator authentication policy;
- rotating refresh, logout and session revocation;
- profile read/update and Administrator account controls;
- denied unauthenticated, wrong-role and suspended-user operations;
- structured problem responses, trace identifiers and redacted logs;
- database access, private object access and audit-event creation.

Later milestone tests add circles, content/moderation, events, YouTube, Meet and broadcast workflows only when those tracker items enter their approved sprint.

### 8. Shift traffic and observe

- Shift traffic gradually to the new revision using the agreed release policy.
- Observe error rate, latency, instance health, database connections, storage failures, provider failures and spend signals.
- Confirm that alerts reach the client-approved recipients.
- Record the release time, revision, image digest, migration version, checks and observer.

### 9. Roll back when required

Roll back if a release-blocking functional, security, data-integrity or availability problem occurs.

- Stop traffic promotion and return traffic to the previous known-good revision.
- If the migration is backward-compatible, keep the schema and investigate safely.
- If a destructive schema reversal would be required, stop and use the reviewed restoration/recovery procedure; never improvise a production downgrade.
- Revoke any newly exposed credential, preserve redacted evidence, open a defect and notify the acceptance owner.
- Re-run health, readiness and critical smoke tests after rollback.

## Environment promotion gates

| Promotion | Minimum evidence |
|---|---|
| Local to development | Current tests pass; configuration validation passes; no secret in source |
| Development to staging | Deployed health/readiness; migration evidence; synthetic end-to-end smoke tests; reviewed OpenAPI |
| Staging to production | Client acceptance for the milestone; independent release review; backup/restore evidence; monitoring and rollback rehearsal; zero known release-blocking defects |

## Evidence record for every deployment

- Environment, timestamp, Git commit, image digest and Cloud Run revision.
- Migration version and database backup identifier.
- Automated-check results and synthetic smoke-test results.
- OpenAPI version and mobile compatibility result.
- Approver, operator and independent reviewer.
- Observed metrics, alert test and rollback target.
- Known non-blocking defects and accepted limitations.

No evidence record may contain tokens, personal data, secret values, signed storage addresses or provider credentials.

## Current verification status

| Part | Status |
|---|---|
| Architecture and release sequence | Versioned in the protected public repository; Cloud Run build and deployment steps executed using an immutable digest |
| Current engagement schema | Corrected logical draft; static checks and both staff-role race directions pass on PostgreSQL 16; not migrated |
| Week 2 REST contract | Local draft package independently reviewed; runtime implementation remains pending |
| GitHub repository | Public repository under the Project Manager account; protected `main`, required checks and pull-request merges are active |
| GitHub verification pipeline | Boundary, contract, backend, security, dependency, container-build and private deployment-health checks have passed |
| Google Cloud resources | Development foundation active: private Cloud Run, private PostgreSQL, private storage, service identities, secret containers, remote state and budget alerts. Staging and production are not created |
| PostgreSQL migration execution | Not run for current schema; no approved runtime available |
| Cloud smoke test, monitoring and rollback | Authenticated private `/health` passed and Terraform reports no drift; dependency readiness, error/uptime notification delivery and rollback rehearsal remain pending |
