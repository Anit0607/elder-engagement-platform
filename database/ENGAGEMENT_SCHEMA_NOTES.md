# Engagement database baseline

Status: Sprint 1 baseline approved, checksum-locked and applied once to the private development PostgreSQL 16 database under EE-003 on 12 September 2026. The successful job had one completed task, no failed task, verified ownership and minimum application permissions. Temporary execution access was removed afterward.

`migrations/V0001__engagement_baseline.sql` is the canonical PostgreSQL 16 baseline for the approved engagement product. Its approved repository bytes are locked by `migrations/manifest.json`. `amiko_v1_schema.sql` belongs to the inherited booking/caregiver scope and is retained only as history.

## Included boundaries

- Member, Contributor, and Administrator identities, detailed profiles, sessions, and account controls.
- Predefined circles and unique active membership history.
- Video, audio, PDF, YouTube reference, and broadcast-replay content.
- Private asset quarantine, Administrator moderation, audience filtering, events, reminder delivery, and audit history.
- Contributor-to-many broadcasts, an initial 100-viewer cap, recording, and moderated replay conversion.

YouTube rows store only the official video identifier and metadata; they never represent a copied or rehosted video. Meeting and telephone join references are treated as secrets and are not returned outside an authorised event response.

## Decisions deliberately left open

- Final profile fields, age groups, circle suggestion rules, notification-window behaviour, retention periods, and deletion/export policy.
- Identity provider, Administrator second factor, dedicated encryption keys, and whether contributor credentials remain local or federated.
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
