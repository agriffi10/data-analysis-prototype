# Spec: Structured Logging — Instrument the Table-Builder Control Plane

**ID:** SPEC-135
**Status:** Draft
**Last Updated:** 2026-07-23
**Depends On:** SPEC-130 (the emitters and `step`), SPEC-134 (the coverage harness), SPEC-133 (the infra pattern)

## Overview

Table-builder is the plane with the most instructive failure in this repo's history, and it is
exactly the failure structured logging exists to prevent. SPEC-070 recorded that a Lake Formation
admin could create tables in any database; that was false. Table-builder therefore **silently
failed to create tables** in users' databases — no table, no error the user saw, no notification.
It was found because a person noticed a table they expected was not there, and the correction took
four PRs (#243–246) and a new TBAC model.

A verb that fails loudly is cheap to diagnose. This plane's canonical failure was a verb that
completed. The narrative this spec adds — the DDL that ran, against which database, with what
outcome, and whether the table was there afterwards — is the record that turns that class of
failure from an observation into a query.

It has a second distinguishing feature. `execute-ddl` **polls Athena inside a 300-second Lambda**,
deliberately, because a `CREATE TABLE` returns in seconds; data-quality moved its poll into the
state machine precisely because a profiling query does not. That in-Lambda poll is a loop that
runs an unbounded number of times per invocation, so it gets the same transition-only treatment
SPEC-132 FR-005 gave `check-query`.

## Scope

### In Scope

- `observability.init(service="table-builder")` and `@observability.traced(<verb>)` on all five
  verbs: validate-authorize, inspect-source, infer-schema, check-table-absent, execute-ddl.
- Named `step` child spans on each verb's bounded phases.
- Narrative covering schema inference, the layout and partition-key rules, the DDL, and the
  post-conditions that would have exposed the silent-create failure.
- Transition-only narrative for the in-Lambda Athena poll.
- The infra pair, and a table-builder entry in the SPEC-134 coverage harness.

### Out of Scope

- **Any behavior change.** No change to validation, the user-declared partition-key model, Athena
  partition projection, the CSV all-string rule, the DDL, TBAC grants, or notifications.
- **Re-verifying the TBAC model.** SPEC-111 passed live e2e and is Completed. This spec makes its
  operation legible; it does not re-open it.
- **`bounded_read` / polars behavior.** Unchanged since #272–274; this spec logs what it reads,
  not how.
- **shared-space, table-share and the singletons** — SPEC-134, 136, 137.

---

## Functional Requirements

### FR-001: The plane joins the pipe

#### Description

`service="table-builder"` for all five verbs, per-verb identity as `verb`.

#### Acceptance Criteria:

- [ ] `observability.init(service="table-builder")` at module scope in all five verb modules, and
      `@observability.traced(<verb>)` on each `handler`.
- [ ] `@traced` is **outermost, above `@notify.notifies_on_failure`**. If it were inner, an
      invocation that failed and notified would close its span `status: "ok"` — the traces would
      report a healthy plane while users received failure notifications.
- [ ] `validate-authorize`'s `notifies_on_failure(..., notify_terminal=False)` is unchanged, and
      the ordering assertion still applies to it.
- [ ] A test asserts `"table-builder"` matches `log_sweep.SERVICE_RE`.
- [ ] A `table-builder` entry is added to the SPEC-134 coverage harness declaring five verbs and
      the `@traced`-above-`notifies_on_failure` expectation.

### FR-002: Named steps

#### Description

| Verb | Steps |
|---|---|
| validate-authorize | `load-registry`, `authorize-space`, `validate-table-name`, `validate-partition-keys` |
| inspect-source | `list-source`, `validate-layout` |
| infer-schema | `check-access`, `infer-columns` |
| check-table-absent | `check-table-absent` |
| execute-ddl | `run-ddl` (the whole call, **never per poll**) |

#### Acceptance Criteria:

- [ ] Each step emits a child span parented to the handler's, carrying `verb` and `request_id`.
- [ ] A step that raises closes `status: "error"` on itself and the handler, and the original
      exception still reaches `notifies_on_failure` unchanged — a test asserts the user
      notification is byte-identical to the uninstrumented run.
- [ ] No step wraps a per-object, per-column or per-poll function.

### FR-003: The silent-create failure would be visible

#### Description

The plane's defining incident. Three facts, logged, make it a query rather than a discovery:
which database the DDL targeted, that the DDL statement ran and what Athena said about it, and
whether the table existed afterwards.

#### Acceptance Criteria:

- [ ] `execute-ddl` logs the target database, the table name, the workgroup, the Athena query
      execution id, the terminal state, and — on any non-`SUCCEEDED` state — the
      `StateChangeReason` verbatim as a field.
- [ ] A permissions failure is logged with the Athena/LF message intact. This is the exact text
      that would have named the missing `CREATE_TABLE` grant, and paraphrasing it into a stable
      token would have thrown away the diagnosis.
- [ ] `check-table-absent` logs its verdict as an explicit boolean plus the database and table it
      checked — the pre-condition and the post-condition are the same check, and having it in the
      record is what makes "the DDL claimed success and the table is not there" statable.
- [ ] The stable reason token required by SPEC-132 FR-003 accompanies the raw message; it does not
      replace it.

### FR-004: The in-Lambda Athena poll narrates transitions only

#### Description

`athena_run.run_ddl` polls `GetQueryExecution` in a loop inside the handler until the statement
reaches a terminal state. Unlike data-quality's poll, this loop is *inside* one invocation, so a
message per iteration would multiply within a single span rather than across invocations — the
same amplification, in a smaller box, and just as pointless: consecutive `RUNNING` observations
carry no information.

#### Acceptance Criteria:

- [ ] No event is emitted for a poll observing the same state as the previous one.
- [ ] One event on each state **transition**, and one on reaching a terminal state, carrying the
      state and the elapsed time.
- [ ] A poll loop that exhausts its budget against the 300-second Lambda ceiling emits `error`
      with the last observed state and the poll count. A `CREATE TABLE` that runs long enough to
      hit that ceiling is a real signal, and today it is indistinguishable from a Lambda timeout.
- [ ] A test drives ≥20 iterations with no state change and asserts exactly the boundary spans
      plus the terminal event — no per-iteration events.

### FR-005: Schema inference says what it read and what it concluded

#### Description

Inference is where this plane guesses, and a wrong guess produces a table that reads but is wrong
— the failure that is hardest to attribute later. The declared partition keys and the inferred
column types are the two outputs worth having permanently.

#### Acceptance Criteria:

- [ ] `infer-schema` logs the object it sampled, the format, the bytes read, the column count, the
      **column names and their mapped Hive types**, and whether the date-type heuristic fired.
- [ ] Under SPEC-130 FR-005 the names and types are schema and are logged; **no sampled value, no
      row and no cell** is. A Parquet schema read and a CSV header are structure; the data beneath
      them is not.
- [ ] `inspect-source` logs the resolved format, the object count, the relative directories it
      saw, and the declared partition names it validated them against — the layout mismatch is the
      most common user-facing rejection here and the two lists side by side are the explanation.
- [ ] The CSV all-string rule firing is logged explicitly, since a user asking why every column is
      a string is asking about a decision, not a bug.

### FR-006: The infrastructure the events need

#### Description

Mirrors SPEC-133 FR-007 and SPEC-134 FR-008.

#### Acceptance Criteria:

- [ ] `logs_queue_url` variable on `modules/table-builder`, wired in `main.tf`, set as
      `LOGS_QUEUE_URL` on all five functions.
- [ ] An `EmitStructuredLogEvents` statement granting `sqs:SendMessage` on the logs queue ARN,
      matching the data-quality Sid and shape.
- [ ] `LOGS_QUEUE_URL` optional by construction — `environ.get`, never `_require`. This plane is
      the one that learned that lesson (PR #196), so it is the one where it must not regress.
- [ ] The deploy-role check is performed and its finding recorded.
- [ ] IAM and environment apply before the instrumented code deploys.

---

## Data Model

Events follow SPEC-127's schema, landing at `logs/service=table-builder/…`. Field vocabulary:

```
space: str          actor: str          database: str       table: str
location: str       prefix: str         objects: int        bytes: int
format: "csv" | "json" | "parquet"      columns: int
column_names: list[str]                 column_types: list[str]
partition_keys: list[str]               declared_dirs: list[str]
query_id: str       workgroup: str      polls: int          elapsed_ms: float
state: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED"
state_change_reason: str                absent: bool        all_string: bool
reason: str
```

## File & Folder Structure

```
lambdas/table-builder-{validate-authorize,inspect-source,infer-schema,check-table-absent,execute-ddl}/
lambdas/table-builder-execute-ddl/athena_run.py
lambdas/control-plane-common/test_instrumentation_coverage.py      # + table-builder entry
infra/modules/table-builder/{variables,lambda}.tf
infra/modules/table-builder/policies/*.json.tftpl
infra/main.tf
```

## Implementation Phases

### Phase 1: Infrastructure, applied first

- Variable, wiring, `LOGS_QUEUE_URL`, the IAM statement, the recorded deploy-role finding.

### Phase 2: Into the pipe

- `init` + `@traced` on all five verbs, outermost above `notifies_on_failure`; the harness entry;
  `SERVICE_RE`.

### Phase 3: The narrative

- Steps; the DDL and post-condition events (FR-003); inference and layout (FR-005).

### Phase 4: The poll

- Transition-only narrative in `athena_run.run_ddl`, with the no-change test and the
  ceiling-exhaustion event.

### Phase 5: Live verification

- Build one table end to end from the UI and confirm the five verbs' events join on `request_id`,
  that the DDL event carries the query id and terminal state, and that `check-table-absent`'s
  verdict is in the record on both sides of the create.
