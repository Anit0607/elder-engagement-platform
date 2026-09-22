# Amiko REST API — Backend Release 1 handover

Share this folder with the separately contracted iOS developer. It is the complete **backend interface package for development integration**, not a claim that the iOS app, client acceptance, or production environment is finished. The Android and iOS apps use the same backend; our scope is the Android app and REST backend, not iOS implementation or iOS testing.

## The four files

| File | What to do with it |
|---|---|
| `README.md` | Read this first for the address, sign-in flow, safety rules and known limitations. |
| `openapi.json` | Import into an OpenAPI-capable tool or use as the definitive list of request/response fields and error formats. It lists 36 implemented backend routes. |
| `postman_collection.json` | Import into Postman for example requests. Every password/token variable is empty. The example identifiers are fictional and must be replaced after sign-in. |
| `manifest.json` | File checksums and the recorded backend build/gateway evidence. |

## Address and version

- Development test base address: **`https://api-test.eldercaresaathi.com`**. Add paths such as `/v1/me/profile` directly; do not repeat `/v1` in the base address.
- API path version: **`/v1`**. Contract document version: **`0.3.5`**.
- This is the client's protected **development** environment. A different production address will be supplied only when production is deployed; it is not available yet. Do not put real customer data in this test environment.
- No iOS developer name, email address, GitHub identity, or iOS bundle identifier is required from us to publish or use this REST contract. The iOS developer manages their own iOS app registration and build.

## Start integration

1. Import `openapi.json` and `postman_collection.json`. The collection already contains the test base address. Start with `GET /health` (expected HTTP 200). Protected requests without a platform login should return HTTP 401.
2. For a **Member**, complete phone one-time-password sign-in using Google's official Firebase Authentication/Identity Platform iOS software development kit in project **`amiko-508302`**. The iOS developer registers their iOS app with that client-owned Google project and obtains its iOS configuration there. Their iOS bundle identifier is needed for that **iOS registration**, not for our REST API. Google supplies the verified identity token; send that token as `providerIdToken` to `POST /v1/auth/member/session`, with a device `installationId` and `platform: "ios"`. Do not send the one-time password to our backend.
3. The session response supplies a short-lived platform `accessToken` and rotating `refreshToken`. Send `Authorization: Bearer <accessToken>` on protected requests. Save tokens only in operating-system protected storage; never place them in logs, screenshots, GitHub or a shared Postman workspace. A new verified Member can access the app immediately; `profileComplete: false` means the Member should fill in the profile.
4. Contributors and Administrators use `POST /v1/auth/staff/session` with an Administrator-created username/password. Administrators also enter the current authenticator-app code in `secondFactorCode`. These are separate staff accounts, not Member phone sign-in. Fictional test staff access is arranged privately; no credential is in this folder.
5. Use the OpenAPI descriptions and examples for profiles/photos, circles, Contributor media upload, Administrator review/publication, Member feed/media, events, notification preferences and account controls. Media upload uses the returned short-lived private upload address; never log or retain it after use.

## Rules that avoid integration errors

- Success status **204** has no response body. Do not try to parse one.
- Refresh tokens rotate. Run only one refresh at a time. If the network result is uncertain, do **not** retry the same refresh token; clear local tokens and sign in again.
- Errors use `application/problem+json` with a stable code and trace identifier. If the response says rate limited, wait for the `Retry-After` number of seconds.
- Use the pagination cursors and limits documented in `openapi.json`; do not infer the next page from item counts.
- A Member cannot claim a staff role. The backend decides each account's role and checks access on every request.
- Changes to the interface are recorded in the project's API change log. A breaking change requires `/v2` or a separately approved migration plan; do not rely on chat descriptions as the contract.

## Test access and current limitations

- **No live token, test phone/code pair, staff password or authenticator setup is in the public package.** The client or authorised project operator provides fictional test access to the iOS developer through a private channel. The developer can build request/response handling now; authenticated end-to-end testing needs that access and the Google iOS app configuration.
- `GET /ready` is an operational dependency check, **not an app integration endpoint**. After the 23 September 2026 fix, it returned HTTP 200 on repeat checks of the database, sign-in protection, storage and Google phone-verification certificates. A failure returns HTTP 503. External checks are cached briefly, so do not use `/ready` as an iOS launch or connectivity gate.
- `GET` and `POST /v1/admin/users` are not implemented and are intentionally absent from this handover. Administrator account creation through the final web console remains later work.
- Live streaming, group calls, Meet, YouTube, payments, automated translation/speech, artificial-intelligence moderation and notification delivery are **not** included in Backend Release 1. Basic events are information-only; reminder preferences are stored but reminders are not sent yet.
- Public gateway checks passed for health, unauthenticated access denial and blocked direct Cloud Run access. The client acceptance journeys and a fresh authenticated public-route smoke test are **not yet signed off**. See `manifest.json` for the recorded build and gateway checks. No production readiness is claimed.

## Who does what next

- **Our backend team:** maintain `/v1`, monitor the readiness check, provide the production address when deployed, and investigate reproducible backend defects.
- **iOS developer:** build and test the iOS app against this contract; register their iOS app in the client's Google identity project; handle its Apple/iOS configuration. That work is not part of the Android/backend delivery.
- **Client/project manager:** forward this public folder; privately arrange fictional test access and Google iOS app registration permission when the developer is ready. No credentials should be sent in the public repository or ordinary chat.
