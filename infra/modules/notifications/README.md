# `notifications` — the single-writer inbox pipeline

A FIFO request queue that triggers one writer Lambda directly. The writer is the **only** thing that
appends to a user's `{username}/user_settings/notifications.json` in the existing user-space bucket.
No new bucket, no EventBridge Pipe, no Step Function — a one-task write does not get a state machine
(`lambdas/info/best-practices/lambdas/lambdas.md` §10).

| File | Holds |
|---|---|
| `sqs.tf` | the FIFO request queue and its DLQ |
| `lambda.tf` | the writer, its log group, and the SQS event-source mapping |
| `iam.tf` | the writer's role — no enqueue grant, which is `module.api`'s |
| `locals.tf` | constructed names and ARNs |
| `outputs.tf` | queue URL/ARN and the writer role ARN |
| `variables.tf` | the module interface |
| `policies/` | writer trust/permissions |

Code: `lambdas/notifications-writer/`.

## FIFO is what makes single-writer true without a lock

`MessageGroupId` is the **target username**, a producer convention. FIFO then delivers one user's
messages strictly in arrival order, one at a time — the next is not released until the prior is
deleted — so the writer never races itself on one user's document. Different users are different
groups and may process concurrently, because they are different files.

Batch size is **1**, so each message is its own invocation, which is what preserves that
one-at-a-time property. Content-based dedup collapses a byte-identical re-send inside the 5-minute
window (a double-click); producers may still set an explicit `MessageDeduplicationId`.

## The `create` boundary: IAM and the API first, a runtime check behind the grant

**The portal role no longer holds a grant on this queue**, and the two user actions
(`markRead`/`markAllRead`) arrive through the API's `notifications.enqueue`, whose request model
accepts no other action — so a user's `create` is refused before the queue. The writer's own check
outlived that grant and stays behind it as a backstop. It was built as a runtime check because IAM
could not do the job: no SQS condition key reaches a field inside a message body, so a policy could
only have denied the portal role `SendMessage` outright — the same principal on the same action the
two user actions needed then. **IAM cannot express "this principal may send these two actions and
not the third" at all.**

So the backstop is enforced at runtime by the writer, against the **`SenderId`** SQS stamps on every
message and a sender cannot set. A `create` whose **role-id half** matches the portal role's unique
ID is refused and dropped.

- **The role-id half, never the role name or ARN.** `SenderId` carries neither, and comparing against
  the wrong one never matches — which reads exactly like a control that works. That is why
  `portal_role_unique_id` has **no default** (a root that forgets to wire it fails at plan) *and* a
  `validation` on the `AROA…` shape (a *wrong* wire would otherwise validate clean and never match).
- **Unset, the writer refuses every create**, rather than passing them: a boundary that cannot run
  must not report a pass.
- A refusal **logs and drops, never raises** — dead-lettering per forged request would drown the one
  undrained DLQ.

The writer takes the body username for a `create` because a plane writes that message itself, not
through the API, so it carries no `identity` block — and the person a plane tells need not be the
caller it acted for. Who may send one is settled upstream, by who holds a grant on the queue and by
the API's route refusing the action; the check refuses one role, and stands behind the first of
those.

## This DLQ is deliberately undrained — the one hole the drain cannot close

Every *other* control plane's request DLQ is drained back into a user notification
(`modules/control-plane-dlq-drain`). This queue is the exception, and not by oversight: **the drain's
only delivery channel is this queue**, so draining it would ask the queue that just failed to deliver
a message to deliver the news about that failure. Circular by construction — a drain here would fail
exactly when it was needed.

What is actually needed is an **operator-facing** signal, a different mechanism from the user-facing
one the drain sends, and out of its scope. Until that exists, a message here is visible only to
someone who looks. **The 14-day retention is what buys that someone the time to look.**

## The writer's role, and the ListBucket that looks unnecessary

It may read and write **any** user's `notifications.json` (the `*` is the per-user prefix segment)
and nothing else app-relevant: **no `DeleteObject` anywhere** — the document is only ever
read-modify-rewritten via `PutObject` — and no admin or shared-bucket access. It verifies no token
at all — a user action's actor comes from the API's `identity` block — so **no Cognito IAM is
required**.

It also holds `s3:ListBucket`, prefix-conditioned. A `GetObject` on a key that does **not** yet exist
— a brand-new user's first notification — returns **403, not `NoSuchKey`**, unless the caller holds
`s3:ListBucket` on the bucket. Without it the read-modify-write can never bootstrap a new user's
inbox. The writer never lists; it needs the grant present for the 404 disambiguation, mirroring the
portal role's prefix-conditioned user-space `ListBucket`.

## Constructed strings versus passed attributes

The ARNs this module builds **for itself** are constructed strings in `locals.tf` — its own log
group, the user-space bucket — known at plan time, which keeps them clear of the "unknown ARN in
list" trap.

Values from **other** modules are ordinary resource attributes passed by the root: two ids from
`module.auth`, and from `module.observability` a queue URL plus `logs_queue_arn`, which is rendered
straight into the writer policy's `Resource`.

**The trap is about a list, not about unknown-ness.** An unknown ARN inside `compact()` or a set
silently drops the change. `logs_queue_arn` is a single scalar `Resource`, and
`portal_role_unique_id` is one value in a Lambda environment **map under a literal key**, so both
render as `(known after apply)` and land correctly. Stated explicitly because an earlier version of
this note pointed a reader at rewriting `logs_queue_arn` as a constructed string, **which would break
the writer's own logs grant**.

**Landing correctly is not the same as being scanned.** A policy document that is `(known after
apply)` is one the rendered-plan IAM gate cannot read, so it refuses a NEW `aws_iam_*` policy whose
document is unknown, and only names an existing one updated that way (`checkov-plan-iam.sh`). The
writer policy already exists, so a change like this to it reaches a warning, not a refusal. A new
policy in a module shaped like this one needs its ARNs known at plan, or the resource they name
landed a pull request earlier.

There is **no `time_sleep` guard** here: the deploy-role grants these resource types need were
applied and propagated in an earlier deploy, so there is no self-grant race for this apply. The
two-PR split is exactly what removes the need for the in-module propagation pause the shared-spaces
module carries.

## The shared import that was once impossible

The writer imports the shared layer — `cpcommon.actor` and `cpcommon.clients` among it — which it
could not before: `cpcommon.config` `_require`d six variables **at import** and only three are set
here, so `cpcommon.auth` was unimportable and the function carried a second copy of the fleet's
JWKS verifier. It needs neither now: a user action's actor comes from the API's `identity` block. Config resolves on
**first access** now, so the import is safe and only the variables actually read are needed. The
three still absent — `ADMIN_BUCKET`, `SHARED_SPACE_BUCKET`, `ATHENA_WORKGROUP` — are absent on
purpose, and a probe imports the module without them (`test_layer_import_safety.py`).

~~`ignore_changes` covers `layers` as well as the code.~~ **Superseded by SPEC-213:** the function is container-packaged, declares no `layers`, and `ignore_changes` names `image_uri`. The lesson below is why the field was there and is kept for it. It was **missing** while the code already
imported `cpcommon`, so an apply landing after a deploy would have stripped the layer straight back
off.
