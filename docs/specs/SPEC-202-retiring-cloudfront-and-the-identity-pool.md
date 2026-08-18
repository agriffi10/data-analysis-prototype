# Spec: Retiring CloudFront & the Identity Pool, and the Arc's Live Checks

**ID:** SPEC-202
**Status:** Draft
**Last Updated:** 2026-08-18
**Depends On:** SPEC-192 (the runtime-configuration document whose `cognitoIdentityPoolId` key this spec removes, the ten-key end state its group (a) declares, and the key-set agreement test that makes the removal fail in CI rather than in production), SPEC-193 (`spa_origin` / `api_origin` — the origins every allowlist here narrows to, the deployed roles the IAM simulation targets, and **the three additive allowlist changes this spec narrows**: both origins on the Cognito app client, `api_origin` in CloudFront's `connect-src`, both origins in API Gateway's CORS. They are SPEC-193 FR-006's, not this spec's; here they are preconditions, verified before merge 1 and never re-introduced), SPEC-194 (the container's nginx header set and `connect-src` derivation, whose final state this spec asserts, and the deploy workflow that replaces `deploy-app.yml`), SPEC-195 (the bearer boundary — `getIdToken` is the one export of `lib/awsCredentials.ts` that survives this spec), SPEC-196 (the portal role's second trust statement, without which removing the Identity Pool's leaves the role unassumable, and the isolation-simulation discipline this spec re-runs post-retirement), SPEC-197 → SPEC-201 (the ported surface — every route this spec's live checks exercise; 198, 199 and 200 each delete part of the browser's AWS client set and each deliberately leave `awsCredentials.ts` and `credentialRetry.ts` standing, which is what FR-005 finishes), SPEC-140 (the response-headers policy, and the CSP verification rule this spec corrects — see FR-008 and FR-011), SPEC-141 (the three prefix-scoped passes and the invalidation deleted here), SPEC-011/013/056 (the Identity Pool ABAC model being retired, and the policies that must keep enforcing without it)

## Overview

Every spec in this arc so far has been **additive**. Two front doors served the portal, two credential
paths reached AWS, and each step was independently revertible because the thing it replaced was still
running. This spec is the subtraction, and subtraction is where this repo's characteristic failure
lives: nothing goes red when a dead CloudFront distribution keeps answering, nothing goes red when the
browser holds AWS credentials it no longer uses, and nothing goes red when a `connect-src` still names
four AWS service hosts that no request goes to any more. A half-finished retirement looks exactly like
a finished one.

So this spec is ordered around a proof rather than a deletion, and it ships in **two merges whose
difference is whether they can be undone**. Merge 1 retires the Identity Pool and the last of the
browser's AWS SDK path. It touches nothing that serves the app: CloudFront still runs, its
`connect-src` still names the API, the Cognito callback and logout lists still name both origins, and
both buckets' CORS still allows both — so the front door can still be moved back to CloudFront and the
app works. **Then the arc's live checks run against the container origin, with that rollback intact.**
Merge 2 narrows the three allowlists and destroys the distribution, and after it there is no rollback
at all: no origin serves the old front door and no allowlist admits it.

That order is not a preference. The load-bearing negative — *the browser makes no AWS call other than
presigned S3 bytes* — **cannot be observed while the Identity Pool exists**, because `lib/amplify.ts`
configures `identityPoolId` whenever the key is present and every `fetchAuthSession()` then vends pool
credentials, including the one `getIdToken` makes on every API call. Running the checks before merge 1
and calling that row a pass is the shape of failure this spec exists to prevent. The checks themselves
are the deliverable a later
session will care about most: a runnable script under `docs/testing/`, whose load-bearing item is a
**negative** (the browser makes no AWS call other than presigned S3 bytes) and whose second is a
**state nobody exercises by accident** (a fresh, signed-out sign-in — SPEC-140's omitted `connect-src`
host broke exactly that for a day while every signed-in session stayed healthy).

**One conflation to head off before the first FR.** The Cognito **User Pool** authenticates people:
Managed Login v2, the Hosted UI round trip, Amplify in the tab, the ID token. The Cognito **Identity
Pool** does something entirely different — it exchanges that ID token for temporary AWS credentials so
the browser can call S3, Athena, Glue and SQS itself. This spec retires the **Identity Pool**.
Sign-in, sign-up, sign-out, the auth gate, `lib/returnPath.ts` and every Cognito value in the runtime
config are untouched, here and in the whole arc. A user cannot tell this spec shipped by signing in;
they can only tell by opening the network panel.

## Scope

### In Scope

- **The cutover order** (FR-001), stated as a decision: which merge can be rolled back, which cannot,
  and what "the rollback still exists" actually requires.
- **Cognito app-client callback and logout URLs** *narrowed* to `spa_origin`, and root `var.app_url`
  retired in favour of `local.spa_origin` (FR-002).
- **Bucket CORS** on both data buckets narrowed to the SPA origin and to `["GET","PUT"]` (FR-003).
- **The Identity Pool retirement** (FR-004): the pool, its principal-tag map, the roles attachment,
  the portal role's federated trust statement, and SPEC-192's `cognitoIdentityPoolId` key.
- **The last of the browser's credential path** (FR-005): `getSessionCredentials` and
  `lib/credentialRetry.ts` — the two modules SPEC-198/199/200 each deliberately left standing — with
  `getIdToken` explicitly surviving, because SPEC-195's bearer needs it; plus the **verification**
  that the four `lib/*Client.ts` modules and all six `@aws-sdk/*` dependencies are actually gone.
- **The enumerating lint rule** (FR-006) that keeps `@aws-sdk/*` out, plus the dependency sweep the
  lint rule cannot perform. This is the arc's own tripwire and it outlives the arc.
- **`infra/modules/app` and `deploy-app.yml`** deleted (FR-007), with the static bucket's disposal
  named rather than assumed.
- **The final header and `connect-src` state** (FR-008) — the arc's open question 2, asserted here
  against the deployed container rather than against a Terraform local.
- **The arc's live checks** as a runnable script, `docs/testing/arc-b-api-container-e2e.md` (FR-009),
  and **the IAM policy simulation against the deployed roles** (FR-010).
- **The documentation reversal** (FR-011): `architecture.md`'s "no backend" premise, the CLAUDE.md
  Key Decisions sweep, and superseded markers at every site still stating a decision this arc
  overturned.
- **A written handover** of what the target-environment arc inherits (the closing section).

### Out of Scope

Everything a reader would reasonably assume travels with "we finished the migration":

- **The BFF, the session cookie, the DynamoDB session store and its KMS key, PKCE, the login
  transaction and the `/auth/*` routes.** Deferred with the target-environment arc — see the closing
  section. The arc's 2026-08-18 re-scope, not an omission.
- **Entra ID, Identity Center, trusted identity propagation and the carrier role.** Nothing IdC-shaped
  ships or is prepared beyond SPEC-200's `{actor, delegated_by, assurance}` fields.
- **Retiring Cognito, Amplify, Managed Login v2, the two Cognito trigger Lambdas, `lib/amplify.ts`,
  `lib/returnPath.ts` or the four Cognito runtime-config keys.** Sign-in is unchanged. A test, note or
  `.env.example` line claiming the browser stops needing Cognito configuration is wrong.
- **`aws-amplify` as a dependency.** It stays, and it vendors `@aws-sdk/*` transitively — which is
  why FR-006's sweep reads `package.json`, never `node_modules`.
- **A WAF, a rate limit, a machine-facing authorizer, autoscaling, capacity providers, multi-AZ
  availability work.** Deferred by the arc; `transition_plan.md` §4.6 records the availability
  obligation a load balancer brings.
- **Deleting the static bucket's *history*.** FR-007 empties and destroys the bucket; anything wanted
  from it is copied out first, by hand, and nothing in this repo reads it.
- **Introducing any allowlist entry.** All three additive changes — both origins on the Cognito app
  client, `api_origin` in CloudFront's `connect-src`, both origins in API Gateway's CORS — are
  **SPEC-193 FR-006's** and landed there. This spec only ever narrows. FR-001's second criterion verifies them as
  preconditions; a builder who finds one missing fixes it in SPEC-193 and does not add it here.
- **Any user-visible behaviour change.** No component, hook, route, label or Help guide changes.
  FR-011 records that explicitly rather than leaving it ambiguous.
- **Re-running the live checks other arcs still owe** (archive, table-builder, Data Explorer, the
  file-ops arc). Those stay owed against the new origin; this spec's script does not absorb them, and
  FR-009 says which of them the new origin invalidates and which it does not.

### What is deleted, what proves it was dead first

The cheapest defence against deleting something that was still load-bearing. Every row's proof is a
**positive observation**, never "nothing broke".

| Deleted | Merge | Proof it was already dead |
|---|---|---|
| Cognito Identity Pool + principal-tag map + roles attachment | 1 | **Not** FR-009 §4: while the pool exists, `lib/amplify.ts` configures it and every `fetchAuthSession()` vends credentials, so that row cannot read zero. The pre-merge proof is the enumerated absence of *consumers* — `getSessionCredentials` has zero importers once FR-005's two substitutions land, the four `lib/*Client.ts` modules are gone (SPEC-198/199/200) and no `@aws-sdk/*` dependency remains (FR-006's sweep). §4 is the **post**-merge-1 confirmation that no residual path exists |
| The portal role's `AssumeRoleWithWebIdentity` trust statement | 1 | CloudTrail **Event history** (there is no management-events trail in this account — the only trail is archive-scoped) shows no `AssumeRoleWithWebIdentity` on the role for 24 h, **with a positive control**: one deliberate credential vend from the pre-merge build must appear, or an empty result is indistinguishable from a source that does not record the event. **And** SPEC-196's statement is present in the **deployed** trust policy (`get-role`), not merely in the plan |
| `getSessionCredentials`, `lib/credentialRetry.ts` (the last two; SPEC-198/199/200 took the four clients) | 1 | Zero importers, enumerated by the sweep — and their tests deleted with them, not left asserting a deleted contract |
| Every `@aws-sdk/*` dependency | 1 | FR-006's lint rule and dependency sweep, each verified against a deliberate violation — the sweep is what sees a dependency whose last importer left with an earlier spec |
| `cognitoIdentityPoolId` in the runtime config | 1 | SPEC-192's key-set agreement test fails if any of the four wiring points still names it |
| Cognito callback/logout entries and bucket CORS entries for the CloudFront origin | 2 | FR-009's whole script passed against `spa_origin` with the retirement already applied — §3 (fresh sign-in), §5 (a real presigned upload and download) and §8 (all eight planes) |
| `infra/modules/app` (distribution, OAC, static bucket, response-headers policy) | 2 | §10's rollback rehearsal was **exercised and recorded** on the distribution, so it is retired knowingly rather than found missing; and its last 24 h of access logs show only the checker's own requests |
| `deploy-app.yml`'s three passes + the invalidation | 2 | SPEC-194's `deploy-spa-image.yml` has deployed the reachable commit; the container's `/healthz` reports the same build sha as HEAD |

### Premises this spec inherits and must not quietly reverse

1. **The isolation model is unchanged, not re-implemented.** SPEC-196's argument is that the API reads
   the same claims from the same token and assumes the same role with the same tag set, so not one IAM
   policy, bucket policy or Lake Formation grant is rewritten. Deleting the Identity Pool is the last
   step of that argument, not a new one — FR-010 re-runs SPEC-196's simulation table **after** the
   pool is gone, and a row that changes is a defect in this spec, not a new decision.
2. **`getIdToken` is not part of the credential path.** It returns the ID token Amplify already holds,
   which is what SPEC-195's `apiClient.ts` sends as a bearer. Deleting `lib/awsCredentials.ts` whole
   breaks every API call in the product. FR-005 splits it.
3. **The rollback is not the distribution alone.** It is the distribution *plus* the three allowlists
   that let a browser served from it work: the Cognito callback and logout URLs, the bucket CORS
   origins, and CloudFront's own `connect-src` naming `api_origin`. All three are SPEC-193 FR-006's
   additions. A spec that narrows any of them before the checks pass has deleted the rollback while
   believing it kept it — which is why every narrowing is in merge 2 and every deletion that does
   **not** touch them is in merge 1 (FR-001).
4. **Retiring the Identity Pool is not a rollback risk, and that is why it goes first.** The CloudFront
   rollback serves HEAD, and HEAD after SPEC-200 makes no AWS call from the browser. So the pool is
   load-bearing for nothing that either origin serves — while it is *live*, it is the one thing that
   makes the arc's central negative unobservable. It is nonetheless the merge's one irreversible
   element in the literal sense: a re-created pool gets a new id. Nothing needs the old one.

---

## Functional Requirements

### FR-001: The cutover order, and what the rollback requires

#### Description:

The order is a decision, not a convenience. CloudFront is the rollback for the whole arc, so it is
retired **last** and only against observed evidence. This FR also fixes a consequence the arc's
earlier specs left implicit: the bundle CloudFront serves is HEAD, not a pre-arc build, so the
rollback path has to be able to reach the API.

The split runs *between* the retirement and the narrowing, not around them. Bundling the Identity Pool
destruction with the distribution's destruction and then re-running the fresh-sign-in check afterwards
would gate a merge on evidence it had already destroyed the remedy for.

#### Acceptance Criteria:

- [ ] The work lands as **two merges, in order, and the first is the one that can be rolled back.**
      **Merge 1 — reversible in the only sense that matters:** FR-004 (the Identity Pool, the trust
      statement, the runtime key), FR-005 (the browser's last credential modules), FR-006 (the lint
      rule and the dependency sweep), FR-008's **container** `connect-src` end state, and FR-009's
      script. It changes no allowlist and destroys no origin, so the app can still be served from
      CloudFront and still works.
      **Merge 2 — the one that cannot be rolled back**, and only after every FR-009 blocking item is
      recorded PASS: FR-002, FR-003, FR-007. After it applies, no origin serves the old front door and
      no allowlist admits it; recovering the rollback means re-creating a distribution and re-widening
      two allowlists.
- [ ] **The three additive allowlist entries are verified as preconditions before merge 1, and this
      spec introduces none of them.** They are SPEC-193 FR-006's: `describe-user-pool-client` returns
      **both** origins in `CallbackURLs` *and* in `LogoutURLs`; `curl -sSI $CLOUDFRONT_URL | grep -io
      'connect-src[^;]*'` contains `$API_ORIGIN`; the API's `cors_configuration` lists both. **A
      missing one is a defect in SPEC-193 and is fixed there** — adding it here would make this spec
      additive and put the arc back where the re-scope found it. Recorded in FR-009 §0.
- [ ] **The pre-merge-1 gate is the deployed trust policy, read back.** `aws iam get-role` shows
      SPEC-196's statement live before merge 1 removes the federated one. A plan showing two statements
      says nothing about what is applied, and a role trusted by nobody is a total outage of every API
      call the product makes.
- [ ] Merge 2 does not proceed while any FR-009 item marked **blocking** is unrecorded or FAIL. The
      script marks each item blocking or non-blocking explicitly; "not run" is never "passed" — the
      rule `security.yml` already holds for scanners.
- [ ] The rollback procedure is written into FR-009's script as a runnable section, rehearsed **after
      merge 1 and before merge 2** (re-point DNS or hand the user the CloudFront URL, and what to
      expect: the app works, served from CloudFront, still talking to the API — **it does not restore
      browser-direct AWS**, because that code is gone from HEAD and, after merge 1, so is the pool that
      backed it). Naming that out loud is the criterion; a reader who assumes otherwise will roll back
      expecting a working pre-arc portal.

### FR-002: The Cognito app client and `var.app_url` point at the SPA origin

#### Description:

`local.callback_urls` in `infra/modules/auth/cognito.tf` feeds both `callback_urls` and `logout_urls`
on the one SPA app client. After SPEC-193 it carries three entries — `http://localhost:5173`,
`var.app_url` (the CloudFront domain) and `spa_origin`. This FR removes the middle one and, with it,
the root variable that supplies it.

`var.app_url` is **not** a module output and cannot be made one: it is a root variable with
`default = ""`, declared at `infra/variables.tf:33`, supplied from the GitHub repository variable
`vars.VITE_APP_URL` through `TF_VAR_app_url` in **both** env blocks of `deploy-infra.yml` (the `plan`
job and the `apply` job), and consumed in three places in `infra/main.tf` — `module.auth`,
`module.data` and `module.shared_spaces`. The same repository variable is also `security.yml`'s ZAP
target. Retiring the CloudFront domain therefore touches Terraform, two workflow env blocks and one
repository variable, and missing any of the four leaves a scanner or a callback list pointed at a
distribution that no longer exists.

#### Acceptance Criteria:

- [ ] After merge 2, `local.callback_urls` is exactly `http://localhost:5173` plus `local.spa_origin`
      (with the same paths they carry today), and the deployed `describe-user-pool-client` returns
      **two** `CallbackURLs` and two `LogoutURLs` and **no CloudFront domain**.
- [ ] **`variable "app_url"` is deleted** from `infra/variables.tf` and from `modules/auth`,
      `modules/data` and `modules/shared-spaces`; all three module blocks take `local.spa_origin`
      instead. The criterion that can fail is a **named absence**, not a substring search:
      `grep -rn 'var\.app_url' infra/` returns nothing, and `grep -rn 'TF_VAR_app_url'
      .github/workflows/` returns nothing. **A `cloudfront`-substring assertion over Terraform is not
      that criterion and must not be written** — there is no `infra/locals.tf`, and the only two
      `cloudfront` substrings at root are a comment in `main.tf` and `variable "app_url"`'s own
      `description`, so the test would pass on a prose edit and fail on a correct one.
- [ ] **The container's `appUrl` already equals `local.spa_origin`**, from SPEC-193's task-definition
      environment block — Amplify's `redirectSignIn`/`redirectSignOut` come from it, so a container
      whose `appUrl` names CloudFront sends every sign-in to the other origin. This is verified as a
      precondition, before merge 1, by FR-009 §3; if it is wrong, it is a defect in SPEC-193.
- [ ] **The repository variable `VITE_APP_URL` is re-pointed to `spa_origin` in the same merge**, and
      `.env.example` with it. Its only remaining consumer after `deploy-app.yml` is deleted (FR-007) is
      `security.yml`'s ZAP target at `vars.VITE_APP_URL` — a stale value there does not fail the job,
      it scans a dead host and reports a clean baseline. A criterion, because that is a report-only
      scanner reading as green for the wrong reason.
- [ ] A **redirect-URI mismatch is a Hosted UI error page, not a silent failure**, so this is
      observable: FR-009 §12 re-runs §3's fresh sign-in and sign-out against the narrowed lists, and
      both are blocking. A build whose `appUrl` disagrees with the app client produces
      `redirect_mismatch` on the Hosted UI, which is the distinguishing symptom to look for.

### FR-003: Bucket CORS lists the SPA origin and nothing else

#### Description:

`aws_s3_bucket_cors_configuration` on the user-space bucket (`infra/modules/data/s3.tf`) and the
shared-space bucket (`infra/modules/shared-spaces/s3.tf`) allow `["http://localhost:5173",
var.app_url]` plus `var.spa_origin` after SPEC-198, over
`allowed_methods = ["GET","PUT","POST","DELETE","HEAD"]`. After SPEC-198 the only browser→S3 traffic is
presigned bytes, and they still need CORS. SPEC-198 FR-011 deliberately left the method list alone and
named this spec as the narrower; **both specs state the same end state so neither can drift.**

#### Acceptance Criteria:

- [ ] Both configurations allow exactly `local.spa_origin` plus `http://localhost:5173`, and no other
      origin. Narrowing only — the additive half is SPEC-198 FR-011's and already applied.
- [ ] **`allowed_methods` is exactly `["GET", "PUT"]`** on both buckets — the same end state SPEC-198
      FR-011 records. That is the whole presigned surface the browser redeems after the arc: a
      presigned `GET` for download (FR-006 there) and a presigned `PUT` for upload over
      `XMLHttpRequest` (FR-005 there). `HEAD` (`objectExists`, `getObjectMetadata` and every collision
      pre-check), `DELETE` and multipart `POST` were the browser's own SDK calls and moved into API
      routes; a test asserts the absence of all three, because a stale-but-working CORS rule is
      invisible. **Narrowing this before merge 2 breaks the rollback** — the CloudFront-served bundle
      is HEAD, so it redeems the same two methods, but the narrowing lands in the merge that destroys
      the distribution anyway.
- [ ] `expose_headers` keeps `ETag` and drops `x-amz-server-side-encryption`, `x-amz-request-id` and
      `x-amz-id-2`. Each of the three removals is gated on a **grep over `apps/portal/src` returning
      zero occurrences of that header name** — a named absent reader, not tidiness. `ETag` is kept
      without such a grep and deliberately: an exposed header nobody reads costs nothing, while a
      missing one fails as an opaque browser error at the first upload.
- [ ] `allowed_headers = ["*"]` and `max_age_seconds = 3000` are **unchanged**, for SPEC-198 FR-011's
      recorded reason: the header set a presigned `PUT` carries depends on what the signer signed, and
      a missing entry fails the *preflight*, which the browser reports as a generic network error.
- [ ] **A CORS failure presents as an opaque browser error with no AWS text**, so the live check is a
      real upload and a real download from `spa_origin` **re-run after merge 2** (FR-009 §12), not an
      inspection of the applied configuration. Blocking.

### FR-004: The Identity Pool is retired

#### Description:

Delete the pool and everything that exists only to serve it. The browser stopped needing AWS
credentials at SPEC-200; this removes the machinery that minted them. **All of it is merge 1** — none
of it touches an allowlist or an origin, and until it applies the arc's central negative cannot be
observed at all.

#### Acceptance Criteria:

- [ ] `infra/modules/auth/identity-pool.tf` is deleted: `aws_cognito_identity_pool.portal`,
      `aws_cognito_identity_pool_provider_principal_tag.username`, and `time_sleep.wait_for_identity_perms`.
- [ ] `aws_cognito_identity_pool_roles_attachment.portal` (`infra/modules/data/iam.tf`) is deleted,
      `var.identity_pool_id` is removed from `modules/data`, and `module.auth`'s `identity_pool_id`
      output and root `cognito_identity_pool_id` output go with it.
- [ ] The portal role's trust policy (`infra/modules/data/policies/portal-role-trust.json.tftpl`)
      keeps **only** SPEC-196's statement admitting the API Lambda's execution role, with
      `sts:AssumeRole` and `sts:TagSession`. The `cognito-identity.amazonaws.com` federated statement
      and its `identity_pool_id` condition are removed, and `portal-role-trust.json.tftpl` takes no
      `identity_pool_id` template variable.
- [ ] **The deployed trust policy is read back before merge 1 applies** — `aws iam get-role` shows
      SPEC-196's statement live. A plan showing two statements says nothing about what is applied, and
      a role trusted by nobody is a total outage of every API call the product makes. FR-009 §0 holds
      the gate.
- [ ] `cognitoIdentityPoolId` is removed from SPEC-192's runtime document, its type, its
      classification, the ECS task definition, `.env.example` and the GitHub repo variable. SPEC-192's
      key-set agreement test is what fails if one site is missed; a criterion here is that the test
      **does** fail when one site is left behind, verified by removing three of the four and running
      it. `lib/support.test.ts`'s `missingRequiredEnv` case asserting the key is *not* required is
      deleted with the key — a test asserting a deleted key's optionality is the shape FR-005's
      "verified, not re-deleted" criterion forbids.
- [ ] **`lib/amplify.ts` collapses to a single `Amplify.configure` call.** It configures two ways
      today, branching on whether an identity pool id is present, and `isAmplifyConfigured`
      deliberately excludes it. One branch is now unreachable, and an unreachable configuration branch
      is indistinguishable from a live one at a glance.
- [ ] Every documentation site naming the identity pool is corrected or marked: `README.md`,
      `.github/workflows/README.md` (both the variable table and the `tofu output` mapping), and
      `docs/testing/e2e.md`'s *Verifying Scoped Credentials & the `username` Principal Tag*
      section, whose whole procedure is the retired path. That section gets a superseded marker
      pointing at FR-010, **not** a deletion — it is the record of how isolation was originally
      proved.
- [ ] Deploy-role IAM: the `cognito-identity:*` grants added for SPEC-011 are removed in a **separate,
      later** apply than the one that destroys the pool. Removing them in the same apply is the
      deploy-role refresh deadlock CLAUDE.md records — the role loses the permission it needs to
      perform the destroy it is in the middle of.
- [ ] `aws cognito-identity describe-identity-pool` on the **recorded** pool id returns
      `ResourceNotFoundException` (FR-009 §11, after merge 1). A **positive absence**; "the resource is
      gone from the plan" is not the same claim. The id is captured from `tofu output -raw
      cognito_identity_pool_id` **before** merge 1, because merge 1 deletes that output — after it,
      there is nothing left to name.

### FR-005: The browser's credential path is deleted, and `getIdToken` survives

#### Description:

**Most of this was already done, and that is the point of the FR.** SPEC-198 deleted `lib/s3Client.ts`
and three `@aws-sdk/*` dependencies; SPEC-199 deleted `lib/athenaClient.ts`, `lib/glueClient.ts` and
two more; SPEC-200 deleted `lib/sqsClient.ts`, `lib/enqueueFifo.ts` and the sixth. Each of those specs
explicitly left `lib/awsCredentials.ts` and `lib/credentialRetry.ts` standing, because a later port
still needed them. This FR takes the **last two** — and then, because six specs each deleted a piece,
**verifies the whole set is gone rather than assuming it**. A dependency nobody imports is invisible
to every one of those six specs' own tests.

`lib/awsCredentials.ts` exports two functions doing unrelated jobs. `getSessionCredentials` mints
Identity Pool credentials and dies here. `getIdToken` returns the Cognito ID token, which is what
SPEC-195's `apiClient.ts` sends as a bearer, and it must survive — deleting the module whole breaks
every API call in the product.

#### Acceptance Criteria:

- [ ] `getIdToken` moves to **`apps/portal/src/lib/idToken.ts`**, byte-identical in behaviour, with
      its tests. The rename is deliberate: a module named `awsCredentials` that holds only a JWT
      accessor invites exactly the mistake this FR is guarding against, and after SPEC-200 there are
      no AWS credentials in the browser to name. Its one production caller today is
      `lib/enqueueFifo.ts`, which SPEC-200 deletes; the surviving caller is SPEC-195's
      `lib/apiClient.ts`.
- [ ] `apps/portal/src/lib/awsCredentials.ts` is deleted, along with `getSessionCredentials` and its
      `SessionCredentials` type.
- [ ] **The two `getSessionCredentials(true)` call sites that are not credential fetches become
      `getIdToken(true)`**: `features/connections/useConnections.ts` (`refresh` and `reconcile`, behind
      SPEC-052's *Refresh connections* control) and
      `features/file-browser/useSharedSpaceAccessRecovery.ts` (`refreshAccess`, the shared-space
      "Refresh access" affordance SPEC-187 pins as still working). Neither wants credentials — both
      force a token re-mint so a newly-granted `shared_space_k` claim is picked up, and after
      SPEC-196 the API reads those claims from the token the browser presents. **Deleting them
      instead makes both controls silent no-ops**: the button still renders, the spinner still runs,
      the listing still fails, and nothing reports an error. Each is covered by a test that fails if
      the forced refresh is removed.
- [ ] `apps/portal/src/lib/credentialRetry.ts` is deleted (`withCredentialRetry`, `isExpiryError`,
      `EXPIRY_ERROR_CODES`). Its job — refresh once on expiry, retry once — now exists twice on the
      server side of the boundary: SPEC-196's forced re-assume, and SPEC-195 FR-008's single token
      refresh in `apiClient.ts`. **A criterion, not an observation:** zero importers remain,
      enumerated by the sweep, and the SDK error names it matched (`ExpiredToken`,
      `CredentialsProviderError`, …) appear nowhere in `apps/portal/src`.
- [ ] **Verified, not re-deleted:** `lib/s3Client.ts`, `lib/athenaClient.ts`, `lib/glueClient.ts`,
      `lib/sqsClient.ts` and `lib/enqueueFifo.ts` are already absent (SPEC-198/199/200). If any is
      still present, it is a defect in the spec that owned it and is fixed **there**, not absorbed
      here — SPEC-198 FR-012 and SPEC-199/200's own criteria are the *there*.
- [ ] **The two consolidated test files are handled per describe, not per file, and neither is
      "already gone".** SPEC-198 owns `lib/clients.test.ts` and `lib/clientAdapters.test.ts` and names
      an owner for every describe in each. By the time this spec runs, `clients.test.ts` holds one
      describe — `awsCredentials` — and `clientAdapters.test.ts` holds one, the `s3Json` block SPEC-198
      **rewrote** against the document routes because `lib/s3Json.ts` survives. So: this spec moves the
      `getIdToken` half of the `awsCredentials` describe into **`lib/idToken.test.ts`**, deletes the
      `getSessionCredentials` half with its subject, and deletes `lib/clients.test.ts` because its last
      describe has left. **`lib/clientAdapters.test.ts` is neither deleted nor edited here** — deleting
      a file whose surviving subject is still shipping is the exact failure SPEC-198's per-describe
      ownership exists to prevent.
- [ ] **`lib/support.test.ts` is reworked, not merely made to pass.** It holds assertions on all three
      retiring modules — a `credentialRetry` describe block, a dynamic `import('./awsCredentials')`
      inside the dev-unauth behavioural half (already retired by SPEC-198), and the seven-row
      `CALL_SITES` enqueue registry (retired by SPEC-200 — seven rows, verified against `main`, not
      eight: `archive.service.ts` reads `VITE_ARCHIVE_QUEUE_URL` but has no `CALL_SITES` row). What
      must survive is the **registry discipline**, not the rows: PR #467's *"the registry names every
      `VITE_` variable the app reads"* block — an `import.meta.glob('?raw')` sweep over every non-test
      module, derived from the source rather than hand-kept — is the mechanism FR-006 borrows, and it
      must still run. Its `DEV_ONLY` set shrinks with SPEC-198's dev-unauth retirement and its
      `REQUIRED_ENV`/`OPTIONAL_ENV` operands become SPEC-192's `REQUIRED_CONFIG`/`OPTIONAL_CONFIG`;
      deleting it because `lib/env.ts` is gone would take the mechanism with the subject.
- [ ] **All six `@aws-sdk/*` entries are gone from `apps/portal/package.json`** — `client-s3`,
      `lib-storage` and `s3-request-presigner` (SPEC-198), `client-athena` and `client-glue`
      (SPEC-199), `client-sqs` (SPEC-200). Any survivor is removed here and `package-lock.json`
      regenerated. This is the criterion that catches the failure none of those six specs can see: a
      dependency whose last importer went with the spec, left in `package.json` because nothing red
      when it stayed.
- [ ] `npm run build` and the full test suite pass with **no** `@aws-sdk/*` resolution anywhere in
      `apps/portal/src`, and `npm run lint` is green under FR-006's new rule.
- [ ] `aws-amplify` is **not** removed, and no criterion above is written in a way that would require
      it to be. It is what `getIdToken`, `AuthProvider` and sign-in run on.

### FR-006: The lint rule, and the sweep the lint rule cannot do

#### Description:

The arc's tripwire. A review cannot hold this line: a later spec adding one `@aws-sdk/*` import
re-opens the browser's direct AWS surface, and the client environment's whole objection with it.
Two mechanisms, because neither catches the other's failure.

#### Acceptance Criteria:

- [ ] An ESLint `no-restricted-imports` clause in `apps/portal/eslint.config.js` forbids
      `@aws-sdk/*` and `@aws-sdk/**` across `src/**`, in the shape of the existing SPEC-155 and
      SPEC-176 clauses, with a message naming the API as the replacement and SPEC-202 as the reason.
- [ ] **Tests are NOT exempt**, unlike the shared-layer clause. A test mocking `@aws-sdk/client-s3` is
      a test of a code path that no longer exists; the absence of an exemption is the assertion.
- [ ] The rule is **verified by committing a deliberate violation** — one `@aws-sdk/client-s3` import
      in a `src/features/**` file and one in a `src/**/*.test.ts` file, confirming `npm run lint` goes
      red for both, then reverting. Reading the config is not verification: SPEC-176 records a clause
      written in the working rule's shape that resolved onto the right files and caught nothing.
- [ ] A test reads `apps/portal/package.json` (`?raw`, the SPEC-153/186 sweep technique) and asserts
      **no key in `dependencies` or `devDependencies` begins with `@aws-sdk/`**. The lint rule cannot
      see an unimported dependency, and an unimported dependency is how the next one arrives.
- [ ] **The sweep reads `package.json`, never `node_modules`.** `aws-amplify` vendors `@aws-sdk/*`
      packages transitively, so a `node_modules` assertion fails permanently and would be deleted
      within a week — which is the failure mode worth naming, since a deleted guard and a passing one
      look identical in CI.
- [ ] The `@aws-sdk/*` row is removed from CLAUDE.md's Tech Stack table in the same merge, and
      replaced by a line naming the lint rule. Leaving the table stating a retired dependency is how
      a later session re-adds it in good faith.

### FR-007: `infra/modules/app` and `deploy-app.yml` are deleted

#### Description:

CloudFront, the static origin, the OAC, the response-headers policy, and the three prefix-scoped
upload passes with their invalidation.

#### Acceptance Criteria:

- [ ] `infra/modules/app/` is deleted entire (`cloudfront.tf`, `s3.tf`, `outputs.tf`, `variables.tf`)
      and its `module "app"` block removed from `infra/main.tf`. **Its four outputs have exactly four
      consumers**, each removed in the same commit: `static_assets_bucket_arn` →
      `module.base`'s `static_bucket_arn` input (and the deploy-role statement it renders), and the
      three root outputs `s3_static_assets_bucket_name`, `cloudfront_distribution_id` and
      `cloudfront_domain`, which map one-to-one onto `static_assets_bucket_name`,
      `cloudfront_distribution_id` and `cloudfront_domain_name`. SPEC-194 moved
      `local.csp_connect_src` and `local.content_security_policy` out of this module to root; a
      criterion here is that exactly one home for them remains and that deleting the module orphans
      neither.
- [ ] **The five `moved` blocks in `infra/moved.tf` targeting `module.app.*` are deleted in the same
      commit.** A `moved` block naming an address no configuration declares is a **plan-time error**,
      so this one fails loudly rather than silently — but it fails the apply that is mid-destroy,
      which is the worst moment to discover it.
- [ ] `.github/workflows/deploy-app.yml` is deleted. The `S3_STATIC_BUCKET` and
      `CLOUDFRONT_DISTRIBUTION_ID` repo secrets are deleted **after** the workflow, and any other
      workflow referencing them is found by a grep over `.github/workflows/` rather than by memory.
      Their rows in `.github/workflows/README.md` (the secrets table **and** the `tofu output` mapping
      snippet) and in the root `README.md` go with them.
- [ ] The static bucket is emptied and destroyed. Anything wanted from it is copied out **before**
      merge 2, by hand; nothing in this repo reads it after SPEC-192 FR-008's `/config.json` moves
      into the container.
- [ ] Deploy-role IAM: the `cloudfront:*` and static-bucket grants are removed in a **later** apply
      than the destroy, for FR-004's reason.
- [ ] `curl -sSI $CLOUDFRONT_URL` returns a connection or DNS failure, not a 200. **This distribution
      maps `403/404 → /index.html` with a 200**, so a status code proves nothing about whether the
      origin still holds anything — the assertion is that the distribution itself is gone.
- [ ] SPEC-141's decision entries — the three-pass scheme, the "exactly one sync pass carries
      `--delete`" criterion and the accepted stale-root-object orphan class — get superseded markers
      at every site still stating them (FR-011). SPEC-194 retired the orphan class; this spec retires
      the passes.

### FR-008: The final header and `connect-src` state, asserted against the deployed container

#### Description:

The arc's open question 2, settled in SPEC-194 and asserted finally here. Every porting spec shrank
`connect-src`; this is where the end state is measured rather than derived.

**The container's `connect-src` reaches its end state in merge 1**, with the pool it stops naming: a
policy permitting `cognito-identity` after FR-004 has made that call impossible is a live permission
for nothing, and the two changes are one fact. CloudFront's copy is left exactly as SPEC-193 shipped
it and is deleted with the module in merge 2 — narrowing it first would only shrink the rollback.

#### Acceptance Criteria:

- [ ] The deployed `connect-src` on `spa_origin` is exactly: `'self'`, `api_origin`, the S3 endpoint(s) presigned
      bytes go to, `https://cognito-idp.{region}.amazonaws.com`, and `https://{cognitoDomain}`.
      **Nothing else** — the `athena`, `glue`, `sqs` and **`cognito-identity`** hosts SPEC-140
      enumerated are gone, and their absence is a criterion. `cognito-identity` is the one worth
      naming: it looks like a sign-in host and is not one, and leaving it is a live permission for
      the exact call FR-004 exists to make impossible.
- [ ] **The two Cognito hosts are present, and their presence is a criterion in its own right.**
      Amplify still runs in the browser and the code exchange is a `fetch`, not a navigation. This is
      the exact omission that broke fresh sign-in for a day (SPEC-140, 2026-08-04) and it is invisible
      to every signed-in session.
- [ ] The `connect-src` is still **rendered from the task environment**, not baked — two containers
      started with different `PORTAL_CSP_CONNECT_SRC` values produce two different policies
      (SPEC-194 FR-006). One image promotes; a baked list does not.
- [ ] The full SPEC-140 header set is present on a deployed response from `spa_origin`, `Server` is
      absent, and the policy is **enforcing** (`Content-Security-Policy`, never
      `Content-Security-Policy-Report-Only`). **A report-only pass proves nothing about enforcement**,
      so the header name alone is not the criterion: FR-009 §7 pairs it with a blocked fetch, its
      negative control, and a `securitypolicyviolation` event whose `disposition` reads `"enforce"`.
- [ ] **The verification method is stated precisely, because the house rule's blanket form is not
      buildable here.** SPEC-140 recorded that CDP evaluation bypasses page CSP; what it *measured*
      was `script-src` — `new Function` reported allowed under `script-src 'self'`, which is the
      debugger's script-evaluation exemption. `connect-src` is a different check at a different
      moment: it is applied to the fetch, whose client is the document, and the pass condition here is
      a **positive** `securitypolicyviolation` naming `connect-src` — an event a bypassed policy does
      not emit at all, so the row reads FAIL, never a false PASS. The rule's original prescription — a
      *same-origin page script* — is **unsatisfiable on this policy**: `script-src 'self'` blocks any
      inline script, and a `<script>` inserted through the Elements panel is parser-marked
      non-executable and runs nothing at all. FR-009 §7 carries the method and a page-script-only
      escalation for anyone who disputes it.
- [ ] `docs/security-baseline.md` is re-baselined against the new origin: the ZAP alert set is diffed
      **per alert ID**, never by total (SPEC-140's rule — a count that does not move can hide one
      finding clearing and another appearing).

### FR-009: The arc's live checks, as a runnable script

#### Description:

`docs/testing/arc-b-api-container-e2e.md`. Not a prose list: fixtures, exact labels, expected numbers,
in an order someone can execute. It is the acceptance gate for the whole arc and the regression
checklist for any later change to the API or the container.

#### Acceptance Criteria:

- [ ] The script exists at that path, with Prerequisites (the origins, the fixtures, a test user, the
      CLI identity each section needs), numbered steps carrying `- [ ] Pass` boxes, an explicit
      **blocking / non-blocking** marker per section, and an Execution Log — the house shape of
      `docs/testing/e2e.md` and `e2e.md`.
- [ ] **§3 — sign-in from a clean, signed-out profile.** Stated first because it is the state nobody
      exercises: an existing session refreshes against `cognito-idp` and stays healthy while fresh
      sign-in is completely broken. Landing page → Hosted UI → back on `/files` with the username in
      the header, plus a sign-out and re-sign-in. **Blocking.**
- [ ] **§4 — the load-bearing negative, how it is counted, and the window it is counted over.** The
      network panel shows **zero** requests to any AWS host other than: the S3 endpoint,
      `cognito-idp.{region}.amazonaws.com` and the Hosted UI host. **The recording must span §5, §7
      *and* §8**, and §4's counting step is performed once §8 has finished — the `sqs.` row is
      otherwise counted over a window containing no enqueue at all, which is a vacuous pass on the
      exact surface SPEC-200 moved. **This section runs after merge 1 and only after merge 1**: while
      the Identity Pool exists the `cognito-identity.` row cannot read zero, because `lib/amplify.ts`
      configures `identityPoolId` and `getIdToken`'s own `fetchAuthSession()` vends credentials.
      Counted by the network panel's filter box, per host, with the count recorded — not by eye, and
      the catch-all row is given as a literal filter string with `-`-prefixed exclusions rather than
      left for the tester to invent. Two things make it non-vacuous, and both are criteria:
      **(a) a positive control** — the same session must record a non-zero API call count and at least
      one presigned S3 `GET` and one `PUT`, because a negative over an app that made no calls passes
      trivially; **(b) each S3 request is asserted to be *presigned*** — an `X-Amz-Signature` query
      parameter and **no** `Authorization` header and **no** `x-amz-security-token` header. A
      SigV4-header-signed S3 request is the browser holding credentials, which is precisely what this
      spec claims is gone, and it is indistinguishable from a presigned one at the host level.
      **Blocking.**
- [ ] **§5 — one exercise of every ported surface**: the file browser (list, head, create folder,
      single-file copy/move/delete), a presigned upload and download **with visible progress**
      (SPEC-198's `XMLHttpRequest` residual — a progress bar stuck at 0% is the symptom), the free-name
      route, a saved query loaded and saved, a Data Explorer exploration, an Athena query with paged
      results, and the notifications inbox. **Blocking.**
- [ ] **§6 — deep link, return path and session expiry.** A deep link while signed out returns to that
      link after sign-in, repeated in **private browsing** (the state `lib/returnPath.ts` degrades in —
      `sessionStorage` is available but per-window, so the assertion is what the user actually lands
      on, not that storage exists). Then expiry: **Arc B has two clocks, not three** — the Cognito
      session and the ID token's own lifetime — because the third (the BFF session cookie) is
      deferred. The check is that a request made with an expired ID token returns 401 and SPEC-195
      FR-008's single refresh recovers it transparently, and that a genuinely ended Cognito session
      lands the user on sign-in rather than on a generic error. Staged by clock skew or by an
      admin-initiated global sign-out, both named in the script. **Blocking.**
- [ ] **§7 — CSP enforcing, with a negative control and a method that actually runs.** A `fetch` to a
      host absent from `connect-src` raises a **`securitypolicyviolation` event** whose
      `effectiveDirective` is `connect-src` and whose `disposition` is `"enforce"`; the negative
      control is a `fetch` to a same-origin path succeeding in the same run. Both halves required: a
      blocked fetch alone is indistinguishable from a broken network, and a policy that is inert
      reports no violations whether or not anything occurred. **The script states why its method
      executes** — an inline `<script>` is blocked by `script-src 'self'`, and one inserted through
      the Elements panel is parser-marked non-executable and runs nothing, so the criterion is a
      **positive violation event** rather than the absence of a response. **Blocking.**
- [ ] **§8 — one request per plane, enqueued through the API, with its notification received.** Eight
      planes (shared-space, notifications, table-build, table-share, data-quality, file-send, archive,
      file-ops), each with a named minimal fixture, the expected notification text, and the
      `logs/service={plane}/` record carrying a real `env` and a real build sha. The archive plane's
      entry is the **archive** direction only — a restore is 3–5 billed hours and belongs to that
      arc's own script. **Blocking.**
- [ ] **§9 — Safari, and 400px.** Safari is the discharging pass: the user browses in Safari and a
      Chromium run corroborates without discharging (Safari also refuses to evaluate a report-only
      policy naming no reporting endpoint, which a Chromium harness cannot surface). The 400px pass
      notes that **400px is not reachable by window resize on macOS**, and that `resize_window`
      reports success while changing nothing the page sees — use the device toolbar and **assert on
      `matchMedia`**, recording the matched query rather than a screenshot. **Blocking.**
- [ ] **§10 — the rollback rehearsal**, per FR-001's last criterion: reach the app on the CloudFront
      origin, confirm it loads and completes one API call, and record that this is a CloudFront-served
      HEAD bundle talking to the API — not a pre-arc portal. Run **after merge 1 and before merge 2**,
      which is the only window in which it is both meaningful and possible. **Blocking.**
- [ ] **§11 — the merge-1 consequences**: FR-010's IAM simulation against the deployed roles,
      `describe-identity-pool` on the recorded id returning not-found, `get-role` showing one trust
      statement, and the lint rule reddening on a deliberate violation in both a feature file and a
      test file. **Blocking.**
- [ ] **§12 — the merge-2 consequences**, and only those: `get-distribution` on the recorded id
      returning `NoSuchDistribution`, §3 re-run against the narrowed Cognito lists, and §5 steps 2–3
      (a real presigned upload and download) re-run against the narrowed bucket CORS — the two
      allowlists merge 2 touches, each re-exercised by the check that can actually detect its
      narrowing. **Blocking.**
- [ ] **What nothing offline can prove is named in the script**: the presigned URL actually being
      honoured by S3 from the container origin (bucket CORS, which unit tests cannot reach), the
      enforcing CSP, the Cognito redirect allowlist agreeing with the deployed `appUrl`, the ALB
      health check keeping a broken task out of rotation, and Lake Formation filtering applied to the
      **assumed** role rather than to the API's own.
- [ ] Every other arc's owed live checks are listed with a one-line disposition: which are invalidated
      by the origin change and must be re-run (anything asserting a URL, a CSP or a browser AWS call),
      and which are not (anything asserting a Lambda, a state machine or a log record). This spec does
      not run them; leaving them unclassified is how a discharged check silently becomes stale.

### FR-010: The IAM policy simulation, against the deployed roles

#### Description:

The arc's central claim is that not one policy was rewritten. This is where that is measured, after
the Identity Pool is gone, against what is actually deployed.

#### Acceptance Criteria:

- [ ] `aws iam simulate-principal-policy` runs against the **deployed** portal role with
      `--context-entries` supplying `aws:PrincipalTag/username` and the `shared_space_k` slot tags,
      reproducing **SPEC-196's table row for row**. Every row returns the same decision as it did
      pre-retirement. A changed row is a defect in this spec.
- [ ] **The three role ARNs are read from the deployed account, not from a root output — because none
      of them is one.** `portal_role_arn` is a *local* in `infra/main.tf`, and the API Lambda's and
      the SPA task's roles are internal to SPEC-193's modules. FR-009 §11 reads the portal role from
      the API Lambda's own `PORTAL_ROLE_ARN` environment variable (SPEC-196's required var), the API
      role from the same `get-function-configuration` response, and the SPA task role from the
      running service's task definition. A `tofu output -raw portal_role_arn` is a hard stop inside a
      blocking section, and reading the deployed value is what FR-010 is asking for anyway.
- [ ] **Every denial is paired with an `allowed` control on the same bucket or catalog.** An
      `implicitDeny` alone cannot distinguish an ungranted action from a wrong resource ARN — this
      repo learned that on a mistyped `dat-prod-athena-admin`.
- [ ] The **API Lambda's execution role** is simulated separately: `sts:AssumeRole` on the portal role
      → `allowed` (control); `s3:GetObject` on a user-space key → `implicitDeny`. The second is the
      one worth the trouble — the API must reach data **only** through the assumed role, and a stray
      direct grant would make every route work while silently bypassing the tag.
- [ ] The **SPA task role** holds no data grant. A role with no policies returns `implicitDeny` for
      everything with no control available, so **this one is not proved by simulation**: the assertion
      is `list-attached-role-policies` and `list-role-policies` both returning empty. Naming why the
      technique changes is the criterion — an unpaired `implicitDeny` presented as a pass is the
      failure mode the rest of this FR exists to avoid.
- [ ] The portal role's trust is verified by `get-role`: exactly one statement, naming the API
      Lambda's execution role, with `sts:AssumeRole` and `sts:TagSession`.
- [ ] The results table lands in FR-009's script with a **date and a run reference**, in the shape
      `e2e.md` §0 uses, so a later session can re-run it rather than re-derive it.

### FR-011: The documentation reversal, as the arc closer

#### Description:

"No backend" is the premise this repo was built on and it is stated in eight places. Reversing it in
one and leaving seven is worse than reversing it in none, because the seven read as current.

#### Acceptance Criteria:

- [ ] `docs/architecture.md` is rewritten where it asserts the old premise: **§System Overview**
      (line ~32, "no backend server. All AWS calls come from the browser"), the "deliberate, scoped
      exceptions to *no backend*" framing at ~42 and ~128 (the control planes are no longer
      exceptions — they sit beside an API), and **§Known Constraints** (~679, "No backend / API
      proxy"). New sections describe the API, the container origin and the two credential planes.
- [ ] `docs/decisions.md`'s **No backend** entry gets an in-place superseded marker naming SPEC-202 —
      **not a deletion**. The reasoning is why the codebase looks the way it does and a later reader
      needs it. Same treatment for the SPEC-140 entry (its CloudFront distribution, its
      `connect-src` derivation and its "there is no backend" sentence) and the SPEC-141 entry
      (FR-007).
- [ ] **SPEC-140's CSP *verification technique* is corrected, not merely superseded**, in
      `decisions.md` and in CLAUDE.md's Key Decisions line. It reads "verify with a same-origin page
      script + a negative control (CDP eval bypasses page CSP)". What was measured was `script-src`
      (`new Function` reported allowed) — the debugger's script-evaluation exemption — and the
      prescription it produced is unsatisfiable against a policy carrying `script-src 'self'`, since
      an inline script is blocked and an Elements-panel-inserted `<script>` is parser-marked
      non-executable. The corrected rule is FR-008's: assert a **positive** `securitypolicyviolation`
      event with `effectiveDirective: "connect-src"` and `disposition: "enforce"`, plus a
      same-origin negative control. Left as it stands, the arc's one enforcement check has no
      runnable method and its failure reads as a broken snippet rather than as a finding.
- [ ] `docs/process.md` (~302, "No backend (browser → AWS direct) except where a decision record
      explicitly reverses it") is corrected.
- [ ] **CLAUDE.md sweep**, four places: the **Project Overview** paragraph ("**No backend** — the SPA
      calls AWS directly with scoped credentials"), the **No backend** Key Decision line, the **Out of
      Scope** line ("No backend/API layer"), and the Tech Stack table's `@aws-sdk/*` row (FR-006).
      The Out-of-Scope line is replaced by its successors — no *second* API, no in-browser AWS SDK —
      rather than simply struck, because a removed fence reads as permission.
- [ ] `decisions.md` gains this spec's own entries, then **one line each** in CLAUDE.md's Key
      Decisions: (1) *the cutover order and what the rollback requires*; (2) *the Identity Pool is
      retired and that is not a change to how anyone signs in* — the conflation this spec's Overview
      exists to prevent; (3) *the `@aws-sdk/*` ban is a lint rule plus a `package.json` sweep, and the
      sweep reads `package.json` because Amplify vendors the SDK*.
- [ ] The `ARCS.md` arc entry is updated with what the arc actually found, its open questions marked
      answered, and the RE-SCOPE block folded into the entry rather than left as a preamble contradicting
      the text below it.
- [ ] **Nothing user-facing changed in this spec.** The Help sweep is recorded as performed and
      skipped, explicitly — no guide, label, route or flow moves. (SPEC-198's dev-unauth retirement
      and SPEC-190/191's file-ops surface own the arc's user-visible changes.)

---

## Data Model

```ts
// apps/portal/src/types/runtimeConfig.types.ts — the arc's end state: TEN keys.
// SPEC-192's classification group (a) is the authority; this spec removes exactly
// one entry from OPTIONAL_CONFIG and adds nothing.

export const REQUIRED_CONFIG = [
  'apiBaseUrl',              // optional in SPEC-192, required from SPEC-197
  'appUrl',
  'awsRegion',               // stays: SPEC-198 froze the service signatures that take a region
  'userSpaceBucket',         // stays, same reason
  'cognitoUserPoolId',
  'cognitoUserPoolClientId',
  'cognitoDomain'
  // athenaWorkgroup — removed by SPEC-199
] as const;

export const OPTIONAL_CONFIG = [
  'environment',
  'maxUploadBytes',
  'sharedSpaceBucket'        // stays, same reason as awsRegion / userSpaceBucket
  // cognitoIdentityPoolId — REMOVED by SPEC-202 (FR-004)
  // the seven queue URLs      — removed by SPEC-200
] as const;

// The four Cognito keys stay: Amplify runs in the browser for the whole arc, and
// the region and both bucket names stay with them. A type declaring a seven-key
// browser document is the shape SPEC-192 explicitly names as wrong.

// apps/portal/src/lib/idToken.ts — the one survivor of lib/awsCredentials.ts
export function getIdToken(forceRefresh?: boolean): Promise<ServiceResult<string>>;
```

---

## API / Interface Contract

```js
// apps/portal/eslint.config.js — FR-006. Verified by committing a violation in
// BOTH a feature file and a test file, never by reading this block.
{
  files: ['src/**/*.{ts,tsx}'],
  rules: {
    'no-restricted-imports': ['error', {
      patterns: [{
        group: ['@aws-sdk/*', '@aws-sdk/**'],
        message:
          'The browser makes no AWS calls (SPEC-202). Go through the API — lib/apiClient.ts — ' +
          'or, for bytes, a presigned URL the API minted. aws-amplify is unaffected.'
      }]
    }]
  }
}
// No test-file exemption, deliberately: a test mocking @aws-sdk/client-s3 tests a
// code path that no longer exists.
```

```bash
# Both ids are captured BEFORE the merge that deletes their root output, and
# recorded in FR-009's Execution Log. After the merge there is nothing left to
# name and the assertion cannot be made at all.
POOL_ID=$(tofu -chdir=infra output -raw cognito_identity_pool_id)      # before merge 1
DIST_ID=$(tofu -chdir=infra output -raw cloudfront_distribution_id)    # before merge 2

# FR-004's last criterion — a positive absence, not "gone from the plan".
aws cognito-identity describe-identity-pool --identity-pool-id "$POOL_ID"
# -> ResourceNotFoundException

# FR-007 — the distribution maps 403/404 -> /index.html with a 200, so a status
# code proves nothing. Assert the distribution itself is gone.
aws cloudfront get-distribution --id "$DIST_ID"   # -> NoSuchDistribution
```

## Environment Variables

No new variable.

**Removed (merge 1):** `VITE_COGNITO_IDENTITY_POOL_ID` and its runtime key `cognitoIdentityPoolId`,
from `.env.example`, SPEC-192's `OPTIONAL_CONFIG`, the ECS task definition and the GitHub repository
variable.

**Removed (merge 2):** the Terraform variable `app_url` — root and all three modules — and with it
`TF_VAR_app_url` from **both** env blocks of `deploy-infra.yml`.

**Changed in value, not in key (merge 2):** the repository variable `VITE_APP_URL` is re-pointed from
the CloudFront domain to `spa_origin`. That kind of change reaches production silently, and after
`deploy-app.yml` is deleted its one remaining consumer is `security.yml`'s ZAP target — where a stale
value scans a dead host and reports a clean baseline rather than failing.

## File & Folder Structure

```
infra/
├── modules/app/                     # DELETED (FR-007)
├── modules/auth/identity-pool.tf    # DELETED (FR-004)
├── moved.tf                         # the five `module.app.*` blocks DELETED (FR-007)
├── main.tf outputs.tf variables.tf  # module "app" + its 4 consumers DELETED; `variable "app_url"`
│                                    #   DELETED and its 3 module blocks take local.spa_origin
└── modules/data/policies/portal-role-trust.json.tftpl   # one statement remains

.github/workflows/deploy-app.yml     # DELETED (FR-007)
.github/workflows/deploy-infra.yml   # TF_VAR_app_url removed from BOTH env blocks (FR-002)

apps/portal/src/lib/
├── awsCredentials.ts                # DELETED — getIdToken moves out (FR-005)
├── idToken.ts                       # NEW (+ idToken.test.ts, from clients.test.ts's surviving half)
├── clients.test.ts                  # DELETED — its last describe leaves with getIdToken
├── clientAdapters.test.ts           # UNTOUCHED — holds SPEC-198's rewritten s3Json describe
└── credentialRetry.ts               # DELETED
#   s3Client / athenaClient / glueClient / sqsClient / enqueueFifo are already gone
#   (SPEC-198/199/200). FR-005 ASSERTS their absence; it does not delete them.

apps/portal/eslint.config.js         # the @aws-sdk/* clause (FR-006)

docs/testing/arc-b-api-container-e2e.md   # NEW (FR-009)
```

---

## Implementation Phases

### Phase 1: The script, and the preconditions it rests on

- `docs/testing/arc-b-api-container-e2e.md` written in full, with blocking markers.
- **Verify, do not add**, SPEC-193 FR-006's three additive changes: both origins on the Cognito app
  client, `api_origin` in CloudFront's `connect-src`, both origins in the API's CORS list. A missing
  one is fixed in SPEC-193.
- Capture and record `cognito_identity_pool_id` and `cloudfront_distribution_id` — merge 1 deletes
  the first output and merge 2 the second.
- Read back the deployed portal-role trust policy (`get-role`): SPEC-196's statement must be live
  before merge 1 removes the federated one.

### Phase 2: Merge 1 — the retirement, with the rollback left intact

- FR-004's Terraform deletions, the runtime key, `lib/amplify.ts`'s collapse to one `configure` call.
- FR-005's browser deletions and the `getIdToken` split; FR-006's lint rule and dependency sweep, each
  verified by a deliberate violation.
- FR-008's **container** `connect-src` end state, which loses `cognito-identity` with the pool.
- Nothing here touches an allowlist or an origin: CloudFront still serves, its `connect-src` still
  names the API, and both narrowable lists still name both origins.
- Deploy-role `cognito-identity:*` grant removal held back to a **later** apply (FR-004).

### Phase 3: Run the script

- §0 → §11 against `spa_origin`, Chrome first for reach, **Safari for the discharge**.
- Record every result in the Execution Log. A blocking item that is not recorded is not passed.
- §4 is only now satisfiable, and §10's rollback rehearsal runs here — after merge 1, while
  CloudFront is still the rollback.

### Phase 4: Merge 2 — the narrowing and the destroy

- FR-002's Cognito narrowing, `variable "app_url"`'s deletion, `TF_VAR_app_url` out of both
  `deploy-infra.yml` env blocks, and the `VITE_APP_URL` repository variable re-pointed.
- FR-003's bucket CORS narrowing to `spa_origin` and `["GET","PUT"]`.
- FR-007's module and workflow deletion, the five `moved` blocks, and the static bucket emptied and
  destroyed.
- Deploy-role `cloudfront:*` and static-bucket grant removals held back to a **later** apply (FR-007).
- **After this applies there is no rollback.** Merge 2 does not open until every blocking item from
  Phase 3 is recorded PASS.

### Phase 5: Verification

Real invocations against the retired state. Half of what this spec claims is about what is *absent*,
and an absence is only observable once the thing is gone — which is why the verification splits the
same way the merges do.

- **After merge 1** (the script's §11): FR-010's simulation row for row against SPEC-196's table;
  `describe-identity-pool` on the recorded id → `ResourceNotFoundException`; `get-role` → one trust
  statement; the lint rule red on a deliberate violation in a feature file and in a test file.
- **After merge 2** (the script's §12): `get-distribution` on the recorded id →
  `NoSuchDistribution`; §3 re-run against the narrowed Cognito lists; §5 steps 2–3 re-run against the
  narrowed bucket CORS. Those two allowlists are the only things merge 2 changes that a browser can
  observe, and each is re-exercised by the check that can detect its narrowing.
- **Not observable, record as owed rather than discharged:** anything about the target-environment
  arc (no IdC, no Entra, no BFF ships here), and the behaviour of the container under real
  concurrency or a task failure — the availability work `transition_plan.md` §4.6 names is deferred.

### Phase 6: Completion ritual — the ARC's, not this spec's

- `Status: Completed`; the `INDEX.md` row; the delivery doc at
  `docs/spec-delivery/SPEC-202-retiring-cloudfront-and-the-identity-pool.md`.
- **FR-011 in full** — `architecture.md`'s reversal, the `decisions.md` superseded markers at every
  site, `process.md`, the CLAUDE.md four-place sweep, this spec's own `decisions.md` entries and
  their one-line digests, and the `ARCS.md` entry.
- A row in `docs/component-inventory/` for `lib/idToken.ts`, and the removal of the rows for every
  module FR-005 deletes — the inventory stating a deleted module is how a later session imports it.
- The Help sweep: **nothing user-facing changed**, recorded explicitly and skipped.
- Prune CLAUDE.md's `## Specs` section of everything the arc made stale, per the doc-size guardrail.

---

## What the target-environment arc inherits

Deferred, not abandoned. Each item below was designed in this arc's first draft or in
`transition_plan.md` and taken back out when the arc was re-scoped on 2026-08-18 to keep Cognito
sign-in exactly as it is. A later session starts here.

**Read `docs/transition_plan.md` §3.5, §4.6 and §4.7 rather than this section.** They carry the
reasoning; this is the index and the supersession map.

| Inherited | Supersedes, when it arrives |
|---|---|
| **The BFF** — the server performs the OIDC code exchange and holds the tokens; the browser gets an opaque `httpOnly`, `Secure`, `SameSite=Lax` cookie and nothing else. The SPA never constructs an IdP URL. | SPEC-195's *"it is a verifier, not an OIDC client"*, and SPEC-195 Premise 2 (*no ambient credential, so no CSRF surface*) — a cookie re-opens CSRF, `SameSite`, and turns the **two-origins-one-registrable-domain** preference back into a requirement. SPEC-197 FR-010's *CORS without credentials* becomes CORS **with** credentials. |
| **The session store and its three clocks** — the refresh token in DynamoDB under a customer-managed KMS key with a TTL; session expiry checked **on read**, because TTL deletes only within a few days and an expired-but-undeleted item is still returned. | This spec's FR-009 §6, which records **two** clocks (the Cognito session and the ID token's lifetime). The third is the cookie. |
| **PKCE, `state`, and the login transaction** held server-side; the server-side return path. | `lib/returnPath.ts`, which Arc B left exactly as it is — including its private-browsing degradation, which FR-009 §6 exercises rather than fixes. The arc's open question 3 was **voided**, not answered. |
| **Entra ID as the identity provider.** | The four Cognito keys SPEC-192 classifies as permanent browser configuration, and SPEC-195's Cognito-shaped defaults (`token_use: id`, `cognito:username`). SPEC-195's provider block is configuration precisely so this is a config change and not a rewrite — but the *claims* move, and `transition_plan.md` §6.1 calls the federated username claim the highest-consequence detail in the migration. |
| **Identity Center and trusted identity propagation** — the jwt-bearer exchange (**single-use**: exchange once at login, then the `refresh_token` grant), `CreateTokenWithIAM`, the carrier role, the identity context on the assumed role, and Lake Formation enforcing against an IdC identity. | SPEC-196's `session_tags()` — the *tag source* changes, not the call site, which is the shape FR-001 there was built for. **Identity Center is not a login provider for a web application**; Entra authenticates the users, IdC propagates their identity into AWS. Re-reading it as a sign-in flow builds something that cannot work. |
| **The `error.stack` interaction, in its larger form.** SPEC-195 FR-007 scrubs the API's exception paths because it handles a user's ID token. A token-**minting** service handles access and refresh tokens it created, and `log-foundry`'s `end_event` attaches `traceback.format_exception` to every failed span. | Nothing — it **extends** SPEC-195 FR-007's `decisions.md` entry rather than reversing it. The existing file-contents exemption does not cover it, and did not cover Arc B's case either. |
| **The machine-facing door** — a non-human authorizer, credential issuance, the may-this-client-act-as-X model, rate limiting. | Nothing. SPEC-200 landed the `{actor, delegated_by, assurance}` contract and every plane accepts it, precisely so the door needs no rework; `delegated_by` is null for a human at a keyboard and stays that way until this arrives. |
| **Availability**: autoscaling, capacity providers, a WAF, and the multi-AZ obligations a load balancer brings (`transition_plan.md` §4.6). | Nothing. Deferred by the arc, and the portal has run behind one ALB since SPEC-193 without them. |
