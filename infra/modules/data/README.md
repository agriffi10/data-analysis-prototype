# `data` — the user-space bucket and the shared portal role

Bucket 1, and the one IAM role every authenticated user assumes. **Per-user isolation is a principal
tag, not a policy per user**: the Identity Pool stamps `username` server-side from the verified
claim, and every statement scopes to `${aws:PrincipalTag/username}`. One role for all users.

| File | Holds |
|---|---|
| `s3.tf` | the bucket, its hygiene config, CORS, and the **bucket policy** |
| `iam.tf` | the portal role's trust, its Identity Pool binding, and its permission policy |
| `outputs.tf` | bucket name/ARN, role ARN, and the role's **unique id** |
| `variables.tf` | the module interface — mostly the allowlist ARNs |
| `policies/` | the trust, permission and bucket-policy templates |

## ⚠ The bucket-policy allowlist is hand-maintained, and omission fails at runtime

The bucket policy **denies** every S3 data action (object CRUD + `ListBucket`) to every principal
except a named list. **An explicit resource-policy Deny beats an identity-policy Allow.** So a role
that holds a perfectly correct identity grant and is *not* on this list is denied at runtime, with
nothing in the plan to warn it.

**This has bitten the repo repeatedly, and it always looks like a code bug.** The tell is that the
plane *half-works*: the shared-space bucket has no bucket policy, so every **shared-space** operation
succeeds and every **personal** one fails `AccessDenied`.

Three control-plane execution roles — table-builder, table-share and data-quality — each held the
identity-side grant and **none** was on this list. The gap was invisible until a live smoke run
became the first time any of them read a real user's files (greenfield, no production users).

**When you add a role that touches this bucket, add it here in the same PR as the role**, not with
the first verb that needs it. `file_ops_execution_role_arn` is deliberately on the list *before* the
plane has any S3 grant at all, for exactly that reason.

Two more exclusions are not optional:

- **The Lake Formation registration role.** LF assumes it to vend credentials for the registered
  user-space location, so when a user queries a Glue table **the S3 read happens as this role**.
  Without the exclusion, queries fail with `PERMISSION_DENIED … s3:ListBucket … explicit deny in a
  resource-based policy`. It is a service role, not user-assumable, so excluding it widens nothing.
- **The deploy role.** `tofu plan`/`apply` calls `HeadBucket`, which is an `s3:ListBucket` action. An
  earlier version omitted it, so once the policy was live the deploy role got 403 on `HeadBucket`,
  **`tofu refresh` reported the bucket as deleted, and every subsequent plan proposed a destructive
  recreate.** It already holds `s3:*` via its identity policy and can rewrite any policy anyway.

Bucket **configuration** actions (`PutBucketPolicy`, lifecycle, …) are intentionally not denied.
Human IAM admins remain denied data access.

The list uses each role's **IAM ARN** (`arn:…:role/NAME`), never the assumed-role session ARN: per
AWS's docs, `aws:PrincipalArn` for an assumed-role request — Cognito `AssumeRoleWithWebIdentity`
included — resolves to the role's IAM ARN, and the docs say not to use the session ARN here. That is
what makes the user exclusion work. Every cross-module ARN arrives as a **root-constructed string**,
so no role needs to exist at apply time and this module plans standalone.

## The role has two doors, and both stamp the same tags

The browser exchanges its ID token with the Identity Pool. The API **assumes the same role with the
same tag set read from the same claims**. That is what makes "not one IAM policy, bucket policy or
Lake Formation grant is rewritten" provable rather than argued — **a policy sees a session tag, not
who stamped it**.

- **Both `sts:AssumeRole` and `sts:TagSession` are required, and either alone is a trap.**
  `AssumeRole` without `TagSession` renders, plans, applies and unit-tests green, then fails at
  runtime with an `AccessDenied` naming neither the tag nor the missing action — reading as a
  permissions bug in whichever feature happened to call first.
- **`sts:TagKeys` is a ceiling, not a floor.** It constrains which tag **keys** may appear, not their
  **values**, and IAM offers no way to constrain values. `ForAllValues:StringEquals` is satisfied by
  a request carrying a subset of the listed keys — **and equally by one carrying none at all** — so
  **this condition cannot require that `username` was stamped.** The unspoofability argument rests
  entirely on where the value comes from: a claim of a signature-verified ID token. Not on this
  condition.
- **The `Null` condition requires transitive tag keys to be absent.** A transitive tag survives role
  chaining; nothing here chains onward, and a tag that outlives its session is a durable escalation.
  Its value is the **string** `"true"` — a JSON boolean is a `MalformedPolicyDocument` at apply.

The key list is built from the same two variables the API function's own environment carries, so the
set the API stamps and the set this statement admits **cannot drift apart by transcription**.
`principal_tag_key` is **not** threaded into the permission templates, which hard-code the literal:
editing those is forbidden while both credential paths run, so the agreement is **asserted by test
rather than made structural**.

## The permission policy, and three things deliberately not granted

Each session may read/write/delete only under its own `{username}/` prefix. A session **without** the
tag matches nothing and gets an implicit deny. The tag variable is escaped as
`$${aws:PrincipalTag/username}` so `templatefile()` emits it literally.

- **Multipart:** `AbortMultipartUpload` + `ListMultipartUploadParts` only.
  `CreateMultipartUpload`/`UploadPart`/`CompleteMultipartUpload` are authorized by the existing
  `PutObject` grant. **`ListBucketMultipartUploads` is deliberately not granted** — lib-storage never
  lists in-progress uploads, and that action does not support the `s3:prefix` condition key, so
  granting it bucket-wide would leak other users' in-progress upload keys.
- **The username directory** is one statement: `GetObject` on `_directory/*`. **No `ListBucket`
  widening** (so `_directory/` is invisible to the file browser and the browser needs no change) and
  **no write** (the daily builder is the only writer). The disclosure is intended and accepted, not
  incidental — recorded in `docs/decisions/storage.md`.
- **The feature flags** are the same shape on `_config/*`, with the same two omissions. A feature
  flag is **presentation, never authorization**, so turning one off revokes no grant. The bucket
  choice is what makes it one line: this bucket already has CORS, its host is already in the
  enforcing CSP `connect-src`, and the portal role is already on the allowlist. The admin bucket has
  none of the three, and `lambdas/test_feature_flags_config.py` asserts all three rather than
  assuming them — **a broken read here falls back silently to all-on**.

### `ArchiveReceiptsAreNotUserWritable`

A Deny on `PutObject`/`DeleteObject`/`AbortMultipartUpload` under the user's own `archive/` prefix.
The receipt is written by the archive execution role: **a user who can rewrite a receipt can
misreport what was archived**, to themselves and to anyone they show it to.

It lives beside the Allow it narrows rather than in the analytics template. `GetObject` and
`ListBucket` are untouched — browsing the folder and downloading a receipt is the whole point of it
being a plain text file, and denying a write action does not perturb listing.

**`AbortMultipartUpload` is included on purpose**, and it is the part that reads as redundant and is
not. A Deny on `PutObject` alone already blocks a multipart upload, so nothing can be written either
way — but with abort left out, a half-started upload **cannot be tidied**, and its orphaned parts sit
billed and invisible to every listing until the bucket's abort rule catches them.

**The UI mirrors this.** An IAM Deny with no UI counterpart produces a bare `AccessDenied` for a rule
this application itself authored — exactly what `isUndeletableRootFolder` exists to prevent for
`athenaresults/`. Nothing gated Upload or New folder on the current *prefix*, so the browser carries
the app's first prefix-based write gate for it.

## Every top-level prefix is a username — with one exception

`_directory/` is the deliberate exception, and it is safe for one **mechanical** reason:
`cpcommon.config.CATALOG_IDENTIFIER_RE` requires a leading **lowercase letter**, so `_directory` can
never *be* a username. The name was chosen precisely because it cannot collide, which is also why the
builder needs no special case to exclude its own output — the same regex that validates a username
drops it.

**Adding a second exception means re-checking that property for the new name.**

## Versioning is off

Deliberate for the MVP: no version history, no undo. Overwrites and deletes are irreversible and the
app guards them in the UI. This is what makes a failure between a control plane's `CopyObject` and
`DeleteObject` unrecoverable — see `docs/architecture.md` → *Constraints that shape the system*. Revisit before real
user data lands.

## `portal_role_unique_id`

SQS stamps `SenderId` on every message, and for a **role** it is `{unique_id}:{session-name}` — a
system attribute a `SendMessage` cannot set, and the one attributable fact a queued message carries
about who sent it. The notifications writer compares the role-id half against this to refuse a
`create` from browser credentials. **The unique id, never the name or the ARN** — `SenderId` carries
neither, and a comparison against the wrong one silently never matches.

## The two `time_sleep` guards

Both absorb an IAM propagation window on **initial creation only**. The bucket's covers the deploy
role racing its own `module.base` grant; the role's covers `iam:CreateRole`/`PassRole` being granted
in the same apply that creates the role.
