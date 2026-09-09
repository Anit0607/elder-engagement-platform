# Elder Engage REST API change log

The contract remains a Pre-Sprint draft and no listed operation is claimed callable.

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
