# Spec: Child Spans in the Shared Control-Plane Helpers

**ID:** SPEC-226
**Status:** Draft
**Last Updated:** 2026-09-08
**Depends On:** SPEC-130 (Completed), SPEC-224

## Overview

`cpcommon.observability.step(name)` opens a child span around one named internal step, turning
"the verb took 8 seconds and failed" into "the listing took 40 ms, the column probe took 7.9 s and
raised". It has been available since SPEC-130 and is used by data-quality, the log sweep, the API,
the DLQ drain and user-directory-build. **Seven planes have none of it** — archive, file-ops,
file-send, results-conversion, shared-space, table-builder and table-share each emit a flat
sequence of `info` events inside one span, so an operator can see that a verb was slow and not
which part of it was.

The cheap way to close that is not seventy-four hand-placed decorators. Every one of those seven
planes reaches its durable work through the same shared modules — `cpcommon.transfer` for the copy
and its manifest, `cpcommon.lock` for the refresh locks, `cpcommon.cas` for the compare-and-swap
writes, `cpcommon.registry` and `cpcommon.s3_listing` for the reads, `cpcommon.notify` for the
sends. Instrumenting those once gives all seven planes per-operation duration, in one blast radius,
against one set of tests.

## Scope

### In Scope

- Child spans on the shared `cpcommon` operations every control plane routes its durable work
  through, so all seven flat planes gain per-operation timing without a per-verb sweep.
- A stated, enforced rule for **where a step may go**, since the cost of a step is an SQS message
  and a line in a day object the sweep rewrites in full.
- A guard that holds the seven planes to having child spans at all, so this cannot silently regress
  to flat the way `notifications-writer` shipped without `@traced`.

### Out of Scope

- **Per-verb steps inside a plane's own module.** A verb whose interesting work is its own, not a
  shared helper's, keeps its flat narrative here. That residue is a follow-up spec, and it is
  deliberately sequenced second: the shared layer is where the duration actually is, and doing it
  first tells the follow-up which verbs still need anything.
- **Any step inside a per-item loop.** Named here because it is the obvious next move and it is
  wrong — see FR-002.
- **New `info`/`warning`/`error` events.** This spec adds spans, not narrative. A step that also
  needs an event is a call-site decision the follow-up makes.
- **data-quality, the log sweep, the API, the DLQ drain, user-directory-build.** They already have
  steps. They will inherit whatever the shared helpers gain, which is fine and is not a change to
  their own instrumentation.

---

## Functional Requirements

### FR-001: The shared durable operations carry child spans

#### Description:

Each shared `cpcommon` operation that performs durable or remote work gains a `@observability.step`
at **operation granularity** — one span per call the verb makes, not per object the call touches.
The modules in scope, and which of the seven planes each reaches:

| Module | Reaches |
|---|---|
| `cpcommon.transfer` (copy, manifest, results) | archive, file-ops, file-send, table-share |
| `cpcommon.lock` | file-ops, table-builder |
| `cpcommon.cas` | shared-space |
| `cpcommon.registry` | archive, file-ops, file-send, results-conversion, table-builder, table-share |
| `cpcommon.s3_listing` | archive, file-ops, file-send, table-builder, table-share |
| `cpcommon.notify` | archive, file-ops, file-send, results-conversion, shared-space, table-builder, table-share |

Derived by import search during authoring, not from memory. Every one of the seven flat planes is
reached by at least two of these modules, so none of them ends this spec still flat. The depth is
**not** even, and the uneven one is named rather than discovered: **results-conversion** reaches
only `registry` and `notify`, because the work that actually takes time in it — the Excel writer in
`results-conversion-convert` — is its own code, not a shared helper. It gains real spans here and
is still the first candidate for the follow-up.

The span name is the operation, not the module — `copy-batch`, `acquire-lock`, `list-prefix` — so a
query groups across every plane that calls it.

`step` is a thin alias for `lf.trace` and is **non-swallowing** by design: it records the failure
and re-raises the original exception unchanged. That property is load-bearing here, because
`@traced` sits outermost above `@notifies_on_failure`, and a step that swallowed would cost the
user their failure notification. Nothing in this spec may put a `try` between a raise and its
notification.

#### Acceptance Criteria:

- [ ] Every shared operation named above carries exactly one `@observability.step`, named for the
      operation.
- [ ] A test drives one call through each instrumented module against a capturing sink and asserts a
      child span exists with that name, with a non-null `parent_span_id` naming the handler's span.
- [ ] A test asserts an exception raised inside an instrumented helper propagates **unchanged** —
      same type, same message, same `__cause__` — so the plane's terminal and notification paths are
      untouched.
- [ ] The existing suites for every plane in the table are green by exit code.

### FR-002: A step may not sit inside a per-item loop

#### Description:

Every event is an SQS message and a line in an appended day object the sweep rewrites **in full**.
A step inside a per-object loop therefore does not cost one event, it costs one event per object,
and an archive can hold tens of thousands. The plane code already states this rule at the call
sites that obey it — archive's `copy-objects` records "per BATCH, never per object" — but the rule
lives only in prose and only where somebody remembered to write it.

This FR makes it checkable: a `@observability.step` may decorate a function that is called a
bounded number of times per invocation, and may not decorate one called once per item.

#### Acceptance Criteria:

- [ ] Every `@observability.step` added by this spec decorates a function called a bounded number of
      times per handler invocation, and the bound is stated in that function's docstring.
- [ ] A test drives a transfer of N objects through the instrumented copy path and asserts the
      number of child spans emitted is **independent of N** — run with two different N and compare.
      An assertion on a fixed count would pass a per-object step whose count happened to match.
- [ ] The rule is recorded in `lambdas/info/shared-layer.md` beside the `observability` entry, in
      the section that already carries the field rule's working detail.

### FR-003: The seven planes cannot silently go flat again

#### Description:

`test_instrumentation_coverage.py` already holds every Lambda in the repo to calling
`observability.init` and carrying `@observability.traced`, because a function outside every plane
descriptor is exactly how `notifications-writer` shipped with `init` and no `@traced` and nothing
failed. Child spans need the same treatment for the same reason: a refactor that moves a plane off
a shared helper takes its child spans with it, silently, and the result is a plane that reads as
instrumented and reports one flat span.

The guard asserts at the **plane** level, not the verb level — a verb with no durable work of its
own legitimately has no child span — by exercising each plane's instrumented path and asserting a
child span arrives.

#### Acceptance Criteria:

- [ ] A test asserts, for each of the seven planes, that at least one of its verbs emits a child
      span through the shared helpers, driven end to end against a capturing sink rather than by
      reading source.
- [ ] The guard is mutation-tested: removing one plane's step reddens it, and the failure message
      names the plane.
- [ ] The guard carries a positive control that the collector collected — an empty event list must
      not satisfy it.

---

## Interface Contract

No new public surface. `cpcommon.observability.step` is used exactly as it is today:

```python
from cpcommon import observability

@observability.step("copy-batch")
def copy_batch(items, reason, echo_fields=()): ...
```

The emitted child span is a normal log-foundry span: its `function` is the step name, its
`parent_span_id` is the handler's root span, and it carries the handler's baggage (`verb`,
`request_id`) because baggage reaches nested spans — which is the whole reason `verb` was moved from
a span default to baggage in SPEC-130.

## Implementation Phases

### Phase 1: The transfer and lock paths

- Steps on `cpcommon.transfer` (copy, manifest, results) and `cpcommon.lock`.
- The FR-001 propagation test and the FR-002 count-independent-of-N test.

### Phase 2: The read, write and notify paths

- Steps on `cpcommon.cas`, `cpcommon.registry`, `cpcommon.s3_listing`, `cpcommon.notify`.
- Docstring bounds for every decorated function.

### Phase 3: The guard and the record

- The seven-plane child-span guard, with its positive control; mutation-test it per plane.
- The per-item rule into `lambdas/info/shared-layer.md`.
- Full local gates green by exit code.
