# Google Cloud infrastructure foundation

Status: Sprint 1 review candidate for EE-001, EE-005, EE-006 and EE-007.

This package defines an idempotent Google Cloud foundation without storing a real project identifier, billing account, email address, credential or secret. It is safe to review publicly, but it is not evidence that cloud resources have been created.

## Design decisions

- Development, staging and production use separate Terraform state and should use separate Google Cloud projects. A single project is permitted for an initial development environment only; production must not share data or state with it.
- Terraform creates secret containers but never generates or stores secret values. Values are inserted through an approved out-of-band process.
- GitHub authenticates through Workload Identity Federation. Long-lived service-account JSON keys are prohibited.
- Runtime, migration, direct-upload signing and GitHub deployment identities are separate and receive only task-specific roles.
- The runtime has no standing media-bucket role. The upload signer can create quarantine objects only; later moderation access must use a separately reviewed identity.
- GitHub federation checks both the repository names and immutable numeric owner/repository identifiers, plus the approved branch.
- Cloud SQL has no authorised IP networks. Cloud Run connects through the managed Cloud SQL connector.
- Cloud SQL uses a private address and Cloud Run uses Direct Virtual Private Cloud egress; no chargeable Serverless Virtual Private Cloud Access connector is created.
- Development Cloud SQL explicitly uses Enterprise edition so its shared-core tier cannot silently default to Enterprise Plus.
- Storage uses uniform access, public-access prevention, versioning and environment-aware lifecycle controls.
- Cloud Run creation is off by default until an immutable reviewed image digest is provided.
- A generated Cloud Run hostname is never guessed. The exact assigned origin is recorded in ignored environment values and in the protected GitHub development environment before acceptance.
- A project-scoped monthly budget and threshold notifications are mandatory.
- Infrastructure creates an empty application database and can optionally create a dormant migration job. Terraform never executes the application schema or starts the job.

## Layout

- `terraform/state-bootstrap` creates the versioned, retention-protected remote-state bucket once per environment.
- `terraform/foundation` enables the approved interfaces and defines identities, storage, PostgreSQL, secrets, Artifact Registry, optional Cloud Run and budget controls.
- `environments/*.tfvars.example` documents non-secret environment inputs. Copy an example to an ignored `.tfvars` file; never edit the example with real values.
- `scripts/Invoke-Infrastructure.ps1` validates, plans by default and requires an exact confirmation phrase before apply.
- `tests/validate-infrastructure.mjs` checks the public safety and control invariants without needing Terraform installed.

## First execution

Install Terraform on the D drive, authenticate the Google Cloud command-line tools, and set their configuration directory to the protected D-drive runtime already established for this project. The guarded runner converts that login into a short-lived access token for Terraform without printing or persisting it. Then create a local ignored values file:

```powershell
Copy-Item infrastructure\environments\development.tfvars.example infrastructure\environments\development.tfvars
```

Fill in the real values locally. Do not commit that file.

For the presently authorised project, only the `development` environment may be planned or applied. Staging and production require their own approved projects, state buckets, budgets and explicit Project Manager authorisation.

Bootstrap remote state first. Record the resulting bucket name in an ignored backend configuration file. Initialise the foundation with a distinct state key such as `elder-engage/development/foundation.tfstate`.

Google Cloud budgets send warnings; they do not automatically stop services or cap spending. The Project Manager must approve the amount and recipients and respond to alerts.

Use the guarded runner from the repository root:

```powershell
.\infrastructure\scripts\Invoke-Infrastructure.ps1 -Environment development -VarFile .\infrastructure\environments\development.tfvars -BackendConfig .\infrastructure\environments\development.backend.hcl
```

That command only creates a plan. Applying requires both `-Action Apply` and `-ConfirmApply APPLY-development`. A reviewed saved plan must be supplied for production.

The separate development-candidate workflow tests the backend, publishes a provenance- and software-bill-of-materials-bearing candidate and smoke-tests the exact Artifact Registry digest. It does not deploy. Set `deploy_application=true` and copy only the reported digest into the ignored development values file, then review a new Terraform plan.

The separate database-migration candidate workflow validates and audits the checksum-locked runner, publishes a dedicated immutable image with provenance and a software bill of materials, verifies that it runs as a non-root user and confirms that it refuses to start without an explicit mode. It does not connect to Cloud SQL, create a job or execute a migration.

The Cloud Run migration job is also disabled by default. Creating the dormant job requires `deploy_database_migration_job=true`, its exact approved image digest and source revision, and two distinct client-approved schema names. The job has one task, no automatic retry and private network egress. No job-invoker permission or automatic execution token is defined. Running it remains a separate controlled change after the database bootstrap, backup and final migration plan are approved.

The one-time execution uses `scripts/Invoke-DatabaseMigration.ps1` with an ignored backend file, the exact ignored reviewed job-creation plan and its separately approved SHA-256 fingerprint. Its default Plan action compares every executable job field with that sealed plan, requires zero prior executions and rejects any existing explicit job-level invoker. The client deliberately accepted this project-level control instead of organization-wide inherited-permission analysis on 12 September 2026. No organization-level inspection role is required.

Apply is allowed only from the exact clean reviewed `origin/main` revision. Before granting the named human a job-level `roles/run.invoker` binding, the runner creates an atomic recovery marker and holds an exclusive D-drive lock. It starts the job once with no overrides, captures the exact execution identity, immediately removes the binding and then monitors only that execution. `finally` remains a cleanup fallback. The runner verifies that explicit job-level permission moves from nobody, to the one approved operator, and back to nobody. It then requires exactly one successful task and the execution-scoped `{"status":"ok","applied":["V0001"]}` log. After any permission-change attempt, the ignored marker becomes a permanent no-retry record and Cleanup never removes it. If the process or computer is interrupted, never rerun Apply. Another authorized named human must use the explicit Cleanup action; emergency Cleanup proves the explicit job binding is absent while the permanent marker prevents an automated retry. The local lock cannot coordinate across workstations, so operations must prohibit a second computer from running Plan, Apply or Cleanup concurrently.

The migration identity uses automatic Identity and Access Management database authentication. It is not permitted to read the application's password-style database connection secret.

### One-time development database bootstrap

The steady-state Cloud SQL configuration explicitly disables the Data API. After client approval and a fresh successful on-demand backup, `scripts/Invoke-DatabaseBootstrap.ps1` can open that authenticated administrative path for only the duration of the initial empty-schema setup. It uses the active named human Google identity, not a stored administrator password. The script creates a temporary Cloud SQL IAM user, executes the reviewed SQL template, disables the Data API first, removes the temporary user and verifies that public Internet Protocol access is still off. Cleanup runs after success or failure. The runner requires PowerShell 7.

Member phone sign-in is controlled by `enable_identity_platform`. When enabled, Google Identity Platform accepts phone authentication, real messages are restricted to the explicitly approved country list, and fictional number/code pairs come only from an ignored environment file. Those testing pairs are never committed, must be rotated, and must not be built into the Android application. Android Firebase application registration and Play Integrity fingerprints remain a separate change after the signing configuration exists.

The default action is a read-only safety plan. It accepts only an ignored Terraform backend file; project, region, instance, database, account names and repository identity are read from the protected Terraform state rather than entered by the operator:

```powershell
pwsh ./infrastructure/scripts/Invoke-DatabaseBootstrap.ps1 `
  -BackendConfig ./infrastructure/environments/development.backend.hcl
```

Live use is restricted to a clean, reviewed `main` branch that exactly matches the approved `origin/main` revision. Record the full reviewed revision without placing it in source, then run with `-Action Apply`, `-ExpectedRevision`, and the exact `BOOTSTRAP-EE-003-development` confirmation. The repository address is verified before Git is allowed to contact it. Never copy the operator identity, rendered SQL or cloud output into Git.

The rendered one-time SQL, recovery marker and process lock are written only beneath ignored `secure-runtime` paths. The exclusive lock permits only one Plan, Apply or Cleanup process at a time on this workstation, and an existing marker can never be overwritten. Operations must also prohibit a second workstation from running bootstrap or cleanup concurrently because the local lock cannot coordinate across computers. If the PowerShell process or computer stops before normal cleanup finishes, do not repeat Apply. Another authorised named human can run `-Action Cleanup` with the same backend file and the exact `CLEANUP-EE-003-development` confirmation. Cleanup uses the protected marker to disable the temporary Data API path first, remove only the recorded temporary operator and delete the residual SQL. After cleanup, create and verify a new on-demand backup before retrying the normal plan.

The SQL template refuses the wrong database or PostgreSQL version, unsafe roles, existing approved schemas and unexpected relations, routines, enum types or domain types outside the approved empty target. It creates only `engagement_app` and `engagement_migrations`, makes the migration identity their owner, grants the application identity usage of only the application schema, removes public access and proves that the named operator has the temporary owner-assignment link before committing. The runner parses Google Cloud's database response, rejects top-level or individual-statement errors and incomplete results, and requires one final row confirming the database and both schemas before it records success. Deleting the temporary operator removes that link immediately afterward. The full application tables are still created later by the separate immutable migration job.

This password-free route is safer than the originally approved temporary-password fallback. While enabled, the Data API is an additional Google-authenticated administrative route even though the database has no public address. The guarded script therefore keeps that window short and closes it before removing the temporary database user. Production must also include an isolated restore drill; a successful backup alone proves that the recovery copy exists, not that a restore has been rehearsed.

The federated GitHub identity has read-only Cloud Run discovery access plus invoke access on the health service only. It has no project-level Cloud Run developer role, because that broader role would also allow migration-job execution.

For an initial private development bootstrap without an assigned URL, Terraform uses an invalid placeholder origin that cannot receive external traffic. After the service is created, copy its exact reported HTTPS origin into the ignored `public_api_origin` value and the protected GitHub `GCP_CLOUD_RUN_ORIGIN` environment variable, review a second plan, and apply it before acceptance. Non-development and unauthenticated deployments cannot use the placeholder.

The primary post-deployment check is the manually triggered `verify-development-deployment.yml` workflow. It uses keyless GitHub federation, mints an identity token for only the exact configured origin and invokes the private health endpoint. An authorised operator with explicit service-account token-creator permission may run the equivalent local verifier without exposing the token:

```powershell
.\infrastructure\scripts\Test-CloudRunHealth.ps1 `
  -ProjectId replace-with-approved-project `
  -Region replace-with-approved-region `
  -ServiceName ee-development-api `
  -VerifierServiceAccount replace-with-approved-verifier@replace-with-approved-project.iam.gserviceaccount.com
```

The verifier resolves the service origin directly from Google Cloud, requests a short-lived token scoped to that exact origin, checks its audience and refuses redirects before validating the health response.

## Secret-value procedure

The reviewed Member-login runtime is enabled separately with `enable_member_session`.
It requires Google phone identity, the approved application schema and numeric
versions for the two session keys. Cloud Run injects those values directly from
Secret Manager at startup; Terraform stores references, never values. Both
values must be base64-encoded independent random keys of at least 32 bytes.
The application connects with the runtime IAM database user through the Python
connector's private-IP, automatic IAM mode; no password URL is loaded.
Disable the Member-session flag to return to the deliberately unavailable
login boundary. Refresh/logout and public mobile release remain later sprint
acceptance items. A deployment must use the separately built reviewed digest.

Terraform creates these empty secret containers: database URL, session signing key, refresh-token pepper and field-encryption key. An authorised operator adds values without printing them, then records only the secret version identifier in private deployment evidence. Secret values must never enter Terraform variables, state, console output, GitHub variables or repository files.

## Validation

```powershell
node infrastructure\tests\validate-infrastructure.mjs
```

When Terraform is available:

```powershell
terraform -chdir=infrastructure\terraform\state-bootstrap fmt -check
terraform -chdir=infrastructure\terraform\state-bootstrap init -backend=false
terraform -chdir=infrastructure\terraform\state-bootstrap validate
terraform -chdir=infrastructure\terraform\foundation fmt -check
terraform -chdir=infrastructure\terraform\foundation init -backend=false
terraform -chdir=infrastructure\terraform\foundation validate
```

## Production gates

Production apply is forbidden until the client approves the environment project, budget, data-retention rules, alert recipients, domain, immutable image digest, database sizing, recovery targets and release/rollback evidence. Client acceptance testing remains a separate release gate.
## Development verification-code rotation

After fictional phone-number testing, replace any verification codes exposed in
screenshots. `scripts/New-DevelopmentTestCodes.ps1` generates replacements only
for existing India test identities in a Git-ignored development tfvars input.
It validates workspace/project/environment boundaries and preserves unrelated
settings. It never prints codes or applies cloud changes itself.

Use the normal reviewed saved Terraform plan/apply workflow afterward, supplying
an absolute plan-file path. Review only resource addresses and safe change
summaries; full Identity Platform configuration and Terraform plan JSON can
contain confidential password-hash metadata even when phone sign-in is the
only enabled provider. Verify the updated test-code map privately and confirm
real phone sign-in and the allowed-country policy are unchanged.
