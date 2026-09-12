# Schema, REST and permission mapping

Status: Sprint 1 controlled baseline under EE-008
Sources: `database/migrations/V0001__engagement_baseline.sql` and `api/openapi/elder-engage-v1.openapi.json`

This mapping prevents the inherited booking product from being mistaken for Amiko. “Draft now” means the operation exists in the Week 2 OpenAPI draft but is not necessarily connected to live providers and data. “Planned” means it is an approved tracker item but is deliberately unavailable in the current contract.

| Data owner/table | API coverage | Member | Contributor | Administrator | Tracker evidence |
|---|---|---|---|---|---|
| `app_users` | Draft now: session exchange, Administrator create/list/status/role | Read own identity summary | Read own summary | Create/list and change governed status/role | EE-009–014, EE-051 |
| `staff_credentials` | Draft now: staff session input; credential storage is never exposed | None | Authenticate own account | Authenticate own account; cannot read hashes | EE-010, EE-015 |
| `user_profiles` | Draft now: own GET/PATCH, photo upload lifecycle, Administrator create and summary list | Read/update permitted own fields | Same for own profile | Create profiles and list summaries; detailed cross-user read/edit remains unavailable until approved | EE-013–015, EE-051 |
| `auth_sessions` | Draft now: create/refresh/logout/list/revoke | Manage own sessions | Manage own sessions | Manage own sessions; cross-user revocation requires a later approved operation | EE-011, EE-015, EE-051 |
| `circles` | Planned REST expansion | View active predefined circles | View active circles | Create/update/deactivate | EE-017, EE-023 |
| `circle_memberships` | Planned REST expansion | View/select/leave own allowed circles | Same Member access unless policy changes | View and administer according to approved rules | EE-017, EE-023 |
| `content_items` | Planned upload, moderation and feed operations | Read approved visible content | Create and view own submissions; no self-approval | Review all governed submissions and archive | EE-018–020, EE-023 |
| `content_assets` | Planned signed upload/complete and approved delivery | Read only through authorised approved content | Upload only to own pending content | Inspect metadata and moderation state; no public bucket access | EE-018, EE-019, EE-025 |
| `content_audiences` | Planned content authoring/moderation and filtered feed | No direct write; determines feed visibility | Propose allowed audience if policy permits | Approve or set governed audience | EE-019, EE-020, EE-023 |
| `moderation_decisions` | Planned approval/rejection operations | None | Read outcome/reason for own content | Create immutable decisions and view audit history | EE-019, EE-023 |
| `events` | Planned event operations | Read visible upcoming events | Create only if final role policy permits | Create/update/deactivate | EE-021, EE-023 |
| `event_audiences` | Planned event operations | No direct write; determines visibility | Governed by event-create permission | Set governed event audience | EE-021, EE-023 |
| `notification_preferences` | Planned preference operations | Read/update own settings | Read/update own settings | No silent override; support action requires audit and approved policy | EE-022, EE-023 |
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
- Final profile fields, circle rules, Administrator authentication, retention/deletion and broadcast consent decisions must be recorded when their sprint requires them.
- Development health, database migration, uptime and alert-policy evidence exist. Alert-email delivery, rollback rehearsal, staging and production evidence remain outstanding.
