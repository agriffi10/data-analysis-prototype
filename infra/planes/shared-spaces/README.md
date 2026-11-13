# `shared-spaces` — Bucket 2 and its provisioning control plane

The shared-space bucket, and the control plane that creates and manages spaces. See
[`../../modules/control-plane/README.md`](../../modules/control-plane/README.md) for the files, roles and
traps every plane shares. What follows is what is distinct here.

`Validate → Choice(action) → { create | add-members | remove-members | leave | delete | forget |
acknowledge-membership }`

A `Choice`-routed **fan-out** rather than a pipeline: one verb runs per request. The Lambda side is
[`lambdas/info/planes/shared-spaces.md`](../../../lambdas/info/planes/shared-spaces.md).

Objects live under `{name}/…` and are seen by **all members of that space** — a single shared copy,
not per-user copies.

## Three roles now, and the old orchestrator role keeps its name

This plane predates the three-role split. Until the planes became calls to one module, the
**orchestrator** role was the single privileged role the Step Function **and every verb Lambda** ran
under (trust = `states` + `lambda`). Now the state machine has the Step Functions role every plane
has, and `orchestrator` is this plane's **execution** role — kept under its own name, with its
inline policy still called `orchestrator`, because the Lake Formation admin list and the user-space
bucket's allowlist name that role. Its policy is the union of the verbs' permissions: Glue, Lake
Formation, S3 on the shared bucket and the admin registry prefix, the user-space cache, Cognito
admin, notifications, logs. `lambda:InvokeFunction` and the log-delivery actions left it with the
state machine. The **pipe** role reads the queue and starts the machine.

**The split has one ordering risk, recorded rather than staged.** Against a state that has the old
shape, one apply shrinks the orchestrator role's trust and policy and swaps the state machine onto
the new role, and nothing orders the two. If the swap fails (on the new role's propagation, say)
after the shrink has landed, the machine still runs as a role that can no longer invoke the verbs,
and the plane cannot run until a re-apply finishes the swap. Production took it on 2026-11-13, in
Deploy Infrastructure run 43422262900, without a failure; the next account is created fresh, where nothing shrinks. A state that
does take the change should be re-applied straight away if it fails.

## Ordered intake, and what actually makes duplicate names impossible

`MessageGroupId` is a **single constant** — a producer convention — so requests are **started one at
a time, in arrival order**. ⚠ **That is not serial execution.** The Pipe starts the machine
`FIRE_AND_FORGET` and sends the next message once `StartExecution` returns, so runs overlap.

**Duplicate-name safety does not depend on the queue.** Content-based deduplication only collapses
byte-identical bodies inside the 5-minute window (it usefully absorbs a double-click), and the group
id orders only the starts. **The registry's atomic conditional `PutObject` (`If-None-Match`) is the
whole guard**: when two users submit one name at once, one write is refused whatever order their
runs reach it in. The other registry writes, bar the final delete, and the cache and membership
index writes are compare-and-swaps; what overlap still costs is recorded in
`docs/decisions/control-planes/` (*A group id orders the STARTS, not the runs*).

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

**Do not flip to enforced without opting in every principal first**, or the file browser's
IAM-authorized S3 access to the shared bucket breaks — the API's calls under the caller's assumed
role, and bytes on URLs that role presigned. Hybrid is what keeps that access on IAM while Athena
reads shared tables through LF.

LF assumes a custom registration role to vend temporary S3 credentials for the location; **the role is
scoped to the shared bucket only**.

The LF **data-lake-settings singleton** (admins, `IAMAllowedPrincipals` removal) lives in
`modules/analytics` and is applied account-wide; the orchestrator role joins its admins list there,
root-wired. **`modules/shared-space-storage` only adds the per-bucket registration**, which is independent of those
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
role creates this plane makes still race at 30 s. The wait lives in `modules/shared-space-storage`,
and the plane's and the transfer reader's root calls depend on that module, so it still precedes
everything that needs a fresh grant.

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

**These verbs once set `timeout` and never `memory_size`**, leaving the AWS default of 128 MB. They
now declare 128 MB explicitly in `infra/plane-shared-spaces.tf`, as data quality did first. **An
unset memory tier is invisible in the plan and only shows up as an OOM in production.**

## The bucket

Hygiene mirrors the user-space bucket: all public access blocked, SSE-S3, `BucketOwnerEnforced`,
**versioning off**, and an abort-incomplete-multipart lifecycle rule for the browser killed
mid-upload.

**The bucket has no bucket policy** — which is why a control-plane role missing from the *user-space*
bucket's allowlist half-works: every shared-space path succeeds and every personal one fails. See
`modules/data`.
