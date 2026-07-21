# Spec: Data Quality — Notification Producer

**ID:** SPEC-114
**Status:** Completed
**Last Updated:** 2026-07-21
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
- The execution role's `sqs:SendMessage` on the **notifications queue ARN only** + the `NOTIFICATIONS_QUEUE_URL` env var.
- Data-quality reason codes registered through the `cpcommon.messages` domain hook (SPEC-107 FR-005).

### Out of Scope

- Any change to the notifications writer, the inbox file, or the `/notifications` page — this spec is a **producer** only.
- A notification per file. One request, one notification: a folder with 40 problem files produces one message carrying the top issues, not 40 messages.
- Notifying anyone but the actor. Data quality has exactly one recipient; there is no fan-out (unlike Table Share).
- **The residual class of failures where nothing ever ran** — a malformed body the Pipe rejects, which exhausts its receives and lands in the **DLQ**. No verb executed and no execution started, so nothing in this spec can reach the user. **SPEC-126** drains that DLQ back into the notification pipeline; see the FR-004 note below.
- **CloudWatch alarms.** An earlier FR-005 here provisioned DLQ + `ExecutionsFailed` alarms as an *operator* backstop. **Removed 2026-07-21 (user decision):** it would have shipped two alarms with no notification target — visible in a console nobody watches, on one arc out of five — when the actual requirement was that the **user** hear about it. Replaced wholesale by SPEC-126.

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
- [ ] **That test must assert against `dqcommon`'s OWN domain table, never `cpmessages.is_known_reason`.** `_known_reasons` is a process-global set extended by every domain layer at import, and `pytest lambdas/` imports tbcommon/tscommon alongside dqcommon — so `is_known_reason("unsupported_format")` is True in the test process purely because **tbcommon** registered it (`tbcommon/messages.py:25-27`), while the deployed data-quality function (cpcommon + dqcommon + polars, no tbcommon) would raise `ValueError` at the raise site. An `is_known_reason` assertion therefore passes for a code this arc never registered — the exact production break SPEC-110 FR-007 exists to prevent, re-introduced in the test meant to catch it.
- [ ] `unsupported_format` for an `.xlsx` source is **plain** — Excel is unsupported everywhere (the file-converter arc does not handle it either); the message carries no convert-first guidance.
- [ ] **`compressed_source_too_large`** explains that a large `.gz` cannot be split across workers and tells the user to **decompress it or split it into several smaller objects** — not that "the file is too big," which is untrue of the same data uncompressed.
- [ ] **`unreadable_header`** names the file whose header/schema could not be read, so the user knows which one to look at.
- [ ] **`too_many_columns`** names the column count and the limit.
- [ ] `query_timeout` tells the user the source is too large, rather than reporting an internal timeout.
- [ ] **Raw AWS / Athena / Python text never appears** in a notification body (SPEC-106 FR-008). The raw Athena `StateChangeReason` stays in CloudWatch and the SFN execution history — the same posture as `lambdas/table-builder-common/tbcommon/notify.py:43-44`.
- [ ] `unauthorized` / `forbidden` collapse to a single "You don't have access…" message leaking no path or space name (mirroring `tbcommon/messages.py:41-42`).
- [ ] Reason codes are registered through the `cpcommon.messages` **domain-scoped** registry hook — registered codes are exported constants; an unregistered code raises at raise-time (SPEC-107 FR-005).
- [ ] Substitution uses `str.replace` on named tokens, never `str.format` — a literal brace in a path or column name must not raise (`tbcommon/messages.py:45-47`).
- [ ] **The per-request tokens reach the emitter via an optional `tokens` mapping on `cpcommon.errors.TerminalError`** (default `None`, so table-builder and table-share are untouched), because the emit happens in the decorator, far from the raise site, and `TerminalError` currently carries only `reason` + a free-prose `detail`. Without it the `{object}`/`{count}`/`{key}`/`{formats}` markers already in `dqcommon/messages.py` render **literally** and the four criteria above cannot be met. The ~10 data-quality raise sites pass `tokens=` alongside `detail`; a test asserts every reason whose body contains a marker is raised with a matching token, so a new marker cannot ship unfilled.
- [ ] `tokens` values are **never raw AWS/Athena text** — they are S3 keys, column names and counts the verb already holds. A comment records the distinction from `detail`, which *is* allowed raw text precisely because it never reaches a user.

### FR-003: No silent failures

#### Acceptance Criteria:

- [ ] Every verb handler carries `@notifies_on_failure(step)`: `TerminalError` and `TransientError` pass through un-notified (the raise site already notified, or the SFN will retry), and **any other exception** emits an `unexpected_error` notification to the actor and re-raises.
- [ ] A test asserts a bare `KeyError` in any verb still reaches the user as a friendly notification.
- [ ] A failure inside `drop-temp-tables` (SPEC-111 FR-005) does not mask the original failure reason the user is notified about. A test asserts the user sees the real cause, not a cleanup error.
- [ ] **A cleanup failure AFTER a written report emits no failure notification at all** (added 2026-07-21, user decision — the edge originally shipped as accepted). `drop-temp-tables` runs on both paths: on the failure path a cleanup error collapses into the real cause via the shared dedup id, but on the SUCCESS path there is no earlier failure to collapse into, so the user would receive a success notification *and* a contradicting failure one. Three layers close it, and the third needs the state machine: (1) `_drop` already swallows a failed DROP, so the ordinary Glue error never becomes a terminal; (2) the dedup collapse covers the failure path; (3) `RecordFailure` carries **`$.reportKey`**, and `notify-failure` stays silent when it is non-null — which can only mean the report was written, the success notification already went out, and what died afterwards was the cleanup **Lambda itself** (an import error, a timeout), the one class no verb-side guard can reach.
- [ ] **`reportKey` is seeded null by `validate-authorize` AND by `ValidateFailureSeed`**, for the same reason `$.location` is (SPEC-112): a Pass state's JSONPath hard-fails on an ABSENT key with an uncatchable `States.Runtime`, killing the execution before `NotifyFailure` and leaving a failed request with no notification at all. A test asserts the key is **present** (not merely falsy) in validate-authorize's output.
- [ ] A **general ASL invariant** in `test_state_machines_cpcommon.py` asserts that every Pass state reachable from a failure seed reads only keys that seed supplies — so this trap becomes a test failure in any arc rather than a silent production one. A test confirms it fires for the SPEC-112 `location` case too.

### FR-004: Every failure notifies — including the ones no verb can catch

#### Description

**This FR is load-bearing for SPEC-123.** The runs dashboard lists **completed checks only** (user decision, 2026-07-12), and that is acceptable **on the explicit condition that a failed check always reaches the user with a concrete reason**. If a failure can happen silently, the dashboard becomes a list that lies by omission — the user sees nothing on the page, nothing in their inbox, and concludes the check simply never ran.

`@notifies_on_failure` (FR-003) is a decorator on the **verb handlers**. It catches an exception *inside a verb*. It does **nothing** when the failure happens where no verb code is running:

- a Lambda that fails at **import** (a bad layer, a config value that fails validate-at-init);
- a **Step Functions-level** error (a state timeout, a payload-size failure, a task that cannot be invoked);
- a message that **never starts an execution** at all — a malformed body the Pipe rejects, which exhausts its receives and lands in the **DLQ**.

The first two are fixable in the state machine, and this FR fixes them. **The third is not fixable here at all** — nothing ran, so nothing in this arc can notify — and it is handed to **SPEC-126**, which drains every control plane's request DLQ back into the notification pipeline. That is the condition SPEC-123's completed-checks-only dashboard depends on, and it is met by SPEC-126 rather than by an alarm.

#### Acceptance Criteria:

- [ ] The state machine's **`NotifyFailure`** Task (on the failure path, after `DropTempTables`/`RecordFailure`, before `Fail`) is **wired to the `notify-failure` Lambda provisioned as a placeholder in SPEC-108 FR-002**; this spec supplies its real handler and does not create a new function. **Notification delivery therefore does not depend on the failing verb being able to emit it.**
- [ ] `NotifyFailure` derives its reason by calling **`cpcommon.errors.failure_reason(event.get("error"))`** on the RAW `{Error, Cause}` object `RecordFailure` carries — there is no pre-decoded `reason` key and there must not be one. **No ASL state may decode an error Cause** *(corrected 2026-07-21 — see the `ParseError` removal)*: `States.StringToJson($.error.Cause)` raises `States.Runtime`, which is neither retriable nor catchable, whenever `Cause` is absent or is not JSON (`States.Timeout`, `States.DataLimitExceeded`, `Lambda.Unknown` — all verified live). The raw `$.error` is carried through to the terminal state and decoded in Python with `cpcommon.errors.failure_reason`. It falls back to `unexpected_error` where it cannot — it **never** terminates without emitting **when a verified actor exists**; a pre-identity failure (e.g. a garbage token) is a **logged no-op** — there is no trustworthy recipient (mirrors `tbcommon/notify.py`).
- [ ] Because both `@notifies_on_failure` and `NotifyFailure` can fire for the same failure, the **`{requestId}:{step}` dedup id** (FR-005) collapses them to one message. A test forces a verb failure and asserts the user receives **exactly one** notification, not two.
- [ ] **The dedup assumption is recorded in a comment:** the decorator emit and the `NotifyFailure` emit land **seconds apart**, so SQS FIFO's **5-minute deduplication window** collapses them — the collapse depends on that window, and the comment says so.
- [ ] A test forces a **Lambda import failure** and asserts the user still receives a friendly notification.
- [ ] A test forces a **Step Functions-level** failure (a state that fails without a verb exception) and asserts the user still receives a friendly notification.
- [ ] The `NotifyFailure` state is reached **after** `DropTempTables` (SPEC-111 FR-005), so a cleanup failure cannot suppress the user's notification.

### FR-005: Best-effort emission, correctly scoped IAM

#### Acceptance Criteria:

- [ ] Emission is **best-effort**: an unset `NOTIFICATIONS_QUEUE_URL` is a logged no-op, a missing recipient is a logged no-op, and any exception during send is logged and swallowed — **a notification failure never fails the pipeline outcome** (`cpcommon.notify.emit_notification`).
- [ ] `MessageGroupId` = the recipient username (per-user single-writer ordering, SPEC-058).
- [ ] `MessageDeduplicationId` = `{requestId}:{step}` (mirroring `tbcommon/notify.py:30-32`) — which is why SPEC-109 FR-001 requires `requestId` on every envelope.
- [ ] **`{step}` is a single shared token — `failure` — for EVERY failure emit in the arc, and `completed` for the success emit.** A comment records why it is not the per-verb name: `NotifyFailure` runs after the execution has already left the failing verb and **cannot know which verb raised**, so a per-verb step would make the decorator's id and `NotifyFailure`'s id differ and the user would get **two** notifications for one failure — the exact outcome FR-004's dedup criterion forbids. Only one verb can fail per execution, so one token per outcome is sufficient to distinguish them. A test asserts the decorator's dedup id and `NotifyFailure`'s dedup id are byte-identical for the same request.
- [ ] Where the decorator and `NotifyFailure` both fire, **the decorator's message is the one delivered** (it emits first, inside the Lambda, before the Catch routes). That ordering is what lets the delivered message carry the per-request tokens (`{object}`, `{count}`) that `NotifyFailure` — which recovers only a reason code from the raw `$.error` — cannot. A comment records it.
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
// MessageDeduplicationId = "{requestId}:{step}"    (collapses decorator + NotifyFailure emits, FR-004/FR-005)
```

## File & Folder Structure

```
lambdas/data-quality-notify-failure/dq_notify_failure.py   (+ tests)  # the REAL handler for the SPEC-108 placeholder — wired, not created, here
lambdas/data-quality-common/dqcommon/messages.py   # + success_message (verdict/top issues/qualifier); reason codes already registered by 109-111
lambdas/data-quality-common/dqcommon/notify.py     # NEW: the domain emitters + notifies_on_failure + the report-link builder
lambdas/control-plane-common/cpcommon/notify.py    # + optional `link` on emit_notification (SPEC-113 FR-008 wire field)
lambdas/control-plane-common/cpcommon/errors.py    # + optional `tokens` on TerminalError (FR-002)
lambdas/data-quality-*/…                            # @notifies_on_failure on every handler; emit at terminals
infra/modules/data-quality/policies/execution.json.tftpl   # + sqs:SendMessage on the notifications queue
infra/modules/data-quality/iam.tf                          # + notifications_queue_arn into the templatefile() call
apps/portal/src/features/data-quality/DataQualityDialog.tsx    # restore the "you'll be notified" copy
apps/portal/src/features/data-quality/DataQualityDialog.test.tsx  # DELETE the SPEC-113 guard test
apps/portal/src/features/help/helpContent.ts               # SPEC-074 sweep: the notification is now real
```

**Already wired by SPEC-108→113 — this spec changes neither:** the `NotifyFailure` state in
`state-machine.asl.json.tftpl` (it already targets the notify-failure function, already sits
after `DropTempTablesOnFailure`/`RecordFailure`, and already carries the raw `$.error`), and
the `NOTIFICATIONS_QUEUE_URL` env in `lambda.tf`.

**The ONE ASL change in scope** (added 2026-07-21 with the FR-003 cleanup criterion — the
spec originally forbade touching the state machine at all): `ValidateFailureSeed` and
`RecordFailure` each gain **`reportKey`**, seeded null and read respectively. No state is
added, removed, or re-pointed, and **no state decodes an error Cause** — the decision that
rule protects is untouched. Any *other* diff to the state machine is still a signal that
something was misread.

```
infra/modules/data-quality/state-machine.asl.json.tftpl   # + reportKey on the two failure Pass states
lambdas/control-plane-common/test_state_machines_cpcommon.py  # + the seed-covers-terminal invariant
```

## Implementation Phases

### Phase 1: Messages + emission

- Verify (do not re-do) that every data-quality reason code is registered through the `cpcommon.messages` hook — SPEC-109→111 already registered all fourteen — and add the test that no raise site can use an unregistered one, asserting against `dqcommon`'s own `_BODIES` table per FR-002.
- `cpcommon`: optional `link` on `emit_notification`, optional `tokens` on `TerminalError`.
- `dqcommon/notify.py`: the domain emitters, `notifies_on_failure(step)`, and the report-link builder; `dqcommon/messages.py`: `success_message`.
- Emit success from `assemble-report` (verdict + top issues + **the `/data-quality/{space}/{requestId}` report link** + the approximate qualifier); implement the real `notify-failure` handler; decorate every handler with `@notifies_on_failure`; pass `tokens=` at the raise sites.
- Restore the "you'll be notified" copy in the dialog + toast + help, and **delete the guard test** in `DataQualityDialog.test.tsx`.

### Phase 2: IAM + end-to-end

- `sqs:SendMessage` on the notifications queue ARN only (the `NOTIFICATIONS_QUEUE_URL` env is already wired); confirm no catalog permission crept in.
- **Live end-to-end is DEFERRED to the end of the arc (user decision, 2026-07-21):** no further live smoke tests until the data-quality feature specs (114, 123, 124) are all built, then one pass covering the arc. The scenarios below are what that pass must cover for this spec, and they are recorded here so they are not lost:
  - a folder with a known drifting column and a large file → the actor's inbox receives **one** message that names the issue, links to the report view, and **says the encoding figure was sampled**;
  - a check that fails authorization → one friendly failure message with no raw AWS text;
  - an `.xlsx` file → the message says the format is unsupported, with no convert-first guidance.
- Completion ritual, including the SPEC-074 help sweep — the arc is now user-visible end to end — and a one-line Key Decisions entry in CLAUDE.md pointing at `docs/data-quality-architecture.md`.
