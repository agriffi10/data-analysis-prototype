# The control-plane module shape

Eight modules are the same machine with different verbs: **shared-spaces**, **table-builder**,
**table-share**, **data-quality**, **file-send**, **archive**, **file-ops** and
**results-conversion**. This page is what they
have in common, so each module's own README carries only what is distinct about it.

```
browser ──HTTPS──▶ API ──sqs:SendMessage──▶ FIFO request queue ──▶ EventBridge Pipe ──▶ Step Function ──▶ verb Lambdas
                                                    │                                                          │
                                                    └──▶ DLQ ──▶ control-plane-dlq-drain          notifications queue
```

## The files, and what each always holds

| File | Always holds |
|---|---|
| `sqs.tf` | the FIFO request queue and **its own DLQ** |
| `pipe.tf` | the EventBridge Pipe, batch size 1, `FIRE_AND_FORGET` |
| `stepfunction.tf` | the Standard state machine, its log group, and the **explicit** function map |
| `state-machine.asl.json.tftpl` | the ASL definition |
| `lambda.tf` | every verb function, `for_each` over the map in `locals.tf` |
| `iam.tf` | the shared execution role, the Step Function role and the Pipe role — **no enqueue grant**, which is `module.api`'s |
| `locals.tf` | constructed names and ARNs, and **the verb map** |
| `policies/` | `.tftpl` templates — no inline `jsonencode` IAM anywhere |

## The invariants

- **One execution role per plane**, shared by every verb, whose policy is the **union** of the verbs'
  needs. **Each plane owns its own DLQ, because the drain names the feature by the DLQ a request
  lands on** — as built, `_source_for` in `dlq_drain.py` reads the DLQ's name, never the untrusted
  body — so a shared DLQ would tell a user the wrong feature failed, or name none. A malformed body
  is not the reason: the Pipe starts an execution for any record that fits Step Functions' input
  limit, and the plane refuses the body inside that execution. A request reaches its DLQ when the
  Pipe's `StartExecution` keeps failing until its receives run out, including a redelivery of one
  that already started, which *A redelivered message is not a re-run*, below, covers.
- **Three roles, three jobs.** The **Pipe** role only calls `states:StartExecution` (plus the SQS
  consume) — it *starts* the execution and does not run it. The **Step Function** role invokes the
  verbs. The **execution** role is what the verbs actually run as.
- **The browser holds no privilege on any plane.** It calls the API's enqueue route, and the API's
  execution role is what writes the request queue: one `sqs:SendMessage` statement in `module.api`
  naming every request queue by ARN, from a list the module refuses at any other length. A new plane
  adds its queue there, not a grant of its own; no Lambda invoke, no DLQ, no Step Function. A
  second producer is admitted only by `SenderId`, as shared-spaces' operator reader is.
  `lambdas/test_queue_writers.py` asserts that no portal-role policy can send to any queue, and
  that the API's grant is rendered from a list of the pinned length with no DLQ and no wildcard —
  by count, not by name, so a swapped entry passes.
- **Batch size 1**, so each message starts its own execution and the FIFO per-`MessageGroupId`
  ordering is preserved.
- **`content_based_deduplication` is on, and the producer also sends an explicit
  `MessageDeduplicationId`.** The explicit id is the real double-submit guard; content dedup usefully
  absorbs a byte-identical retry inside the 5-minute window.
- **Cross-module ARNs are constructed strings from the root locals**, never another module's output,
  so they are known at plan time and each module plans standalone. An unknown ARN inside `compact()`
  or a list **silently drops the change**.
- **Terraform owns the function infrastructure; CI owns which image it runs.** Every verb is a call
  to [`../modules/docker-lambda`](../modules/docker-lambda/README.md), carrying
  `ignore_changes = [image_uri]`. That cuts both ways: without it every apply would drag the fleet
  back to whatever tag Terraform was last handed, and with it Terraform never moves a function
  forward either — so CI must point every function on every deploy, and a pipeline that pushes an
  image and points nothing leaves the fleet on the previous one, each function still working.
- **Every verb gets its task's real timeout and memory**, not one number for the plane: a small
  validator is not the polars infer step.
- **No `time_sleep` guard.** The deploy-role grants these resource types need are applied in
  `modules/base` in their own **earlier PR**, so there is no self-grant propagation race to wait out.

## The traps every plane shares

- **The state machine's `TimeoutSeconds` is a TOP-LEVEL field of the ASL document**, not a Terraform
  argument — `aws_sfn_state_machine` has no `timeout_seconds` and `tofu validate` rejects it. And
  **catchers do not cover top-level execution failures**, so a ceiling ships **with** an EventBridge
  `TIMED_OUT` rule — never `FAILED`, or every caught failure double-notifies.
- **Every cap is computed by a test**, against the budget that sized it, and names that budget. A
  hard-coded number hides a wrong model.
- **`stepfunction.tf` passes an EXPLICIT per-function map, not a loop.** A new ASL state referencing a
  new function needs its key added there or `templatefile()` fails at **plan**. Easy to miss precisely
  because `lambda.tf`, being `for_each` over the same map, does not.
- **Every variable the domain layer's `config` requires must be COMMON to all verbs.** The layer's
  config runs on any import chain, so a verb missing one fails on whichever branch reads it. Per-verb
  env is reserved for **optional** action env only. This caused a production break on 2026-07-05:
  `check-table-absent` raised `RuntimeError COGNITO_USER_POOL_ID unset` at cold start.
- **No ASL state may decode an error `Cause`.** `States.StringToJson($.error.Cause)` raises
  `States.Runtime`, which is **uncatchable anywhere**. Carry the raw `$.error`; decode with
  `cpcommon.errors.failure_reason`, the only decoder.
- **Every plane notifies on a pre-verb failure** — a `NotifyFailure` before `Fail`, reached on every
  path, because the no-verb-ran paths cannot be selected for in ASL.
- **A post-identity failure needs its own seed.** A `Pass` hard-fails on an ABSENT key — an
  uncatchable `States.Runtime`, raised *before* the notifier — so a catch may only route to a state
  whose every read its seed supplies, whatever the key is called. Nothing reads `$.raw` any more,
  which is what retired the instance of this that used to bite; the rule is the general one, and a
  fleet guard walks every seed's forward path to hold it.
- **Everything unbounded travels by pointer**, never on the state, and a cap is not a substitute.
- **The actor travels in the API's NESTED `identity` block, and no token travels at all.** A plane
  reads it through `cpcommon.actor`, which cannot verify: who may write the queue is the
  authorization — the API, plus any producer the plane admits by `SenderId`. The DLQ drain takes its recipient from that block and redacts
  only **legacy top-level** token fields, one of which holds the token in any message enqueued
  before the API stopped sending one — pointed at `identity`, it would blank the logged recipient
  and remove nothing sensitive.
- **An expected refusal is a RETURN VALUE**; only unpredicted faults raise. A `TerminalError` cannot
  name the colliding item, and the user needs it named.
- **One producer says every per-recipient outcome**, at the end of the machine — not each verb.

## A redelivered message is not a re-run

**At-least-once delivery does NOT give you a re-run** (measured 2026-08-10, and it applies to
every plane). The Pipe starts executions `FIRE_AND_FORGET` and **cannot name them** — Pipes exposes no
execution-name parameter at all — and the names it generates are **v5 UUIDs**, i.e. derived
deterministically from something stable per message (the SQS `messageId` is v4/random, so it is
not simply copied). What a repeated name does is **measured, not just documented** (2026-08-10,
against the deployed table-share machine), and the middle case is the trap: same name + same input
**while the original is still running** → the call succeeds and **returns the original execution
ARN**, no second run; once the original has **closed** → **400 `ExecutionAlreadyExists`**; and the
name is only reusable **90 days after it closes**. So a redelivered SQS message does not retry the work — it is either swallowed or it
**fails the target invocation**, and a target that keeps failing exhausts the redrive policy and
lands on the request DLQ, where the DLQ drain turns it into a **user-facing failure
notification for a request that may have SUCCEEDED**. Do not design a plane's recovery story
around SQS redelivery.
> **How the name semantics were verified, and how to re-verify:** start an execution with a
> deliberately malformed input (`[]`), which dies at `validate-authorize` **before an actor
> exists** — so `NotifyFailure` runs with `actor=` and messages nobody. Call `StartExecution`
> again with the same name and input while it runs (expect the same ARN back), then again once it
> has closed (expect `ExecutionAlreadyExists`). Zero blast radius; the only cost is a FAILED
> execution in history and **a name burned for 90 days**, so pick a fresh one.
>
> **Still unproven:** that Pipes derives the name *per message*. It is inferred from the v5
> version nibble — the namespace is private, and no combination of the message id, pipe ARN or
> state-machine ARN reproduces an observed name. **A redrive cannot settle it and is not worth
> attempting:** an SQS DLQ redrive needs a message in the DLQ, and Step Functions'
> `RedriveExecution` restarts states *within the same execution ARN* — it never calls
> `StartExecution`, so it can never collide on a name. Only a genuine SQS **redelivery of the same
> `messageId`** tests it, which means forcing the Pipe to miss its delete inside the queue's
> 60-second visibility timeout — production drift on an IaC-managed queue, racing a sub-second
> window. Declined as not worth it. Until then, treat redelivery as unreliable.

## Where the rest lives

The Lambda side — the verbs, the shared-code split, and each plane's own fences — is
[`lambdas/info/INDEX.md`](../../lambdas/info/INDEX.md) and its `planes/` pages. The long-form
reasoning is `docs/architecture.md` → *The control planes* and [`docs/decisions/control-planes.md`](../../docs/decisions/control-planes.md).
