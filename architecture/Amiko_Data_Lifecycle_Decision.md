# Amiko personal-data lifecycle: client-approved product direction

Status: client approved the product direction on 21 September 2026. This is an
engineering decision record, **not** a published privacy notice, a claim of
legal compliance, or evidence that the features below have been deployed.
The client remains responsible for approving the final notice and obtaining
Indian legal advice before processing real production data.

## Approved product behaviour

| Area | Approved direction | Delivery boundary |
| --- | --- | --- |
| Launch age | Registration is for adults aged 18 or over. The `55+` profile label remains optional and is not an admission rule; adults under 55 may join. | Add an accessible age declaration and rejection path before public registration. Phone verification alone does not establish age. Do not collect a full birth date merely to enforce this rule without a further need. |
| Active profiles and approved content | Retain while the account is active and the information is needed to provide the service. | Published content is governed by its author/Administrator controls and moderation rules. |
| Inactive accounts | After 24 months without activity, contact the member, allow 30 days to respond, then consider closing the account. | This is a client-selected service rule, not a statutory inactivity period. Do not run automatic closure until reliable notice delivery, response capture and exception handling are tested. |
| Access and export | After identity verification, provide information about processing and a downloadable copy of the requester's own supported account/profile/contribution data. Target a response within 30 calendar days. | Do not include another person's data, passwords, tokens, internal security secrets or confidential moderation material. Full machine-readable export is a product promise, not a general statutory portability right. |
| Requested deletion | Promptly disable sign-in and remove the account and content from normal/public use. Target removal of data no longer required from active systems within 30 calendar days. | Segregate any records that must be kept for law, investigation or an active dispute; restrict access, record the reason and expiry, and tell the requester what remains. Never promise immediate erasure from every backup or legally required record. |
| Security and processing records | Retain the minimum records needed for the applicable one-year legal period, or longer only under another applicable legal obligation or documented hold. | Never log one-time passwords, clear-text passwords, authenticator seeds or session tokens. A final category-by-category schedule requires legal review. |
| Routine database backups | Use the planned 14 retained daily production database backups and verify restoration. A restore must reapply deletion/suppression records before reopening access. | The existing infrastructure definition specifies a backup count, not a promise that every copy expires exactly 14 days after an individual deletion. Manual backups need their own expiry decision. |
| Uploads and recordings | Rejected uploads stay private. Recordings require consent, Administrator approval and controlled replay access. | Exact retention periods for rejected media, manually created backups and live-stream recordings are **not yet specified**; do not enable automatic permanent purge or recording retention on an invented period. |

## Request process to implement and test

1. Present privacy information and consent in English, Bengali and Hindi, and
   publish a route to contact the client's privacy/grievance owner.
2. Accept an access/export or deletion request from an authenticated account,
   with a safe assisted route for someone who cannot sign in. Verify identity
   without asking for a password or one-time code in email or chat.
3. Record the request, due date, operator, outcome, retained exceptions and
   confirmation sent to the requester. Give a plain-language status response.
4. For deletion, revoke sessions and remove public visibility promptly, then
   purge eligible active copies. Keep any legally required evidence separately
   protected until its recorded expiry. Ensure a database restore cannot
   reactivate an account that was deleted after the backup was taken.
5. Test Member and Contributor cases, published media, group membership,
   notifications, audit records and backup/restore behaviour before production
   acceptance. iOS and Android must receive the same backend outcome.

## Legal interpretation to verify before production

- The Digital Personal Data Protection Act, 2023 provides rights to information
  about processing and to erasure subject to lawful retention. The main rights
  and retention provisions are scheduled to commence 18 months after the
  13 November 2025 notification. Design for them now; do not label them all
  currently operative.
- Rule 8(3) of the Digital Personal Data Protection Rules, 2025 requires
  one-year retention of specified personal data, associated traffic data and
  processing logs for Seventh Schedule purposes once operative. Rule 6(e)
  addresses security records. Counsel must map these requirements to the
  actual data categories rather than assume that all records have one expiry.
- Because the service hosts contributor content and member interaction, counsel
  must determine whether the Information Technology Intermediary Rules apply.
  If they do, the 180-day rules for registration information after cancellation
  and certain removed content must be reflected in the final schedule.
- The client's privacy owner must approve the final public notice, processor
  terms, contact/grievance route, and record of any other legal holds.

Primary sources:

- [Digital Personal Data Protection Act, 2023](https://www.meity.gov.in/static/uploads/2024/02/Digital-Personal-Data-Protection-Act-2023.pdf)
- [Digital Personal Data Protection Rules, 2025](https://www.meity.gov.in/static/uploads/2025/11/53450e6e5dc0bfa85ebd78686cadad39.pdf)
- [Commencement notification, 13 November 2025](https://www.meity.gov.in/static/uploads/2025/11/c56ceae6c383460ca69577428d36828b.pdf)
- [Information Technology Intermediary Rules, consolidated to 10 February 2026](https://www.meity.gov.in/static/uploads/2026/02/550681ab908f8afb135b0ad42816a1c9.pdf)

## Open decisions and sprint placement

- Client/legal adviser: confirm intermediary-rule applicability and the final
  category-by-category retention schedule before production personal data.
- Client: set expiry for manual backups, rejected uploads and approved replay
  recordings, plus a process for lawful holds.
- Client: confirm broad-location wording. Existing profiles use volunteered
  country/state/city fields; no device-location permission is part of this
  decision.
- EE-027: client tests the eight Backend Release 1 journeys; this approval is
  not acceptance of those journeys.
- EE-045 (Week 11): implement and verify the final privacy notice, age gate,
  access/export, deletion and retention controls. No production claim before
  that work and its acceptance evidence.
