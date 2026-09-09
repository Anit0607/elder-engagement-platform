# Engagement database baseline

Status: Pre-Sprint controlled draft under EE-003. This is not a production migration and has not been applied to a client database.

`engagement_platform_v1_schema.sql` is the current logical/physical PostgreSQL draft for the approved engagement product. `amiko_v1_schema.sql` belongs to the inherited booking/caregiver scope and is retained only as history.

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
- Google Cloud region, database tier, backup settings, storage lifecycle, domains, and provider identifiers.

These values must become explicit configuration or approved immutable migrations after the client responds. No real personal data, secret, host name, or provider credential appears in this draft.

## Before migration approval

1. Map every table and constrained state to the accepted OpenAPI operations and permission matrix.
2. Replace the inherited metadata-driven Alembic baseline with immutable operations for this current schema.
3. Add database-level enforcement that `staff_credentials` belongs only to Contributor or Administrator accounts.
4. Test empty-database upgrade, upgrade from every released version, downgrade policy, PostgreSQL concurrency, indexes, backup, and restore.
5. Obtain independent review and record the exact Git revision and database image used for the test.
