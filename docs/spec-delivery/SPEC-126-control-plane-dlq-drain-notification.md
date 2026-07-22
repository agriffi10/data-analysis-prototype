# Completed Spec — SPEC-126: Control-Plane DLQ Drain → User Notification

## What was completed?

A request that a control plane could not process used to vanish silently: no verb ran, so no
`@notifies_on_failure` fired; no execution started, so no `NotifyFailure` state was reached.
**One** drain Lambda now sits on **all four** request DLQs and turns each dead-lettered
message into one sentence in the actor's inbox.

- **`lambdas/control-plane-dlq-drain/dlq_drain.py`** — a per-source descriptor table keyed off
  the record's `eventSourceARN` (the domain noun + the field its token lives in), the verified
  recipient, the redacted forensic log, and per-message paths that are total by construction.
- **`cpcommon.auth.verified_username_ignoring_expiry`** — the one relaxation, as a
  **separately named** entry point over a shared private body. Signature/issuer/audience are
  still enforced; only `exp` is not, because a dead-lettered message is old by construction
  (three failed receives, then a wait in a 14-day queue) while an ID token lives an hour — and
  this path grants nothing, it picks a notification recipient.
- **`infra/modules/control-plane-dlq-drain/`** — function, execution role (four DLQ reads +
  one notifications send + logs, nothing else), log group, and four event-source mappings
  keyed by queue name.
- **`infra/modules/base`** — the deploy-role grants, applied in their own PR first (#265).
- **Wording sweep:** the `/data-quality` footer line, its test, and the help guide said a
  failed check *"usually"* reports itself in notifications. That hedge existed for exactly the
  hole this closed, so all three now say **always**.

**Deviations, all technical and taken in-session:**

- **`batch_size = 5`, not 1.** Records are independent and the handler is total, so batching
  only reduces invocations on queues that are almost always empty. Deliberately **no**
  `ReportBatchItemFailures`: reporting a failure asks SQS to redeliver, which is the loop
  FR-005 forbids.
- **The four DLQ ARNs are constructed strings in the root module**, not arc-module outputs —
  known at plan time, no module→module edge, matching how every producer scopes to the
  notifications queue.
- **A generic-noun fallback** for an unrecognised queue. It should be unreachable (the
  coverage test fails first), but a wrong-but-honest message beats the silence this spec
  exists to remove.

## What changed from earlier specs?

- **SPEC-114 FR-005 is replaced**, not deferred — no CloudWatch alarms were added.
- **SPEC-123's FR-006 footer line** is tightened from "usually" to "always" (and its test
  inverted), which was the amendment SPEC-123's delivery doc left owed.
- `cpcommon/auth.py`'s body moved into a private `_verified_username`; `verified_username`'s
  behaviour is unchanged and a test pins that it still enforces expiry.
- `infra/modules/notifications/sqs.tf` gained the comment recording why **its** DLQ is
  deliberately undrained (FR-006) — the one hole this design cannot close, since the drain's
  only delivery channel is the queue that DLQ implies is broken.

## Verification

`pytest lambdas/` 1015 passed · `vitest` all green · `tofu fmt -check -recursive` ·
`tofu validate`.

**7 mutations, 7 guard failures**: recipient taken from the body instead of the token; the
redaction removed; a body value interpolated into the message; a source dropped from the
descriptor table; `verified_username` swapped in for the expiry-relaxed entry point; the
handler's outer catch removed (needed its own forced-throw test — every inner path is already
total, so the batch tests passed with it deleted, a false green on the guard that decides
whether a poison message loops).

**Deferred:** the live end-to-end (Phase 3's scenario) — hand-place a malformed body on the
data-quality DLQ with a valid token and confirm one "couldn't be started" notification
arrives naming no path from the body, then repeat with a bad-signature token and confirm
nobody is notified. It joins the arc-wide smoke pass 108→126 still owed. (Now expect the
notification within one ~10-min sweep interval, not seconds — see the follow-up below.)

## Follow-up (2026-07-22): four event-source mappings → one EventBridge scheduled sweep

The four SQS event-source mappings long-polled four almost-always-empty DLQs around the clock,
and that idle polling was the bulk of the account's SQS request volume (it was tripping the
1M/month free tier). They were replaced by **one EventBridge rule** (`rate(10 minutes)`) that
invokes the drain; the handler now **polls all four DLQs itself** — receive → notify → delete,
until empty — via `DLQ_ARNS` (the same ARNs, as an env JSON list).

- **`dlq_drain.py`** gained `_sweep_one_queue` / `_dlq_arns` / `_queue_url` / `_guarded_notify`;
  `_notify_one` and everything it calls is unchanged. `handler` dispatches: a scheduled event
  (no `Records`) sweeps; an SQS event still takes the per-record path, so a captured record can
  be replayed with `aws lambda invoke`.
- **`infra/modules/control-plane-dlq-drain/lambda.tf`** drops the four mappings and adds an
  `aws_cloudwatch_event_rule` + target + `aws_lambda_permission` (a resource-based grant for
  `events.amazonaws.com` — no separate invoke role, unlike EventBridge Scheduler). The execution
  role is **unchanged**: it already held the four DLQ read/delete grants the mappings polled with.
  `DLQ_ARNS` was added to the function env; the now-unused `dlq_queue_names` var and `dlq_by_name`
  local were removed.
- **Deploy-role grant** (`events:` rule management, scoped to the `*-control-plane-dlq-drain-sweep`
  rule) applied in its own PR first (#270), before the resource PR — perms before resources.

**Semantic shift:** the drain now **deletes every message it reads whether or not it could
notify**, so "total by construction" now means *never redeliver* rather than *safe to be
redelivered*. The redelivery loop the original FR-005 guarded against is gone because nothing
redelivers; the `_guarded_notify` belt stays so one bad message can't abort the sweep. The old
`batch_size = 5` / no-`ReportBatchItemFailures` rationale no longer applies.

**Trade-off:** a dead-lettered request surfaces within one sweep interval (~10 min) instead of
seconds — immaterial for a queue nothing watches live. Idle SQS receives fell from ~10⁵–10⁶/month
to a few thousand.
