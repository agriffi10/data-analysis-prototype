# The control-plane module shape

Seven modules are the same machine with different verbs: **shared-spaces**, **table-builder**,
**table-share**, **data-quality**, **file-send**, **archive** and **file-ops**. This page is what they
have in common, so each module's own README carries only what is distinct about it.

```
browser ──sqs:SendMessage──▶ FIFO request queue ──▶ EventBridge Pipe ──▶ Step Function ──▶ verb Lambdas
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
| `iam.tf` | the shared execution role, the Step Function role, the Pipe role, and the portal role's enqueue policy |
| `locals.tf` | constructed names and ARNs, and **the verb map** |
| `policies/` | `.tftpl` templates — no inline `jsonencode` IAM anywhere |

## The invariants

- **One execution role per plane**, shared by every verb, whose policy is the **union** of the verbs'
  needs. **A plane sharing another plane's DLQ lets one malformed request dead-letter someone else's
  work** — each plane owns its own.
- **Three roles, three jobs.** The **Pipe** role only calls `states:StartExecution` (plus the SQS
  consume) — it *starts* the execution and does not run it. The **Step Function** role invokes the
  verbs. The **execution** role is what the verbs actually run as.
- **The browser's only privilege on any plane is `sqs:SendMessage` to that plane's request queue.** No
  Lambda invoke, no DLQ, no Step Function. The policy is attached to the shared portal role **by
  name** (the role is created in `module.data`).
- **Batch size 1**, so each message starts its own execution and the FIFO per-`MessageGroupId`
  ordering is preserved.
- **`content_based_deduplication` is on, and the producer also sends an explicit
  `MessageDeduplicationId`.** The explicit id is the real double-submit guard; content dedup usefully
  absorbs a byte-identical retry inside the 5-minute window.
- **Cross-module ARNs are constructed strings from the root locals**, never another module's output,
  so they are known at plan time and each module plans standalone. An unknown ARN inside `compact()`
  or a list **silently drops the change**.
- **Terraform owns the function infrastructure plus a placeholder zip; CI owns the Python code and
  every layer attachment.** `ignore_changes = [filename, source_code_hash, layers]` on every function
  — without `layers`, an apply landing after a deploy strips the layer back off and the function
  fails at cold start on an import that had been working.
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
- **A post-identity failure needs its own seed.** A catch routed to a state reading `$.raw` raises an
  uncatchable error *before* the notifier, because `$.raw` exists on no post-validate state.
- **Everything unbounded travels by pointer**, never on the state, and a cap is not a substitute.
- **The request envelope is FLAT** — `actor` is the raw token at the top level — because the DLQ drain
  reads and **redacts** that field flatly. Nested, a dead-lettered request notifies nobody *and*
  writes the JWT to CloudWatch.
- **An expected refusal is a RETURN VALUE**; only unpredicted faults raise. A `TerminalError` cannot
  name the colliding item, and the user needs it named.
- **One producer says every per-recipient outcome**, at the end of the machine — not each verb.

## Where the rest lives

The Lambda side — the verbs, the layer split, and each plane's own fences — is
[`lambdas/info/INDEX.md`](../../lambdas/info/INDEX.md) and its `planes/` pages. The long-form
reasoning is `docs/architecture.md` → *Control Planes* and `docs/decisions.md`.
