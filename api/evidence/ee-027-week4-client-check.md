# EE-027 — Week 4 client backend check

Status: **accepted for the Week 4 backend milestone**. This is not acceptance
of the whole Android application or the final production release.

On 24 September 2026, the Project Manager reported that all five checks on the
local review page worked as expected, with no defect reported. The Project
Manager then explicitly confirmed that the client had formally accepted Week 4.

Environment: client-owned development project `amiko-508302`, protected test
address `https://api-test.eldercaresaathi.com`, backend source revision
`7b7f2afc040d07233b574ebf1fae678cdb56a1eb`, running image digest
`sha256:f5ef5dca510f231586d47ad4482fa2cd3537ed9b1790f3fcab151ad8e90053e1`.
Verified 24 September 2026 with fictional accounts and generated media only.

| Week 4 client journey | Engineering observation through the public test address | Client decision |
|---|---|---|
| 3. Circles | Administrator-only changes, profile-based suggestions, five-circle limit, Member join/leave and Administrator assignment passed. | Accepted |
| 4. Uploads | Generated video, audio and PDF remained private and entered pending review. | Accepted |
| 5. Approval | Contributor could not moderate; private previews, approve/reject reasons and no publication by approval alone passed. | Accepted |
| 6. Feed | Approved media reached only its selected circle; removing membership removed feed and media access. | Accepted |
| 7. Events/preferences | Administrator event rules, circle-only visibility, removal of access, saved Member preferences and rejection of unexpected fields passed. No notification was sent. | Accepted |

The public route also returned HTTP 200 for health and readiness, denied an
unauthenticated profile read with HTTP 401, and allowed a fictional Member to
sign in, read their own profile and sign out. Direct private Cloud Run access
remains blocked. The Week 2 Member, staff, profile and account-control journeys
were previously client-tested; they are separate from the five EE-027 journeys.

The former direct-address test commands are not the correct acceptance route
after the load-balancer protection was enabled. The local review page in
`services/engagement-api/tools/development_week4_acceptance_page.py` uses the
protected public address. It displays only safe pass/fail descriptions, not
passwords, phone numbers, tokens, account identifiers or media links. Repeated
fictional sign-ins can temporarily return HTTP 429 because the intended login
rate limit is working; wait for the window to clear rather than disable it.

The five EE-027 journeys have a recorded **Accepted** outcome with no defect
reported. This closes Week 4 backend client acceptance. It does not claim an
Android screen, final web console, or production deployment.
