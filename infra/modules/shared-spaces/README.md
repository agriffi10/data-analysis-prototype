# `shared-spaces` — Bucket 2 and its provisioning control plane

The shared-space bucket, and the control plane that creates and manages spaces. See
[`../../info/control-plane-shape.md`](../../info/control-plane-shape.md) for the files, roles and
traps every plane shares. What follows is what is distinct here.

`Validate → Choice(action) → { create | add-members | remove-members | leave | delete | forget |
acknowledge-membership }`

A `Choice`-routed **fan-out** rather than a pipeline: one verb runs per request. The Lambda side is
[`lambdas/info/planes/shared-spaces.md`](../../../lambdas/info/planes/shared-spaces.md).

Objects live under `{name}/…` and are seen by **all members of that space** — a single shared copy,
not per-user copies.

## Two roles, not three

This plane predates the three-role split. The **orchestrator** role is the single privileged role the
Step Function **and every verb Lambda** run under (trust = `states` + `lambda`), so its policy carries
the union of every verb's permissions: Glue, Lake Formation, S3 on the shared bucket and the admin
registry prefix, the user-space cache, Cognito admin, `lambda:InvokeFunction`, states and logs. The
**pipe** role reads the queue and starts the machine.

## Serial intake, and what actually makes duplicate names impossible

`MessageGroupId` is a **single constant** — a producer convention — so requests are processed
**strictly one-at-a-time, in order**.

**Duplicate-name safety does not depend on SQS content dedup.** Content-based deduplication only
collapses byte-identical bodies inside the 5-minute window (it usefully absorbs a double-click). **The
registry's atomic conditional `PutObject` (`If-None-Match`) is the real guard**, and serial intake is
what makes it sufficient even when two users submit the same name at once.

## The portal role's third inline policy

After `data`'s `user-space-access` and `analytics`' `analytics-access`. **Fixed size — ten slots
regardless of how many shared spaces exist** — so it stays well inside the portal role's inline-policy
aggregate.

Each slot is templated on `${aws:PrincipalTag/shared_space_k}`: S3 object CRUD plus multipart, Glue
database and table scoped to the slot's space, a `ListBucket` conditioned on the slot prefix and the
shared delete-denies. No slot carries a queue grant: the request queue is written by the API's
execution role and the operator transfer reader, never the portal role. **An unset slot stamps no tag, so
the statement matches nothing** — verified with
`aws iam simulate-custom-policy`.

**`SharedArchiveReceiptsAreNotUserWritableSystemSettings` uses the wildcard space segment**
(`${shared_space_bucket_arn}/*/system_settings/archive/*`) rather than a per-slot loop, **and that is not a
shortcut**: a **Deny needs no tag to be correct**, so one wildcard statement covers every membership
slot including ones the user does not hold — where the per-slot **Allows** must be tag-scoped or they
would grant access to spaces the user is not in. `GetObject`/`ListBucket` are untouched: a member can
browse the space's archive folder and download a receipt.

## ⚠ Lake Formation is registered in HYBRID mode

**Do not flip to enforced without opting in every principal first**, or the file browser's direct S3
access to the shared bucket breaks. Hybrid is what lets the browser keep direct-IAM S3 while Athena
reads shared tables through LF.

LF assumes a custom registration role to vend temporary S3 credentials for the location; **the role is
scoped to the shared bucket only**.

The LF **data-lake-settings singleton** (admins, `IAMAllowedPrincipals` removal) lives in
`modules/analytics` and is applied account-wide; the orchestrator role joins its admins list there,
root-wired. **This module only adds the per-bucket registration**, which is independent of those
settings. Per-shared-database LF grants and the `DATA_LOCATION_ACCESS` grant on this location are
issued by the orchestrator at create time.

**`DATA_LOCATION_ACCESS` for each control-plane execution role is the location half the
`portal-managed` LF-Tag cannot express** — tags cover database and table resources, **not S3
locations**. One per-bucket grant; per-space gating stays at `validate-authorize`. An empty list (a
standalone plan) means no grants.

Per-space isolation is still **IAM** — the membership-tag Glue database and S3 prefix scoping — not
these grants.

## The 60-second propagation guard, and what must depend on it

Same rationale as `data/s3.tf` and `auth/lambda.tf`. **60 s, not 30 s**, because the Lambda and IAM
role creates this module makes still race at 30 s.

**Every resource that needs a freshly-granted permission depends on it** — the bucket, the queues, the
IAM roles, the log groups, the functions, the state machine, the pipe — **not just the bucket**, or
those calls race the propagation.

## The `cpcommon` variable that is set and never read

No shared-space verb uses it. It is set because `cpcommon`'s config requires it and any code path may
read it — **and it landed and applied *before* the code that imports `cpcommon` deployed**, which is
the ordering that stopped a function ever reaching shared code its environment could not satisfy.

`NOTIFICATIONS_QUEUE_URL` is deliberately **not** mirrored by a `config._require`: a verb that loses it
must **log to stdout and keep working**, never crash the plane at cold start.

## A known gap this plane is the precedent for

**These verbs set `timeout` and never `memory_size`**, leaving the AWS default of 128 MB. `lambda.tf`
carries the note; `modules/data-quality` sets both explicitly on every verb and records this as the
precedent it fixes. **An unset memory tier is invisible in the plan and only shows up as an OOM in
production.**

## The bucket

Hygiene mirrors the user-space bucket: all public access blocked, SSE-S3, `BucketOwnerEnforced`,
**versioning off**, and an abort-incomplete-multipart lifecycle rule for the browser killed
mid-upload.

**The bucket has no bucket policy** — which is why a control-plane role missing from the *user-space*
bucket's allowlist half-works: every shared-space path succeeds and every personal one fails. See
`modules/data`.
