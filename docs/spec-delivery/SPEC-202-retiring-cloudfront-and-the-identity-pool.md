# Completed Spec — SPEC-202: Retiring CloudFront & the Identity Pool, and the Arc's Live Checks

The subtraction that closes Arc B. Two merges, then a follow-up apply, then this ritual.

- **Merge 1** — [#563](https://github.com/agriffi10/data-analysis-prototype/pull/563), 2026-08-31:
  the retirement, with the rollback deliberately left intact.
- **Merge 2** — [#608](https://github.com/agriffi10/data-analysis-prototype/pull/608), 2026-09-02:
  the narrowing and the destroy. After it there is no rollback.
- **The follow-up apply** — [#614](https://github.com/agriffi10/data-analysis-prototype/pull/614),
  2026-09-02: the deploy role's grants on the destroyed resources, removed one apply later.

## What was completed?

**The Identity Pool is gone, and no one's sign-in changed.** The pool, its principal-tag map, its
role attachment and the portal role's `AssumeRoleWithWebIdentity` trust statement (two statements to
one), plus `cognitoIdentityPoolId` from the runtime document. The User Pool, Managed Login v2, the
Hosted UI round trip and the ID token are untouched — reading this as "Cognito is retired" sends the
next reader looking for a change that does not exist.

**The browser's credential layer is deleted.** `lib/awsCredentials.ts` became `lib/idToken.ts` with
one export, `getIdToken` — named for a JWT rather than for credentials, because there are no AWS
credentials in the browser to name and a module called `awsCredentials` invites putting some back.
`credentialRetry.ts` went with it. The `@aws-sdk/*` ban is now a lint rule declared in every clause
that governs `src/`, **plus** a sweep over `package.json`, because a dependency nobody imports is
invisible to an import rule.

**CloudFront is destroyed.** The distribution, its OAC, the SPEC-140 response-headers policy, the
static-assets bucket, `infra/modules/app` entire, `deploy-app.yml` with its three prefix-scoped
passes and its `/*` invalidation, and the five `moved` blocks that named the module. The container
behind `spa_origin` is the only front door.

**The three allowlists are narrowed** to one deployed origin each — Cognito's callback and logout
lists, the API's CORS `allow_origins`, and both buckets' CORS (each keeping `localhost:5173`, which
is dev, not a second deployed origin).

**The arc's live checks ran between the merges**, which is the whole reason there were two. Results
are in [`sessions.md`](../testing/sessions.md); what did not run is in
[`owed.md`](../testing/owed.md) → *SPEC-202*.

### Deliberate deviations

- **Merge 2 was taken with four checks waived, not passed** (user decision, 2026-09-01): the fresh
  sign-in from a clean profile, the deep link and its two clocks, the archive plane's row, and
  400px. The first is the one that gates merge 2 specifically — it exercises the narrowed Cognito
  lists, and a broken fresh sign-in is invisible to every signed-in session. The arc's §12 re-runs
  it *after* the irreversible step instead of before it; that is the risk that was accepted, and it
  is still owed.
- **The Safari half of the responsive check was retired at its premise**, not left owed: the
  audience has no Safari (user decision, 2026-09-01).
- **FR-008 AC4 was corrected rather than the deployment.** It asked for `Server` to be absent;
  nginx cannot strip it without a third-party module, and that is one of SPEC-194's three recorded
  divergences. The criterion was written before the container was measured.
- **The grant retirement became its own PR**, and found a trap the spec did not forecast (below).

## What changed from earlier specs?

- **SPEC-011/013/056's ABAC model is unchanged and was re-proved.** FR-010 re-ran SPEC-196's IAM
  simulation against the deployed roles after the retirement, row for row: `alice/` allowed, `bob/`
  implicit-deny, each denial paired with an allowed control on the same bucket. **No row moved.**
- **SPEC-140's entry is superseded and its CSP *verification technique* corrected.** The old rule —
  "verify with a same-origin page script, because CDP evaluation bypasses page CSP" — generalised
  from a `script-src` measurement and is unsatisfiable under `script-src 'self'`. Measured
  2026-08-31: CDP evaluation is exempt from `script-src`, **not** from `connect-src`. The rule is
  now a **positive** `securitypolicyviolation` (`effectiveDirective: "connect-src"`,
  `disposition: "enforce"`) plus a same-origin negative control in the same run.
- **SPEC-141's three-pass scheme is retired outright**, with the two findings that outlive it kept:
  `--exclude` *protects* keys from `--delete`, and the bug was the browser cache rather than the CDN.
- **SPEC-192's key set went from six wiring sites to five** — `deploy-app.yml` carried two of them.
  The count went **down by a deletion**, which is the direction that hides a gap, so the container
  entrypoint's two lists gained a real comparison in merge 1 rather than inheriting a claim that a
  deleted workflow's tests had been covering them.
- **SPEC-198's `s3Client` era ends**: the dev-unauth path and the browser's last AWS client are both
  gone, so `lib/env.ts` is the whole `VITE_` allowlist.

## The trap the follow-up apply found

The deploy role's `cloudfront:*` and static-bucket grants were left standing through the destroy on
purpose — removing a grant in the same apply that destroys what it covers is the refresh deadlock
`infra/info/deploy-role-iam.md` records. Removing them one apply later turned out to be blocked by a
gate nobody had connected to the grant: **both accepted Checkov plan findings on the deploy role
were that `cloudfront:*` statement**, so deleting it made both acceptances match nothing, and a
stale accept is a hard error. The grant-removal PR would have failed its own plan job.

Measuring it against the pinned scanner rather than arguing it also corrected the accept list's
stated reason. `cognito-idp:CreateUserPool`, `logs:DescribeLogGroups` and the Lake Formation
account-level actions were **never** co-causes: both checks wrap cloudsplaining, which strips an
action it classifies as taking no resource type before either one counts. What raises them is an
action that **could have been scoped and was not** — CKV_AWS_355 for any such action, CKV_AWS_290
for the write subset. The list is empty now and every IAM finding on the plan blocks.

A second correction, same class: the accept list's forward-looking note named CKV_AWS_356 /
CKV_AWS_111 / CKV_AWS_49 as what a new wildcard grant would fire. Those are the
`aws_iam_policy_document` **data-source** twins and cannot evaluate an `aws_iam_role_policy` at all.

## One obligation that dissolved rather than being discharged

`CLAUDE.md` carried a note saying this spec must re-point SPEC-206's `SenderId` boundary, "which
still names the portal role it retires". **This spec does not retire the portal role** — it retires
the Identity Pool, and the role is *reused* by the API, which is exactly why no permission policy
had to change. The boundary needed nothing; the deployed writer's
`NOTIFICATIONS_UNTRUSTED_SENDER_ID` equals the live role's unique id, checked 2026-09-02. The note
was written from a premise that reads "the credential path is retired" as "the role is retired".

## Verification

**Local:** `tofu fmt -check -recursive` and `validate`, `ruff`, `mypy`, `pytest lambdas/` (2431
passed, coverage 89.19%), `scripts/validate_docs.py`, and the gate script exercised both ways with
the empty accept list — a clean plan reports 0 unaccepted, and the pre-retirement policy (the
"someone re-added the grant" mutation) reports 2 and fails under `block`.

**Against the account, 2026-09-02, CLI only** — every absence proved positively:
`get-distribution` → `NoSuchDistribution`; `head-bucket` on the static bucket → 404;
`list-identity-pools` → `[]`; the Cognito callback and logout lists, the API's CORS and both
buckets' CORS each naming one deployed origin; the served header set and `connect-src` carrying no
`cognito-identity.`, `athena.`, `glue.` or `sqs.`; `/config.json` with no `cognitoIdentityPoolId`;
and the deploy role's inline policy down to 22 statements. Full record in
[`sessions.md`](../testing/sessions.md).

**Deferred to a browser:** the fresh sign-in and the three other waived checks —
[`owed.md`](../testing/owed.md) → *SPEC-202*.

**Help sweep: performed and skipped.** Nothing user-facing changed — no guide, label, route or flow
moves. The arc's user-visible changes belong to SPEC-198's dev-unauth retirement and SPEC-190/191's
file-operations surface.
