# Engagement database baseline

Status: V0001–V0009 are checksum-locked and applied to the private development PostgreSQL 16 database.

`migrations/V0001__engagement_baseline.sql` is the canonical PostgreSQL 16 baseline for the approved engagement product. Its approved repository bytes are locked by `migrations/manifest.json`. `amiko_v1_schema.sql` belongs to the inherited booking/caregiver scope and is retained only as history.

## Included boundaries

V0004 added approved English to profile-language choices without rewriting released
V0001–V0003 or changing saved profiles. Bengali/Hindi remain valid. The `55+` age
label is not an enforced minimum age. V0005 added the private profile-photo lifecycle.

- Member, Contributor, and Administrator identities, detailed profiles, sessions, and account controls.
- Predefined circles and unique active membership history.
- Video, audio, PDF, YouTube reference, and broadcast-replay content.
- Private asset quarantine, Administrator moderation, audience filtering, events, reminder delivery, and audit history.
- Contributor-to-many broadcasts, an initial 100-viewer cap, recording, and moderated replay conversion.

YouTube rows store only the official video identifier and metadata; they never represent a copied or rehosted video. Meeting and telephone join references are treated as secrets and are not returned outside an authorised event response.

## Decisions deliberately left open

- Retention periods and deletion/export policy. Profile fields, the nonrestrictive `55+` label, circle suggestion rules and notification-window behaviour are approved.
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

## EE-017 additive candidate: V0006

`V0006__circle_membership_configuration.sql` adds one controlled setting whose
initial value is the approved maximum of five active circle memberships. An
Administrator may later change it only within the accepted range of one to twenty.
It does not alter the released circle or membership history tables. Its fresh backup,
reviewed migration job, development deployment and live fictional proof passed.

## EE-018 applied update: V0007

`V0007__contributor_content_uploads.sql` adds a short-lived upload-authorisation
record, a versioned Contributor rights confirmation and English content language.
It keeps the uploaded object in private quarantine and uses the existing pending
moderation state. It does not approve or publish content. Its backup, migration job,
private deployment and live synthetic MP4/MP3/PDF verification passed.

## EE-019 applied update: V0008

`V0008__content_moderation_reasons.sql` adds the controlled rejection-reason code
and optional Administrator note to each immutable moderation decision. Existing
decisions are safely backfilled; any older long free-text reason is shortened only
in the new note copy, while the original reason remains unchanged. The `other`
choice requires an explanation. It does not publish, delete or move content.
Its fresh backup, reviewed migration job, restricted preview identity, private
deployment and live synthetic MP4/MP3/PDF moderation proof passed.

## EE-021 applied addition: V0009

`V0009__event_reminder_rules.sql` adds normalized reminder offsets for the
existing events table. Each event may use unique timings from five minutes to
seven days before its start. The table records scheduling rules only; it does
not send a notification or add a provider credential. Controlled database
application, private deployment and live fictional proof remain pending.
