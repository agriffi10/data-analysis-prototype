# Spec: Structured Logging — Narrative Primitives and Function Identity

**ID:** SPEC-130
**Status:** Draft
**Last Updated:** 2026-07-23
**Depends On:** SPEC-127 (the pipe), SPEC-128 (the pilot), SPEC-129 (FIFO + day objects)

## Overview

The pipe SPEC-127/128/129 built carries **boundaries only**. Every trace is a `span.start` /
`span.end` pair per invocation with nothing in between, so a failed run tells an operator which
verb failed and how long it took, and nothing whatsoever about what it was doing when it failed.
The story — how many objects were listed, which destination was written, whether a retry happened
— exists today only in `logging.getLogger()` calls that reach CloudWatch and never reach the
structured store those same functions feed.

`log-foundry` already has both halves of the fix: level emitters (`lf.info`/`warning`/`error`)
that attach an event to the current span, and nested `@lf.trace` child spans that give per-step
duration and status. What is missing is a **sanctioned door** to them. `cpcommon.observability`
exports `init`, `flush` and `traced` and nothing else, so a verb wanting to narrate would import
`log_foundry` directly and bypass the never-raise discipline every other line of that module is
built around.

Two identity defects surface at the same time and are fixed here, because instrumenting call
sites on top of them would multiply the damage rather than expose it. Every root span in the
fleet reports `function: "handler"` — `traced` never passes a name, so `log-foundry` falls back to
`fn.__qualname__`, and every Lambda entry point in this repo is named `handler`. And `verb` is a
per-span **default** rather than baggage, so the moment a child span exists it does not inherit
the one field that says which verb it belongs to.

This spec ships the primitives and the identity fix. It changes **no call site** — SPEC-131 and
SPEC-132 are the consumers.

## Scope

### In Scope

- `observability.info` / `warning` / `error` — never-raise emitters over `lf.*`.
- `observability.step(name)` — a decorator opening a **child span** around a named internal step.
- `traced` names the root span after the **verb**, so `function` stops being `"handler"`.
- `verb` moves from span defaults to **baggage**, so child spans and messages inherit it.
- A stated rule for what may and may not become a field value — the line is **file contents**, not
  user-derived data — and the rule that none of it reaches the console.
- A test that enforces the never-raise guarantee by making the sink fail.

### Out of Scope

- **Every call site.** No verb, and not the sweep, gains a message in this spec. The primitives
  land unused; SPEC-131 (sweep) and SPEC-132 (data-quality) spend them. This is deliberate — the
  `cpcommon` layer attaches to every control-plane verb, so a change to it and a change to nine
  call sites do not belong in one blast radius.
- **`lf.continue_trace` / cross-Lambda stitching.** One run is still nine traces joined on
  `fields.request_id` (SPEC-128 FR-002/FR-005). Unchanged here.
- **`debug` and `critical` levels.** Three levels are the whole vocabulary: `info` for what
  happened, `warning` for a degraded-but-continuing path, `error` for a path that failed. A
  fourth level is a decision nobody will make consistently across four control planes.
- **`echo=True`.** Not merely unused — prohibited, and handled explicitly, in FR-006.
- **Instrumenting `control-plane-dlq-drain`**, which has neither `init` nor `@traced` today. Real
  gap, separate spec.
- **Any change to the sink, the queue, the sweep's layout, or retention.**
- **Backfilling or migrating the spans already written** as `function: "handler"` (see FR-002).

---

## Functional Requirements

### FR-001: Sanctioned emitters that cannot fail a verb

#### Description

`observability.info(message, **fields)`, and the same for `warning` and `error`. Thin passthroughs
to `lf.info`/`lf.warning`/`lf.error`, wrapped in the module's existing never-raise discipline: a
failure inside the emitter degrades to `logger.warning` and returns, exactly as `flush` and
`_stamp_request_id` already do.

They exist so that no call site anywhere imports `log_foundry` directly. The invariant being
protected is the one the module docstring already states — *logging must never be the reason a
verb fails* — and an emitter is a far more attractive place to violate it than a decorator,
because it sits in the middle of business logic where an exception is a real failure path.

`message` is a **literal**, and everything variable is a field. `info("appended", events=12)`
groups across every invocation; `info(f"appended {n} events")` produces a distinct message string
per run and cannot be counted, filtered or alerted on.

#### Acceptance Criteria:

- [ ] Three functions, signature `(message: str, **fields: object) -> None`, in
      `cpcommon/observability.py`, added to the module docstring's list of names.
- [ ] A sink that raises on emit does **not** propagate: a test replaces the configured sink with
      one whose `emit` raises, calls each emitter, and asserts the call returns normally and the
      caller's own return value is unaffected.
- [ ] That test asserts the degradation is **visible** — `logger.warning` was called — rather than
      only that nothing raised. A silently swallowed emitter is indistinguishable from a working
      one.
- [ ] An emitter called **inside** a traced call attaches its event to that span: same `trace_id`
      and `span_id` as the enclosing `span.start`, and it inherits `verb` and `request_id`.
- [ ] An emitter called with **no span open** emits a standalone one-event span rather than being
      dropped (`log-foundry` FR-004 behavior), and the test asserts the event reached the sink.
- [ ] The docstring states the literal-message rule and shows the counter-example.

### FR-002: The root span is named after the verb

#### Description

`traced` passes `name=verb` to `lf.trace`, so `traced("inspect-source")` emits
`function: "inspect-source"` instead of `function: "handler"`.

This is a **discontinuity in a store retained forever** (SPEC-127 FR-009), and that cost is
accepted rather than unnoticed: `logs/` will hold pre-change spans saying `"handler"` and
post-change spans saying the verb, in the same day's object across the cutover. No migration —
the objects are appended NDJSON and rewriting them to change a field would risk a day of logs to
tidy a boundary that a `WHERE` clause handles. `fields.verb` remains populated (FR-003), so a
query written against either era still works.

#### Acceptance Criteria:

- [ ] `traced("x")` emits `span.start` and `span.end` with `function == "x"`.
- [ ] `functools.wraps` still applies to the returned wrapper, so Lambda continues to resolve the
      entry point as `module.handler` **by name**. A test asserts `wrapper.__name__ == "handler"`
      — losing this makes every function in the fleet fail to start.
- [ ] A comment at the `name=` argument records the discontinuity, its date, and why no migration
      is done.
- [ ] `fields.verb` is still present on the root span (it is now baggage — FR-003), so a query
      filtering on `verb` is unaffected by the rename.

### FR-003: `verb` is baggage, so children inherit it

#### Description

`verb` is currently `lf.trace(defaults={"verb": verb})` — a **span** default, which applies to
that span's events and to nothing nested inside it. The moment FR-004's child spans exist, a step
event carries `request_id` (baggage) but not `verb`, so it can be joined to its run but not
attributed to the verb that produced it.

Setting it as baggage in `traced`'s wrapper fixes both, and must happen **after** `_reset_baggage`
— that call exists to stop a warm container leaking the previous invocation's `request_id`
(SPEC-128), and it clears the whole mapping.

#### Acceptance Criteria:

- [ ] `traced` calls `lf.set_baggage(verb=verb)` in the wrapper, **after** `_reset_baggage()` and
      alongside `_stamp_request_id`. `defaults={"verb": ...}` is removed, not duplicated.
- [ ] The call is wrapped so a failure degrades to `logger.warning` rather than failing the verb,
      matching `_stamp_request_id`.
- [ ] A test asserts a child span opened by `step()` (FR-004) carries **both** `fields.verb` and
      `fields.request_id`.
- [ ] A test asserts the root span's `span.start` still carries `verb`, confirming the library
      backfills baggage onto events already buffered when the baggage was set.
- [ ] The existing warm-container test still passes: two successive invocations, the second with
      no `requestId`, and the second's events carry no `request_id` at all.

### FR-004: `step(name)` — a child span around a named internal step

#### Description

`@observability.step("append-day")` on an internal function opens a child span, giving that step
its own `function`, `duration_ms` and `status`, parented to the handler's span within the same
`trace_id`. This is what turns "the verb took 8 seconds and failed" into "the listing took 40ms,
the column probe took 7.9s and raised".

It is a thin alias for `lf.trace(name=name)` and stays one, because the library's decorator is
**non-swallowing** by design — it records the failure and re-raises the original exception
unchanged — and that property must survive contact with this wrapper. A step that swallowed would
convert a terminal failure into a silent wrong answer.

**Which functions get a step is not decided here.** Per-item loops in particular are a volume
decision, since every event is an SQS message and a line in a day object the sweep rewrites in
full; SPEC-131 and SPEC-132 name their own steps and justify the count.

#### Acceptance Criteria:

- [ ] `step(name)` returns a decorator; a decorated function emits `span.start`/`span.end` with
      `function == name`, a `duration_ms`, and a `status`.
- [ ] The child's `trace_id` equals the enclosing handler span's, and its `parent_span_id` equals
      the handler span's `span_id`.
- [ ] A step that raises: the child closes `status: "error"` with `error.type` set, the **parent**
      also closes `status: "error"`, and the original exception reaches the caller **unchanged**
      — same type, same args, same `__cause__`. A test asserts identity of the exception object,
      not merely its type.
- [ ] A `TerminalError` raised inside a step is unaffected in every user-visible way: its
      `tokens` and `detail` survive, and `notifies_on_failure` still sees it. This is the failure
      mode that would matter most, since `@traced` sits outermost above `@notifies_on_failure`.
- [ ] A step called with **no** handler span open (a unit test calling the helper directly) starts
      its own root trace rather than raising.
- [ ] A sink that raises does not fail the decorated function.

### FR-005: What may become a field value — the file-contents line

#### Description

`logs/` lives in the **admin bucket** and is read by administrators for administrative purposes.
That destination is what makes user-derived *metadata* the right thing to log rather than the
wrong thing: an operator debugging a failed run needs the file name, and a store that omits it in
the name of caution is a store that sends them to CloudWatch instead (user decision, 2026-07-23).

**Permitted, and encouraged where it aids debugging:** file names, S3 keys, prefixes and
locations; usernames; database, table and column names; space names; counts, sizes, durations,
booleans, attempt numbers, enum-ish states; and `request_id`, `service`, `verb`. **Usernames are
not sensitive** in this system — the username *is* the S3 prefix, the principal tag and the Glue
database name (SPEC-033), so it is already the primary key of every operator-facing record.

**The one line, and it is absolute: no data from inside a file.** A cell value, a sampled row, a
parsed record, a decoded byte range, a rendered result set — any of it can be PII, none of it is
needed to debug a control plane, and `logs/` is retained forever. Column *names* are schema and
are permitted; column *values* are file contents and are not.

**Also never, regardless of provenance: tokens, credentials, and email addresses.** A bearer
credential is not metadata — an expired ID token is still a signed assertion about a real person,
which is why `dlq_drain._redacted` already replaces every known token field before its forensic
log line. An email address is excluded for a different reason: unlike a username it appears
nowhere else in this system's operator records, carries no operational meaning here, and would be
the only personal contact detail in a prefix retained forever. It reaches only the two Cognito
triggers, where SPEC-137 FR-005 makes the exclusion testable.

`lf.trace`'s no-capture setting stays exactly as it is (SPEC-127 FR-009). It is unchanged by this
rule and for a different reason: an automatic capture of every argument and return value across
34 functions would sweep up file contents by default, which is precisely the line above.

#### Acceptance Criteria:

- [ ] The rule is written in the `observability` module docstring, as the permitted list, the
      file-contents line, and the token exclusion.
- [ ] The emitters do **not** attempt to enforce it at runtime, and the docstring says so, so the
      absence of a filter reads as a decision rather than an omission. The rule turns on
      *provenance* — did this value come from inside a user's file — and no filter over a field
      name or a value shape can determine that. Enforcement is review plus the per-call-site
      criteria in SPEC-131, SPEC-132 and SPEC-133.

### FR-006: The narrative never reaches the console

#### Description

These events go to the logs queue and from there to the admin bucket. They do not go to stdout,
stderr, or a CloudWatch log line (user decision, 2026-07-23). The library's `echo=` parameter
writes a synchronous human-readable line to the console, and nothing in this repo may use it.

`**fields` makes this an unusually quiet mistake: `info("appended", echo=True)` does not fail and
does not echo — it silently emits a field named `echo`. So `echo` is handled explicitly rather
than left to be absorbed.

One exposure is named rather than closed. When `LOGS_QUEUE_URL` is unset, `init` falls back to
`StdoutSink`, and those events do reach CloudWatch. That fallback **stays** — it is the cold-start
safety property the whole module is shaped around (a function missing the variable must log to
stdout rather than crash a control plane, PR #196) — and it is bounded: the same functions'
existing `logging.getLogger()` calls already put keys and locations in CloudWatch today, so the
fallback exposes nothing the log group does not already hold.

#### Acceptance Criteria:

- [ ] No emitter accepts or forwards `echo`. The wrappers call `lf.*` with `echo=False`
      unconditionally.
- [ ] `echo` passed as a field is **dropped, not emitted**, and produces a `logger.warning` naming
      the mistake. A test asserts the emitted event has no `echo` field and that the warning
      fired — dropping it silently would be the same class of quiet failure.
- [ ] No `echo=True` anywhere in the repo; a test greps the four instrumented trees for it.
- [ ] The `StdoutSink` fallback is unchanged, and its comment records that the narrative can reach
      CloudWatch through it, why the fallback stays anyway, and what bounds it.

---

## API / Interface Contract

```python
from cpcommon import observability

observability.init(service="data-quality")

@observability.step("probe-columns")
def _probe_columns(bucket: str, key: str, fmt: str) -> list[dict]:
    ...

@observability.traced("inspect-source")           # -> function: "inspect-source"
@notify.notifies_on_failure(...)
def handler(event, context) -> dict:
    observability.info("listed source", objects=142, bytes=99_812, format="csv")
    observability.warning("cap reached", limit=1000, taken=1000)
    observability.error("probe failed", step="probe-columns", reason="unreadable-header")
```

Emitted shape (fields abridged), one root span and one child, joined by `trace_id`:

```json
{"message": "span.start",  "function": "inspect-source", "parent_span_id": null,
 "fields": {"verb": "inspect-source", "request_id": "a1b2"}}
{"message": "listed source", "function": "inspect-source",
 "fields": {"verb": "inspect-source", "request_id": "a1b2", "objects": 142, "format": "csv"}}
{"message": "span.start",  "function": "probe-columns", "parent_span_id": "88cd…",
 "fields": {"verb": "inspect-source", "request_id": "a1b2"}}
{"message": "span.end",    "function": "probe-columns", "status": "ok",    "duration_ms": 7910.2}
{"message": "span.end",    "function": "inspect-source", "status": "error", "duration_ms": 8004.7,
 "error": {"type": "TerminalError"}}
```

## File & Folder Structure

```
lambdas/control-plane-common/cpcommon/observability.py
lambdas/control-plane-common/test_observability_cpcommon.py
```

No infra change, no IAM change, no new environment variable, no SPA change.

## Implementation Phases

### Phase 1: Identity

- `traced` passes `name=verb`; `verb` moves from span defaults to baggage, set after
  `_reset_baggage()`.
- Tests: `function` is the verb; `wrapper.__name__` is still `handler`; the warm-container
  baggage-reset test still passes.

### Phase 2: Emitters and steps

- `info` / `warning` / `error` / `step`, each never-raise on the instrumentation path and
  transparent to the wrapped function's exceptions.
- Tests: attachment to the enclosing span, orphan emission, parent/child linkage, error status on
  both spans, exception identity preserved, failing sink at every entry point.

### Phase 3: The rules, written down

- Module docstring: the three names, the literal-message rule, the permitted-fields list, the
  file-contents line, the token exclusion, and why no runtime filter can enforce a provenance rule.
- `echo` dropped-and-warned; the repo-wide `echo=True` grep test; the `StdoutSink` fallback
  comment recording what it exposes and what bounds it.
