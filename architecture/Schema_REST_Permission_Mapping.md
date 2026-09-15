# Schema, REST and permission mapping

Status: Sprint 3 controlled mapping through the EE-019 source candidate
Sources: the checksum-locked migration manifest and `api/openapi/elder-engage-v1.openapi.json`

This mapping prevents the inherited booking product from being mistaken for Amiko. “Draft now” means the operation exists in the controlled OpenAPI draft but is not claimed live until its deployment record passes. “Planned” means it is an approved tracker item but is deliberately unavailable in the current contract.

| Data owner/table | API coverage | Member | Contributor | Administrator | Tracker evidence |
|---|---|---|---|---|---|
| `app_users` | Draft now: session exchange, Administrator create/list/status/role | Read own identity summary | Read own summary | Create/list and change governed status/role | EE-009–014, EE-051 |
| `staff_credentials` | Draft now: staff session input; credential storage is never exposed | None | Authenticate own account | Authenticate own account; cannot read hashes | EE-010, EE-015 |
| `user_profiles` | Draft now: own GET/PATCH, photo upload lifecycle, Administrator create and summary list | Read/update permitted own fields | Same for own profile | Create profiles and list summaries; detailed cross-user read/edit remains unavailable until approved | EE-013–015, EE-051 |
| `auth_sessions` | Draft now: create/refresh/logout/list/revoke | Manage own sessions | Manage own sessions | Manage own sessions; cross-user revocation requires a later approved operation | EE-011, EE-015, EE-051 |
| `circles` | Draft now: Member suggestions/list and Administrator create/list/update/deactivate | View active circles and any inactive joined circle | None | Create/list/update/deactivate | EE-017, EE-023 |
| `circle_memberships` | Draft now: own join/leave and Administrator assign/remove | View/select/leave own circles, initially up to five | None | Assign/remove active Members and change the one-to-twenty limit | EE-017, EE-023 |
| `circle_configuration` | Draft now: Administrator GET/PUT | No direct access | No direct access | Read/change the one-to-twenty membership limit | EE-017, EE-023 |
| `content_items` | Draft now: Contributor private upload start/complete and Administrator moderation; feed planned | No current operation | Create own pending submissions; no self-approval | List/preview pending items and approve/reject; approval does not publish | EE-018–020, EE-023 |
| `content_assets` | Draft now: validated quarantine record and private Administrator preview; approved delivery planned | No current operation | Complete only own authorised upload | Receive a two-minute read-only preview of pending files | EE-018, EE-019, EE-025 |
| `content_uploads` | Draft now: short-lived signed upload and validated completion | None | Start/complete own private upload | No direct operation | EE-018, EE-023 |
| `content_audiences` | Planned content authoring/moderation and filtered feed | No direct write; determines feed visibility | Propose allowed audience if policy permits | Approve or set governed audience | EE-019, EE-020, EE-023 |
| `moderation_decisions` | Draft now: final approval/rejection with controlled reason | None | No direct operation | Create one immutable decision per pending item; `other` requires a note | EE-019, EE-023 |
| `events` | Live development `POST /v1/admin/events`, `GET /v1/events` | Read visible upcoming/past events | No create permission in EE-021 | Create information-only events; update/deactivate remain later | EE-021, EE-023 |
| `event_audiences` | Governed by the live development event operations | No direct write; determines visibility | No direct write | Set an all-Member or active-circle audience during creation | EE-021, EE-023 |
| `event_reminder_rules` | Governed by the live development event operations | Read reminder timing with a visible event | No direct write | Set zero-to-five bounded offsets during event creation | EE-021, EE-023 |
| `notification_preferences` | Verified development own GET/PUT | Read/update own settings | Read/update own settings | No silent override; support action requires audit and approved policy | EE-022, EE-023 |
| `broadcasts` | Planned Week 12 broadcast-control operations | Join authorised live broadcast as viewer | Schedule/start/end own authorised broadcast | Govern schedules, caps and incident controls | EE-040–042 |
| `broadcast_audiences` | Planned Week 12 broadcast-control operations | No direct write; determines join entitlement | Propose authorised audience | Approve or govern audience | EE-040–042 |
| `recordings` | Planned Week 12 recording/replay workflow | View only approved visible replay content | View processing state for own broadcast | Govern retention, approval and replay conversion | EE-041, EE-042 |
| `notification_deliveries` | Internal worker only; no direct client CRUD | No direct access | No direct access | Operational status through a future restricted support view only if approved | EE-021, EE-022, EE-024 |
| `audit_events` | Internal append-only service; restricted review operation may be added | No access | No general access; actions generate records | Restricted read; actions generate immutable records | EE-007, EE-014, EE-019, EE-024 |

## Permission rules that apply to every operation

1. Authentication alone is not authorisation. The backend checks role, account status, ownership, circle audience, resource status and requested action.
2. A suspended or deleted account cannot use an existing mobile token to continue normal operations.
3. Contributors cannot approve their own content or change their own role/status.
4. Members never receive pending, rejected, archived or unauthorised-circle content.
5. Storage object keys, staff credential hashes, provider references and encrypted join references are never exposed as ordinary response fields.
6. Administrator changes to users, moderation, audiences and retention produce an audit event with a trace identifier and reason where required.
7. Planned operations stay unavailable until their tracker sprint, contract review, runtime tests and acceptance evidence are complete.

## Remaining delivery gaps

- The checksum-locked baseline is applied and verified in development; future schema changes must repeat the recorded migration, review and backup controls.
- Each planned operation must be added to the OpenAPI only in its approved sprint and linked to automated permission tests.
- The Member flow must be updated to the approved immediate-access self-registration journey. Contributors remain Administrator-created.
- Retention/deletion and broadcast-consent decisions must be recorded when their sprint requires them. Profile, circle and Administrator-authentication rules are recorded.
- Development health, database migration, uptime and alert-policy evidence exist. Alert-email delivery, rollback rehearsal, staging and production evidence remain outstanding.
