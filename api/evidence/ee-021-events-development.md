# EE-021 private development verification

Verified: 16 September 2026

This record covers basic information-only events and reminder-rule storage in
the private Google Cloud development environment. It is not a production-release
claim and does not claim that reminders are sent.

## Released source and infrastructure

- Feature source revision: `c9abcfadcf77f206ecb7f4d027a62f730ddc0fec`
- Reviewed live-proof source revision: `134123a6da7a052f69a210f8352a47038c0be046`
- Application image: `sha256:83ef6323db34660967bec09345f89a4b159e9f66ffec902d6426166ba0f095ca`
- Ready application revision: `ee-development-api-00021-7nd`, receiving 100 percent of development traffic
- Interface version: `0.3.5`; SHA-256 `ec5b2315bf8a010d4ce29eae57615d1773197d4df67d7b599e715276cc25a2b6`
- GitHub application-build run: `35028738394`, passed package smoke testing
- GitHub migration-build run: `35028739098`, passed fail-closed migration testing
- GitHub deployment-health run: `35030069255`, passed
- Safety backup: on-demand Cloud SQL backup `1789509895293`, successful before migration
- Database update: execution `ee-development-database-migration-7fztv` applied only `V0009` successfully

## Live acceptance result

The repeatable live check used only fictional Administrator, Contributor and
Member accounts, synthetic event text and one temporary test circle. It passed
all of the following:

1. A Contributor could not create an event.
2. An Administrator created a future circle event and the two reminder offsets were retained.
3. Only the Member currently assigned to the selected circle could see the event.
4. Removing that Member from the circle immediately removed event visibility.

The test event is information-only. No meeting link, telephone number, real
notification, real text message, personal data or client material was used.
The temporary circle was deactivated and its memberships were removed after
the proof. No credential, token or identifier was printed or committed.

## Deliberate boundary

EE-021 records reminder timings but does not send push, text-message or email
reminders. Actual delivery, Google Meet or telephone joining, event editing and
event cancellation remain separate planned work.
