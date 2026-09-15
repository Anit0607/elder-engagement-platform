# EE-020 private development verification

Verified: 16 September 2026

This record covers the approved-content feed and circle-visibility workflow in the private Google Cloud development environment. It is not a production-release claim.

## Released source and infrastructure

- Source revision: `bc792f0569b299799de9878f8270f55959312bcd`
- Application image: `sha256:2dbf50415c934d73bd325a948a3ddaa5b9c51d6776f88a5135d621e478e2511e`
- Ready application revision: `ee-development-api-00019-grh`, receiving 100 percent of development traffic
- Interface version: `0.3.4`; SHA-256 `d46acd1b39acb06d11888546b58ea90be3255d8ca0e1c7789ab66f4df9e7df20`
- GitHub candidate-build run: `35025789348`, passed package smoke testing
- GitHub deployment-health run: `35026205518`, passed
- Database update and safety backup: not required; EE-020 uses the existing checksum-locked tables already present in private Cloud SQL

## Live acceptance result

The repeatable live check used only fictional accounts, one generated MP4 and one temporary test circle. It passed all of the following:

1. A Contributor could not read the Member feed.
2. An Administrator published the approved generated video to the selected circle.
3. Only the Member currently assigned to that circle could see the feed item.
4. The eligible Member opened the exact reviewed file through a five-minute private link; the out-of-circle Member was denied.
5. Removing the eligible Member from the circle immediately removed both feed and media access.

The temporary circle was deactivated after the proof. No credential, token, account identifier, signed media address, personal data or client-owned material was printed or committed. The approved bucket remains private and the test material was never publicly visible.

## Defects caught before acceptance

The controlled development checks found and corrected two fail-closed integration defects: ordinary mobile JSON circle identifiers were initially rejected, and successful upload file checks were not recorded consistently for later approval/publication. Regression tests now cover both cases. Failed trials left their material private and unpublished.

The current automatic file checks confirm declared type, exact size, SHA-256 fingerprint and file signature. This verification does not claim advanced malware or artificial-intelligence content screening.
