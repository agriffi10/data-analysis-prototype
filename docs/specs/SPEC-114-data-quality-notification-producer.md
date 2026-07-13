# Spec: Data Quality — Notification Producer

**ID:** SPEC-114
**Status:** Draft
**Last Updated:** 2026-07-13
**Depends On:** SPEC-058 (notifications write pipeline), SPEC-107 (`cpcommon.notify` / `messages`), SPEC-108 (the `notify-failure` placeholder Lambda this spec wires), SPEC-112 (the summary payload), SPEC-113 (the UI + the report view this links to)

> **Read `docs/data-quality-architecture.md` §8 first.** Mirrors SPEC-072 (table-builder) and SPEC-094 (table-share).

## Overview

Close the loop. The check is asynchronous and the browser never waits, so the **notification is the completion channel** — the only thing that tells the user their check finished, what the verdict is, and where to read the detail.

Two requirements here are not boilerplate.

**The notification must link to the report view.** SPEC-113 hides the reports folder from the file browser. If the notification only names a key, the user has no way to reach the report at all.

**The notification must say when a figure is approximate.** SPEC-112 sets `hasApproximateFigures` precisely so this spec can honour it. An unqualified "clean" over a sampled encoding scan is a lie, and it is the kind of lie a user would only discover after trusting it.

## Scope

### In Scope

- A **success** notification: the verdict, the top issues, a **link to the report view**, and an explicit qualifier when any figure is sampled or approximate.
- A **failure** notification for **every** terminal failure — including failures **no verb can catch** (a Lambda import error, a Step Functions-level error), via the `NotifyFailure` state on the failure path (FR-004). This spec **wires** that state to the **`notify-failure` Lambda SPEC-108 provisioned as a placeholder** — no new function appears here. **This is the condition on which SPEC-123's completed-checks-only dashboard was accepted** (user decision, 2026-07-12): a check that fails must always reach the user with a concrete reason.
- `@notifies_on_failure` on every verb handler, so an unexpected crash still reaches the user.
- **DLQ and `ExecutionsFailed` CloudWatch alarms** (FR-005) — the operator backstop for the residual class of failures that cannot notify anyone, because nothing ever ran.
- The execution role's `sqs:SendMessage` on the **notifications queue ARN only** + the `NOTIFICATIONS_QUEUE_URL` env var.
- Data-quality reason codes registered through the `cpcommon.messages` domain hook (SPEC-107 FR-005).

### Out of Scope

- Any change to the notifications writer, the inbox file, or the `/notifications` page — this spec is a **producer** only.
- A notification per file. One request, one notification: a folder with 40 problem files produces one message carrying the top issues, not 40 messages.
- Notifying anyone but the actor. Data quality has exactly one recipient; there is no fan-out (unlike Table Share).

---

## Functional Requirements

### FR-001: Success notification

#### Acceptance Criteria:

- [ ] On a successful check, exactly **one** notification is emitted to the **actor** — the verified `cognito:username`, never a body value.
- [ ] The message states the verdict (clean, or issues found), names the checked location, and **links to the SPEC-113 report view at `/data-quality/{space}/{requestId}`** — the space segment included, matching SPEC-113 FR-005's route exactly. A test asserts the link is present on every success message **and that it carries the space**.
- [ ] A comment records why the space is in the link and not just the `requestId`: the report lives at `{space}/_data-quality-reports/{requestId}/report.json`, so a link without the space **cannot locate a shared-space report** — the notification would deep-link the user to a permanent "not found", which is worse than no link at all. A test builds the link for a **shared-space** check and asserts it resolves.
- [ ] The link builder honours SPEC-113 FR-005's **resolution precedence**: the actor's own username always resolves personal, and shared-space names are checked only when the segment ≠ the username — so the producer never mints a link the view would resolve to the wrong space.
- [ ] When issues were found, the message carries the **top issues** from SPEC-112's summary — not the full report, which stays a file.
- [ ] **When `hasApproximateFigures` is true, the message says so explicitly** — e.g. that the encoding check examined only a sample of a large file, or that the duplicate count could not be computed, or that type consistency was skipped on a Parquet source. A test asserts that a summary with `hasApproximateFigures: true` never produces an unqualified "clean" message.

### FR-002: Failure notification

#### Acceptance Criteria:

- [ ] Every terminal failure emits one notification to the actor with a **friendly** reason. The registered set is **exhaustive** and must cover every terminal any verb can raise: **`invalid_request`** (SPEC-109 FR-001/FR-004 — the malformed-envelope terminal), `unauthorized`, `forbidden`, `unsupported_format`, `mixed_formats`, `no_data_files`, `too_many_files`, **`unreadable_header`** (SPEC-110 FR-005), **`compressed_source_too_large`** (SPEC-110 FR-004), **`too_many_partition_values`** (SPEC-110 FR-005 — the `DQ_MAX_PARTITION_VALUES` breach), **`too_many_columns`** (SPEC-111 FR-001), `query_failed`, `query_timeout`, `unexpected_error`.
- [ ] A comment records why the set must be exhaustive: registered codes are **exported constants**, and an **unregistered code raises at raise-time** (SPEC-107 FR-005) — so a missing code is not a vague message, it is a raise site that blows up when the failure it exists for occurs. A test walks every `TerminalError` raise site anywhere in the arc — **including the typed terminal `cpcommon.events` raises for a malformed envelope** — and asserts each code is registered.
- [ ] `unsupported_format` for an `.xlsx` source is **plain** — Excel is unsupported everywhere (the file-converter arc does not handle it either); the message carries no convert-first guidance.
- [ ] **`compressed_source_too_large`** explains that a large `.gz` cannot be split across workers and tells the user to **decompress it or split it into several smaller objects** — not that "the file is too big," which is untrue of the same data uncompressed.
- [ ] **`unreadable_header`** names the file whose header/schema could not be read, so the user knows which one to look at.
- [ ] **`too_many_columns`** names the column count and the limit.
- [ ] `query_timeout` tells the user the source is too large, rather than reporting an internal timeout.
- [ ] **Raw AWS / Athena / Python text never appears** in a notification body (SPEC-106 FR-008). The raw Athena `StateChangeReason` stays in CloudWatch and the SFN execution history — the same posture as `lambdas/table-builder-common/tbcommon/notify.py:43-44`.
- [ ] `unauthorized` / `forbidden` collapse to a single "You don't have access…" message leaking no path or space name (mirroring `tbcommon/messages.py:41-42`).
- [ ] Reason codes are registered through the `cpcommon.messages` **domain-scoped** registry hook — registered codes are exported constants; an unregistered code raises at raise-time (SPEC-107 FR-005).
- [ ] Substitution uses `str.replace` on named tokens, never `str.format` — a literal brace in a path or column name must not raise (`tbcommon/messages.py:45-47`).

### FR-003: No silent failures

#### Acceptance Criteria:

- [ ] Every verb handler carries `@notifies_on_failure(step)`: `TerminalError` and `TransientError` pass through un-notified (the raise site already notified, or the SFN will retry), and **any other exception** emits an `unexpected_error` notification to the actor and re-raises.
- [ ] A test asserts a bare `KeyError` in any verb still reaches the user as a friendly notification.
- [ ] A failure inside `drop-temp-tables` (SPEC-111 FR-005) does not mask the original failure reason the user is notified about. A test asserts the user sees the real cause, not a cleanup error.

### FR-004: Every failure notifies — including the ones no verb can catch

#### Description

**This FR is load-bearing for SPEC-123.** The runs dashboard lists **completed checks only** (user decision, 2026-07-12), and that is acceptable **on the explicit condition that a failed check always reaches the user with a concrete reason**. If a failure can happen silently, the dashboard becomes a list that lies by omission — the user sees nothing on the page, nothing in their inbox, and concludes the check simply never ran.

`@notifies_on_failure` (FR-003) is a decorator on the **verb handlers**. It catches an exception *inside a verb*. It does **nothing** when the failure happens where no verb code is running:

- a Lambda that fails at **import** (a bad layer, a config value that fails validate-at-init);
- a **Step Functions-level** error (a state timeout, a payload-size failure, a task that cannot be invoked);
- a message that **never starts an execution** at all — a malformed body the Pipe rejects, which exhausts its receives and lands in the **DLQ**.

The first two are fixable in the state machine. The third is not, and needs an operational backstop.

#### Acceptance Criteria:

- [ ] The state machine's **`NotifyFailure`** Task (on the failure path, after `ParseError` and `DropTempTables`/`RecordFailure`, before `Fail` — SPEC-108's canonical order) is **wired to the `notify-failure` Lambda provisioned as a placeholder in SPEC-108 FR-002**; this spec supplies its real handler and does not create a new function. **Notification delivery therefore does not depend on the failing verb being able to emit it.**
- [ ] `NotifyFailure` derives its reason from the parsed error where one exists, and falls back to `unexpected_error` where it cannot — it **never** terminates without emitting **when a verified actor exists**; a pre-identity failure (e.g. a garbage token) is a **logged no-op** — there is no trustworthy recipient (mirrors `tbcommon/notify.py`).
- [ ] Because both `@notifies_on_failure` and `NotifyFailure` can fire for the same failure, the **`{requestId}:{step}` dedup id** (FR-006) collapses them to one message. A test forces a verb failure and asserts the user receives **exactly one** notification, not two.
- [ ] **The dedup assumption is recorded in a comment:** the decorator emit and the `NotifyFailure` emit land **seconds apart**, so SQS FIFO's **5-minute deduplication window** collapses them — the collapse depends on that window, and the comment says so.
- [ ] A test forces a **Lambda import failure** and asserts the user still receives a friendly notification.
- [ ] A test forces a **Step Functions-level** failure (a state that fails without a verb exception) and asserts the user still receives a friendly notification.
- [ ] The `NotifyFailure` state is reached **after** `DropTempTables` (SPEC-111 FR-005), so a cleanup failure cannot suppress the user's notification.

### FR-005: The backstop for failures that cannot notify at all

#### Description

Two holes remain that **no amount of state-machine wiring can close**, and pretending otherwise would be worse than naming them.

**A message that never starts an execution** — a malformed body, a Pipe failure — exhausts its receives and lands in the **DLQ**. Nothing has run, so nothing can notify. **And notification emission is best-effort by design** (FR-006): if the `SendMessage` to the notifications queue fails, it is logged and swallowed, because a notification failure must never fail the pipeline.

So there is a residual class of failures the user cannot be told about. The answer is not to pretend it away; it is to make sure **an operator** finds out. The DLQ alarm was previously deferred across both arcs as a "known cross-cutting gap." **It cannot be deferred any longer**, because the dashboard's completeness now *depends* on notifications being the failure channel.

#### Acceptance Criteria:

- [ ] A **CloudWatch alarm on the data-quality DLQ** fires when its depth exceeds zero. A comment records why: a message in the DLQ is a check the user asked for, will never hear about, and will not see on the dashboard.
- [ ] A **CloudWatch alarm on the state machine's `ExecutionsFailed`** metric fires on any failed execution — the backstop for a failure that somehow reaches `Fail` without notifying.
- [ ] Both alarms are provisioned in `infra/modules/data-quality/` and the deploy role is expanded for the new resource type (CloudWatch alarms), per the CLAUDE.md infra rule.
- [ ] Neither alarm has a notification target wired in v1 (there is no on-call rotation) — they exist so the failure is **visible in the console** rather than invisible everywhere. A comment records that a target is the obvious follow-up and that shipping the alarm without one is deliberate, not an oversight.

### FR-006: Best-effort emission, correctly scoped IAM

#### Acceptance Criteria:

- [ ] Emission is **best-effort**: an unset `NOTIFICATIONS_QUEUE_URL` is a logged no-op, a missing recipient is a logged no-op, and any exception during send is logged and swallowed — **a notification failure never fails the pipeline outcome** (`cpcommon.notify.emit_notification`).
- [ ] `MessageGroupId` = the recipient username (per-user single-writer ordering, SPEC-058).
- [ ] `MessageDeduplicationId` = `{requestId}:{step}` (mirroring `tbcommon/notify.py:30-32`) — which is why SPEC-109 FR-001 requires `requestId` on every envelope.
- [ ] The execution role gains `sqs:SendMessage` on the **notifications queue ARN only** — no other queue, no other SQS action.
- [ ] The Glue/Athena/LF grants from SPEC-111 are unchanged; this spec adds no catalog permission. A plan assertion confirms it.

---

## Data Model

The emitted SQS body — the producer side of the notification wire contract (the writer is SPEC-058, amended by SPEC-113 FR-008 to persist `link`):

```jsonc
// Body sent to the notifications queue
{
  "action": "create",                       // trusted-producer-only (SPEC-058)
  "username": "alice",                      // the verified actor — the recipient
  "message": "Data quality check on alice/sales/ finished: issues found — …",
  "link": "/data-quality/alice/7f3a…"       // in-app path only (SPEC-113 FR-008); space per the precedence rule
}
// MessageGroupId         = the recipient username  (per-user single-writer ordering, SPEC-058)
// MessageDeduplicationId = "{requestId}:{step}"    (collapses decorator + NotifyFailure emits, FR-004/FR-006)
```

## File & Folder Structure

```
lambdas/data-quality-notify-failure/notify_failure.py      (+ tests)  # the REAL handler for the SPEC-108 placeholder — wired, not created, here
lambdas/data-quality-common/dqcommon/messages.py   # reason codes → friendly text (registered via cpcommon)
lambdas/data-quality-*/…                            # @notifies_on_failure on every handler; emit at terminals
infra/modules/data-quality/state-machine.asl.json.tftpl    # NotifyFailure state → the notify-failure Lambda
infra/modules/data-quality/policies/execution.json.tftpl   # + sqs:SendMessage on the notifications queue
infra/modules/data-quality/lambda.tf                       # + NOTIFICATIONS_QUEUE_URL env
```

## Implementation Phases

### Phase 1: Messages + emission

- Register **every** data-quality reason code through the `cpcommon.messages` hook (incl. `invalid_request`, `unreadable_header`, `compressed_source_too_large`, `too_many_partition_values`, `too_many_columns`) and test that no raise site can use an unregistered one; emit success from `assemble-report` (verdict + top issues + **the `/data-quality/{space}/{requestId}` report link** + the approximate qualifier) and failure from each terminal path; implement the `notify-failure` handler and wire the `NotifyFailure` state to it; decorate every handler with `@notifies_on_failure`.

### Phase 2: IAM + env + end-to-end

- `sqs:SendMessage` on the notifications queue ARN only; the `NOTIFICATIONS_QUEUE_URL` env var; confirm no catalog permission crept in.
- End-to-end: run a check on a folder with a known drifting column and a large file, and assert the actor's inbox receives **one** message that names the issue, links to the report view, and **says the encoding figure was sampled**. Run a check that fails authorization and assert one friendly failure message with no raw AWS text. Run a check on an `.xlsx` file and assert the message says the format is unsupported — with no convert-first guidance.
- Completion ritual, including the SPEC-074 help sweep — the arc is now user-visible end to end — and a one-line Key Decisions entry in CLAUDE.md pointing at `docs/data-quality-architecture.md`.
