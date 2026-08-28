# `verification` — the audit record live checks read

Two things that exist only so an owed live check can be settled: a **CloudTrail trail** over the
archive vault, and a **read-only role** an operator assumes to read the catalog back.

| File | Holds |
|---|---|
| `s3.tf` | the trail's own bucket, its hygiene config and its delivery policy |
| `cloudtrail.tf` | the trail and its advanced event selector |
| `iam.tf` | the read-only verification role and its policy |
| `outputs.tf` | the role ARN/name, the trail bucket and the trail name |
| `variables.tf` | the module interface |
| `policies/` | `verification-role.json.tftpl` |

**The trail is unconditional. The role is not created unless a principal is named.**

## Why a trail exists at all

One owed assertion could be made by **no principal in the account**: that a `destination_occupied`
refusal did **not** already initiate retrieval. Making it requires knowing whether `RestoreObject`
was ever called for a run, and:

- `dat-prod-archive` explicit-denies the laptop IAM user,
- its execution role trusts `lambda.amazonaws.com` only,
- the deploy role is GitHub-OIDC-only,
- and **no CloudTrail trails existed**.

`RestoreObject` is an S3 **object-level** call, which CloudTrail classifies as a **data event** — it
never appears in the console's Event history, which is why nothing recorded it. The check script
itself records that a refusal which had already started retrieval "looks identical from the UI", so
there is no proxy, and **the cost of being wrong is 3–5 billed, uncancellable hours**.

This is the read-only, audit-shaped answer rather than a grant on the data path: it answers "was
`RestoreObject` called for this run" **directly**, and it is arguably the record a plane that spends
real money on an uncancellable operation should have had from the start.

**One run can be isolated** because the archive key layout is `{personal|shared}/{space}/{archiveId}/…`,
so `requestParameters.key` carries the archive id and a check greps for the id it was handed. No
correlation field is needed — and none could be added, since the caller is a Lambda whose request the
plane does not tag.

The trail records **data events for one bucket and management events for none**, single-region and
single-account. It is neither a general-purpose audit trail nor a cost of any size.

The event selector matches `resources.ARN` with **`starts_with`** on the object ARN, which is why
this module takes a bucket **name** rather than an ARN.

## ⚠ The principal ARNs come from a repo variable, never a local `terraform.tfvars`

**A local apply is not available to any human identity here.** The laptop IAM user is not on the data
buckets' policy allowlists — portal, deploy and execution roles, the account root, and the Lake
Formation registration role; an IAM user ARN matches none of them, `:root` included. So `tofu` reads
`dat-prod-user-space` and `dat-prod-archive` as **absent** and plans to **destroy and recreate them**
— measured 2026-08-14 as `25 to add, 3 to change, 13 to destroy`, with both buckets in the replace
set. The same plan also fails outright on `GetLFTag` for `portal-managed`.

The value is therefore the **`TF_VAR_verification_principal_arns` repo variable** (a JSON list),
reaching tofu through `deploy-infra.yml`, which runs as the deploy role. That keeps operator ARNs out
of git without routing anyone through a local apply.

**Empty by default, and the role is then not created.** A role nobody has named is a role nobody
needs.

Delegating to the account root instead — the standard AWS idiom, which grants nothing by itself since
an account principal still needs its own `sts:AssumeRole` — was **rejected by the plan scan
(`CKV_AWS_61`), and rejecting it was right**. The accept list is for findings with *no scopable
alternative*: CloudFront and Cognito creation have no ARN before the resource exists and no applicable
condition key. That is not true here — **naming the principal is the alternative**, so accepting the
finding would have been suppressing a fixable one.

## Three Glue ARNs, not `catalog` + `catalog/*`

**Glue has no `catalog/*` hierarchy.** `GetTable` and `GetTableVersions` each need the **database**
ARN and the **table** ARN alongside the catalog — the shape `portal-role-analytics` and the
table-builder execution role already use.

The first version scoped to `catalog/*`, which **applies cleanly and then denies at runtime**: the
read-back this role exists for stays blocked with no gate having failed, which is exactly the class of
defect this work was written to close. A test asserts the resource set.

The `database/*` + `table/*/*` breadth is **not** a widening: Lake Formation gates every one of these
calls independently, and this role holds only the DESCRIBE tag grant. There is deliberately **no
`lakeformation:GetDataAccess`** — that is the credential vend for reading a table's **data**, it is
easy to add "to make `GetTable` work", and it is not needed for it.

**The reasoning is here and not in the `.tftpl`.** An IAM policy document must be printable ASCII, and
a first version carrying `"//"` comment keys with em dashes was **rejected at `CreatePolicy`** —
invisible to `tofu validate` and to the plan.

## The IAM grant is necessary and not sufficient

Lake Formation gates the catalog independently, and its refusal — `Insufficient Lake Formation
permission(s): Required Describe` — is the exact error the owed read-backs hit.

**The LF half is granted in `modules/analytics`, not here**, because it hangs off the `portal-managed`
LF-Tag that module owns: the databases are created at runtime, one per username and one per shared
space, so nothing static can enumerate them and a tag policy is the only expression that covers them
all. This module outputs the role ARN and analytics grants DESCRIBE against it — deliberately
**DESCRIBE alone**, and deliberately no `DATA_LOCATION_ACCESS`, so the role can read a table's
definition and still not read a byte of what the table points at.

Analytics consumes the output through `compact()`, which drops the empty string rather than granting
DESCRIBE to a role that does not exist.

## The trail bucket's policy, and the Deny that is deliberately absent

CloudTrail's own delivery grants and **nothing else**. Unlike the archive vault this bucket carries no
allowlist: it is meant to be readable by an account principal with ordinary admin read permissions,
because **a record nobody can read is the situation this requirement exists to fix**. What it must not
become is writable by anything but CloudTrail.

**There is no blanket write-Deny, and the omission is deliberate.** The obvious one — `Deny
s3:PutObject` where `aws:PrincipalServiceName != cloudtrail.amazonaws.com` — rests on a condition key
**CloudTrail's own delivery must populate for the Allow above to survive it**. If it does not,
delivery fails and the trail is silently **empty**, which is this project's own "did not run is never
clean" failure with the evidence rather than a scanner. The bucket is private, public access is
blocked, and this policy grants nothing but CloudTrail. The residual is that an account principal with
identity-based S3 write could tamper with the record — acceptable for an operator's verification aid,
and not for a compliance vault.

The lifecycle rule is **unfiltered and bucket-wide**, like the archive vault's own expiry and for the
same reason: **a lifecycle rule can include a prefix but never exclude one**, so a rule that missed a
prefix would keep those objects forever without saying so.

Retention is 400 days — long enough that a live check run months after a deploy still has its record,
short enough that this never becomes a storage line item.

**A trail that is off reads exactly like a `RestoreObject` that never happened**, which is why
`trail_name` is exported: confirm it is logging before trusting an empty result.
