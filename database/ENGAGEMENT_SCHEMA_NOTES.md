# Engagement database baseline

Status: Sprint 1 baseline approved, checksum-locked and applied once to the private development PostgreSQL 16 database under EE-003 on 12 September 2026. The successful job had one completed task, no failed task, verified ownership and minimum application permissions. Temporary execution access was removed afterward.

`migrations/V0001__engagement_baseline.sql` is the canonical PostgreSQL 16 baseline for the approved engagement product. Its approved repository bytes are locked by `migrations/manifest.json`. `amiko_v1_schema.sql` belongs to the inherited booking/caregiver scope and is retained only as history.

## Included boundaries

Week 2 candidate V0004 adds approved English to profile-language choices without
rewriting released V0001–V0003 or changing saved profiles. Bengali/Hindi remain
valid. The `55+` age label is not an enforced minimum age. V0004 is not yet applied
to the client database; migration execution and live verification remain required.

- Member, Contributor, and Administrator identities, detailed profiles, sessions, and account controls.
- Predefined circles and unique active membership history.
- Video, audio, PDF, YouTube reference, and broadcast-replay content.
- Private asset quarantine, Administrator moderation, audience filtering, events, reminder delivery, and audit history.
- Contributor-to-many broadcasts, an initial 100-viewer cap, recording, and moderated replay conversion.

YouTube rows store only the official video identifier and metadata; they never represent a copied or rehosted video. Meeting and telephone join references are treated as secrets and are not returned outside an authorised event response.

## Decisions deliberately left open

- Final profile fields, age groups, circle suggestion rules, notification-window behaviour, retention periods, and deletion/export policy.
- Dedicated staff-authenticator runtime encryption key and secure enrollment/recovery. Member phone identity uses Google; Administrator password plus an authenticator-app code and Administrator-created Contributor username/password have been approved.
- Final domains and external provider identifiers.

These values must become explicit configuration or later approved immutable migrations after the client responds. No real personal data, secret, host name, or provider credential appears here.

## Migration safety boundary

`migration_runner.py` applies the manifest in one bounded transaction. It verifies the exact database and non-administrative migration/runtime roles, schema ownership, PUBLIC access, an empty first-install database, the immutable ledger and runtime permissions. Concurrent runners serialize on a PostgreSQL advisory lock. Cloud execution accepts no database connection string: it uses Application Default Credentials, the Cloud SQL Python Connector, private Internet Protocol addressing and automatic Identity and Access Management database authentication. The reviewed one-time bootstrap used a short-lived Google-authenticated administrative path, created no stored database password and removed temporary access afterward. The immutable migration job was also removed after its single successful execution.

## Controls retained for later migrations

1. Map every table and constrained state to the accepted OpenAPI operations and permission matrix.
2. Pass the checksum, upgrade, rerun, rollback, concurrency and least-privilege migration gates.
3. Keep the PostgreSQL 16 concurrency regression in `database/tests/test_staff_role_concurrency.py` passing; it proves that credential insertion and role demotion cannot race past each other.
4. Test empty-database upgrade, upgrade from every released version, downgrade policy, remaining PostgreSQL concurrency, indexes, backup, and restore.
5. Obtain independent review and record the exact Git revision and database image used for the change.

## EE-010 additive candidate: V0002

`V0002__staff_authentication.sql` is a new, separately checksum-locked migration;
it does not edit the applied baseline. It adds encrypted staff-authenticator
storage, a nonnegative last-used code step, a credential version and a staff
session version snapshot. Credential changes revoke previous sessions; accepted
steps cannot move backwards without replacing/disabling the authenticator.

This candidate is not yet applied to the client database. Existing rows with
`second_factor_enabled=true` but no encrypted seed deliberately fail the update;
do not silently disable their protection to make it pass. Secure staff enrollment
and current role/version authorization checks remain application work. The
original one-time cloud executor is pinned to V0001 and its source/image; applying
V0002 requires a reviewed new release path and a verified usable backup.

`V0003__role_change_session_revocation.sql` adds atomic owned-session revocation
on role changes. Staff refresh must not be enabled without this guard: an old
Contributor refresh token must not inherit Administrator access after promotion.
It does not edit applied migrations. Cloud execution remains pending reviewed
release preparation and a fresh verified backup.
