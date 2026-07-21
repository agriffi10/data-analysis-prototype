# Spec: Control-Plane DLQ Drain → User Notification

**ID:** SPEC-126
**Status:** Draft
**Last Updated:** 2026-07-21
**Depends On:** SPEC-058 (notifications write pipeline), SPEC-107 (`cpcommon.auth` / `notify` / `messages`), SPEC-114 (the data-quality producer whose FR-005 this replaces)

## Overview

Every control plane dead-letters a request it cannot process. When that happens the user is
told **nothing at all**: no verb ran, so no `@notifies_on_failure` fired; no execution
started, so no `NotifyFailure` state was reached. The request simply vanishes, and the
person who made it is left watching a spinner that will never resolve — or worse, assuming
it worked.

This spec drains each control plane's **request DLQ** back into the notification pipeline
the user already reads, so a request that never started still reaches the person who made
it.

**It replaces SPEC-114 FR-005** (CloudWatch DLQ + `ExecutionsFailed` alarms), dropped
2026-07-21 by user decision. That FR would have shipped two alarms with **no notification
target** — visible in a console nobody watches, on one arc out of five, while the four
sibling control planes with the identical hole got nothing. The requirement behind it was
never "an operator should be able to find this"; it was **"the user needs to know their
request failed."** A notification does that. An unwatched alarm does not.

The user does **not** need a failed request to appear in their data-quality runs list, or
any other per-domain history. They need one sentence saying it didn't run.

## Scope

### In Scope

- **One shared drain Lambda** with an SQS event source on each control plane's **request
  DLQ**: data-quality, table-builder, table-share, shared-spaces.
- A **per-source descriptor** (domain wording + the body's token field name) so one
  function serves four queues without four copies.
- **Verified recipient identity**, derived from the token inside the dead-lettered body —
  never a body-asserted username (the whole point of every validate-authorize verb).
- **Forensic capture**: the dead-lettered body is logged before the drain consumes it,
  because consuming a DLQ message destroys the only copy.
- Self-poison safety: the drain must never dead-letter itself into an invisible loop.
- Execution-role IAM: `sqs:ReceiveMessage`/`DeleteMessage`/`GetQueueAttributes` on the four
  DLQ ARNs only, and `sqs:SendMessage` on the notifications queue ARN only.

### Out of Scope

- **The notifications DLQ itself.** Draining it *through the notifications queue* is
  circular: the queue that just failed to deliver is the one being asked to deliver the
  news. Nothing in this spec touches it, and FR-006 records that as the one hole this
  design cannot close.
- **Redrive / replay.** A dead-lettered request is not retried, re-queued, or repaired. The
  message says it didn't run; the user re-submits. Automatic replay of a poison request is
  how a poison request becomes a poison loop.
- **CloudWatch alarms.** Explicitly dropped (see Overview). This spec adds none, and
  SPEC-114 FR-005 is removed rather than deferred.
- Any change to the notifications writer, the inbox file, or the `/notifications` page —
  this is a **producer** only, reusing the SPEC-058 `create` contract unchanged.
- Per-domain failure history (a "failed runs" list). The dashboard specs stay
  completed-checks-only; this spec is what makes that acceptable.

---

## Functional Requirements

### FR-001: Every request DLQ drains into a notification

#### Description

Four request queues dead-letter today (`infra/modules/{data-quality,table-builder,table-share,shared-spaces}/sqs.tf`),
each with `maxReceiveCount = 3` and 14-day retention. All four get the same treatment from
one function.

#### Acceptance Criteria:

- [ ] A single drain Lambda has an SQS event source mapping on **each** of the four request
      DLQs. A test asserts the descriptor table covers every DLQ the repo provisions, so a
      fifth control plane cannot be added without either wiring it or failing the test.
- [ ] Each mapping carries a **source descriptor**: the domain's user-facing noun ("data
      quality check", "table", "share", "shared space") and the body field holding the
      actor's token. A comment records why the field name is per-domain and not a constant:
      data-quality, table-builder and shared-spaces put the token in **`idToken`**, while
      table-share puts it in **`actor`** (`table_share_validate_authorize.py:134`) — a
      single hard-coded field name would silently notify nobody for one of the four.
- [ ] One dead-lettered message produces **exactly one** notification to **exactly one**
      recipient. No fan-out, no batching several failures into one message.
- [ ] A batch of N dead-lettered messages produces N notifications; one message failing to
      resolve a recipient does not suppress the others in the batch.

### FR-002: The recipient is verified, never asserted

#### Description

A dead-lettered body is **untrusted input** — it is, by definition, a message the pipeline
refused. It may be malformed, and it may be hostile: the DLQ is reachable by anything that
can enqueue, and a body carrying `"username": "someone-else"` must never route a
notification to that someone else.

#### Acceptance Criteria:

- [ ] The recipient is the **verified `cognito:username`** from the body's token, obtained
      through `cpcommon.auth` — the same offline JWKS verification every validate-authorize
      verb uses. A test asserts a body whose `username`/`actor` field names a *different*
      user than the token's claim notifies the **token's** user.
- [ ] **Expiry is not enforced on this path, and signature/issuer/audience still are.** A
      comment records the reasoning: a dead-lettered message is old by construction (three
      failed receives, then an unbounded wait in the DLQ), and Cognito ID tokens live one
      hour — so enforcing `exp` would silently drop exactly the late-arriving failures this
      spec exists to surface. An expired but **authentically signed** token still proves who
      sent the request, and this path **grants nothing**: it selects a notification
      recipient and touches no user data. A test asserts an expired-but-validly-signed token
      still notifies, and that a token with a **bad signature** notifies nobody.
- [ ] A body with no token, an unparseable body, or a token that fails verification is a
      **logged no-op** — there is no trustworthy recipient, and guessing one is worse than
      silence (mirrors `tbcommon/notify.py`'s pre-identity posture and SPEC-114 FR-004).
- [ ] The verification relaxation is implemented as an **explicit, separately-named**
      `cpcommon.auth` entry point (e.g. `verified_username_ignoring_expiry`) — never a
      boolean flag threaded through `verified_username`. A comment records why: an
      `verify_exp=False` parameter on the function every authorization path calls is one
      wrong argument away from disabling expiry on a path that **does** grant access.
- [ ] A test asserts the standard `verified_username` still enforces expiry after this spec.

### FR-003: The message says it never ran

#### Acceptance Criteria:

- [ ] The message states, in the domain's own noun, that the request **could not be
      started** and that **nothing was created or changed** — the two facts the user needs
      to decide whether to re-submit. It does not say "failed", which reads as "it ran and
      went wrong."
- [ ] The message tells the user to **try again**, and to contact the Administrator if it
      recurs.
- [ ] **No raw AWS/Python/SQS text ever appears** (SPEC-106 FR-008). The dead-lettered body
      and the receive count stay in CloudWatch. A test asserts the emitted message contains
      none of the body's raw content.
- [ ] The message names **no path, table name, or space name** taken from the untrusted
      body. A comment records why: every other producer's message interpolates values a
      verb already **authorized**, and nothing here has authorized anything — echoing an
      attacker-supplied path back into a victim's inbox would make the notification pipeline
      a text-injection channel. A test asserts a body with a hostile `location` produces a
      message that does not contain it.
- [ ] A new reason code is registered through the `cpcommon.messages` domain hook, so it is
      a valid `TerminalError` reason like every other (SPEC-107 FR-005).
- [ ] `MessageGroupId` = the recipient username. `MessageDeduplicationId` = the dead-lettered
      body's `requestId` when it has one, so a message that dead-letters and is somehow
      re-delivered collapses to one notification; a body **without** a usable `requestId`
      falls back to content dedup rather than inventing an id.

### FR-004: The dead-lettered body survives consumption

#### Description

An SQS event source **deletes** the message on successful handling. The DLQ's 14-day
retention exists so an operator can inspect a poison request — and this spec's drain is
precisely what destroys that copy. The forensic value has to move somewhere before it does.

#### Acceptance Criteria:

- [ ] The **full dead-lettered body** and its `ApproximateReceiveCount` are logged before
      any emit, at a level that survives to CloudWatch under the log group's retention.
- [ ] The token is **redacted** from that log line. A comment records why: it is a bearer
      credential, and CloudWatch Logs has a wider read audience than the SQS queue it came
      from. A test asserts the token value never appears in the logged output.
- [ ] A comment records that consuming the DLQ trades the 14-day queue copy for the log
      group's retention, and that this is the deliberate cost of the user hearing about it.

### FR-005: The drain cannot poison itself

#### Description

If the drain throws, SQS redelivers, and a message that always throws is redelivered until
retention expires — burning invocations on a failure that, by construction, **nobody is
watching**, because the whole reason this spec exists is that the DLQ was invisible.

#### Acceptance Criteria:

- [ ] Every per-message path is total: an unparseable body, a missing token, a failed
      verification and a failed emit are each **caught, logged and treated as handled**, so
      the message is deleted rather than redelivered.
- [ ] Emission is best-effort via `cpcommon.notify.emit_notification` (already catches and
      swallows) — a notification failure never fails the drain.
- [ ] A test asserts a handler invocation over a batch containing a **completely malformed**
      message returns normally rather than raising.
- [ ] The drain's own DLQ-on-a-DLQ is **not** provisioned, and a comment records why: a
      handler that cannot fail does not need one, and a second-order DLQ would be exactly as
      invisible as the first-order one this spec exists to fix.

### FR-006: IAM, infra, and the hole that stays open

#### Acceptance Criteria:

- [ ] The drain's execution role gains `sqs:ReceiveMessage`, `sqs:DeleteMessage` and
      `sqs:GetQueueAttributes` on the **four DLQ ARNs only**, and `sqs:SendMessage` on the
      **notifications queue ARN only**. No other queue, no other action, no S3, no Glue.
- [ ] The deploy role is expanded for any new resource type per the CLAUDE.md infra rule,
      **in its own PR, applied before the resources land** (the deploy-perms-before-resources
      rule). A plan assertion confirms no other module's IAM changed.
- [ ] The Lambda follows the repo's code/infra split: Terraform owns the function and a
      placeholder; CI deploys the code (architecture.md → *Lambda code/infra split*).
- [ ] **The notifications DLQ is documented as out of scope in the module itself**, not just
      in this spec. A comment on the notifications module records that its DLQ is
      deliberately undrained because the drain's only delivery channel is the queue that
      DLQ implies is broken — and that the honest answer there is an operator-facing one,
      which this spec does not attempt.

---

## Data Model

```jsonc
// The source descriptor, one per wired DLQ (in the drain's own module).
{
  "source":     "data-quality",   // for logs; also selects the wording
  "noun":       "data quality check",
  "tokenField": "idToken"         // "actor" for table-share (see FR-001)
}

// The emitted SQS body — the SPEC-058 trusted-producer contract, unchanged.
{
  "action": "create",
  "username": "alice",            // the VERIFIED actor from the dead-lettered token
  "message": "Your data quality check couldn't be started, so nothing was created or changed. Please try again."
}
// MessageGroupId         = the recipient username
// MessageDeduplicationId = the body's requestId when present (FR-003)
// NO `link` — there is nothing to link to; the request never ran.
```

## File & Folder Structure

```
lambdas/control-plane-dlq-drain/dlq_drain.py            (+ tests)
lambdas/control-plane-common/cpcommon/auth.py           # + the expiry-relaxed entry point (FR-002)
lambdas/control-plane-common/cpcommon/messages.py       # + the could-not-start base reason
infra/modules/control-plane-dlq-drain/                  # function, role, 4 event source mappings
infra/modules/base/policies/github-actions-deploy*.tftpl # deploy-role expansion (own PR, first)
```

## Implementation Phases

### Phase 1: Deploy-role IAM

- Expand the deploy role for whatever resource types the new module introduces, and let it
  apply on its own before any resource references it (deploy-perms-before-resources).

### Phase 2: The drain

- `cpcommon.auth` expiry-relaxed entry point + the registered reason code; the drain handler
  (descriptor table, verified recipient, redacted forensic log, total per-message paths);
  unit tests for every FR-002/FR-003/FR-005 criterion.

### Phase 3: Infra + end-to-end

- The module, role, and four event source mappings; the notifications-module comment.
- End-to-end: hand-place a malformed body on the data-quality DLQ with a valid token and
  assert the actor's inbox receives one message that says it could not be started, names no
  path from the body, and carries no raw AWS text. Repeat once with a bad-signature token
  and assert nobody is notified.
- Completion ritual, including the SPEC-074 help sweep.
