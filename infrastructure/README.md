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
- A project-scoped monthly budget and threshold notifications are mandatory.
- Infrastructure creates an empty application database only. It never executes the application schema or a data migration.

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

The separate development-candidate workflow tests the backend, publishes a provenance- and software-bill-of-materials-bearing candidate and smoke-tests the exact Artifact Registry digest. It does not deploy. Set `deploy_application=true` and copy only the reported digest into the ignored development values file, then review a new Terraform plan. After an authorised apply, verify the private service without exposing the identity token:

```powershell
.\infrastructure\scripts\Test-CloudRunHealth.ps1 `
  -ProjectId replace-with-approved-project `
  -Region replace-with-approved-region `
  -ServiceName ee-development-api
```

The verifier resolves the service origin directly from Google Cloud, requests a short-lived token scoped to that exact origin, checks its audience and refuses redirects before validating the health response.

## Secret-value procedure

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
