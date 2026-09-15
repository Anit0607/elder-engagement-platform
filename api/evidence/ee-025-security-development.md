# EE-025 private development security verification

Verified: 16 September 2026

This record covers common misuse and upload-intent controls in the private
Google Cloud development environment. It is not a production-release or
public-internet protection claim.

## Automated verification

- The complete Amiko backend suite passed: 870 passed and 30 deliberately skipped.
- The focused security suite passed 150 checks.
- The locked Python dependency audit found no known vulnerabilities.
- GitHub backend, interface/database contract and public-repository boundary
  checks passed for the reviewed live-proof revisions `228bdf8` and `20ff49c`.

## Live development result

The repeatable, non-mutating test passed all of the following against the
private Cloud Run development service:

1. A request without an application login was rejected.
2. Invalid and unexpected input fields were rejected safely.
3. A request body larger than one mebibyte was rejected.
4. Unsupported file types, absent rights confirmation and an oversized audio
   upload request were rejected.
5. An unsafe request-tracking value was replaced with a safe generated value.

The test used only synthetic request data. It uploaded no file, created no
content, changed no database state and printed no credential, token or personal
identifier.

## Existing safeguards confirmed by the code suite

- Video, audio, PDF and profile-photo requests have type and size boundaries.
- Content upload requests require a rights confirmation and SHA-256 checksum.
- File signatures are checked before a submitted asset is accepted.
- Profile photos are decoded and rewritten, removing unneeded source metadata.
- Member session creation and failed staff sign-in attempts use persistent
  database-backed limits.

## Deliberate boundary before public exposure

File-signature checking is not malware scanning or artificial-intelligence
moderation. A public edge defence for whole-service traffic is also not yet
enabled. The development service must remain private until the production
traffic-protection design is selected and verified. Public staging, load and
penetration testing remain separate Week 4 work.
