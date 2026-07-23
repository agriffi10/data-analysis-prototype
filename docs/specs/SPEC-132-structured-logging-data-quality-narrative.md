# Spec: Structured Logging — Narrate the Data-Quality Control Plane

**ID:** SPEC-132
**Status:** Draft
**Last Updated:** 2026-07-23
**Depends On:** SPEC-130 (the emitters and `step`), SPEC-128 (the nine verbs are traced)

## Overview

SPEC-128 put all nine data-quality verbs in the pipe, and what the pipe carries is nine
`span.start`/`span.end` pairs joined on `request_id`. That answers *which verb failed* and *how
long each took*, and nothing else. A run that dies in `inspect-source` after eight seconds leaves
an operator unable to tell, from the store, whether it listed nothing, listed ten thousand
objects, resolved a format it could not probe, or timed out reading a header — the four
possibilities have completely different fixes and identical traces.

This spec spends SPEC-130's primitives across the nine verbs: what each one found, which named
step it was in, and why it stopped. Data-quality is the right plane for it for the same reasons it
was the right pilot — the longest chain, the newest under real load, and entirely operator-facing,
so a mistake costs log quality rather than access.

Two amplification hazards shape it more than the narrative does. `check-query` is invoked on a
**30-second poll** for as long as the profiling query runs, which is minutes to tens of minutes,
so anything it says on every poll is multiplied by fifty. And `byte-scan` and `inspect-source`
iterate per file, per region and per column, where a single misplaced emitter turns one run into
thousands of events. Both are handled by prohibition rather than by care.

## Scope

### In Scope

- Narrative events across all nine verbs: what each found, and why it stopped.
- Named `step` child spans on the bounded internal steps of each verb (the table in FR-002).
- A stated failure vocabulary — stable reason tokens, never a stringified exception.
- Per-item and per-poll prohibitions, with tests that fail when either is violated.
- Extending `test_instrumentation_coverage.py` so an un-narrated verb fails the suite.

### Out of Scope

- **Any change to what the verbs do.** No change to validation, authorization, SQL, the manifest,
  the report, the notification, or the state machine. Observation only.
- **Removing existing `logging.getLogger()` calls.** They stay; under FR-004 they hold the
  specifics the structured store deliberately does not.
- **The other three control planes** — table-builder, table-share, shared-space — none of which is
  instrumented at all. Rollout continues one plane at a time (SPEC-127).
- **`control-plane-dlq-drain`**, which has neither `init` nor `@traced`.
- **Cross-verb trace stitching.** One run is still nine traces (SPEC-128 FR-002/FR-005).
- **Any Athena table or query over `logs/`.**

---

## Functional Requirements

### FR-001: Every verb says what it found, not only that it ran

#### Description

Each verb emits at least one `info` event describing the work it actually did — counts, shapes,
and the names of the things it touched. The measure of success is a specific one: reading a run's
events for a verb should let an operator say what that verb *found* and go straight to the object
it found it in, without opening CloudWatch and without the source data itself.

#### Acceptance Criteria:

- [ ] Per-verb minimum content:
      - **validate-authorize** — the actor, the target space and whether it was the actor's own or
        a shared one, the normalized source location, and the authorization outcome.
      - **inspect-source** — the listing prefix, objects listed, total bytes, resolved format, the
        column names found, the partition keys detected, and whether a cap was hit.
      - **create-temp-tables** — column count, format, whether a raw CSV table was also created.
      - **start-profile-query** — how many queries were started (profile / ragged / duplicates,
        as a count and which of the optional ones were applicable).
      - **check-query** — the aggregate status, and per-query terminal states **only on change**
        (FR-005).
      - **byte-scan** — files scanned, bytes scanned, how many invalid sequences were found and
        the **byte offsets** at which they occurred, whether the scan was bounded by its share.
        Offsets are positions; the bytes at those positions are file contents and are not logged.
      - **assemble-report** — result rows read, findings assembled, the report key written.
      - **drop-temp-tables** — the tables dropped, and how many drops failed without failing the
        run.
      - **notify-failure** — which outcome it notified about, and whether a report link was minted
        (FR-007).
- [ ] Every message string is a **literal**, with all variation in fields (SPEC-130 FR-001).
- [ ] Each verb's unit tests assert on the emitted events for its happy path, via a capturing
      sink, not merely that the verb returned.

### FR-002: Named steps, bounded per invocation

#### Description

A `step` child span on the internal functions that represent a distinct, bounded phase, so a
verb's duration decomposes. Every one of these runs a bounded number of times per invocation —
that is the selection criterion, not importance.

| Verb | Steps |
|---|---|
| validate-authorize | `authorize`, `validate-destination` |
| inspect-source | `list-objects`, `resolve-format`, `probe-columns`\*, `detect-partitions`, `write-manifest` |
| create-temp-tables | `run-ddl` (≤2 per invocation) |
| start-profile-query | `start-queries` |
| check-query | `describe-queries` |
| byte-scan | `scan` (**the whole scan — never per file or per region**) |
| assemble-report | `find-result`, `read-results`, `write-report` |
| drop-temp-tables | `drop-table` (≤2 per invocation) |
| notify-failure | none — the handler is the step |

\* `probe-columns` and `scan` wrap the **whole loop**, in `_probe_all` / `_scan_all`, not the
per-object `_probe_columns` / `_scan_file`. Naming them in this table while the criterion below
forbids a step on a per-file function reads as a contradiction; extracting the loop is what
satisfies both, and it is what the duration an operator wants ("how much of the verb went into
reading headers") actually measures. A folder of 900 objects would otherwise mint 900 child spans,
each an SQS message and a line in a day object the sweep rewrites in full.

#### Acceptance Criteria:

- [ ] Each step above emits a child span with `function` equal to the step name, parented to the
      handler's span, carrying `verb` and `request_id` (SPEC-130 FR-003/FR-004).
- [ ] A step that raises closes `status: "error"` on itself **and** on the handler span, and the
      original exception reaches `notifies_on_failure` unchanged — a test asserts a `TerminalError`
      raised inside a step still produces the same user notification, with its `tokens` intact.
- [ ] No step wraps a function called once per file, per region, per object or per column.
- [ ] The step count per invocation is bounded by a constant for every verb; `run-ddl` and
      `drop-table` are the only repeated ones and are capped at two by the verbs themselves.

### FR-003: A failure names its step and its reason

#### Description

When a verb stops, the store should say which step and why, in a form that can be filtered and
counted across runs. That means a **stable reason token**, not a rendered message.

`TerminalError.detail` is operator-only by design and carries the AWS message or the key that
explains the failure, so it belongs in the event. The stable token is required **alongside** it,
not instead of it, and for a reason unrelated to sensitivity: `detail` is prose, and prose cannot
be counted. "How often does this fail this way" needs a value that does not vary with the object
that happened to trigger it.

One exception, and it is the file-contents line (SPEC-130 FR-005) reaching into an error path: a
`detail` built by interpolating **parsed content** — a parser quoting the offending value, a type
mapper naming the cell it could not convert — is file data wearing an error message. Those sites
log the reason token and the exception type and omit `detail`.

#### Acceptance Criteria:

- [ ] Every `TerminalError` raise site in the nine verbs is preceded by an `error` event carrying
      the step name, the exception type, and a stable reason token.
- [ ] The reason token is derived from the `messages` constant's **name**, not by parsing or
      substringing the rendered message text. Scraping a token out of prose is the failure
      `dq_create_temp_tables._create` already has a comment warning against.
- [ ] `detail` is logged where present. The build **audits every raise site** for a `detail`
      interpolating parsed file content; each one found is listed in the delivery doc and logs the
      token only. A criterion that says "be careful" is not a criterion — the deliverable is the
      list.
- [ ] `TerminalError.tokens` are logged too. They are counts and names bound for the user's own
      notification, and a field that reproduces what the user was told is exactly what makes a
      support question answerable.
- [ ] Degraded-not-failed paths emit `warning`, not `error`: a failed ragged or duplicates query
      degrading to `not_computed` (SPEC-111 FR-004), and a tolerated drop failure in
      drop-temp-tables. A run that succeeded must not contain `error` events.

### FR-004: Metadata yes, file contents never

#### Description

SPEC-130 FR-005's rule, made concrete for the plane whose entire job is reading users' files —
which makes it both the plane that benefits most from naming them and the only plane that can
leak what is inside them.

**Permitted, and expected:** the source location and listing prefix, individual object keys and
file names, the database and table names, column names, partition-key names, the space name, the
actor's username, the report and manifest keys, plus every count, size, duration and enum. An
operator reading a failed run's events should be able to go straight to the object.

**Never:** anything read out of a file. Cell values, sampled rows, a `SELECT` result set, a
decoded byte range, the text at a byte offset a UTF-8 scan rejected, a header row's contents
where those are values rather than column names. This plane's verbs hold all of it in memory at
some point — `byte-scan` decodes user bytes, `assemble-report` reads Athena result rows,
`inspect-source` parses headers — so the rule is a live constraint here, not a formality.

**Never, separately: the actor's ID token**, which is the one thing in the request envelope that
is a credential rather than a name.

#### Acceptance Criteria:

- [ ] `inspect-source` logs column names and partition-key names — reversing the caution, because
      the names are what a schema bug is *about*.
- [ ] `byte-scan` logs offsets and counts and **never the bytes or the decoded text** at them.
      This is the single highest-risk call site in the plane: the verb's whole purpose is holding
      user bytes, and the natural debugging instinct is to log the sequence that failed to decode.
- [ ] `assemble-report` logs row and finding **counts** and the report key, never a result row.
- [ ] `check-query` logs query ids, states and the Athena `StateChangeReason`; never a result.
- [ ] A test over the nine verb modules asserts no emitter call passes a field whose name is in a
      contents denylist (`value`, `values`, `sample`, `samples`, `row`, `rows`, `cell`, `content`,
      `contents`, `preview`, `head`, `text`, `token`, `id_token`). **The denylist wins over this
      spec's own Data Model, which lists `rows: int`** — a count of rows is spelled `row_count`,
      because the tripwire's whole value is that it is dumb and strict, and a field an author has
      to argue is fine is a field whose name should say so instead. (Caught on the guard's first
      real run, against `assemble-report`.) Name-based and therefore imperfect — it is a tripwire for the obvious mistake, not the enforcement; the rule turns on
      where a value came from, which no name test can see.
- [ ] The existing `logging.getLogger()` calls are **unchanged**.

### FR-005: `check-query` narrates transitions, not polls

#### Description

`CheckQuery` is invoked from a 30-second `Wait` loop for as long as the profiling query runs —
minutes to tens of minutes by design, since the poll was deliberately moved into the state machine
to escape Lambda's 900-second ceiling. A verb that emits four events per invocation therefore
emits two hundred per run, all of them saying the query is still running.

Boundary spans already record every poll. The narrative must add information, which means state
**changes** only.

#### Acceptance Criteria:

- [ ] A poll that observes no change from the incoming state emits **no** `info` event — the
      `span.start`/`span.end` pair is the record that a poll happened.
- [ ] A query reaching a terminal state (`SUCCEEDED`, `FAILED`, `CANCELLED`) emits exactly one
      event, at the poll that observes it.
- [ ] A degradation to `not_computed` emits one `warning`; a `query_timeout` emits one `error`.
- [ ] A test drives a run of ≥20 polls with no state change and asserts the total non-boundary
      event count across them is zero.

### FR-006: The coverage guard extends to narrative

#### Description

`test_instrumentation_coverage.py` exists because partial instrumentation is worse than none — a
run showing eight of nine verbs looks like a run that *stopped* at eight. Narrative has the same
property with a nastier edge: a verb that traces but never narrates looks, in a query filtered to
narrative events, exactly like a verb that never ran.

#### Acceptance Criteria:

- [ ] The existing test module gains a per-verb case asserting each of the nine modules contains
      at least one `observability.info(` / `.warning(` / `.error(` call, by AST inspection.
- [ ] The existing guard that the enumeration found nine modules still holds, so a tenth verb
      cannot be added without narrating it.
- [ ] The existing assertions — every handler `@traced`, every module `init(service=
      "data-quality")`, `@traced` outermost above `@notifies_on_failure` — are unchanged and still
      pass. Touching all nine files is exactly when decorator order gets disturbed.
- [ ] The denylist test from FR-004 lives in the same module, for the same enumerate-don't-list
      reason.

### FR-007: `notify-failure` narrates the case where nothing else can

#### Description

The one verb with no `notifies_on_failure`, because it *is* the failure handler, and the one
invoked precisely when the rest of the run has already gone wrong. It is also the verb most likely
to receive a malformed event and therefore to emit its span with `request_id` **absent** — which
SPEC-128 FR-002 requires, since a fabricated correlation key silently merges unrelated runs.

An event with no `request_id` cannot be joined to its run, so what it says about itself is all
there is.

#### Acceptance Criteria:

- [ ] It emits one `info` naming the outcome it notified about and whether a report link was
      minted — the link builder mints nothing where the report view would resolve wrong
      (SPEC-114), and "no link" is a real state worth distinguishing from "no notification".
- [ ] An invocation whose event carries no usable `requestId` emits a `warning` saying so, and its
      events still carry **no** `request_id` field. A test asserts both: the warning is present
      and the field is absent, not empty.
- [ ] A failure inside notify-failure itself emits `error` and does not prevent the handler from
      completing — this verb staying total is what keeps a failed run from failing silently.

---

## Data Model

No stored shape changes. Events follow SPEC-127's schema and land in
`logs/service=data-quality/year=…/month=…/day=…/data.jsonl`.

Field vocabulary introduced by this spec — counts and shapes, plus the identifiers that make an
event actionable. Nothing here is read from inside a file (FR-004):

```
# counts and measures
objects: int        bytes: int          columns: int        partition_keys: int
files: int          invalid: int        rows: int           findings: int
queries: int        tables: int         dropped: int        failed: int
offsets: list[int]  duration_ms: float  capped: bool        link: bool

# identifiers — permitted, and the point of the exercise
actor: str          space: str          location: str       prefix: str
key: str            database: str       table: str          report_key: str
column_names: list[str]                 query_id: str

# enums
format: "csv" | "json" | "parquet"
space_kind: "own" | "shared"
status: "SUCCEEDED" | "FAILED" | "CANCELLED" | "not_computed" | "query_timeout"
step: str           reason: str
```

Run volume, so the budget is stated rather than discovered: eight verbs at roughly 4–8 events
each, plus `check-query` at **4** boundary events per 30-second poll (the handler span **and**
FR-002's `describe-queries` step, which this figure originally omitted) and near-zero narrative —
on the order of **250** events for a run with a ten-minute profiling query, against ~40 today.
The step is kept at one per invocation rather than one per query for exactly this reason: three
would have made it eight per poll.

## File & Folder Structure

```
lambdas/data-quality-validate-authorize/dq_validate_authorize.py
lambdas/data-quality-inspect-source/dq_inspect_source.py
lambdas/data-quality-create-temp-tables/dq_create_temp_tables.py
lambdas/data-quality-start-profile-query/dq_start_profile_query.py
lambdas/data-quality-check-query/dq_check_query.py
lambdas/data-quality-byte-scan/dq_byte_scan.py
lambdas/data-quality-assemble-report/dq_assemble_report.py
lambdas/data-quality-drop-temp-tables/dq_drop_temp_tables.py
lambdas/data-quality-notify-failure/dq_notify_failure.py
lambdas/data-quality-common/test_instrumentation_coverage.py
(+ each verb's co-located test_*.py)
```

No infra change, no IAM change, no new environment variable, no SPA change.

## Implementation Phases

### Phase 1: The guards first

- Extend `test_instrumentation_coverage.py` with the narrative-presence case and the FR-004
  denylist case. Both fail against the current tree — that is the point of writing them first.

### Phase 2: The front half

- validate-authorize, inspect-source, create-temp-tables, start-profile-query: steps, narrative,
  and failure events.

### Phase 3: The back half

- check-query (transition-only, with the no-change test), byte-scan, assemble-report,
  drop-temp-tables, notify-failure.

### Phase 4: Live verification

- Start a real check from the UI and confirm one run's nine traces carry the narrative, join on
  `request_id`, and that a successful run contains no `error` events.
- This run is also the one SPEC-128 FR-002 and SPEC-129's append still owe at real volume — the
  probe payloads were rejected at validation, so no data-quality run has yet exercised either.
