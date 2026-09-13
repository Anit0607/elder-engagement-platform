# Elder Engage REST API change log

The contract remains a controlled Sprint 2 draft and no listed operation is claimed callable until its matching backend deployment is verified.

## Member refresh development verification — 13 September 2026

- The Member refresh implementation from commit `83f095c578794da6bf046ecaefa141e2242bee0e` is deployed and verified in the private development environment. GitHub passed 207 backend tests, including PostgreSQL 16 integration checks; the deployed private-health check also passed.
- Seven live fictional-account checks passed: stable Android/iOS Member identifier, replacement credentials, old-access rejection, reuse-family revocation with another family unaffected, logout blocking renewal, own-device removal blocking renewal, and private-service access. No real SMS was sent.
- This does not make every operation in this draft callable. Android persistent-session acceptance and EE-010 staff support remain outstanding. No public/production origin or iOS handover is included.

## Member refresh implementation note — 13 September 2026

- Implemented single-use Member refresh at the existing `/v1/auth/refresh` path: stable user identifier, new credentials, unchanged session-family expiry, and committed family revocation on token reuse.
- Added the dependency-outage response. Clients must not replay a refresh token after an uncertain outcome or an outage response; sign in again instead. This operation does not advertise automatic outage retries.
- Renewals do not consume the fresh phone-sign-in allowance. Logout, removed-device, suspended-account and expired-session protections apply to renewal.
- No success-payload or path changes. Candidate is not yet deployed. Android persistence/renewal and EE-010 staff-session acceptance remain outstanding; EE-011 is not complete.

## Member session-control implementation note — 12 September 2026

- Added explicit suspension and dependency-outage responses for Member device listing, logout and device removal, plus invalid-path validation for device removal.
- Clarified owner isolation, token-family revocation and rejection of a removed session.
- No path or success-payload changes. Backend candidate remains undeployed; staff sessions and refresh rotation are not included in this implementation step.

## 0.2.0-draft — 12 September 2026

- Replaced Administrator-pre-provisioned Member sign-in with the approved immediate-access self-registration journey.
- Added `profileComplete` and a new-Member response example so Android and iOS can route incomplete profiles to self-service setup.
- Kept Contributor creation under Administrator control.

## 0.1.3-draft — 12 September 2026

- Added the documented retryable dependency-unavailable response to Member session creation.
- Began the callable Member-session foundation while keeping external phone verification, persistent member lookup and secure token storage fail-closed until their production adapters are connected.

## 0.1.2-draft — 9 September 2026

- Added distinct safe problem codes for unexpected internal errors, oversized request bodies and unsupported methods.
- Added health/readiness documentation for safe 413 and 500 responses to align the current EE-002 process foundation.
- Retained dependency outages as retryable 503 responses; unexpected application failures are not classified as dependency outages.

## 0.1.1-draft — 9 September 2026

- Established the engagement-platform contract as the current source and marked inherited booking interfaces legacy.
- Closed strict Profile composition and response-token direction defects.
- Added manual role-specific profile onboarding and profile-photo upload lifecycle.
- Added stable authentication/session error actions and HTTP-status mappings.
- Defined manual Member pre-provisioning, invited staff state, serialized refresh recovery, profile patch and notification-window semantics.
- Added eight synthetic examples, repeatable JSON Schema checks and a matching 16-request Postman companion.

No staging origin, implementation, deployment, iOS receipt or client acceptance is included in this draft release.

## Change rules

- Additive, optional version-one fields require OpenAPI, example, contract-test, Postman and change-log updates in the same pull request.
- Removing or changing a field, or making optional input mandatory, requires `/v2` plus a documented migration window unless the client and iOS developer explicitly approve a recorded exception before merge.
- Each shared draft records its Git commit, contract checksum, recipient, date, questions and acknowledgement in the notification log.
