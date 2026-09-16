# Amiko Backend Release 1 notes

Status: client-test package prepared; stable client address and public traffic
protection are not yet approved. This file does not claim public or production
availability.

## Included and verified in private development

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

## Release gates still required

1. Approve the public traffic-protection design and stable client-test address.
2. Nominate the client acceptance owner and testers.
3. Supply the iOS developer's technical contact and GitHub identity.
4. Approve privacy, retention, export and deletion rules.
5. Complete the client test guide and record pass/fail evidence.

The deployed source revision, OpenAPI checksum, Postman checksum and client-test
address will be inserted only after the reviewed release candidate is deployed.
