# EE-027 — Week 4 client backend check

Status: **awaiting client review and explicit acceptance**. Engineering checks
are evidence for the client; they are not the client's acceptance decision.

On 24 September 2026, the Project Manager reported that all five checks on the
local review page worked as expected, with no defect reported. This records the
Project Manager's test result; it does not presume the client's formal sign-off.

Environment: client-owned development project `amiko-508302`, protected test
address `https://api-test.eldercaresaathi.com`, backend source revision
`7b7f2afc040d07233b574ebf1fae678cdb56a1eb`, running image digest
`sha256:f5ef5dca510f231586d47ad4482fa2cd3537ed9b1790f3fcab151ad8e90053e1`.
Verified 24 September 2026 with fictional accounts and generated media only.

| Week 4 client journey | Engineering observation through the public test address | Client decision |
|---|---|---|
| 3. Circles | Administrator-only changes, profile-based suggestions, five-circle limit, Member join/leave and Administrator assignment passed. | Pending |
| 4. Uploads | Generated video, audio and PDF remained private and entered pending review. | Pending |
| 5. Approval | Contributor could not moderate; private previews, approve/reject reasons and no publication by approval alone passed. | Pending |
| 6. Feed | Approved media reached only its selected circle; removing membership removed feed and media access. | Pending |
| 7. Events/preferences | Administrator event rules, circle-only visibility, removal of access, saved Member preferences and rejection of unexpected fields passed. No notification was sent. | Pending |

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

The acceptance owner must review journeys 3–7, report each as Pass or Fail with
any reproducible defect, then choose **Accepted**, **Accepted with listed
non-blocking issues**, or **Rejected with release blockers**. Do not close
EE-027 or call this production-ready until that decision is recorded. This
milestone is backend development acceptance, not an Android screen, final web
console, or production deployment.
