---
type: Decision
title: "Control-plane DLQ drain → user notification (SPEC-126)"
description: "**The DLQ drain** sweeps request DLQs and notifies from **`identity.actor`**; its redaction blanks the two LEGACY token fields, one of which holds a token in any message enqueued before the API stopped sending one. Two are undrained: notifications (circular), feedback (no identity in its body)."
---

Replaces SPEC-114 FR-005. Every control plane dead-letters a request it cannot process, and until this shipped the user was told **nothing at all** — no verb ran, so no `@notifies_on_failure` fired; no execution started, so no `NotifyFailure` state was reached. **One shared drain Lambda** (`lambdas/control-plane-dlq-drain/`, `infra/function-control-plane-dlq-drain.tf`) sits on all four request DLQs (data-quality, table-builder, table-share, shared-spaces) and turns each dead-lettered message into one notification. Four things are load-bearing: (1) the recipient is the **verified `cognito:username` from the token inside the body** — a body-asserted `username` would let anyone route a notification to anyone; (2) **expiry is not enforced** on this path (`cpcommon.auth.verified_username_ignoring_expiry`, a **separately named** entry point, never a flag on the function every authorization path calls) because a dead-lettered message is old by construction while an ID token lives an hour — signature/issuer/audience still are, and this path **grants nothing**; (3) **no value from the untrusted body reaches the message** — every other producer interpolates what a verb already authorized, nothing here has authorized anything, and echoing an attacker-supplied path into a victim's inbox would make notifications a text-injection channel; (4) every per-message path is **total** — a throw means redelivery, and a message that always throws loops until retention expires, burning invocations on a failure nobody is watching, which is the invisibility this exists to end. The dead-lettered body is logged (**token redacted**) before the drain consumes it, trading the DLQ's 14-day copy for the log group's.

> **Superseded in part by SPEC-201 (2026-08-30):** points (1) and (2). The recipient is the
> `identity.actor` the API stamped, trusted because SPEC-200 FR-008 made the API the only principal
> that may write these queues — provenance rather than cryptography. So (2) is void: there is no
> expiry to relax and no `*_ignoring_expiry` entry point left, and the per-source `token_field`
> column is gone rather than set to one value on every row. The redaction did **not** go with it:
> it now blanks the two LEGACY top-level token fields, because a message enqueued before the API
> stopped sending a token carries one and is exactly what this drain surfaces. It must not be
> pointed at `identity` — top-level replacement would blank the block the recipient was just read
> from. Points (3) and (4),
> and the undrained notifications DLQ, are unchanged.
>
> **Narrowed (2026-09-10):** point (3) governs the MESSAGE and still holds. The row's `payload`
> now carries the body's `requestId` and nothing else from it — see *`requestId` rides on every
> row*.

The **notifications DLQ is deliberately undrained** and is the one hole this cannot close — the drain's only delivery channel is the queue that DLQ implies is broken; the honest answer there is operator-facing. **No redrive, no replay, no CloudWatch alarms** (an alarm with no target told the user nothing — the user decision that killed SPEC-114 FR-005). **Follow-up (2026-07-22): the four SQS event-source mappings became one EventBridge scheduled sweep** (`rate(10 minutes)`) — the mappings idle-long-polled four almost-always-empty DLQs around the clock, and that was the bulk of the account's SQS request volume (it was tripping the 1M/month free tier). The handler now polls all four DLQs itself (`DLQ_ARNS`, the same ARNs as an env JSON list) and **deletes every message it reads whether or not it could notify**, so "total by construction" now means *never redeliver* rather than *safe to be redelivered* — the redelivery-loop hazard in (4) is moot because nothing redelivers (the `_guarded_notify` belt stays, so one bad message can't abort the sweep). A resource-based `lambda:AddPermission` lets the rule invoke the function, so **no invoke role** is needed (unlike EventBridge Scheduler); the execution role is unchanged (it already held the four DLQ read/delete grants the mappings polled with). Cost fell from ~10⁵–10⁶ idle receives/month to a few thousand; the price is that a dead-lettered request surfaces within one interval (~10 min) rather than seconds, immaterial for a queue nothing watches live. Detail: `spec-delivery/SPEC-126`.

## History

### 2026-09-10

- **Changed:** The row's `payload` now carries the body's `requestId`, while the rule that nothing from the body reaches the message stands.

### 2026-08-30

- **Changed:** SPEC-201 made the recipient the stamped `identity.actor`, voiding the token recovery and the expiry relaxation; the redaction now blanks the two legacy token fields.

### 2026-07-22

- **Changed:** The four SQS event-source mappings became one scheduled sweep that polls every DLQ and deletes each message it reads.

### 2026-07-21

- **Settled:** SPEC-126.
