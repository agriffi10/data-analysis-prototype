# Spec: Child Spans for the Seven Flat Planes

**ID:** SPEC-226
**Status:** Draft
**Last Updated:** 2026-09-08
**Depends On:** SPEC-130 (Completed), SPEC-224

## Overview

`cpcommon.observability.step(name)` opens a child span around one named internal step, turning "the
verb took 8 seconds and failed" into "the listing took 40 ms, the column probe took 7.9 s and
raised". It has been available since SPEC-130 and is used by data-quality, the log sweep, the API,
the DLQ drain and user-directory-build. **Seven planes have none of it** — archive, file-ops,
file-send, results-conversion, shared-space, table-builder and table-share each emit a flat sequence
of `info` events inside one span, so an operator can see that a verb was slow and not which part of
it was.

Most of that is bought from the shared layer: all seven route their durable work through the same
`cpcommon` modules, so instrumenting those once covers them without touching seventy-odd verbs. But
**the shared layer alone does not finish the job**, and where it falls short is where the time
actually goes: `results-conversion-convert` — the Excel writer, the verb this arc would most want
timed — reaches a shared helper only on the failure path, so on a successful personal-space
conversion it would gain **zero** child spans. Five of table-builder's eleven verbs are in the same
position. Those are named and instrumented here rather than left for a reader to discover.

## Scope

### In Scope

- Child spans on the shared `cpcommon` operations the seven planes route durable work through,
  enumerated as a literal table rather than described.
- Child spans on the named verbs the shared layer does not reach on a **successful** run.
- A stated, enforced rule for where a step may **not** go, with the mechanism behind each case.
- A measured budget for the events this spec adds.
- A guard that holds each of the seven planes to having child spans, redденable per plane.

### Out of Scope

- **Steps inside `copy_batch`'s worker pool.** Forbidden by FR-002 for a mechanical reason, not a
  stylistic one.
- **New `info`/`warning`/`error` events.** This spec adds spans, not narrative.
- **data-quality, the log sweep, the API, the DLQ drain, user-directory-build.** They already have
  steps and will inherit whatever the shared helpers gain.
- **Retro-fitting steps to every remaining verb.** The seven planes are covered where their durable
  work is; a verb whose body is a dict rearrangement gets nothing, and should.

---

## Functional Requirements

### FR-001: The instrumentation points are a literal table

#### Description:

The shared modules each of the seven planes reaches, derived by import search during authoring —
attribute-style imports counted, since `from cpcommon import notify` followed by `notify.send(...)`
is invisible to a submodule-path scan:

| Module | Reaches |
|---|---|
| `cpcommon.transfer` (copy, manifest, results) | archive, file-ops, file-send, table-share |
| `cpcommon.lock` | file-ops, table-builder |
| `cpcommon.cas` | shared-space |
| `cpcommon.registry` | archive, file-ops, file-send, results-conversion, table-builder, table-share |
| `cpcommon.s3_listing` | archive, file-ops, file-send, table-builder, table-share |
| `cpcommon.notify` | all seven |

**A module list is not an instrumentation list**, and a criterion phrased over "every operation in
the modules above" is satisfied by any subset and stays satisfied after a deletion. The spec
therefore fixes the *decision*, and the test holds a literal `(module, function, span name)` table
asserted **by count**, the way `Plane.verb_count` is a literal in
`test_instrumentation_coverage.py` "so a short enumeration fails rather than passing vacuously".

The contested candidates are resolved here rather than at build time, because each is a case FR-002
would otherwise forbid while FR-001 mandated it:

| Candidate | Decision | Why |
|---|---|---|
| `transfer.copy.copy_batch` | **step** | Once per invocation; the batch is the unit. |
| `transfer.copy.copy_one` | no | Per item, and inside the worker pool — FR-002. |
| `transfer.manifest.write_manifest` | **step** | Once per invocation. |
| `transfer.results.read_failed_items` | **step** | Once per invocation. |
| `transfer.results._read_json` | no | Once per result file; grows with the Map Run's children. |
| `lock.acquire`, `lock.release` | **step** | Once each. |
| `cas.cas_mutate` | **step** | Once per mutation, bounded by its own retry cap. |
| `registry.load` | **step** | Once per invocation. |
| `s3_listing.list_data_records`, `list_data_objects` | no | Generators — FR-002. |
| `s3_listing.object_size` | no | Per file entry — FR-002. |
| `notify.emit_notification` | **step** | Once per invocation. |

`list_data_objects` is `list_data_records` narrowed, so instrumenting both would nest two spans
measuring one listing even if they were not generators. The listing is timed at the bounded,
non-generator function that **consumes** it, which is where the library's own refusal message points.

#### Acceptance Criteria:

- [ ] A test holds the literal table above and asserts, for each row, that the named function
      carries a `@observability.step` with the named span name — and that the number of decorated
      functions in those modules equals the table's length, so an extra one is caught too.
- [ ] Driving one call through each instrumented function against a capturing sink emits a child
      span of that name whose `parent_span_id` is the handler's root span **and** whose
      `duration_ms` covers the work — asserted by making the instrumented call take a measurable
      time, so a span that closed before the body ran would fail.
- [ ] An exception raised inside an instrumented helper propagates unchanged — same type, message
      and `__cause__` — **and** the child span of that name is emitted with `status: "error"`. Both
      halves: the propagation assertion alone passes identically on an undecorated function.
- [ ] Every plane's suite is green by exit code. A scoped per-plane run needs `--no-cov`, since
      `addopts` carries `--cov-fail-under=85` and a partial run exits 1 regardless of results.

### FR-002: Where a step may not go, and the mechanism in each case

#### Description:

Three prohibitions, each with a failure mode that a reviewer reading the diff would not see.

**Not inside a per-item loop.** Every event is an SQS message and a line in an appended day object
the sweep rewrites **in full**, so a step per object costs one of each per object, and an archive
can hold tens of thousands.

**Not inside `copy_batch`'s worker pool** — and the reason is mechanical rather than volume.
log-foundry's span stack and baggage are `contextvars`, which do not cross into
`ThreadPoolExecutor` workers: a step planted on `copy_one` does not emit a *child* span at all, it
emits N **root** spans with `parent_span_id: None` in a separate trace. So the damage is not only
volume, it is that the events are unattributable — and a guard counting child spans cannot see it.

**Not on a generator function.** `s3_listing`'s two listers are generators. On `log-foundry` 0.6.0
`@trace` accepts one and traces the *call*: the span opens and closes before the body runs,
reporting `status: "ok"` and a duration of microseconds for a listing that has not happened and may
still raise. On 1.0.0 — which SPEC-224 brings — it is a `TypeError` **at decoration**, so for this
fleet it is a module-import failure and a cold start that never completes. Both measured during
authoring. The 1.0.0 behaviour is the safer one and is why this is a build-time failure rather than
a production one, but the rule is stated because the fix is not "decorate it anyway".

#### Acceptance Criteria:

- [ ] Every function in FR-001's table has its per-invocation call bound stated in its docstring.
- [ ] A test drives a transfer of N objects at two different N and asserts the emitted span count is
      identical — and counts **every** span emitted, not only those with a non-null
      `parent_span_id`, so a step planted inside the worker pool is visible as N extra root spans
      rather than invisible.
- [ ] That test is mutation-tested by planting a step on `copy_one`, which must fail it.
- [ ] A test asserts no function in the instrumented modules is both a generator and decorated,
      by AST — the same guard SPEC-224 FR-005 establishes for the fleet, applied to these modules.
- [ ] The rule is recorded in `lambdas/info/shared-layer.md` beside the `observability` entry.

### FR-003: The verbs the shared layer does not reach on a successful run

#### Description:

The shared layer gives every one of the seven planes child spans, but two planes get them only on
paths a successful run does not take, and this spec's promise is not met by that.

**`results-conversion-convert`** reaches `registry.load` only when the destination is a shared space
— it sits in the `else` of the personal-space branch — and `emit_notification` only from the failure
emitters and the separate notify verb. On a successful personal-space conversion it gains nothing.
It is also the verb the Overview names as where the time goes: the Excel writer.

**Five of table-builder's eleven verbs** — `apply-refresh`, `execute-ddl`, `infer-schema`,
`diff-schema`, `load-table-definition` — reach `cpcommon.notify` only through
`@notifies_on_failure`, so they gain nothing on a green run.

Each gets a step on its own principal operation, at the same one-per-invocation granularity FR-001
uses, added to the same literal table.

#### Acceptance Criteria:

- [ ] `results-conversion-convert` emits at least one child span on a **successful personal-space**
      conversion, asserted by driving that path.
- [ ] Each of the five table-builder verbs emits at least one child span on a **successful** run,
      asserted by driving each.
- [ ] Their rows are in FR-001's literal table and counted by the same assertion.

### FR-004: Each of the seven planes is held to having child spans, and can be reddened alone

#### Description:

A guard is needed for the reason `test_instrumentation_coverage.py` exists: a refactor that moves a
plane off a shared helper takes its child spans with it, silently, leaving a plane that reads as
instrumented and reports one flat span.

**The obvious guard cannot be mutation-tested.** "At least one of this plane's verbs emits a child
span" is satisfied for every plane by two or more independent modules, so removing any single step
reddens the guard for no plane at all — strike `registry.load`'s and results-conversion still passes
through `notify`. A guard whose mutation cannot be performed is a guard nobody can trust.

So the guard asserts per plane against a **named verb and a named span**, drawn from FR-001's table,
on a path the plane actually takes on a successful run. Removing one step then reddens exactly one
plane, and the message names it.

It is a runtime guard, unlike `test_instrumentation_coverage.py`, which is pure AST. Every plane
already drives handlers in its own suite and `captured_events` is fleet-wide, so the drivers exist;
what they lack is a parent-span helper on `_CapturingSink`, which this FR adds.

#### Acceptance Criteria:

- [ ] For each of the seven planes, a test drives one named verb and asserts a named child span with
      a non-null `parent_span_id` matching that verb's root span.
- [ ] Mutation-tested per plane: removing that plane's step reddens exactly that plane's case, and
      the message names the plane, the verb and the span.
- [ ] The guard carries a positive control that the collector collected — an empty event list must
      not satisfy it.
- [ ] `_CapturingSink` gains a helper for child spans by parent, used by every case rather than
      re-implemented per plane.

### FR-005: The event volume this spec adds is measured, not assumed

#### Description:

The area's Fences require that every cap is computed by a test against the budget that sized it, and
this spec's whole prohibition rests on the cost of an event without ever stating what it is adding.
Each step is two events — a `span.start` and a `span.end` — so the delta is twice the number of
steps a verb's path actually executes, and the sweep rewrites the day object in full.

#### Acceptance Criteria:

- [ ] A test computes the per-invocation event delta for the worst-case verb on each of the seven
      planes and asserts it against a stated budget, with the budget's derivation recorded beside it.
- [ ] The budget carries deliberate headroom, and the amount and reason are stated — a budget pinned
      exactly at the measurement leaves the next legitimate step nothing to spend.
- [ ] The delta is measured by counting emitted events through a capturing sink, not by counting
      decorators.

---

## Interface Contract

No new public surface. `cpcommon.observability.step` is used exactly as today:

```python
from cpcommon import observability

@observability.step("copy-batch")
def copy_batch(items, failure_reason, *, echo_fields, concurrency=COPY_CONCURRENCY): ...
```

The signature is reproduced as it actually is: `echo_fields` is **keyword-only with no default**,
which is a settled decision — "a default hands a new caller either table-share's vocabulary or an
empty set, and both are wrong without a review" — and this spec does not change it.

An emitted child span carries the handler's baggage (`verb`, `request_id`) **on the calling
thread**. Baggage is a `ContextVar` and does not reach `copy_batch`'s worker threads, which is
FR-002's second prohibition stated once more where an implementer would otherwise assume the
opposite.

## Implementation Phases

### Phase 1: The table and the prohibitions

- The steps in FR-001's table on the shared modules; docstring bounds; the AST generator guard.
- The literal-table test and the two-N span-count test, each mutation-tested.

### Phase 2: The verbs the shared layer misses

- Steps on `results-conversion-convert` and the five table-builder verbs; their table rows.
- The driven success-path assertions for each.

### Phase 3: The guard and the budget

- `_CapturingSink`'s parent-span helper; the per-plane guard, mutation-tested plane by plane.
- FR-005's measured delta and its budget; the rule into `lambdas/info/shared-layer.md`.
- Full local gates green by exit code.
