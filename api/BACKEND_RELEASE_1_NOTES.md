# Amiko Backend Release 1 notes

Status: protected development test address active at
`https://api-test.eldercaresaathi.com`. The public health check, sign-in
boundary and blocked direct Cloud Run address passed the
[gateway verification run](https://github.com/Anit0607/elder-engagement-platform/actions/runs/35680338910).
This is not a production release or client acceptance.

## Included and verified in development

- Member phone sign-in, immediate Member access and secure saved sessions.
- Contributor username/password sign-in and Administrator password plus
  authenticator-app sign-in.
- English, Bengali and Hindi profile preference; detailed own-profile updates;
  private profile-photo handling.
- Administrator account status and role controls.
- Predefined circles, suggestions, Member join/leave, Administrator assignment
  and a changeable membership limit.
- Private Contributor MP4, MP3/M4A and PDF uploads with rights confirmation,
  per-type size limits, checksum and basic file-signature checks.
- Administrator review, approve/reject reasons and separate publication.
- Member feed restricted to all Members or selected circles, with short-lived
  private media access.
- Information-only events, circle visibility and stored reminder preferences.
- Private Google Cloud deployment, PostgreSQL backups, isolated restore proof,
  administrative audit history, health monitoring and alerts.

## Not included in Backend Release 1

- Sending push, text-message or email reminders.
- Google Meet, group calling, live broadcasting or recording.
- YouTube integration, payments or subscriptions.
- Automatic transcription, translation, generated Bengali/Hindi audio or
  artificial-intelligence moderation.
- Advanced malware scanning. Current file checks validate declared type, size,
  checksum and recognised file signature.
- Android production release or Google Play submission.
- Administrator user listing and account creation through `GET` and
  `POST /v1/admin/users`; these two documented operations are explicitly
  marked planned and are not callable in Backend Release 1.

## Release gates still required

1. Nominate the client acceptance owner and testers.
2. Implement the approved privacy direction and obtain the final category-specific retention/legal review before any real production data. The client approved the direction in `../architecture/Amiko_Data_Lifecycle_Decision.md`; approval alone does not deliver the age gate, export or deletion operations.
3. Complete the client test guide and record pass/fail evidence. iOS application implementation/testing is not a backend release gate.

The development integration handover, recorded backend source revision, checksums,
build evidence and gateway smoke evidence are in `handover/backend-release-1/`.
That package does not itself establish client acceptance or production readiness.
The EE-052 development readiness check is repaired and verified in
`evidence/ee-052-readiness-development.md`.
