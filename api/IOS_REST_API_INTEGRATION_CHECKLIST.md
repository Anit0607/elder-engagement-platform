# iOS REST API Integration Checklist

Status: Pre-Sprint draft pending the client's iOS developer contact
Owner: Lead Orchestrator
Tracker items: EE-051 and EE-023

## Week 1 contract review package

- [ ] Confirm the iOS technical contact and GitHub identity.
- [ ] Confirm the application bundle identifier is not required by backend version 1 unless a provider explicitly needs it.
- [ ] Publish the OpenAPI 3.1 contract for the approved engagement-platform scope.
- [ ] Document the `/v1` base path, media types, date/time representation, pagination, sorting, and filtering.
- [ ] Document Member one-time-password, Contributor credential, Administrator, refresh, logout, and session-revocation flows.
- [ ] Document Member, Contributor, and Administrator permission boundaries.
- [ ] Provide request and response examples for identity, profile, circle, upload, moderation, feed, and event operations.
- [ ] Use one problem response containing HTTP status, stable error code, human-safe message, field errors where relevant, and trace identifier.
- [ ] Mark every planned but unavailable operation clearly; do not expose a fake staging address.
- [ ] Agree how breaking and non-breaking changes are communicated through GitHub.
- [ ] Obtain written acknowledgement from the iOS developer or log unresolved questions.

## Week 2 usable foundation

- [ ] Provide a client-owned staging base address over HTTPS.
- [ ] Provide non-production Member, Contributor, and Administrator test identities through a secure channel.
- [ ] Verify one-time-password request and verification, token refresh, logout, session expiry, and revocation.
- [ ] Verify detailed profile read/update and role-based denial scenarios.
- [ ] Publish an executable Postman collection and safe placeholder environment without secrets.
- [ ] Run automated OpenAPI validation and contract tests in the delivery pipeline.
- [ ] Complete an iOS smoke test covering sign-in, token refresh, profile retrieval, invalid input, and unauthorised access.

## Week 4 production-ready REST API version 1 package

- [ ] Freeze the agreed version 1 interface for circles, contributor uploads, moderation, feed, events, and notification preferences.
- [ ] Confirm upload size/type rules and short-lived upload-authorisation behaviour.
- [ ] Verify pagination, filtering, stable identifiers, timestamps, idempotency where required, and concurrency behaviour.
- [ ] Verify rate limits, generic authentication errors, safe validation messages, and traceable server errors.
- [ ] Publish release notes, change log, known limitations, and supported version policy.
- [ ] Provide the final OpenAPI file and Postman collection from the same Git commit as the deployed backend.
- [ ] Complete the agreed iOS integration smoke test and log evidence or reproducible defects.
- [ ] Record client/iOS acceptance or remaining release-blocking defects in the tracker.

## Rules that prevent iOS rework

1. OpenAPI is the source of truth; chat messages are not interface changes.
2. A pull request that changes an interface must update contract, examples, tests, and change log together.
3. Removing a field, changing its meaning, or making optional input mandatory is a breaking change. It requires `/v2` and a documented migration window unless the client and iOS developer explicitly approve a recorded exception before implementation.
4. No production credential, access token, one-time password, signed media address, or personal data belongs in GitHub or the Postman package.
5. Android, iOS, Contributor, and Administrator clients use the same backend rules; security is never implemented only in a client application.
