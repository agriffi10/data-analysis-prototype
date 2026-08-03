# Spec: File Converter — Notification Producer

**ID:** SPEC-121
**Status:** Cancelled
**Last Updated:** 2026-07-13
**Depends On:** SPEC-058 (notifications write pipeline), SPEC-107 (`cpcommon.notify` / `messages`), SPEC-115 (the `notify-failure` placeholder this spec wires), SPEC-119 (the summary payload), SPEC-120 (the UI that starts the conversion)

> **Read `docs/file-converter-architecture.md` §7 first.** Mirrors SPEC-072 (table-builder) and SPEC-094 (table-share).

## Overview

Close the loop. Conversion is asynchronous and the browser never waits, so the **notification is the completion channel** — the only thing that tells the user their files converted, **where the output landed**, and whether anything about the result needs their attention.

That last part is not boilerplate. SPEC-117's reconciliation can **succeed while quietly turning a column into text**, when two files disagree on a type in a way no common type resolves. The conversion "worked," the table Table Builder later builds over the output will be perfectly valid, and the column will be text instead of a number. **This notification is the only moment the user can learn that.** A success message that says only "converted 12 files" is a spec violation.

## Scope

### In Scope

- A **success** notification naming the destination, the object count, and **any string-fallback columns** with the types that conflicted.
- A **failure** notification for every terminal failure, with friendly wording — and, when the `UNLOAD` had already started, **a statement that partial output may remain, naming the path**, because the pipeline holds no delete permission and cannot remove it (SPEC-116 FR-006 / SPEC-118 FR-004).
- `@notifies_on_failure` on every verb handler, so an unexpected crash still reaches the user.
- **Wiring the `notify-failure` Lambda** (provisioned as a placeholder in SPEC-115 FR-002) into a dedicated **`NotifyFailure`** state on the failure path, plus the ASL change that routes it.
- **DLQ + `ExecutionsFailed` CloudWatch alarms** (`infra/modules/file-converter/alarms.tf`) — the operator backstop SPEC-115 deferred here.
- The execution role's `sqs:SendMessage` on the **notifications queue ARN only** + `NOTIFICATIONS_QUEUE_URL`.
- File-converter reason codes registered through the `cpcommon.messages` domain hook (SPEC-107 FR-005).

### Out of Scope

- Any change to the notifications writer, the inbox file, or the `/notifications` page — producer only.
- A notification per file. One request, one notification.
- Notifying anyone but the actor. One recipient; no fan-out (unlike Table Share).
- Telling the user their destination sits under a table's LOCATION — the pipeline does not spend a Glue lookup to find out. That risk is discharged by SPEC-120's dialog warning, at the only moment it can be.

---

## Functional Requirements

### FR-001: Success notification

#### Acceptance Criteria:

- [ ] On a successful conversion, exactly **one** notification is emitted to the **actor** — the verified `cognito:username`, never a body value.
- [ ] The message names the **destination path**. The user's next action is to point Table Builder at it, so the path is the payload.
- [ ] It states the number of objects written.
- [ ] **If any column fell back to string** (SPEC-117 FR-005, carried through SPEC-119 FR-002), the message says so, names the column(s), and names the conflicting types — e.g. *"the column `note` was saved as text because some files had dates and others had numbers."* A success message that omits this is a spec violation.
- [ ] A test asserts a conversion with a string fallback produces a message naming the column, and that a clean conversion does not mention fallbacks at all.

### FR-002: Failure notification

#### Acceptance Criteria:

- [ ] Every terminal failure emits one notification with a **friendly** reason. The registered set is **exhaustive** and must cover every terminal any verb can raise: `unauthorized`, `forbidden`, `forbidden_destination`, `destination_not_empty`, `unsupported_format`, `mixed_formats`, `unsupported_json_shape`, **`inconsistent_headers`**, **`unreadable_file`** (SPEC-117 FR-003), **`compressed_source_too_large`** (SPEC-117 FR-002), `too_many_files`, `too_many_partitions`, `no_data_files`, `query_failed`, `query_timeout`, `incomplete_result`, `unexpected_error`. (The former Excel-path codes `source_too_large` and `conversion_failed` are gone with the Excel strip — no verb can raise them.)
- [ ] A comment records why the set must be exhaustive: a code raised by a verb but **not registered** through the `cpcommon.messages` hook is a **hard error at import** (SPEC-107 FR-005) — a missing code is not a vague message, it is a Lambda that fails to load. A test walks every `TerminalError` raised anywhere in the arc and asserts each code is registered.
- [ ] **`inconsistent_headers`** — the failure a user is most likely to hit and least likely to understand — names **which file differs and how**, and suggests running the **data-quality check** to see the full picture. A test pins this message.
- [ ] **`unreadable_file`** names the object whose header/schema could not be probed, so the user knows which one to look at.
- [ ] **`compressed_source_too_large`** explains that a large `.gz` **cannot be split across workers** and tells the user to **decompress it or split it into several smaller objects** — not that "the file is too big," which is untrue of the same data uncompressed.
- [ ] `destination_not_empty` tells the user what to do (choose an empty folder), not just that it failed. A comment records that this reason is raised by **`validate-authorize` alone**: Athena does **not** enforce an empty `UNLOAD` destination when partitioning (SPEC-118 FR-002), so there is no second, engine-raised source for it.
- [ ] `query_timeout` tells the user the source is too large, rather than reporting an internal timeout, and does **not** mention a workgroup setting — the limit is an account Service Quota (SPEC-115 FR-003).
- [ ] **Raw AWS / Athena / polars / Python text never appears** in a notification body (SPEC-106 FR-008); the raw Athena `StateChangeReason` stays in CloudWatch and the SFN execution history (`tbcommon/notify.py:43-44`).
- [ ] `unauthorized` / `forbidden` collapse to a single "You don't have access…" message leaking no path or space name (`tbcommon/messages.py:41-42`).
- [ ] Reason codes are registered through the `cpcommon.messages` domain hook; a duplicate code is a hard error at import.
- [ ] Substitution uses `str.replace` on named tokens, never `str.format` — a literal brace in a path or column name must not raise (`tbcommon/messages.py:45-47`).

### FR-003: No silent failures, and no silent partial results

#### Acceptance Criteria:

- [ ] Every verb handler carries `@notifies_on_failure(step)`: `TerminalError`/`TransientError` pass through un-notified; **any other exception** emits `unexpected_error` to the actor and re-raises.
- [ ] A test asserts a bare `KeyError` in any verb still reaches the user as a friendly notification.
- [ ] Every failure produces a **failure** notification — the user is **never** told "converted" over an incomplete destination (SPEC-119 FR-001 verifies against the `UNLOAD` data manifest). A test forces a mid-`UNLOAD` failure and asserts a failure notification, not a success one.
- [ ] **A failure after the `UNLOAD` began tells the user that partial output may remain, and NAMES THE DESTINATION PATH.** A comment records why this is a requirement and not a nicety: the pipeline holds **no `s3:DeleteObject`** (SPEC-116 FR-006), so it **cannot** clean up after itself — the notification is the **only** way the user learns there is something to delete. And they must delete it: SPEC-116's empty-destination rule will block their retry until they do, which is the interlock that stops a retry from doubling the data. A test asserts the failure message carries the destination path.
- [ ] A failure inside `drop-temp-table` (SPEC-118 FR-004) does not mask the original failure reason. A test asserts the user sees the real cause, not a cleanup error.
- [ ] **The arc mirrors SPEC-114 FR-004 and FR-005**, with concrete delivery vehicles. A dedicated **`NotifyFailure`** Task on the failure path **wires the `notify-failure` Lambda provisioned (as a placeholder) in SPEC-115 FR-002** — this spec supplies its code and the ASL change; it creates no new function. Its purpose: a Lambda import error or a Step Functions-level error still reaches the user, which `@notifies_on_failure` alone cannot do.
- [ ] **The failure path becomes `DropTempTable → NotifyFailure → Fail`** (no `ParseError` — **No ASL state may decode an error Cause** *(corrected 2026-07-21 — see the `ParseError` removal)*: `States.StringToJson($.error.Cause)` raises `States.Runtime`, which is neither retriable nor catchable, whenever `Cause` is absent or is not JSON (`States.Timeout`, `States.DataLimitExceeded`, `Lambda.Unknown` — all verified live). The raw `$.error` is carried through to the terminal state and decoded in Python with `cpcommon.errors.failure_reason`.), and it is **tolerant of a notify failure**: an error inside `NotifyFailure` still reaches `Fail` (its own `Catch` routes there) and never masks the original failure reason.
- [ ] `NotifyFailure` derives its reason via **`cpcommon.errors.failure_reason(event.get("error"))`** on the raw `{Error, Cause}` — never a pre-decoded `reason` key — and falls back to `unexpected_error`; because both `@notifies_on_failure` and `NotifyFailure` can fire for the same failure, the `{requestId}:{step}` dedup id (FR-004) collapses them to **one** message. A test asserts exactly one notification for a forced verb failure.
- [ ] **DLQ and `ExecutionsFailed` CloudWatch alarms** exist in `infra/modules/file-converter/alarms.tf` (depth > 0 / any failed execution; no notification target in v1, mirroring SPEC-114 FR-005), and the deploy role is expanded for the alarm resource type per the CLAUDE.md infra rule. This delivers the alarms SPEC-115's Out of Scope explicitly defers here.
- [ ] A comment records that the backstop matters *more* here than for data quality: a converter failure can leave **partial Parquet in the destination** (SPEC-118 FR-004), so a silent failure means the user is unaware of wreckage they must clear before they can retry.

### FR-004: Best-effort emission, correctly scoped IAM

#### Acceptance Criteria:

- [ ] Emission is **best-effort**: an unset `NOTIFICATIONS_QUEUE_URL`, a missing recipient, or a send exception are each a logged no-op — **a notification failure never fails the pipeline outcome** (`cpcommon.notify.emit_notification`).
- [ ] `MessageGroupId` = the recipient username (SPEC-058 per-user ordering).
- [ ] `MessageDeduplicationId` = `{requestId}:{step}` (`tbcommon/notify.py:30-32`) — which is why SPEC-116 FR-001 requires `requestId` on every envelope.
- [ ] The execution role gains `sqs:SendMessage` on the **notifications queue ARN only** — no other queue, no other SQS action.
- [ ] The Glue/Athena/LF grants from SPEC-118 are unchanged; this spec adds no catalog permission. A plan assertion confirms it.
- [ ] **A plan assertion confirms the rendered policy still contains no `s3:DeleteObject` action at all** (SPEC-116 FR-006) — the last spec in the arc is the last chance for one to creep back in.

---

## Data Model

The exact SQS message emitted to the notifications FIFO queue — the SPEC-058 `create` envelope, byte-compatible with what `tbcommon`/`tscommon` send (`tbcommon/notify.py:124-131`):

```jsonc
// MessageBody
{ "action": "create", "username": "<actor>", "message": "<friendly text>" }
```

```
MessageGroupId          = <actor>                # per-user ordering (SPEC-058)
MessageDeduplicationId  = "{requestId}:{step}"   # collapses @notifies_on_failure + NotifyFailure
                                                 # duplicates for the same failure (FR-004)
```

**Environment:** `NOTIFICATIONS_QUEUE_URL` is set on every verb Lambda **and** `notify-failure`; when unset, emission is a logged no-op (FR-004) — it is deliberately *not* validated-at-import, because a missing queue must degrade to silence in the logs, never a Lambda that fails to load.

## File & Folder Structure

```
lambdas/file-converter-common/fccommon/messages.py   # reason codes → friendly text (registered via cpcommon)
lambdas/file-converter-notify-failure/notify_failure.py     # real code for the SPEC-115 placeholder (+ tests)
lambdas/file-converter-*/…                            # @notifies_on_failure; emit at terminals
infra/modules/file-converter/state-machine.asl.json.tftpl    # DropTempTable → NotifyFailure → Fail
infra/modules/file-converter/alarms.tf                       # DLQ depth + ExecutionsFailed alarms
infra/modules/file-converter/policies/execution.json.tftpl   # + sqs:SendMessage on the notifications queue
infra/modules/file-converter/lambda.tf                       # + NOTIFICATIONS_QUEUE_URL env
infra/modules/base/policies/github-actions-deploy-file-converter.json.tftpl   # + cloudwatch:*Alarm* (deploy role)
```

## Implementation Phases

### Phase 1: Messages + emission

- Register **every** reason code through the `cpcommon.messages` hook (incl. `unreadable_file` and `compressed_source_too_large`) and test that no verb can raise an unregistered one; emit success from `finalize` (destination + object count + **string fallbacks**) and failure from every terminal path (**naming the destination when partial output may remain**); decorate every handler with `@notifies_on_failure`.

### Phase 2: NotifyFailure + alarms + IAM + env + end-to-end

- Code for the SPEC-115 `notify-failure` placeholder; the ASL failure-path change (`DropTempTable → NotifyFailure → Fail`, tolerant of a notify failure); `alarms.tf` (DLQ + `ExecutionsFailed`) with the deploy-role expansion.
- `sqs:SendMessage` on the notifications queue ARN only; `NOTIFICATIONS_QUEUE_URL`; confirm no catalog permission crept in **and that `s3:DeleteObject` is still granted nowhere**.
- End-to-end: convert a CSV folder whose files disagree on a column type; assert the inbox receives one message naming the destination **and** the string-fallback column. Convert a folder with mismatched headers and assert the `inconsistent_headers` message names the file and suggests the data-quality check. **Force a mid-`UNLOAD` failure and assert a failure notification (never a success) that names the destination path where partial output may remain.** Convert into a non-empty destination and assert the friendly `destination_not_empty` message with no raw AWS text.
- Completion ritual — including the SPEC-074 help sweep (the arc is now user-visible end to end) and a one-line Key Decisions entry in CLAUDE.md pointing at `docs/file-converter-architecture.md`.
