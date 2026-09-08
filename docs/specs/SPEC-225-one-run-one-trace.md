# Spec: One Run, One Trace — the Mechanism and the Success Path

**ID:** SPEC-225
**Status:** Draft
**Last Updated:** 2026-09-08
**Depends On:** SPEC-128 (Completed), SPEC-130 (Completed), SPEC-224

## Overview

A control-plane run is one user action carried out by many Lambda invocations — ten for a
data-quality run, twenty-five Task states on the archive machine. Each opens its own root span, and
`log-foundry`'s trace context is per-process, so each mints its own `trace_id` and every root span's
`parent_span_id` is null. A run is therefore as many traces as it has verbs, joined only by a
`request_id` field that SPEC-128 added for that reason. An operator asking "what happened to this
request" gets a field filter over unrelated traces, and the shape of the run — which verb followed
which, and where the time went — is not in the store at all.

**And the join key is missing on nine verbs.** `_extract_request_id` reads a top-level `requestId`
or an EventBridge Pipe's SQS body, and neither shape reaches a Map child: the six Distributed-Map
copy verbs receive `{"Items": [...]}`, and the three inline-Map children receive the parent state
nested under `request`. Verified during authoring. Those nine — including every copy verb, which is
where a transfer's time goes — emit spans that cannot be joined to their run at all. That is not a
new problem this spec introduces; it is a hole the same extractor change closes.

This spec makes a run one trace on the **success path**: the traceparent is minted once at the API,
threaded through the state payload as `requestId` is, and adopted by every verb before its span
opens. `request_id` stays — it is the join key for anything outside the trace, and removing a
working correlation key while installing a new one is how a store retained forever ends up with a
window that has neither.

This was **deliberately deferred**, not overlooked — recorded as "correlation now, stitching later"
(user decision, 2026-07-22), sequenced after the pipe was proven live. It is unblocked now for a
specific reason: on `log-foundry` 0.6.0 `continue_trace` is **sticky**, and a sticky adoption in a
warm Lambda container is worse than no adoption — measured, one call keeps every later root span in
the inbound trace, so the container's next, unrelated invocation silently joins the previous run's
trace and merges two users' work. SPEC-224's 1.0.0 makes it one-shot.

## Scope

### In Scope

- Trace adoption inside `cpcommon.observability`, over **all four** event shapes a verb can receive.
- Closing the `request_id` hole on the nine Map-child verbs, in the same extractor.
- Minting the run's traceparent at the API, where a run begins.
- Threading it along the **success** path: the six Distributed Maps, the six field-naming `Pass`
  states and the four field-naming Task `Parameters` blocks that feed a Lambda.
- A guard that a run is one trace, driven end to end rather than read off the source.

### Out of Scope

- **The failure path.** SPEC-227. It is separated deliberately rather than for size: the guard that
  would police it, `test_a_failure_seed_supplies_every_key_the_failure_terminal_reads`, identifies a
  seed structurally and **cannot see eight of the fleet's seed states**. A reviewer planted this
  spec's prescribed edit on archive and the whole suite stayed green while six archive failure paths
  would hit an absent `$.traceparent` — a `States.Runtime` error that is neither retriable nor
  catchable, killing the run *before* `NotifyFailure`, so a user whose archive failed would hear
  nothing at all. Threading the failure path requires widening that guard first, and that is a spec,
  not an FR.
- **The ASL↔verb cross-check that five planes do not have.** SPEC-227.
- **Removing `request_id`.** It stays, on both boundary events and narrative.
- **Migrating existing records.** `logs/` is appended NDJSON retained forever; rewriting a day
  object to backfill a `trace_id` would risk a day of logs to tidy a field boundary — the call
  SPEC-130 already made about the `function: "handler"` rename.
- **Stitching the singleton and queue-consumer Lambdas** — the log sweep, the DLQ drain,
  `notifications-writer`, `feedback-writer`, `user-directory-build`, the Cognito triggers. They are
  not part of a state-machine run. `notifications-writer` is excluded on **cost and sequencing, not
  mechanism**: FR-002 builds queue-body threading, so the mechanism would exist — but a notification
  is written after a run completes, its queue is fed by seven planes, and each producer would need
  the same change. It is a spec of its own if it is wanted.
- **Child spans.** SPEC-226.

---

## Functional Requirements

### FR-001: `observability` adopts an inbound trace over every event shape a verb receives

#### Description:

`cpcommon.observability` gains adoption and a reader, keeping its one-door rule.

**There are four event shapes, not two.** `_extract_request_id` handles two; the other two are why
nine verbs have no `request_id` today. All four are enumerated here because the spec's own failure
mode is a verb silently dropping out of the trace:

| Shape | Where the value sits | Which verbs receive it |
|---|---|---|
| State payload | top-level `traceparent` | every Task-invoked verb |
| Pipe envelope | `[{"body": "<json string>"}]` | the eight `validate-authorize` verbs |
| Distributed-Map batch | `BatchInput.traceparent` beside `Items` | the six copy/retrieve verbs (FR-003) |
| Inline-Map child | `request.traceparent` | file-send `check-target-absent`, table-share `check-target-absent` and `create-table` |

`_extract_request_id` is widened to the same four shapes in the same change — it is the same walk
over the same event, and leaving it on two while the traceparent reads four would mean a verb that
joins the trace and still cannot be filtered by request.

**The reader is `run_traceparent()`, and it is not "the current span's".** A verb that adopted an
inbound trace returns **the value it adopted**, unchanged, so the run threads one traceparent and
every verb parents to the API span that minted it. Only where nothing was adopted — the API, which
*is* the root — does it fall back to the current span's. The distinction is not cosmetic and was
measured: inside an adopted span, `lf.current_traceparent()` returns the same trace id with **a
different span id**, so a validator returning that would re-parent the rest of the run onto itself.
Both shapes give one `trace_id`, which is exactly why this must be decided here rather than left for
a guard to discover.

Order inside `traced`'s wrapper is load-bearing: the reset clears an adopted context as well as
baggage (SPEC-224 FR-002, asserted there behaviourally), so adoption must come **after** it and
**before** the span opens, since `continue_trace` applies to the next root span and to none already
open.

Adoption never fails a verb. Missing, malformed, or a `ContinueResult` reporting `ok=False` all mean
"mint a fresh trace and carry on", warned and never raised. Measured on 1.0.0: `''`,
`'not-a-traceparent'` and `'00-zzz-yyy-01'` all return `ok=False, reason='rejected'`; `None` returns
`reason='nothing-supplied'`.

#### Acceptance Criteria:

- [ ] A `@traced` handler invoked with a traceparent emits a root span whose `trace_id` is the
      inbound one and whose `parent_span_id` is the inbound span id — asserted **once per shape**,
      for all four shapes in the table, parametrised over that table so a fifth shape added later
      cannot be missed.
- [ ] `_extract_request_id` returns the request id for all four shapes; a test asserts it for the
      two that return `None` today, and that test fails against the current extractor.
- [ ] A handler invoked with no traceparent, and one invoked with each of the three malformed forms
      above, emit a freshly minted `trace_id`, do not raise, and log a warning.
- [ ] **A second invocation on the same warm container, with no traceparent, mints a fresh
      `trace_id` and does not join the first invocation's trace.** Asserted directly — this is the
      property 0.6.0 did not have.
- [ ] `run_traceparent()` returns the **adopted** value byte-for-byte when one was adopted, and the
      current span's only when none was. A test asserts the byte-for-byte case, which is what
      distinguishes the threaded design from the re-parenting one.
- [ ] No **non-test** module outside `cpcommon.observability` imports `log_foundry`. The two test
      harnesses do, by SPEC-224 FR-003's design.

### FR-002: The run's traceparent is minted where the run begins

#### Description:

A run begins at the API: the browser calls a route, the router opens a span, and `enqueue` sends the
request onto its plane's queue. `enqueue.build_message` adds the API span's traceparent to the
message body alongside the fields it already stamps, making the API's own span the root of the run's
trace.

The traceparent is a **stamped** value, not a caller-supplied one: a body field a caller could set
would let a client join or poison another run's trace, and the body is untrusted input. It is
written from `run_traceparent()` on the server, and `build_message` spreads `**dict(payload)` first,
so a stamped value already overwrites a caller's — the criterion below pins that rather than
assuming it.

#### Acceptance Criteria:

- [ ] Every message `enqueue` sends carries a `traceparent` whose trace id matches the API span's.
- [ ] A caller-supplied `traceparent` in the request body does not survive into the sent message,
      asserted by sending one.
- [ ] The added field is inside the message-size cap — asserted by a test that builds a
      maximum-size payload and shows the refusal fires, not by re-stating that the guard measures
      after stamping, which is already true and needs no work.

### FR-003: The six Distributed Maps carry the traceparent to their children

#### Description:

**Six**, not four: archive alone has three — `TransferObjects`, `RetrieveObjects` and
`CopyBackObjects` — beside one each on file-ops, file-send and table-share. Counted during authoring
by parsing all eight templates and reading `ItemProcessor.ProcessorConfig.Mode`. The two on
archive's restore arm are the largest data movement in the repo, and they are exactly the ones a
"four Maps" claim would leave outside the trace.

None of the six has an `ItemSelector`; all six read a JSONL manifest through `ItemReader`, so the
parent state is invisible to a child. All six already declare an `ItemBatcher`, and **no template in
the repo uses `BatchInput`** — that is the mechanism: a payload template evaluated against the Map
state's input and delivered once per **batch**. Writing the traceparent into the manifest instead
would repeat it on every line of a dataset that can hold tens of thousands, which is the wrong unit.

**This mechanism must be proved by execution, not by citation.** AWS documents `BatchInput`'s shape
and that its `.$` paths resolve against the Map state's input, but every documented example uses an
inline array through `ItemsPath`; no page shows `ItemReader` and `BatchInput` together, and all six
Maps here use `ItemReader`. Nothing contradicts it and the field-application order implies it, but
the whole Map half of this spec rests on it, so it is settled with a `TestState` call or a one-off
execution against a two-line JSONL fixture before the ASL edits are written.

The three **inline** Maps need no ASL change — they already carry `"request.$": "$"` — but their
children receive the parent state **nested under `request`**, which is the fourth shape FR-001
handles. "No ASL change" is not "no change".

#### Acceptance Criteria:

- [ ] A `TestState` call or a recorded one-off execution shows `BatchInput` reaching a child of an
      `ItemReader`-fed Distributed Map, with `Items` unchanged beside it. Recorded on the PR; the
      ASL edits are not written before it passes.
- [ ] All **six** Distributed Maps carry `ItemBatcher.BatchInput` delivering the traceparent — the
      count derived by parsing the templates in the test, never written as a literal, so a Map added
      later is included automatically.
- [ ] A copy verb driven with a `{"BatchInput": {...}, "Items": [...]}` event joins the inbound
      trace and carries the request id, asserted by driving the verb.
- [ ] `test_the_whole_map_state_stays_under_the_payload_limit`'s hand-built state model includes the
      new key, so it keeps bounding the state that actually exists.
- [ ] `tofu -chdir=infra validate` passes, and the rendered plan differs only in the state machine
      definitions.

### FR-004: Every success-path state that names fields individually names the traceparent

#### Description:

Most threading is free: a Task using `"Payload.$": "$"` with `"OutputPath": "$.Payload"` carries a
new key with no edit. Two classes of state break that, and the second is easy to miss because it is
a Task rather than a `Pass`.

**Six field-naming `Pass` states on a path that feeds a Lambda** — archive `Validated`; file-send
`Validated` and `ShapeSummary`; results-conversion `Validated`, `Described` and `Converted`.
`ShapeSummary` is the one a survey misses: its five keys become the entire input to file-send's
`NotifyOutcomes`. The `Pass` states that are genuinely terminal — archive's `ArchiveComplete` and
`RestoreComplete`, table-share's `ShapeSummary` — go to `Succeeded` and are correctly excluded.

**Four Task states that name their `Payload` fields individually** — archive's `NotifyArchived`,
`NotifyRestoreStarted` and `NotifyRestored`, and table-share's `FinishRecipients/CreateTable`. A
field-naming Task `Parameters` block drops a key exactly as a `Pass` does; the notify verbs are
`@traced` and would otherwise sit outside the run's trace.

Five planes — data-quality, file-ops, shared-spaces, table-builder, table-share — have no
field-naming state on the success threading path and need only their validator changed. Note that
eight shared-spaces verb Tasks carry neither `OutputPath` nor `ResultPath`, so the raw invoke
envelope replaces the state; harmless today because each goes straight to `Succeeded`, and named
here so the survey sentence is true rather than nearly true.

#### Acceptance Criteria:

- [ ] Every plane's `validate-authorize` returns `traceparent`, including shared-spaces', whose
      return is the one validator in the fleet with a conditionally-shaped key set.
- [ ] The six field-naming `Pass` states and the four field-naming Task `Parameters` blocks name it.
- [ ] A sweep over **all eight** templates asserts that every state naming fields individually on a
      path that reaches a Lambda names `traceparent`. It derives that population by parsing, carries
      a positive control that it found states at all, and is mutation-tested by removing the key
      from one state — the failure must name the plane and the state.
- [ ] The sweep classifies terminal states as terminal by walking to `Succeeded`, not by a hard-coded
      exclusion list, so a state that stops being terminal is caught.

### FR-005: A run is one trace, proved end to end

#### Description:

The claim this spec exists to make is a property of a whole run, and every per-verb test can pass
while the run is still many traces — a verb that adopts correctly still mints its own if the state
payload never delivered one. The guard drives a run's verbs in sequence, feeding each the previous
one's output the way the state machine does, and asserts one `trace_id` across every span.

**The plane it drives is named, not chosen at build time.** A guard run against data-quality,
shared-spaces or table-builder would exercise no Map hop, no field-naming state and no inline-Map
nesting — every mechanism this spec adds — and pass. It runs against **file-send**, which has a
Distributed Map, an inline Map, two field-naming `Pass` states and a notify verb, and against
**archive**, which has three Distributed Maps and three field-naming Task states.

#### Acceptance Criteria:

- [ ] For file-send and archive end to end, and for the API-to-first-verb hop, every span emitted
      across the run carries one `trace_id`.
- [ ] The guard asserts a non-zero span count and more than one contributing verb before asserting
      the shared trace id, so an empty collector cannot satisfy it.
- [ ] The guard is mutation-tested three ways — dropping `traceparent` from the state payload,
      dropping it from a Map's `BatchInput`, and dropping the adoption from `traced` — and the
      failure message distinguishes the three.
- [ ] `request_id` is present on **every** span emitted by both runs, including the Map children
      and the inline-Map children, which is false of the fleet today.

---

## Data Model

```ts
// The control-plane state payload, after validate-authorize
type StatePayload = {
  requestId: string;
  traceparent: string;   // W3C: "00-<32 hex trace id>-<16 hex span id>-<2 hex flags>"
  // …the plane's own fields, unchanged
};

// A Distributed-Map child's event, after ItemBatcher.BatchInput
type MapChildEvent = {
  BatchInput: { traceparent: string; requestId: string };
  Items: TransferItem[];      // unchanged
};
```

## Interface Contract

```python
# cpcommon/observability.py — the additions

def run_traceparent() -> str | None:
    """The traceparent identifying THIS RUN.

    The value adopted from the inbound event when there was one — returned unchanged, so the
    run threads one traceparent and every verb parents to the span that minted it. The current
    span's only where nothing was adopted, which is the API, which is the root.
    """

# inside `traced`'s wrapper, in this order:
_reset_context()          # clears baggage AND any adopted context (SPEC-224 FR-002)
_stamp_verb(verb)
_stamp_request_id(event)  # widened to four shapes
_adopt_trace(event)       # continue_trace(...) — applies to the next root span
try:
    return span(*args, **kwargs)
finally:
    flush()
```

## Implementation Phases

### Phase 1: Prove the Map mechanism, then build the extractor

- Settle `ItemBatcher.BatchInput` against an `ItemReader` dataset by `TestState` or a one-off
  execution. Nothing else in this spec starts until it holds.
- `_extract_traceparent` and the widened `_extract_request_id` over all four shapes; `_adopt_trace`;
  `run_traceparent()`; the wrapper ordering.
- FR-001's per-shape tests, each mutation-tested.

### Phase 2: The producer, the Maps and the field-naming states

- `enqueue.build_message` stamps the traceparent; the caller-cannot-set test.
- Every validator returns it; the six `ItemBatcher.BatchInput` blocks; the six `Pass` states and the
  four Task `Parameters` blocks.
- The parsing sweep with its positive control and per-state mutation test.

### Phase 3: The proof and the record

- FR-005's file-send and archive one-trace guards, mutation-tested three ways.
- Replace the "one run is nine traces" claim at its live sites — `lambdas/info/shared-layer.md:184`,
  `docs/decisions/control-planes.md:235` (the **entry**, not the Fences, which say nothing about
  trace counts) and `docs/specs/ARCS.md`. Completed specs and delivery docs stay as history.
- Full local gates green by exit code, including `tofu validate` and `validate_docs.py`.
