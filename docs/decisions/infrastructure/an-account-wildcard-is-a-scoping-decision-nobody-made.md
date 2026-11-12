---
type: Decision
title: "An account wildcard is a scoping decision nobody made"
description: "**An ARN in a deploy grant names ONE account.** The account field is a scoping decision like any other, and a `*` there reads identically to a considered one. It is not inert everywhere: where a resource carries its own policy — SQS, ECR, `lambda:InvokeFunction`, EventBridge, and the Glue catalog under Lake Formation — a foreign account holding a `dat-*`-matching resource whose policy admits this role was reachable. Elsewhere (EC2, Logs, Lambda config, Step Functions, Pipes) the request evaluates in the owner's account with nothing to say yes, so the wildcard authorized nothing; pin it anyway, because the two are indistinguishable in a diff. **The exception is a resource AWS owns:** every managed prefix list is `arn:aws:ec2:<region>:aws:prefix-list/…`, and the SPA's egress rule names the S3 one — so that ARN is pinned to `aws`, not to this account. **An empty account field is legal** (S3, Route 53, API Gateway) and is not a wildcard. `test_no_deploy_grant_wildcards_the_account` walks the parsed document, not the `Resource` field, because two of these ARNs live in `Condition`s."
---

192 of the 216 ARNs in the deploy role's seventeen policy templates wildcarded the account:
`arn:aws:glue:${aws_region}:*:catalog`, and 191 others. Of the remaining 24, 21 carry an empty
account field, which is legal, and 3 already named the id. Sibling modules had pinned the identical
shapes with `${account_id}` all along (`infra/plane-table-share.tf`,
`analytics/policies/portal-role-analytics.json.tftpl`), so this was house style in one tree and
not the other, and neither reads as deliberate.

**What it was actually worth is narrower than "wildcards are bad", and worth stating so it is not
re-litigated.** An identity policy alone cannot authorize a cross-account call. For EC2, Logs,
Lambda configuration, Step Functions and Pipes there is no resource policy to supply the other
half, so the `*` authorized nothing that a pinned ARN would not. It mattered where a resource
carries its own policy — SQS, ECR, `lambda:InvokeFunction`, EventBridge, and the Glue catalog
under Lake Formation, which is the case that prompted the sweep: were this account ever made an
LF recipient of another account's catalog, nothing in the grant stopped the deploy role altering
that shared table. Measured against the account's own resources, every foreign-account identity
those patterns reached is closed by the pin, and no live resource stopped being reachable.

**The Lake Formation case is only half closed, and the other half is not this change's to
close.** Pinning the account closes the `glue:` catalog, database and table ARNs. The inline
document's `LakeFormationManage` still grants fourteen `lakeformation:*` actions on
`Resource: "*"`, which no account pin reaches — that is a question about the `NON_SCOPABLE` set,
and it is still open.

**One ARN must NOT be pinned, and a simulate against a self-owned resource would never say so.**
All sixteen managed prefix lists here are AWS-owned — `arn:aws:ec2:us-east-1:aws:prefix-list/…`,
`OwnerId: AWS` — and the SPA task's egress rule names the S3 one, because a CIDR rule does not
match gateway-endpoint traffic. Pinned to this account, `ec2:ModifySecurityGroupRules` reads
`implicitDeny` against the real list; pinned to `aws` it reads `allowed`. It is pinned to the
owner rather than left wildcarded, which leaves the exemption scoped to the one resource type
that earns it. Of the security-group **mutators** only `ModifySecurityGroupRules` accepts a
`prefix-list` resource type — `AuthorizeSecurityGroupEgress` and `RevokeSecurityGroupEgress` do
not, per the live Service Reference — so that is the action the pin is load-bearing for. Say
"the mutators", not "the actions in that statement": the merge below puts `ec2:CreateTags` and
`DeleteTags` in the same statement and **both** accept a `prefix-list`, so the narrower sentence
was falsified by its own commit. This paragraph has now been wrong twice, in both directions.

**The evidence is a live-ARN sweep, not the simulate pair the fence normally asks for.** A
simulate answers "does this pattern match this string" for a string you chose; both legs of
"pinned matches same-account, refuses foreign-account" are true by construction. The risk that
actually costs a trunk is a pattern that stops matching a resource the account **holds** — and it
would not fail on this apply, which refreshes under the *current* wildcard document, but on the
next apply's refresh, on an unrelated PR, where the fix is itself denied. So every ARN the
account holds, across the twenty-nine resource types these grants scope, was matched against the
pre- and post-change pattern sets: **zero** reached before and not after, **zero** widenings,
and all but a handful reached by the pinned grant as the positive control. Two independent runs
agreed on all three directional results and disagreed on the raw totals, because each enumerated
the account slightly differently — which is why no total is written here. Re-derive it; a
population counted once rots between the count and the next reader.

**The population is textual, not the `Resource` field.** Two of the 192 sit in `Condition` values
(`ArnLike` on `lambda:FunctionArn`, in the feedback and notifications event-source-mapping
statements). A sweep reading `Resource` reports those two clean forever, and a guard built the
same way inherits the blind spot.

**The same population trap caught this change too, and it is recorded above** — *The rules also
guarded two documents of seventeen*. `MANAGED_POLICIES` globs `github-actions-deploy-*.json.tftpl`,
and that trailing `-` excludes the inline document, which holds 18 of the 192. Both changes reached
for that constant and both had to widen it; the second one knew to look only because the first had
written the lesson down. `POLICIES` is now the single population, and it is one constant rather
than the two these two changes independently created.

**A budget the change nearly spent, and the constraint that was false.** Pinning costs eleven
characters an ARN, and `github-actions-deploy-platform` sits closest to the hard, unadjustable
6,144: pinned but unmerged it measures 6,117, leaving **27**. The first plan justified restructuring by claiming the role was
at its attachment ceiling — it is not, it carries **16** against 20 (the 20 was read off the
constant asserting the ceiling, not off a count). The restructuring stands on its own reason
instead: `PlatformNetworkManage` and `PlatformNetworkTags` held byte-identical ten-ARN lists that
had to be hand-synced, and the comment above them already said "nine". Merged — their union is
IAM-equivalent, both having no `Condition` — the document ends at 5,534 with 610 free, more than
the 350 it had before the pin. The cost is that `CreateTags` can no longer be conditioned alone,
which the same comment argues against wanting.

Pin the account even where the wildcard authorized nothing, because the two cases are indistinguishable in a diff. An empty account field (S3, Route 53, API Gateway) is legal and is not a wildcard. `test_no_deploy_grant_wildcards_the_account` walks the parsed document, not the `Resource` field, because two of these ARNs live in `Condition`s.

## History

### 2026-09-07

- **Settled:** entered the register.
