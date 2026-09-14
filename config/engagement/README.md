# Engagement platform configuration contract

Status: dependency-free EE-006 Pre-Sprint draft
Scope: the current Member, Contributor and Administrator engagement platform only

The files in this directory define names and validation rules, not provisioned infrastructure. `backend/.env.example` and `backend/app/*` belong to the inherited service-booking implementation and are legacy inputs; they are not the configuration source for the current engagement-platform build.

## Environment boundary

Development, staging and production must use different Google Cloud projects or an equivalently approved hard isolation boundary. Each environment has its own Cloud SQL database, storage buckets, identity/provider configuration, Secret Manager secret versions, encryption context and runtime identities. Staging is synthetic-only and must never receive a production database copy or production personal data.

The checked-in `.env.example` is intentionally a local development example. Values containing `example` are non-operational. A staging or production file containing `example`, `replace`, `pending`, `localhost` or loopback addresses fails validation.

## Configuration inventory

| Group | Non-secret configuration | Secret Manager references | Rule |
|---|---|---|---|
| Runtime | `EE_ENVIRONMENT`, `EE_APP_NAME`, `EE_API_PREFIX`, `EE_LOG_LEVEL` | — | Environment is one of development, staging, production; API prefix remains `/v1`. |
| Google Cloud | `EE_GCP_PROJECT_ID`, `EE_GCP_REGION` | — | Client supplies permanent project and region before staging. |
| Network | `EE_PUBLIC_API_ORIGIN`, `EE_TRUSTED_HOSTS`, `EE_CORS_ORIGINS` | — | Staging/production origins use HTTPS; wildcard hosts/origins are forbidden. |
| PostgreSQL | `EE_CLOUD_SQL_INSTANCE` | `EE_DATABASE_URL_SECRET_REF` | Runtime receives a secret reference, never a database password in a checked-in file. |
| Rate limits | `EE_RATE_LIMIT_STORE` | `EE_REDIS_URL_SECRET_REF` | Memory is local-only. Staging/production requires the approved shared Redis-compatible store and its secret reference. The managed product/cost choice remains open. |
| Sessions and data protection | token lifetimes | `EE_SESSION_SIGNING_KEY_SECRET_REF`, `EE_REFRESH_TOKEN_PEPPER_SECRET_REF`, `EE_FIELD_ENCRYPTION_KEY_SECRET_REF` | References are distinct; environments never share secret versions. Raw signing/encryption material is forbidden in source. |
| Member identity | `EE_MEMBER_IDENTITY_PROVIDER`, `EE_FIREBASE_PROJECT_ID`, `EE_MEMBER_TOKEN_AUDIENCE` | — | `mock` is local-only. Firebase Authentication versus Identity Platform and test numbers remain client decisions. Workload identity/ADC is preferred over JSON keys. |
| Uploads | bucket names, signer identity, size, MIME allow-list, authorisation lifetime | — | Buckets are private. Staging/production requires explicit approved values. Upload grants are short-lived and constrained. |
| FCM | `EE_FCM_ENABLED`, `EE_FCM_PROJECT_ID` | — | When enabled, the notification workload uses ADC; no downloaded Firebase service-account key. |
| YouTube | `EE_YOUTUBE_ENABLED` | `EE_YOUTUBE_API_KEY_SECRET_REF` | Required only when enabled; use official interfaces and embedded playback. |
| Meet | `EE_MEET_MODE` | `EE_MEET_OAUTH_CLIENT_SECRET_REF` | `disabled`, link handoff, or API. OAuth secret is required only for API mode. |
| Broadcast | `EE_BROADCAST_PROVIDER`, `EE_AGORA_APP_ID` | `EE_AGORA_APP_CERTIFICATE_SECRET_REF` | Agora values are required only when the approved broadcast provider is enabled. |

Secret reference values use `projects/<project>/secrets/<name>/versions/<version>`. Production should pin an approved numeric version for controlled rollout where the deployment process supports it; `latest` is acceptable only for local/staging iteration under an explicit rotation procedure.

## Validation rules

Account controls are off by default (`EE_ACCOUNT_CONTROLS_ENABLED=false`) and
require connected staff authentication. Turning the switch on never grants a
Member/Contributor Administrator permissions; current server-side authorization
and invitation/enrollment boundaries still apply on every request.

Profiles are off by default (`EE_PROFILE_ENABLED=false`). Enabling them requires
connected identity and the V0004 English preference migration at runtime startup.
This flag is not a production acceptance switch and does not complete the photo
workflow. English/Bengali/Hindi profile choices and a non-blocking `55+` age label
are approved; age-based exclusion is not enabled.

Staff login is off by default (`EE_STAFF_SESSION_ENABLED=false`). Turning it on
requires the connected Member runtime and a dedicated, numeric
`EE_STAFF_AUTHENTICATOR_KEY_SECRET_REF`, distinct from session and field-encryption
secrets even across versions. Secret material is injected privately; startup
rejects missing/invalid material and absent staff database guards. Configuration
validation alone does not prove enrollment, database execution or acceptance.

- Reject duplicate, malformed and unknown keys. This prevents an undocumented setting from silently changing behavior.
- Reject raw credential-style keys such as `*_PASSWORD`, `*_TOKEN`, private keys or service-account JSON; only documented `*_SECRET_REF` names are accepted.
- Reject secret-reference fields that do not name a Secret Manager version.
- Reject placeholders, local addresses, HTTP origins, mock identity and memory rate limits in staging/production.
- Require valid HTTPS API/CORS origins in staging/production, require CORS explicitly, and require the public API host in the trusted-host list.
- Require Redis reference when the rate-limit store is Redis.
- Require Firebase project/audience when Firebase or Identity Platform identity is selected.
- Require provider-specific identifiers and secret references only when FCM, YouTube, Meet API or Agora is enabled.
- Enforce bounded numeric values for token lifetime, upload size and signed-upload duration.

Run the dependency-free checks from the repository root:

```powershell
node tools\validate_engagement_config.mjs
node --test config\engagement\validation.test.mjs
```

## Least-privilege Google Cloud identity map

These are proposed deploy-time identities, not created accounts. Apply roles to the named resource wherever possible; do not grant project Owner, Editor, Service Account Admin or long-lived service-account keys.

| Identity | Purpose | Minimum starting access | Explicitly excluded |
|---|---|---|---|
| `ee-runtime-api@<project>` | Cloud Run REST API | Cloud SQL Client; Secret Accessor on database/session/refresh/encryption secrets only; Logging Writer; Monitoring Metric Writer; permission to mint upload grants through the dedicated signer | Project-wide Secret Accessor, bucket admin, IAM admin, provider-admin roles |
| `ee-upload-signer@<project>` | Authority represented by short-lived quarantine upload grants | Storage Object Creator on the quarantine bucket only; API runtime gets Service Account Token Creator on this identity only | Read/list/delete objects, approved-media access, downloadable key |
| `ee-moderation-worker@<project>` | Inspect quarantine objects and publish approved assets | Cloud SQL Client; database secret access; object read/delete in quarantine and object create in approved bucket, preferably a custom bucket-scoped role | IAM changes, unrelated secrets, project-wide Storage Admin |
| `ee-notification-worker@<project>` | Dispatch approved FCM reminders | Cloud SQL Client; database secret access; Firebase Cloud Messaging send role in the environment project | Firebase project administration, user management, service-account key |
| `ee-broadcast-worker@<project>` | Agora control and recording orchestration | Cloud SQL Client; database and Agora secret access; bucket-scoped recording object creator when recording is approved | Other provider secrets, bucket admin, project editor |
| `ee-schema-migrator@<project>` | Run reviewed immutable migrations as a one-shot job | Cloud SQL Client; migration database secret only; Logging Writer | Runtime traffic, bucket/provider access, database-owner use after migration |
| GitHub OIDC principal / `ee-ci-deployer@<project>` | Build and deploy reviewed revisions | Workload Identity User for the exact repository/ref; Artifact Registry Writer on one repository; Cloud Run Developer on named services/jobs; Service Account User on the listed runtime identities | JSON key, project Owner/Editor, IAM policy administration, arbitrary service-account impersonation |

IAM bindings must be duplicated per environment rather than sharing identities. Human production access is separate, time-bound, auditable and outside this machine-identity map.

Role names and scoping were checked against the current official documentation for [Cloud Run access](https://docs.cloud.google.com/run/docs/securing/managing-access), [Cloud SQL conditions](https://docs.cloud.google.com/sql/docs/postgres/iam-conditions), [Secret Manager access](https://docs.cloud.google.com/secret-manager/docs/access-control), [Cloud Storage roles](https://docs.cloud.google.com/storage/docs/access-control/iam-roles), [signed URL permissions](https://docs.cloud.google.com/storage/docs/access-control/signing-urls-with-helpers), [Firebase Cloud Messaging roles](https://docs.cloud.google.com/iam/docs/roles-permissions/firebasecloudmessaging), [Artifact Registry access](https://docs.cloud.google.com/artifact-registry/docs/access-control), [Cloud Logging access](https://docs.cloud.google.com/logging/docs/access-control) and [Cloud Monitoring access](https://docs.cloud.google.com/monitoring/access-control). The notification sender should prefer a custom role limited to `cloudmessaging.messages.create`; the API-to-upload-signer binding should prefer a custom role limited to `iam.serviceAccounts.signBlob` when the client permits custom roles.

## Client dependencies still open

- Client-owned Google Cloud project(s), billing, region, organisation policy and approved environment-isolation model.
- Permanent product name, domains, Cloud Run service names and Cloud SQL/storage naming convention.
- Firebase Authentication versus Identity Platform, project identifiers, allowed test phone numbers and token audience.
- Approved Redis-compatible managed service and budget.
- Approved upload MIME types, file-size limits, retention, moderation scanning and bucket locations.
- FCM, YouTube, Meet and Agora accounts, quotas, feature modes and provider-specific secret names.
- Broadcast recording/retention decisions and 100-viewer test controls.
- Security owner approval for IAM roles, custom-role permissions, secret rotation and human break-glass access.
