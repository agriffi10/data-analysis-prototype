# Spec: Table Builder — Notification Producer (per-step failure + success)

**ID:** SPEC-072
**Status:** Completed
**Last Updated:** 2026-07-01
**Depends On:** SPEC-058 (notifications queue + `create` contract + writer), SPEC-070 (terminal success/recorded-failure states + structured outcome), SPEC-067/068/069 (the verb Lambdas + their terminal reasons), SPEC-066 (verb roles + module)

> **Reference:** `docs/table-builder-architecture.md` §6; pattern mirrors SPEC-061 (shared-workspace producer).
> Producer-side only: wires the table-builder pipeline to the **SPEC-058 notifications queue** so each verb Lambda
> emits a **failure** notification at its terminal-failure branch and **execute-ddl** emits a **success**
> notification — addressed to the **requesting actor**. No UI, no new notifications infra. If SPEC-058 isn't
> deployed yet, emission is a logged no-op (the pipeline still records its outcome in the SFN execution).

## Overview

A create-table request runs entirely server-side, so the user learns the result through their **notifications
inbox** (SPEC-058→060). This spec makes the table-builder pipeline a **trusted producer** of `create`
notifications: at each step's **terminal failure** the responsible verb Lambda emits a clear, reason-specific
message to the **actor** (e.g. *"Couldn't create table 'orders': a table with that name already exists."*), and on
**terminal success** `execute-ddl` emits *"Table 'orders' is ready to query in 'salesdata'."*. Each emitting
verb-Lambda role gains `sqs:SendMessage` on the notifications queue; the queue URL is passed to the verb Lambdas;
emission uses a small **best-effort** shared helper so a missed notification never changes the pipeline outcome.
Unlike the shared-spaces producer, every event here has a **single recipient — the actor** (no fan-out).

## Scope

### In Scope

- **Failure notifications (per step)** — at each verb Lambda's terminal-failure branch (the reason it sends to the
  recorded-failure state, SPEC-067→070), emit one `create` notification to the **actor** with a human-readable
  message mapping the terminal reason:
  - `unauthorized` / `forbidden` / `invalid_table_name` / `invalid_partition_keys` (validate-authorize)
  - `table_exists` (check-table-absent; **also execute-ddl since 2026-09-15**, when its read-back
    finds the statement was a no-op over a table another request built)
  - `no_data_files` / `mixed_formats` / `unsupported_format` / `unexpected_partitioning` /
    `partition_layout_mismatch` (inspect-source)
  - `schema_inference_failed` / `unmappable_type` (infer-schema)
  - `ddl_execution_failed` / `ddl_timeout` (execute-ddl)
- **Success notification** — on `execute-ddl` terminal success (`status:'created'`), emit one notification to the
  actor: `Table "{tableName}" is ready to query in "{database}".`
- **Verb-role grant** — each emitting verb Lambda's `.tftpl` role policy gains `sqs:SendMessage` on the
  **notifications queue ARN only** (a SPEC-058 trusted producer); no other notifications-pipeline action.
- **Cross-module wiring** — the notifications queue URL/ARN (SPEC-058 outputs) reaches `infra/modules/table-builder/`
  as `compact()`-safe constructed-string locals; each verb Lambda's env gains `NOTIFICATIONS_QUEUE_URL`.
- **Shared emit helper** — `emit_notification(username, message, dedup_id=None)` in the table-builder **common
  module** (`lambdas/table-builder-common/notify.py`) building the SPEC-058 `create` envelope and `SendMessage`-ing
  it FIFO (`MessageGroupId` = recipient; `MessageDeduplicationId` from `requestId` + step). **Best-effort**:
  errors are caught + logged, never raised; unset `NOTIFICATIONS_QUEUE_URL` ⇒ no-op + one log line (independently
  deployable). (May reuse the SPEC-061 helper pattern; a thin per-arc copy is acceptable to keep modules
  decoupled.)
- **Tests** — each terminal branch emits the correct **recipient (actor) + message**; success emits the ready
  message; non-terminal/retryable steps emit **nothing**; an emit failure does not change the pipeline outcome;
  the e2e doc gains the producer flow.

### Out of Scope

- **The notifications infra** (queue, writer, role, cap) — SPEC-058; **the read/UI** (bell, page) — SPEC-059/060.
- **The pipeline behavior** itself (validation/inspection/inference/DDL) — SPEC-067→070 (this spec only adds the
  emit calls + grant + wiring at the already-defined terminal branches).
- **Fan-out / multi-recipient** — every table-builder event notifies exactly the **actor** (no member fan-out;
  that's a shared-spaces concept).
- **De-duplication beyond FIFO `MessageDeduplicationId`** — a rare out-of-window pipeline-replay duplicate inbox
  row is acceptable (same stance as SPEC-061).

---

## Functional Requirements

### FR-001: Emitting roles may send to the notifications queue

#### Acceptance Criteria:

- [ ] Every emitting verb Lambda role (validate-authorize, check-table-absent, inspect-source, infer-schema,
  execute-ddl) gains a `.tftpl` statement allowing `sqs:SendMessage` on the **notifications queue ARN only** (no
  Lambda invoke, no DLQ, no writer-role access, no Step Function).
- [ ] The notifications queue ARN reaches the table-builder module as a constructed-string/`compact()`-safe local
  so the module still `validate`s/`plan`s standalone (no unknown-ARN-in-list drop).
- [ ] `aws iam simulate-custom-policy` confirms an emitting role can `SendMessage` to the notifications queue and
  **cannot** to an unrelated queue.

### FR-002: Verb Lambdas receive the queue URL + share the emit helper

#### Acceptance Criteria:

- [ ] Each emitting verb Lambda's env gains `NOTIFICATIONS_QUEUE_URL` (the SPEC-058 output).
- [ ] `emit_notification(username, message, dedup_id=None)` builds `{ "action":"create", "username":<actor>,
  "message":<text> }` and `SendMessage`s it FIFO with `MessageGroupId = <actor>` + a `MessageDeduplicationId`
  derived from `requestId` + the step; it is **best-effort** (catches + logs all errors, never raises).
- [ ] If `NOTIFICATIONS_QUEUE_URL` is unset, emit is a **no-op + one log line** (the pipeline still completes and
  records its SFN outcome) — modules stay independently deployable (`lambdas.md` §6).

### FR-003: Failure notifications

#### Acceptance Criteria:

- [ ] At each verb's **terminal-failure** branch, exactly **one** notification is emitted to the **actor** with a
  reason-specific message (table below); **no** notification is emitted on a retryable/transient error or a
  non-terminal step.
- [ ] The message is human-readable and names the table + (where relevant) the database/reason; raw internal
  reason codes are mapped to friendly text.
- [ ] An emit failure is swallowed (FR-002) and does not change the recorded-failure outcome.

### FR-004: Success notification

#### Acceptance Criteria:

- [ ] On `execute-ddl` terminal success (`status:'created'`, SPEC-070), exactly one notification is emitted to the
  actor: `Table "{tableName}" is ready to query in "{database}".`
- [ ] No success notification is emitted for a replayed no-op that did not reach a fresh `created` outcome beyond
  the first (best-effort; a rare replay duplicate is acceptable — FIFO dedup covers the common case).

### FR-005: Tests + e2e

#### Acceptance Criteria:

- [ ] Python unit tests (per verb): each terminal reason emits the correct **actor recipient + mapped message**;
  success emits the ready message; transient/non-terminal paths emit **nothing**; an `emit_notification` error
  does not change the verb's result; the FIFO `MessageGroupId`/dedup are set.
- [ ] IaC: `tofu -chdir=infra validate` + `plan` clean; each emitting role's SendMessage statement is scoped to
  the notifications queue ARN; the verb Lambdas' env has `NOTIFICATIONS_QUEUE_URL`.
- [ ] The table-builder and notifications acceptance scripts: a real create that **succeeds** lands a
  ready notification in the actor's inbox; a create that **fails** (e.g. mixed formats, name taken) lands the
  matching failure notification — both visible on the notifications page (SPEC-060).

---

## Data Model

```jsonc
// SendMessage body — SPEC-058 create contract (trusted producer = the emitting verb Lambda)
// FIFO: MessageGroupId = <actor>, MessageDeduplicationId = `${requestId}:${step}`
{ "action": "create", "username": "<actor>", "message": "<event text>" }
```

Recipient is always the **actor**. Message per outcome:

| Step / outcome | Reason | Message |
|---|---|---|
| validate-authorize | `unauthorized`/`forbidden` | `You don't have access to create a table here.` |
| validate-authorize | `invalid_table_name` | `Couldn't create table "{name}": the name isn't a valid table name.` |
| validate-authorize | `invalid_partition_keys` | `Couldn't create table "{name}": the partition keys aren't valid (check names, types, and ranges).` |
| check-table-absent | `table_exists` | `Couldn't create table "{name}": a table with that name already exists in "{database}".` |
| execute-ddl *(added 2026-09-15)* | `table_exists` | the same sentence — the read-back found the statement had been a no-op over a table another request built. `docs/decisions/control-planes.md`, *A group id orders the STARTS, not the runs* |
| inspect-source | `no_data_files` | `Couldn't create table "{name}": no supported data files were found in that folder.` |
| inspect-source | `mixed_formats` | `Couldn't create table "{name}": the folder mixes file formats — use a single format.` |
| inspect-source | `unsupported_format` | `Couldn't create table "{name}": that file format isn't supported (use Parquet, CSV, or JSON).` |
| inspect-source | `unexpected_partitioning` | `Couldn't create table "{name}": the folder is partitioned but no partition keys were provided.` |
| inspect-source | `partition_layout_mismatch` | `Couldn't create table "{name}": the partition keys don't match the folder layout (check names and order).` |
| infer-schema | `schema_inference_failed`/`unmappable_type` | `Couldn't create table "{name}": the data schema couldn't be read.` |
| execute-ddl | `ddl_execution_failed`/`ddl_timeout` | `Couldn't create table "{name}": creating the table failed ({reason}).` |
| execute-ddl | `created` (success) | `Table "{name}" is ready to query in "{database}".` |

## API / Interface Contract

```python
# lambdas/table-builder-common/notify.py
def emit_notification(username: str, message: str, dedup_id: str | None = None) -> None:
    """Best-effort SPEC-058 `create` emit to the FIFO NOTIFICATIONS_QUEUE_URL
    (MessageGroupId=username, MessageDeduplicationId=dedup_id). Catches+logs all
    errors, never raises; no-op (one log line) if the queue URL is unset."""
```

## Environment Variables

Each emitting verb Lambda (server-side):

```
NOTIFICATIONS_QUEUE_URL=<SPEC-058 notifications queue URL>
```

## File & Folder Structure

```
lambdas/table-builder-common/
└── notify.py                              ← emit_notification (best-effort) + tests

lambdas/table-builder-<verb>/<verb>.py     ← + inline emit_notification at terminal branch(es) (FR-003/004)
lambdas/table-builder-<verb>/test_<verb>.py← + emit assertions (recipient, message, silence on retryable)

infra/modules/table-builder/
├── policies/<verb>.tftpl                  ← + sqs:SendMessage on the notifications queue ARN (FR-001)
├── lambda.tf                              ← + NOTIFICATIONS_QUEUE_URL env on each verb Lambda (FR-002)
└── variables.tf                           ← + notifications_queue_arn/_url (constructed-string locals)

infra/modules/base/policies/               ← deploy-policy-table-builder: SendMessage grants (FR-001)
docs/testing/e2e.md          ← + producer flow (FR-005)
```

## Implementation Phases

### Phase 1: Wiring (grant + env + helper)

- Pass the notifications queue ARN/URL into the table-builder module; add `sqs:SendMessage` (notifications queue
  ARN) to each emitting verb role; set `NOTIFICATIONS_QUEUE_URL`; add the best-effort `emit_notification` helper
  (no-op if unset) (FR-001, FR-002, FR-005 IaC).

### Phase 2: Emit at each terminal branch

- Add emit calls at each verb's terminal-failure branch (reason→message map) and at execute-ddl success; unit-test
  recipient/message + silence on retryable; update the e2e doc (FR-003, FR-004, FR-005).
