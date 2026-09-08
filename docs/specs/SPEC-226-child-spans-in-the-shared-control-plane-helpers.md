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
file-send, results-conversion, shared-space, table-builder and table-share.

**An earlier draft of this spec claimed the shared `cpcommon` layer could buy all seven at once.
That is false, and the correction is the reason this spec has the shape it has.** A reviewer built
it and checked the call bounds: five of the eight shared functions it named are invoked **inside
loops** — `notify.emit_notification` once per recipient, `registry.load` once per recipient,
`cas.cas_mutate` once per member, `lock.acquire` and `lock.release` once per target. Verified
independently. Stepping any of them is exactly the per-item instrumentation this spec forbids.

What survives as genuinely once-per-invocation is the **transfer trio** — `copy_batch`,
`write_manifest`, `read_failed_items` — which reaches four planes. The other three planes get their
spans at the bounded call site in their own code, because there is no shared bounded site to use.
That is a smaller shared win than the earlier draft promised and a larger per-plane one, and saying
so is the point: a spec that promised the cheap version would have had a builder ship five per-item
steps.

## Scope

### In Scope

- Child spans on the three shared operations that really are once-per-invocation.
- Child spans at the bounded call site in each plane the shared layer cannot reach.
- A stated, enforced rule for where a step may **not** go, with the mechanism behind each case —
  including the five shared functions that look eligible and are not.
- The delivery-timing change that decorating a narrating helper causes, which is not obvious and
  broke thirteen existing tests when a reviewer added a step to `lock.py`. **Measured on this
  build: it breaks nothing.** With every step in this spec applied, removing the drain reddens
  exactly one test — the control written for it — and every other test in the suite passes. A
  count is not written here on purpose: the suite grew inside this branch and a dated number reads
  as current to whoever does not check it. The thirteen are history
  about `lock.py`, which this spec forbids stepping; in `add_members` the narrative tests assert on
  is emitted after both steps have closed, and `cache.py`'s `"roster fanned out"`, the one event now
  inside a span, is asserted by no test. The drain is a forward guard, not a repair.
- A guard that holds each of the seven planes to having child spans, reddenable per plane.

### Out of Scope

- **Steps inside `copy_batch`'s worker pool**, and inside any of the five looping functions above.
- **New `info`/`warning`/`error` events.** This spec adds spans, not narrative.
- **A verb whose body does no I/O.** `diff-schema` is the case: it imports no client and its body is
  a comparison over column dicts. An earlier draft mandated a step there while its own Scope
  excluded it; the Scope wins.
- **data-quality, the log sweep, the API, the DLQ drain, user-directory-build**, which already have
  steps.

---

## Functional Requirements

### FR-001: The three shared operations that are genuinely bounded

#### Description:

| Module | Function | Span | Bound | Reaches |
|---|---|---|---|---|
| `transfer.copy` | `copy_batch` | `copy-batch` | exactly once per invocation | archive, file-ops, file-send, table-share |
| `transfer.manifest` | `write_manifest` | `write-transfer-manifest` | **at most** once per invocation | archive, file-ops, file-send, table-share |
| `transfer.results` | `read_failed_items` | `read-failed-items` | **at most** once per invocation | archive, file-ops, file-send, table-share |

**Two of the three are "at most once", corrected during the build.** file-ops guards
`write_manifest` with `if lines:` (`file_ops_build_transfer_manifest.py:204`), and three of the four
collect verbs return early before `read_failed_items`. Only `copy_batch` is unconditional in every
caller. A driven bound test asserting exactly one call per invocation fails on a fixture with
nothing to transfer.

The span name is the operation, kebab-cased, so a query groups across every plane that calls it. A
name that is a bare verb (`load`, `acquire`) is **module-qualified**, because the span name is the
field an operator filters on and `load` names nothing across a fleet where several modules could own
one — that rule matters for FR-002's call sites rather than these three.

**`write-manifest` became `write-transfer-manifest` during the build, and the reason generalises
the rule.** The name this FR originally gave collides with `archive-write-manifest`, a whole verb
whose root span is `write-manifest`, and with a pre-existing data-quality step of the same name —
so `function = "write-manifest"` would have returned a Lambda's total duration, data-quality's
manifest write and four planes' transfer-manifest writes together. Checking each new span against
its OWN verb's root span, which is how three other names were corrected, cannot see this. A
fleet-wide guard now sweeps every step name against every verb name.

The literal table is asserted as a **sorted list, not a set**: set equality hides two functions
sharing one span name.

**The count assertion cannot be "decorated functions in these modules".** `lock.LockWording` carries
`@dataclass` and `notify.notifies_on_failure` carries a nested `@functools.wraps`, so a literal
reading is unsatisfiable. It counts functions carrying `observability.step`, paired with a second
guard asserting **no scanned module imports `log_foundry`** — without which a step added through
`lf.trace` directly is invisible to the count and bypasses the one-door rule at the same time.

#### Acceptance Criteria:

- [ ] A test holds the table as a sorted list and asserts the set of `observability.step`-decorated
      functions in the scanned modules equals it exactly, so an extra one fails too.
- [ ] A second test asserts no scanned module imports `log_foundry`.
- [ ] The module scan globs `transfer/*.py` with a positive control that the glob collected, so a
      new module beside `copy.py` is scanned on day one.
- [ ] Driving each instrumented function emits a child span of that name whose `parent_span_id` is
      the handler's root span and whose `duration_ms` covers the work. The duration floor is a
      **literal**, not derived from the fixture's delay: a derived floor collapses to `>= 0.0` when
      the delay is mutated to zero, which was measured. A separate test keeps delay and floor in step.
- [ ] An exception raised inside an instrumented helper propagates unchanged **and** its child span
      is emitted with `status: "error"`. The propagation half alone passes on an undecorated function.

### FR-002: Where a step may not go, and the mechanism in each case

#### Description:

Four prohibitions. The first is the one an earlier draft of this spec got wrong.

**Not on a shared function that its callers invoke in a loop.** These look like the cheap win and
are not, and each is named because the next author will reach for them too:

| Function | Actual bound | Where |
|---|---|---|
| `notify.emit_notification` | per recipient | the notification loops in `add_members`, `remove_members` and `delete_space` |
| `registry.load` | per recipient / per name | the recipient loop in table-share's and file-send's `validate-authorize` |
| `cas.cas_mutate` | per member | `cache.write_roster_to_all`'s fan-out |
| `lock.acquire`, `lock.release` | per target | the target loop in `file_ops_acquire_lock` |

Cited by symbol rather than by line: three line numbers in an earlier draft of this table went
stale inside the very commit that added them, because the edits moved the code they pointed at.

**Not inside a per-item loop generally.** Every event is an SQS message and a line in an appended
day object the sweep rewrites **in full**.

**Not inside `copy_batch`'s worker pool** — and the reason is mechanical rather than volume.
log-foundry's span stack and baggage are `contextvars`, which do not cross into
`ThreadPoolExecutor` workers. Measured with a step planted on `copy_one` over five items: **five
spans, every one with `parent_span_id: None`, six distinct trace ids, and empty `fields`** — no
`verb`, no `request_id`. So the damage is not only volume; the events are unattributable, and a
guard counting *child* spans cannot see them.

**Not on a generator function.** `s3_listing`'s two listers are generators. On 0.6.0 `@trace`
accepts one and traces the *call* — measured `status: "ok"`, `duration_ms: 0.23`, emitted before the
body is consumed. On 1.0.0, which SPEC-224 brings, it is a `TypeError` **at decoration**, so for
this fleet it is a module-import failure and a cold start that never completes.

#### Description of the delivery-timing consequence:

Decorating a helper that already narrates **changes when its existing events are delivered**.
log-foundry delivers an event emitted with no span open **synchronously**, and buffers one emitted
**inside** a span until the worker flushes. Measured:

```
after a call with no span open : ['no span open']
after a call inside a span     : ['no span open']
after flush()                  : ['no span open', 'span.start', 'span open', 'span.end']
```

So a shared helper that emits `info` and gains a `@step` stops delivering that `info` synchronously.
A reviewer adding a step to `lock.py` broke **thirteen** existing tests this way, all of which
asserted on events that had not been flushed yet. This will recur for every future step on a
narrating module, so it is fixed once in the harness rather than per test.

#### Acceptance Criteria:

- [ ] Every function in FR-001's table states its per-invocation call bound in its docstring, and a
      test asserts each bound by driving the function's callers — not by reading the docstring.
- [ ] A test asserts none of the five looping functions in the table above carries a step.
- [ ] A test drives a transfer at two values of N and asserts the emitted span count is identical,
      counting **every** span including root spans, so a pool-planted step is visible as N extra
      root spans rather than invisible. Mutation-tested by planting a step on `copy_one`.
- [ ] A test asserts no function in the instrumented modules is both a generator and decorated.
- [ ] `_CapturingSink` drains the worker on every read, so an absence assertion over it means
      "nothing was emitted" rather than "nothing has been flushed yet". **The mutation control this
      criterion originally named cannot exist** — removing a drain can only make an absence
      assertion *more* likely to pass, so no absence alone detects it. The control is the PRESENCE
      half in the same test: an event emitted inside a span is visible to a read with no explicit
      flush. That is what dies when the drain is removed, and it is what makes the absence half mean
      anything. Verified by planting.
- [ ] The rule and the timing consequence are recorded in `lambdas/info/shared-layer.md`.

### FR-003: The bounded call site in each plane the shared layer cannot reach

#### Description:

shared-space, results-conversion and table-builder route their durable work through the five looping
functions FR-002 forbids, so the shared layer gives them nothing. Their spans go at the bounded call
site in their own code — the loop, not its body.

- **shared-space** — the roster fan-out and the notification loop, one span each around the whole
  loop.
- **results-conversion-convert** — **three** spans, not one: `download-results`, `write-conversion`,
  `upload-conversion`. The body is download → write → upload with three comparable costs, so a
  single span covering ~90% of the root tells an operator nothing. An earlier draft said "its own
  principal operation", singular, which is not answerable for this verb.
- **table-builder** — `athena-run-ddl` in execute-ddl; `infer-columns` around `_infer_columns`;
  `glue-get-table` around `load-table-definition`'s `_get_table`. `apply-refresh` makes **three**
  Glue round trips with no principal one, so it gets three named spans — `glue-get-table`,
  `glue-update-table`, `glue-read-back-table` — rather than an arbitrary pick.
  `diff-schema` gets **none** — it performs no I/O, and Scope excludes it.

**Three corrections made during the build, each measured against the code.**

1. **`table-builder-execute-ddl/athena_run.py` does not exist.** It was deleted; `athena_run` is
   now a bound runner INSTANCE (`execute_ddl.py:27`) and `run_ddl` is a method on
   `cpcommon.athena`'s runner class, shared with data-quality and table-share — decorating it
   would silently instrument two other planes. The step goes on a bounded wrapper in
   `execute_ddl.py`, which is still the plane's own code and still outside FR-001's scanned
   modules, so the guard-ownership note below holds unchanged.
2. **`apply-refresh` makes THREE Glue round trips, not four**: `_get_table`, `_update` and
   `_post_condition`. The fourth candidate, `_abandon_if_changed`, calls
   `glue.update_time(live_table)` — a pure dict read on a response already in hand, not a call.
3. **Three of the span names this FR originally gave collide with their own verb's root span.**
   `execute-ddl`, `infer-schema` and `load-table-definition` are already those verbs'
   `@observability.traced` names, and `function` carries the same value for parent and child — so
   filtering on the span name returns the verb's total and the inner operation together, with the
   durations counted twice. That is exactly what FR-001's naming rule exists to prevent, so they
   are named for their operations instead. `glue-get-table` repeats across load-table-definition
   and apply-refresh deliberately: same call, same catalog, and one name is what makes a query
   group across the two verbs that make it.

Note that `athena-run-ddl`'s step lands on a helper in `table-builder-execute-ddl/execute_ddl.py`,
outside the modules FR-001's count test scans, so the guard for these is FR-004's, not FR-001's.

#### Acceptance Criteria:

- [ ] Each verb above emits its named child spans on a **successful** run, asserted by driving it —
      including `results-conversion-convert` on a successful *personal-space* conversion, which
      reaches no shared helper at all.
- [ ] `diff-schema` emits none, asserted, so a later author does not add one.
- [ ] Each span's call bound is stated and asserted the same way FR-002 requires.

### FR-004: Each of the seven planes is held to having child spans, and can be reddened alone

#### Description:

A guard is needed because a refactor that moves a plane off an instrumented path takes its child
spans with it, silently, leaving a plane that reads as instrumented and reports one flat span.

**"At least one of this plane's verbs emits a child span" cannot be mutation-tested** where a plane
has two independent sources, so the guard asserts per plane against a **named verb and a named
span** from FR-001's and FR-003's tables. Removing one step then reddens exactly one plane.

#### Acceptance Criteria:

- [ ] For each of the seven planes, a test drives one named verb and asserts a named child span with
      a non-null `parent_span_id` matching that verb's root span.
- [ ] Mutation-tested per plane: removing that plane's step reddens exactly that plane's case, and
      the message names the plane, the verb and the span.
- [ ] A positive control that the collector collected.
- [ ] `_CapturingSink` gains a child-spans-by-parent helper, used by every case.

### FR-005: The event volume this spec adds is measured against a stated budget

#### Description:

Each step is two events. **The budget's inputs are stated here because an earlier draft demanded a
"stated budget" and stated no number, which is an acceptance criterion with no assertable value.**
The inputs: the sweep rewrites one day object per service-day in full, so the bound that matters is
**events per service-day**, not per invocation; the ceiling is the day object's practical size
against the sweep's read-modify-write; and the headroom is the fraction reserved for the steps
SPEC-227 and later specs will add.

#### Acceptance Criteria:

- [ ] The per-invocation delta is measured for the worst-case verb on each of the seven planes by
      counting events through a capturing sink, not by counting decorators.
- [ ] It is asserted against a budget expressed in **events per service-day**, derived from the
      day-object ceiling and the fleet's invocation rate, with the derivation recorded beside the
      number and headroom stated with its reason. — **NOT MET; owed.** Both inputs are missing.
- [ ] If the day-object ceiling cannot be established from the sweep's own constants, that is
      recorded as owed rather than met with a number chosen to pass. — **This is what happened.**

**Outcome, decided during the build.** The ceiling is not establishable and neither is the rate, so
the third criterion is the one that fires:

- `log_sweep.LARGE_OBJECT_WARN_BYTES` (64 MiB) reads like the ceiling and is **a detector sized to
  fire early**. `infra/modules/observability/README.md` states the sweep's memory is 512 MB and that
  this constant "warns long before that becomes binding"; the sibling constant's guard in
  `test_feedback_writer.py` asserts `memory_bytes > LARGE_OBJECT_WARN_BYTES * 4` because peak
  resident while appending is several multiples of the object. The real ceiling is 512 MB ÷ that
  multiple, and the multiple is nowhere measured. Pressing the warn threshold into service as a
  ceiling would understate it several-fold and put a wrong derivation into `docs/` where nothing
  tests it.
- The invocation rate does not exist: greenfield, no production users, no reserved concurrency, no
  API throttle.

What ships instead is the measurement (criterion 1, in full: seven planes' worst-case verbs driven
and counted) plus a **ratchet** on those measured per-invocation counts, named a ratchet rather than
a budget so nobody reads it as the fence criterion 2 asked for. The budget and both of its missing
inputs are in `docs/testing/owed.md`.

A **rate-free budget was considered and rejected**: expressing this spec's cost as a share of each
plane's per-invocation event volume makes the rate cancel, but the denominator is a quantity this
spec and every later one inflates, so the same three steps would score 37.5% today and 23% after an
unrelated spec narrated more — a threshold that loosens as the thing it guards grows.

---

## Interface Contract

```python
from cpcommon import observability

@observability.step("copy-batch")
def copy_batch(items, failure_reason, *, echo_fields, concurrency=COPY_CONCURRENCY): ...
```

The signature is reproduced as it is: `echo_fields` is **keyword-only with no default**, a settled
decision this spec does not change.

A child span carries the handler's baggage (`verb`, `request_id`) **on the calling thread only**.
Baggage is a `ContextVar` and does not reach `copy_batch`'s workers — FR-002's third prohibition,
stated again where an implementer would otherwise assume the opposite.

## Implementation Phases

### Phase 1: The three shared steps and the prohibitions

- Steps on the transfer trio; call-bound docstrings; the literal-table and no-`log_foundry` guards.
- The two-N span-count test and the generator guard, each mutation-tested.
- `_CapturingSink`'s drain, mutation-tested against an absence assertion.

### Phase 2: The three planes the shared layer cannot reach

- shared-space's two loop spans; results-conversion's three; table-builder's six across four verbs.
- The driven success-path assertions, including the personal-space conversion.

### Phase 3: The guard and the budget

- The per-plane guard with its positive control, mutation-tested plane by plane.
- FR-005's measurement and budget, or the owed row if its ceiling cannot be derived.
- The rule and the timing consequence into `lambdas/info/shared-layer.md`.
