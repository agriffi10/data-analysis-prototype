# Spec: Logs Queue → FIFO, and One Object Per Service-Day

**ID:** SPEC-129
**Status:** Completed
**Last Updated:** 2026-07-23
**Depends On:** SPEC-127 (the queue, the sweep), SPEC-128 (the data-quality producer)

## Overview

Three changes to the structured-logging pipe SPEC-127/128 shipped, all driven by what running it
revealed (user decisions, 2026-07-23).

The sweep produced **one object per run** — and, because it instruments itself, it produced one
even when it swept nothing. At a 5-minute cadence that is 288 objects a day of pure self-telemetry
against a prefix retained forever, which is the many-tiny-files pathology that makes an Athena
table over `logs/` slow before it is ever built. Halving the cadence and collapsing a day into one
object addresses both ends of that.

The queue was also the only **standard** (non-FIFO) queue in the repo, and only because
`log-foundry`'s `SQSSink` could not populate `MessageGroupId`. `log-foundry` 0.5.0 (log-forge
SPEC-016) adds FIFO support, so the exception can be retired.

## Scope

### In Scope

- Sweep cadence **5 → 10 minutes**.
- Partition layout → `logs/service={service}/year=YYYY/month=MM/day=DD/data.jsonl`, with each
  sweep **appending** to the day's object.
- Logs queue → **FIFO**, with `message_group_id` = the **service**.
- `log-foundry` pin 0.4.0 → **0.5.0**.
- The deploy-role and execution-role IAM the above requires.

### Out of Scope

- **A Glue table / Athena view over `logs/`.** Still deferred; this layout is chosen so one can
  be added without a repartition migration, but nothing queries the logs here.
- **Migrating the objects SPEC-127 already wrote** under `logs/{service}/dt=…/hh=…/`. They are a
  few hundred KB of probe data. The new layout is written alongside; the old keys are left where
  they are (FR-005).
- **Any change to what is logged.** No new field, no new call site, no control-plane change.
- **A `logs/` lifecycle rule.** Still retained indefinitely (SPEC-127 FR-009).

---

## Functional Requirements

### FR-001: The sweep runs every 10 minutes

#### Description

Freshness traded for churn. A log is now up to ten minutes behind the run that produced it —
which reverses SPEC-127 FR-004's argument for 5 ("a log you cannot see for ten minutes is not
usable while you are debugging the run that produced it"). The reversal is deliberate: with a
day's events collapsed into one object, each sweep is now a read-modify-write of a growing file,
so halving the cadence halves both the invocation count and the bytes moved.

#### Acceptance Criteria:

- [ ] `schedule_expression = "rate(10 minutes)"`.
- [ ] The comment records the reversal, its date, and the freshness cost — not just the new value.
- [ ] The function timeout (300s) stays below the interval; the comment notes the headroom
      doubled.

### FR-002: One object per service-day, appended

#### Description

`logs/service={service}/year=YYYY/month=MM/day=DD/data.jsonl`. `service=` is a partition column
like the date parts so an Athena table can prune on it.

`month=` is present deliberately: `year=YYYY/day=DD` as first sketched would put every 15th of the
month in one partition, silently interleaving twelve calendar dates in one file (user decision,
2026-07-23, after the collision was raised).

#### Acceptance Criteria:

- [ ] The key is exactly as above; partition values come from the **event's own** timestamp, not
      the sweep clock (unchanged from SPEC-127 FR-005).
- [ ] A sweep **appends** to an existing day's object and **creates** it when absent. A test
      asserts a second sweep's lines join the first's rather than replacing them.
- [ ] Unroutable bodies go to `logs/service=_unrouted/…`, still verbatim, still deleted.
- [ ] One sweep writes **one object per `(service, year, month, day)`** it encountered.

### FR-003: The append cannot lose a concurrent writer's events

#### Description

S3 has no append, so this is read-modify-write — and two overlapping sweeps would both read the
same object and the second `PUT` would erase the first one's events with no error anywhere.

#### Acceptance Criteria:

- [ ] Every write is conditional: `If-None-Match: *` to create, `If-Match: <etag>` to extend.
- [ ] A precondition failure **re-reads and re-applies** rather than retrying the same bytes,
      bounded by an attempt cap. Same CAS shape as `dqcommon.index_store` (SPEC-123).
- [ ] Exhausting the cap leaves the messages **queued** — never deleted. A test asserts it.
- [ ] A failed **read** is treated as "absent, no etag", so the following write uses
      `If-None-Match: *` and *conflicts* rather than silently overwriting a day of logs. A test
      asserts an existing day survives a read error.
- [ ] The test fake implements real conditional-put semantics with a changing ETag — a fake that
      ignored preconditions would make the CAS loop green either way.

### FR-004: FIFO, grouped by service

#### Description

A FIFO queue's name must end in `.fifo`, and the name is ForceNew — so this is a
**destroy-and-create**, not an update.

#### Acceptance Criteria:

- [ ] `fifo_queue = true`, name `{project}-{env}-logs.fifo`.
- [ ] **No `content_based_deduplication`.** `log-foundry` mints a UUID `MessageDeduplicationId`
      per event, so messages are already unique; content-based dedup would make SQS silently drop
      a genuine duplicate event inside the 5-minute window. A comment records this.
- [ ] `SQSSink` is constructed with `message_group_id=<service>`, overriding the library's default
      of one group per `trace_id`. A comment records what that trades: the default maximises
      parallel delivery, which a single-consumer sweep cannot use anyway.
- [ ] The deploy role holds `DeleteQueue` on the **old** name and `CreateQueue` on the **new** one
      in the same apply — shipped and applied in its **own prior PR**, or the conversion fails
      halfway, after destroying the queue.
- [ ] `log-foundry==0.5.0` pinned exactly; the comment records that it is a **hard floor**, since
      on 0.4.0 every FIFO batch would fail and the events would be abandoned to stderr.

### FR-005: The reversal of "the sweep reads nothing" is recorded

#### Description

SPEC-127 FR-006 states the sweep role "writes logs; it reads nothing." Appending requires
`s3:GetObject`. That is a real reduction in the role's bound and must be written down where the
role is defined, not just implied by the diff.

#### Acceptance Criteria:

- [ ] `s3:GetObject` is granted on **`{admin-bucket}/logs/*` only** — the same prefix as the
      write, so the role can read its own output and nothing else in the admin bucket.
- [ ] A comment at the statement records the reversal, why it is needed, and what still bounds it.
- [ ] No new grant on the user-space or shared-space buckets; no `s3:DeleteObject`.
- [ ] The Lambda's memory is raised to 512 MB, because peak memory now tracks a day's log volume
      rather than one batch, and the handler warns when a day's object gets large.

---

## Data Model

```
s3://{admin-bucket}/
  logs/
    service=data-quality/year=2026/month=07/day=23/data.jsonl
    service=observability/year=2026/month=07/day=23/data.jsonl
    service=_unrouted/year=2026/month=07/day=23/data.jsonl
```

Event shape is unchanged (SPEC-127).

## File & Folder Structure

```
lambdas/log-sweep/log_sweep.py                            (+ test_log_sweep.py)
lambdas/control-plane-common/cpcommon/observability.py    # message_group_id=<service>
lambdas/control-plane-common/requirements.txt             # log-foundry==0.5.0
infra/modules/observability/{sqs,lambda,iam,locals}.tf
infra/modules/base/policies/github-actions-deploy-observability.json.tftpl   # PR 1
```

## Implementation Phases

### Phase 1: Deploy-role IAM

- Both queue ARNs (`-logs` and `-logs.fifo`) on the deploy policy, applied on its own first.

### Phase 2: The pipe

- FIFO queue + `message_group_id`; the 0.5.0 pin; the 10-minute schedule.
- The day-partitioned append with CAS; `s3:GetObject` on `logs/*`; 512 MB.

### Phase 3: Live verification

- Confirm the queue is FIFO and the nine producers + the sweep pick up the new URL without a
  cold-start failure.
- Confirm a sweep appends to an existing day rather than replacing it, and that a second sweep in
  the same day extends the same object.
- Confirm messages carry the per-service group id.
