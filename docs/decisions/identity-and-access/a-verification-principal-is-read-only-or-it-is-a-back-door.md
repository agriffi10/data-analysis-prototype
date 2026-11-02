---
type: Decision
title: "A verification principal is read-only, or it is a back door"
description: "The verification role is read-only and audit-shaped, with no data-path grant (`SELECT`, `lakeformation:GetDataAccess`, a data-bucket ARN, `Resource: \"*\"`), and exists only once a named principal is set; the archive trail is unconditional."
---

Two owed assertions were unmakeable by anyone. SPEC-170's is the load-bearing one — that a
`destination_occupied` refusal did **not** already initiate retrieval — and `dat-prod-archive`
explicit-denies the laptop IAM user, its execution role trusts `lambda.amazonaws.com` only, the
deploy role is GitHub-OIDC-only, and **no CloudTrail trails existed**. The script itself records
that a refusal which had already started retrieval "looks identical from the UI", so there was no
proxy, and being wrong costs 3–5 billed, uncancellable hours.

The answer is **audit-shaped, not a grant on the data path**: a trail recording the archive
bucket's object-level events (`RestoreObject` is a CloudTrail **data** event, which is why it never
appears in the console's Event history), and a role that reads the catalog back. What is
deliberately absent is the whole of its safety: no `SELECT`, no `DATA_LOCATION_ACCESS`, no
`lakeformation:GetDataAccess` (the credential vend for reading a table's *data*, easy to add "to
make `GetTable` work", which it is not needed for), no data-bucket ARN, no `Resource: "*"`, and no
`iam:PassRole` on the deploy side — nothing but a human may assume it. A test asserts each, and
asserts the role appears nowhere in `portal-role-permissions`.

**The role is trusted to NAMED principals and does not exist until one is named**, which the
plan scan is what forced. The first version delegated to the account root; `CKV_AWS_61` rejected it,
and accepting the finding would have violated the accept list's own rule — that list is for findings
with **no scopable alternative**, and naming the principal is one. `verification_principal_arns` is
empty by default. **The trail is unconditional**, because it needs no principal and is the half that
unblocks SPEC-170.

> **CORRECTED 2026-08-14 (#461): the ARNs travel as a repo variable, NOT a gitignored
> `terraform.tfvars`.** The original wording named tfvars, which implies a local apply — and no
> human identity in this account has one. The laptop IAM user is not on the data buckets' policy
> allowlists, so `tofu plan` reads `dat-prod-user-space` and `dat-prod-archive` as absent and
> proposes to destroy and recreate them: measured `25 to add, 3 to change, 13 to destroy`, both
> buckets in the replace set, before failing on `GetLFTag` for `portal-managed`. `modules/data/s3.tf`
> had already recorded this exact failure mode for the deploy role under SPEC-016 — the general
> lesson was written down and still did not reach the one variable a human was told to set by hand,
> which is the part worth carrying: **a config route that only an operator walks is not exercised by
> anything, so it is worth checking that the route exists before documenting it.**

**The trail's own status is part of the assertion.** A trail that is off returns an empty result,
which reads exactly like a `RestoreObject` that never happened — so the script confirms
`IsLogging: true` before reading an absence as evidence.

**No blanket write-Deny on the trail bucket**, and the omission is deliberate: the obvious one rests
on a condition key CloudTrail's own delivery must populate for its Allow to survive, and if it does
not, delivery fails and the record is silently empty. That is this spec's own failure mode with the
evidence rather than a scanner.

## History

### 2026-08-14

- **Settled:** entered the register.
- **Changed:** The principal ARNs travel as a repo variable, not a gitignored `terraform.tfvars`, because no human identity here can run a local apply (#461).
