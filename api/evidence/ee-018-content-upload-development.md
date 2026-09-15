# EE-018 private development evidence

Date: 16 September 2026

Scope: Contributor private MP4, MP3/M4A and PDF upload authorisation, rights confirmation, stored-file verification and pending Administrator review. This is development evidence, not production acceptance.

## Reviewed source and release

- Reviewed source: `26943c253a04ca0a3e929ff31646a0f19c8df1ce`
- Database migration source: `3820d30e84a754178fd77acd96529f7d24e9f183`
- Safety backup: Cloud SQL on-demand backup `1789500834656`, successful before migration
- Migration execution: `ee-development-database-migration-tx7wh`, one successful task, no retry
- Migration result: exactly `V0007` applied
- Cloud Run revision: `ee-development-api-00015-r4v`, 100 percent traffic
- Authenticated health workflow: GitHub Actions run `35016617102`, successful

## Live fictional proof

The repository's safe development checker signed in as the fictional Contributor and uploaded generated test-pattern material only:

- MP4 video: stored in private quarantine and returned `pending`
- MP3 audio: stored in private quarantine and returned `pending`
- PDF document: stored in private quarantine and returned `pending`

For every sample the service required an explicit rights confirmation, exact content type, exact byte count, SHA-256 fingerprint and a create-only signed link. Completion checked the file signature and recorded a quarantined asset awaiting scanning and Administrator moderation. It did not publish or move any sample to approved storage.

No real text message, client-owned content, personal photo, credential, token, account identifier or signed link was printed or committed. The three synthetic pending items are intentionally retained for EE-019 Administrator approval/rejection testing.

## Defect found and corrected

The first live attempt was rolled back because PostgreSQL could not infer the rights-statement audit parameter type. No partial upload record was committed. Pull request 72 explicitly typed the parameter, added a regression assertion and passed the full GitHub gate before revision `ee-development-api-00015-r4v` was deployed. The repeated live proof then passed for all three file types.

Result: EE-018 development acceptance passed. Production acceptance remains part of the later release gate.
