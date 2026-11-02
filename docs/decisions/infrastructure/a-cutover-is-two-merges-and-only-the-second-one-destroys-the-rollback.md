---
type: Decision
title: "A cutover is two merges, and only the second one destroys the rollback (SPEC-202)"
description: "**Origins are admitted ADDITIVELY** and narrowed only at the cutover — an allowlist naming one origin makes the other a rollback nobody can exercise. **A cutover is TWO merges:** the retirement, which touches nothing serving the app, then the live checks **while the rollback still works**, then the narrowing and the destroy. A half-finished retirement looks exactly like a finished one, so a deleted resource is proved gone **positively** (`NoSuchDistribution`, not \"absent from the plan\") and a grant outlives its resource by one apply — where SPEC-202 found the next trap: the Checkov accept list was holding that grant's own findings open, so removing it made both acceptances stale, which is a hard error."
---

Every spec in the API-and-container arc was **additive** — two front doors, two credential paths,
each step revertible because the thing it replaced was still running. The retirement is the
subtraction, and subtraction is where this repo's characteristic failure lives: nothing goes red when
a dead distribution keeps answering, nothing goes red when the browser holds credentials it no longer
uses, and nothing goes red when a `connect-src` still names four AWS hosts no request goes to. **A
half-finished retirement looks exactly like a finished one.**

So the shape is two merges whose difference is whether they can be undone.

- **Merge 1 retires, and touches nothing that serves the app.** The Identity Pool, the browser's last
  credential modules, the lint rule, the container's narrowed `connect-src`. CloudFront still ran,
  its `connect-src` still named the API, the callback and logout lists still named both origins and
  both buckets' CORS still allowed both — so the front door could still be moved back and the app
  would work.
- **Then the live checks run, with that rollback intact.** This is the whole reason for the split:
  the arc's load-bearing negative cannot be observed while the Identity Pool exists (see the identity
  register), and the rollback rehearsal is only meaningful in the window where the old origin still
  serves.
- **Merge 2 narrows the three allowlists and destroys the distribution.** After it there is no
  rollback at all: no origin serves the old front door and no allowlist admits it.

**What the rollback actually was, stated because it is easy to overstate.** The rehearsal loaded the
app from the CloudFront domain and completed a real cross-origin API call — a CloudFront-served
**HEAD** bundle talking to the API. It did **not** restore browser-direct AWS, because that code was
already gone from HEAD and so was the pool that backed it. A rollback of the front door is not a
rollback of the arc.

**A grant outlives the resource it covers by one apply, deliberately.** The deploy role's
`cloudfront:*` and static-bucket statements were left standing through the destroy and removed in the
next change, because removing a grant in the same apply that destroys what it covers is the refresh
deadlock [`deploy-role-iam.md`](../../../infra/info/deploy-role-iam.md) records. The follow-up found
the trap that ordering hides: **the accept list was holding the grant's own findings open.** Both
accepted Checkov plan findings on the deploy role were that `cloudfront:*` statement, so removing it
made both acceptances match nothing — and a stale accept is a hard error, which would have failed
the grant-removal PR on its own gate. Measured with the pinned scanner rather than argued, which
also corrected the accept list's stated reason: an action AWS defines no resource type for raises
neither check (cloudsplaining strips it first), so `cognito-idp:CreateUserPool` and the Lake
Formation account actions were never co-causes. **What raises them is an action that could have been
scoped and was not.** The list is empty now and every IAM finding on the plan blocks.

**The waiver is part of the record.** Merge 2 was taken with five checks open — a fresh sign-in from
a clean profile, the deep-link return path, the archive plane's row, 400px, and the first half of
membership propagation — recorded as *waived, not passed*. The one that gates that merge
specifically is the fresh sign-in, because merge 2 narrows the Cognito lists and **a broken fresh
sign-in is invisible to every signed-in session**; the re-run happens after the irreversible step
instead of before it, which is the risk that was accepted. Whether it has been run is
[`owed.md`](../../testing/owed.md)'s to say, not this entry's — and that ledger, not the deleted arc
script, is where the instruction lives.

A deleted resource is proved gone positively (`NoSuchDistribution`), not by its absence from the plan.

## History

### 2026-09-02

- **Settled:** SPEC-202.
