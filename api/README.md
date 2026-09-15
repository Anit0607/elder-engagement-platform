# Elder Engagement REST API v1

Status: Sprint 3 controlled contract with verified private development through EE-019 and an EE-020 source candidate
Tracker ownership: EE-051 for the initial contract and EE-023 for the Week 4 production-ready integration package.

## Current source of truth

- `openapi/elder-engage-v1.openapi.json` — current OpenAPI 3.1.1 contract draft for the approved engagement platform.
- `IOS_REST_API_INTEGRATION_CHECKLIST.md` — receipt, review, test, and acceptance checklist for the client's separate iOS developer.
- `../tools/validate_engagement_openapi.mjs` — dependency-free contract integrity check.
- `contract-tests/` — repeatable JSON Schema compilation, example validation, and negative contract tests.
- `postman/Elder_Engage_Sprint3_Draft.postman_collection.json` — generated safe, synthetic Sprint 3 companion collection.
- `CHANGELOG.md` and `IOS_CONTRACT_NOTIFICATION_LOG.md` — interface history and iOS receipt evidence.

Run the current check from the project root:

```powershell
node tools\validate_engagement_openapi.mjs
cd api\contract-tests
npm install
npm test
cd ..\..
node tools\generate_engagement_postman.mjs
```

The contract defines the Week 2 foundation plus Sprint 3 notification-preference, predefined-circle, private Contributor-upload, Administrator-moderation and circle-filtered Member-feed interfaces. The private development deployment verifies authentication, sessions, own profiles, profile photos, status/role controls, notification preferences, circles, Contributor uploads and Administrator moderation. The feed remains a source candidate until its separate delivery identity, approved-file promotion and live audience-isolation proof pass. Administrator user creation/listing remains contract-only until its planned Administrator workflow is implemented. Events and later broadcast operations will be added under their approved milestones. No staging or production availability is claimed.

## Version and server rules

- Operations use the `/v1` path prefix; a deployment origin does not repeat `/v1`.
- The local origin in the draft is not a promised staging or production address.
- Removing a field, changing its meaning, or making optional input mandatory requires `/v2` and a documented migration window unless the client and iOS developer explicitly approve a recorded exception before implementation.
- Additive optional fields may remain in version 1 when old clients continue to work.
- Contract, examples, automated checks, change log, and iOS notification must change in the same GitHub pull request.

## Authentication boundary

The mobile client completes phone one-time-password verification through the client-approved Firebase Authentication or Identity Platform project. It sends the resulting identity-provider token to the REST backend to create the platform session. The REST backend never accepts or logs the one-time password itself.

A verified phone identity receives immediate Member access. The backend atomically finds or creates the active Member account, and a `profileComplete=false` response sends a new Member to self-service profile setup without blocking the session. Contributor and Administrator profiles use a username and remain Administrator-created. Fictional development accounts were provisioned through a controlled one-time job; the production Administrator console and real-account invitation/recovery flow remain later work. The backend determines roles from stored account data and never accepts the mobile client's claim of a role.

Contributor and Administrator credentials use the separate staff session operation. The client-approved stronger Administrator method is a password plus a changing code from an authenticator app; the private development deployment verifies this method with a fictional Administrator.

## Security rules

- Access control is denied by default and enforced by the backend.
- Access tokens are short-lived; refresh tokens rotate and can be revoked.
- Successful `204` responses have no response body and mobile clients must not attempt to decode one.
- Mobile clients serialize token refresh. After an uncertain response they follow `REFRESH_OUTCOME_UNKNOWN`, never retry the same refresh token, clear local tokens and return to sign-in because the current draft has no safe status-recovery operation.
- Rate-limit responses document `Retry-After` in seconds.
- Errors use the documented `application/problem+json` schema and contain a trace identifier.
- No production credential, provider token, one-time password, access token, refresh token, signed media address, or personal data belongs in GitHub, OpenAPI examples, or Postman files.
