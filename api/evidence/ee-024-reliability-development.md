# EE-024 private development reliability verification

Verified: 16 September 2026

This record covers backup recovery, administrative audit history and monitoring
in the private Google Cloud development environment. It is not a production
retention-policy or disaster-recovery service-level claim.

## Backup and isolated restore

- Source instance: `ee-development-postgres`, PostgreSQL 16, private address only.
- Backup `1789509895293` was successful before the EE-021 database update.
- The backup was restored into the isolated private instance
  `ee-development-restore-drill-20260916`; the working database was not targeted.
- The restored copy contained the `engagement` database and the expected limited
  runtime and migration Google Cloud database accounts.
- The first verification attempt failed safely and rolled back because Cloud SQL
  does not copy source database flags during restore. Enabling
  `cloudsql.iam_authentication` on the temporary target corrected the recovery
  procedure without changing the working database.
- Verification execution `ee-development-restore-verification-20260916-gjc8h`
  succeeded and brought the restored backup forward by applying `V0009`.
- The temporary verification job and temporary Cloud SQL instance were deleted.
  A final inventory check found neither resource, and the working database
  remained `RUNNABLE`.

## Administrative audit history

A read-only, private-network verification counted only action names and totals;
it printed no personal identifier or content. The live development database had
records for Contributor creation, account status and role changes, profile and
photo updates, circle creation/settings/membership changes, content upload,
moderation and publication, notification preferences, and event creation.

The one-use audit verification job was deleted after the successful check.

## Monitoring

- Uptime check `ee-development-api-health` runs every 60 seconds from
  Asia-Pacific, Europe and the United States with a 10-second timeout.
- Alert policies `ee-development-api-unavailable` and
  `ee-development-api-error-log` are enabled and connected to the approved
  operations email channel.
- The latest 20-minute sample contained 585 successful uptime points and zero
  failed points across five reported series.

## Remaining policy boundary

The client must still approve privacy, consent, retention, export and deletion
rules before production data handling is accepted. Production recovery targets,
responsible contacts and rehearsal frequency must also be documented before the
production release.
