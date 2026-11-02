---
type: Spec
id: SPEC-136
title: "Structured Logging — Instrument the Table-Share Control Plane"
description: "Gives operators structured events for the fan-out table-share plane, tagging each event with its recipient so partial success across concurrent per-recipient copies can be told apart."
spec_status: Completed
depends_on: [SPEC-130, SPEC-134, SPEC-133]
arc: observability
arc_order: 10
---

**Dependency notes:** SPEC-130 (the emitters and `step`), SPEC-134 (the coverage harness), SPEC-133 (the infra pattern)
## Overview

Table-share is the only control plane that **fans out**. `validate-authorize` and `inspect-source`
run once per request; then a Step Functions `Map` over `$.recipients` runs
`check-target-absent → copy-objects → create-table` **once per recipient**, at up to five
concurrently, with a per-item `Catch` so one recipient's failure never aborts its siblings.

That makes partial success this plane's normal outcome — three recipients requested, two shared,
one failed — and it breaks an assumption every other instrumented plane rests on. Elsewhere
`request_id` identifies one run and one invocation of each verb, so an event saying "copied
objects" is unambiguous. Here the same `request_id` produces three invocations of the same verb,
concurrently, and three identical-looking events. Without the recipient on every event, the store
records that copying happened somewhere and nothing about where.

So the defining requirement of this spec is not what to say but what to say it *about*: every
event from a per-recipient verb carries its recipient, and the request's outcome is legible as a
per-recipient breakdown rather than a single status.

## Scope

### In Scope

- `observability.init(service="table-share")` and `@observability.traced(<verb>)` on all five
  verbs: validate-authorize, inspect-source, check-target-absent, copy-objects, create-table.
- `recipient` as a mandatory field on every event from the three fan-out verbs.
- Narrative for the clone-the-definition path, the copy, and the per-recipient outcomes.
- The infra pair, and a table-share entry in the SPEC-134 coverage harness.

### Out of Scope

- **Any behavior change.** No change to the `Map`, its concurrency, the per-item `Catch`, the
  clone-never-re-infer rule, the push-without-consent model, the recipient caps, or notifications.
- **Reconciling the per-recipient summary shape** that SPEC-092/094 established. This spec reads
  it; it does not reshape it.
- **shared-space, table-builder and the singletons** — SPEC-134, 135, 137.

---

## Functional Requirements

### FR-001: The plane joins the pipe

#### Description

`service="table-share"` for all five verbs.

#### Acceptance Criteria:

- [ ] `observability.init(service="table-share")` at module scope in all five verb modules, and
      `@observability.traced(<verb>)` on each `handler`.
- [ ] `@traced` is **outermost, above `@notify.notifies_on_failure`**, on all five;
      `validate-authorize`'s `notify_terminal=False` is unchanged.
- [ ] A test asserts `"table-share"` matches `log_sweep.SERVICE_RE`.
- [ ] A `table-share` entry is added to the SPEC-134 coverage harness declaring five verbs.

### FR-002: Every fan-out event names its recipient

#### Description

The requirement the plane's shape forces. `check-target-absent`, `copy-objects` and `create-table`
each run once per recipient inside the `Map`, so `request_id` alone cannot distinguish their
events. `recipient` — its name and its kind — is what makes a per-recipient story readable.

Concurrency makes it sharper: with `MaxConcurrency: 5`, five recipients' events interleave in the
logs queue and, after the sweep, in one day's object. Ordering recovers nothing. The recipient
field is the only thing that separates them.

#### Acceptance Criteria:

- [ ] Every event emitted by the three fan-out verbs carries `recipient` (the name) and
      `recipient_kind` (user or space). No exceptions, including error events.
- [ ] `recipient` is set as a **field**, never as baggage. Baggage is per-invocation, which happens
      to be per-recipient here — but relying on that couples the field to the `Map`'s structure,
      and a future `Map` over something else would silently mislabel every event. Same reasoning
      as SPEC-133 FR-002.
- [ ] A test runs the three verbs for three different recipients and asserts every emitted event
      is attributable to exactly one recipient, with no event carrying a recipient it did not run
      for.
- [ ] The two once-per-request verbs (`validate-authorize`, `inspect-source`) carry the **recipient
      count** and the recipient list, not a single recipient — they run before the fan-out.

### FR-003: Partial success is legible

#### Description

Two of three recipients succeeding is a normal outcome, not an error, and it is the outcome most
likely to generate a support question. The store should answer "which recipients got it" without
reading a Step Functions execution history.

#### Acceptance Criteria:

- [ ] Each fan-out verb emits a terminal event per recipient naming the outcome and, on failure, a
      stable reason token drawn from the plane's existing vocabulary (`unknown_user`,
      `unknown_space`, `conflict`, `target_not_readable`, `copy_failed`, `create_failed`).
- [ ] A per-recipient failure emits `error` and the request's other recipients still emit their
      own events — a test asserts that a failing middle recipient does not suppress its siblings'
      narrative, mirroring the per-item `Catch` the `Map` already implements.
- [ ] The reason token is recovered the way the rest of the plane recovers it — through
      `cpcommon.errors.failure_reason` from the raw `$.error` — and **never** by decoding a Cause
      in ASL, which raises an uncatchable `States.Runtime` (#252).
- [ ] No new state, field or `Catch` is added to the state machine. This spec logs from the verbs.

### FR-004: Named steps

#### Description

| Verb | Steps |
|---|---|
| validate-authorize | `authorize-source`, `normalize-recipients`, `annotate-recipients` |
| inspect-source | `read-definition`, `enforce-definition-cap` |
| check-target-absent | `resolve-destination`, `check-prefix-empty` |
| copy-objects | `copy` (the whole copy, **never per object**) |
| create-table | `create-table` |

#### Acceptance Criteria:

- [ ] Each step emits a child span parented to the handler's, carrying `verb`, `request_id` and —
      for the fan-out verbs — `recipient`.
- [ ] No step wraps a per-object function. `copy-objects` moves every object in a table's prefix,
      bounded only by the plane's `SHARE_MAX_*` caps, and a span per object would put thousands of
      events into a day object the sweep rewrites in full.
- [ ] A step that raises still reaches `notifies_on_failure` with the exception unchanged, and the
      per-item `Catch` still ends that item without aborting the `Map`.

### FR-005: The clone path and the copy report what moved

#### Description

The plane's settled decision is to **clone** the source Glue table definition rather than re-infer
it (SPEC-088→094), and the definition carries a size cap. Both are silent today.

#### Acceptance Criteria:

- [ ] `inspect-source` logs the source database and table, the cloned definition's column count and
      serialized size, and whether the cap was approached or hit.
- [ ] Hitting the definition cap emits `error` with the size and the cap — a share failing because
      a table definition is too large is otherwise indistinguishable from a permissions problem.
- [ ] `copy-objects` logs the source prefix, the destination prefix, the object count and total
      bytes copied, and the count of objects skipped as already present.
- [ ] `create-table` logs the destination database and table and the created column count, so the
      clone can be compared against its source without opening the catalog.
- [ ] No object's **contents** are logged anywhere — keys, prefixes, counts and sizes only
      (SPEC-130 FR-005). `copy-objects` streams user data through, which makes it the one verb here
      where the file-contents line is a live constraint rather than a formality.

### FR-006: The infrastructure the events need

#### Description

Mirrors SPEC-133 FR-007.

#### Acceptance Criteria:

- [ ] `logs_queue_url` variable on `modules/table-share`, wired in `main.tf`, set as
      `LOGS_QUEUE_URL` on all five functions.
- [ ] An `EmitStructuredLogEvents` statement granting `sqs:SendMessage` on the logs queue ARN,
      matching the data-quality Sid and shape.
- [ ] `LOGS_QUEUE_URL` optional by construction — `environ.get`, never `_require`.
- [ ] The deploy-role check is performed and its finding recorded.
- [ ] IAM and environment apply before the instrumented code deploys.

---

## Data Model

Events follow SPEC-127's schema, landing at `logs/service=table-share/…`. Field vocabulary:

```
actor: str            source_database: str    source_table: str
recipient: str        recipient_kind: "user" | "space"
recipients: int       recipient_names: list[str]
destination_database: str   destination_table: str
source_prefix: str    destination_prefix: str
objects: int          bytes: int              skipped: int
columns: int          definition_bytes: int   definition_cap: int
status: "ok" | "failed"
reason: "unknown_user" | "unknown_space" | "conflict" | "target_not_readable"
      | "copy_failed" | "create_failed"
```

## File & Folder Structure

```
lambdas/table-share-{validate-authorize,inspect-source,check-target-absent,copy-objects,create-table}/
lambdas/control-plane-common/test_instrumentation_coverage.py      # + table-share entry
infra/modules/table-share/{variables,lambda}.tf
infra/modules/table-share/policies/*.json.tftpl
infra/main.tf
```

## Implementation Phases

### Phase 1: Infrastructure, applied first

- Variable, wiring, `LOGS_QUEUE_URL`, the IAM statement, the recorded deploy-role finding.

### Phase 2: Into the pipe

- `init` + `@traced` on all five verbs, outermost above `notifies_on_failure`; the harness entry;
  `SERVICE_RE`.

### Phase 3: The recipient field

- `recipient` / `recipient_kind` on every fan-out event, as a field; the attribution test across
  three concurrent recipients.

### Phase 4: The narrative

- Steps; per-recipient outcomes and reason tokens; the clone, cap and copy reports.

### Phase 5: Live verification

- Share one table to **at least three recipients, with one deliberately invalid**, and confirm:
  every event is attributable to its recipient, the two successes and the one failure are each
  readable from `logs/` alone, and the failing recipient did not suppress its siblings.
