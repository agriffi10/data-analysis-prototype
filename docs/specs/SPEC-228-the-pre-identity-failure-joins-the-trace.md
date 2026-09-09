# Spec: The Pre-Identity Failure Joins the Trace, from the Envelope the State Already Carries

**ID:** SPEC-228
**Status:** Draft
**Last Updated:** 2026-09-09
**Depends On:** SPEC-227 (Completed)

## Overview

A run is one trace on the success path (SPEC-225) and on the failure path (SPEC-227), with one
recorded exception: a **pre-identity** failure — one where `validate-authorize` raised before it
returned — carries `traceparent: null` on its seed, so `notify-failure` opens a trace of its own.
That is the failure an operator is most likely to be looking at, because it is the one where the
request never started and the user was told only that it could not be.

SPEC-227 recorded this as a limit rather than an oversight, and its reasoning about **ASL** is
correct and stands: `$$.Execution.Input` is the raw SQS batch, the traceparent sits inside
`[0].body` as a JSON string, and prising it out needs `States.StringToJson` — banned fleet-wide for
the uncatchable `States.Runtime` that whole arc exists to avoid.

**What the limit rests on that is not true is the second half.** SPEC-227's own text names it:
"`cpcommon.observability._shape_values` walks the event's top level, `BatchInput` and `request` —
it never walks `raw`, so even a parsed envelope would not be adopted." Read the other way round,
that is the repair. The envelope does not need to be parsed in ASL at all. It is already on the
state as `raw` on four planes, it can be put on the other four with one key read from the context
object, and the verb that needs it — `notify-failure`, a Python function under `@traced` — can read
the traceparent out of it exactly the way `validate-authorize` already reads it out of the same
envelope on the way in.

The value that comes back is provably the right one. `raw` is `$$.Execution.Input`, which is *this
execution's* input and can be no other run's; its `body` is the message `enqueue.build_message`
assembled, whose `traceparent` the API stamps unconditionally over anything a caller sent. So the
adopted trace is the run's own, by construction rather than by convention.

The result is that every guard SPEC-227 built stays **green and unchanged**: seeds still supply a
literal `null`, `RecordFailure` still reads `$.traceparent`, and the pre-identity/post-identity
split is still derived the same way. Adoption moves to the place that can already do it.

## Scope

### In Scope

- A fifth shape in `cpcommon.observability._shape_values`: the forwarded SQS envelope carried on
  the state as `raw`.
- `raw` on all eight planes' `RecordFailure`, read from the **context object** so no seed has to
  supply it and the failure-seed guard is not disturbed.
- Retiring the `raw` keys on failure seeds that this change makes dead, derived rather than listed.
- Deriving the state-size bound this puts on a failure path, and giving the API's message cap the
  budget it currently lacks.
- Driving a pre-identity failure end to end on one plane from each half, and asserting
  `notify-failure`'s span carries the run's `trace_id`.
- Correcting the limit where it is recorded — the register Fences and entry, `ARCS.md`, SPEC-227's
  spec and delivery doc, and the `docs/testing/owed.md` row whose live check currently instructs a
  human to confirm the opposite of what will be true.

### Out of Scope

- **An `input_template` on the eight Pipes.** It would work — implicit body data parsing means
  `<$.body.traceparent>` resolves for an SQS source, and it runs in the Pipe where the
  `States.StringToJson` ban does not reach. It is excluded on blast radius, not on capability: the
  Execution Input is the entry contract for all eight planes, read by `ValidateAuthorize`'s
  `Payload.$: "$"` into `cpcommon.events.parse_sqs_request` (which requires `[0].body` to be a JSON
  **string**) and by four planes' seeds as the only surviving copy of the caller's identity. Any
  template that hoists a field also moves the record, and `parse_sqs_request`, eight validators and
  every envelope fixture move with it — to reach one verb per plane that a state field already
  reaches.
- **Carrying the traceparent as an SQS message attribute.** Also available: the Pipes SQS record
  exposes `messageAttributes` as structured JSON, so a state could read it with a plain JSONPath and
  no intrinsic. Excluded because an absent attribute is unreachable-key death: a `Pass` reading a
  path that is not there raises the uncatchable `States.Runtime`, and the attribute is absent for
  every message already in flight or sitting on a DLQ when the change lands, and for any future path
  where `run_traceparent()` returns `None`. `$$.Execution.Input` cannot be absent. Choosing a
  mechanism that fails that way, in a spec whose subject is a failure path going silent, would be
  the trap this arc keeps paying for.
- **Giving the four planes that gain `raw` an identity recovery from it.** `archive`, `file-ops`,
  `file-send` and `results-conversion` recover the actor out of `raw` when the state has none, and
  after this change `data-quality`, `shared-spaces`, `table-builder` and `table-share` will carry the
  same envelope. Whether their notifiers should use it is a per-plane notification question with its
  own recipients and its own wording, and it is not what this spec is for.
- **Giving `table-share` a `requestId`.** Still unjoinable outside a trace, still recorded, still
  SPEC-225's exclusion rather than this one's.
- **The success path.** Untouched. `raw` reaches no success-path verb, and this spec adds it to none.

---

## Functional Requirements

### FR-001: The extractor walks the forwarded envelope carried on the state

#### Description:

`_shape_values` gains a fifth shape. When the event is a dict whose `raw` is a list, the existing
envelope branch is applied to it — `[0].body`, JSON-parsed, one key read — so a verb holding the
forwarded batch as a state field reads it the same way a verb holding it as its whole event does.

The branch is walked **last**, after the top level, `BatchInput` and `request`. A post-identity
failure carries both a real top-level `traceparent` and `raw`; both name the same run, so the order
is not a correctness question, but the threaded value stays authoritative and the parse is not paid
for when a top-level value is present.

Both extractors gain it, because both read through this helper. For `_extract_request_id` that is
the intended consequence and not a side effect: a pre-identity seed supplies `requestId: null`, so
today a pre-identity failure correlates on **nothing at all** — neither a trace nor the join key
that exists for everything outside one.

The value the request-id branch will read is the caller's own `requestId`, spread into the message
from the payload by `build_message`. That is not a new exposure and not the hole SPEC-225 closed:
a plane's `requestId` **is** the caller's by design — the API echoes it back and the planes carry it
— and the existing envelope branch already reads exactly this field from exactly this place for
every `validate-authorize` in the fleet. What SPEC-225 narrowed was a **bare dict**'s `body`, which
for an API Gateway payload-2.0 request is the caller's live HTTP body. `raw` is written only by ASL
from `$$.Execution.Input` and never by a caller, so the list-only narrowing is not reopened.

#### Acceptance Criteria:

- [ ] A dict event whose `raw` is a single-element list of SQS records yields that record's
      `body.traceparent` from `_extract_traceparent`, and its `body.requestId` from
      `_extract_request_id`.
- [ ] A top-level `traceparent` **wins** over the one inside `raw` when both are present and differ,
      asserted with two different values so the assertion cannot pass on the shapes agreeing.
- [ ] A dict whose `raw` is absent, is not a list, is an empty list, holds a record with no `body`,
      or holds a body that is not valid JSON, yields nothing and **raises nothing** — one case each,
      because a logging helper that can raise is a verb that can fail for a logging reason.
- [ ] The security narrowing is unchanged and asserted: a **bare dict** carrying a top-level `body`
      string still yields nothing from that `body`, so an API Gateway payload-2.0 event cannot name
      either key.
- [ ] The new branch is **mutation-tested**: deleting it reddens a named test, and the test's failure
      message is asserted so a neighbouring branch cannot satisfy it. Naming which plant reddens the
      new branch and not the pre-existing envelope branch is part of the criterion.

### FR-002: Every plane's `RecordFailure` carries the envelope, from the context object

#### Description:

All eight `RecordFailure` states carry `raw`, read as `$$.Execution.Input`. Four already carry
`raw` as `$.raw` from their seed; those move to the context read, and the four that carry none gain
it.

The context object rather than the state is the whole trick, and it is what keeps this change from
touching 29 states. `_read_keys` in the failure-seed guard matches `$.<key>` and a `$$.` value does
not match, so a `RecordFailure` reading `$$.Execution.Input` is not a read any seed must supply.
`$$.Execution.Input` is also available in every state of every one of these machines — all eight
`RecordFailure` states are top-level, none sits inside a Map — and it is never absent, which is the
property the alternatives lack.

Once no state reads `$.raw`, the `raw` keys on the failure seeds are dead, and they are removed:
a field nothing reads surviving into production is exactly what the archive machine's own comment
warns about.

This puts a bound on the failure state that nothing currently computes. `raw` is the forwarded
batch, and `RecordFailure` is `raw` plus the error object plus its literals; if that exceeds the
Step Functions maximum input/output size, the execution dies with `States.DataLimitExceeded` — a new
way for a failure path to go silent, introduced by a change whose purpose is to make failures
legible. The bound is therefore computed rather than assumed, and where it does not clear, **the
API's `MAX_MESSAGE_BYTES` is lowered until it does**: that cap is the only place the input can be
bounded before an execution exists, it is already a computed constant, and it currently has no
budget behind it beyond the SQS limit.

#### Acceptance Criteria:

- [ ] All eight `RecordFailure` states carry `raw` as `$$.Execution.Input` — the population derived
      from the templates, not listed, and asserted to be exactly eight.
- [ ] **No state on any plane reads `$.raw`**, derived by parsing rather than by grep, and no failure
      seed supplies a `raw` key.
- [ ] `test_a_failure_seed_supplies_every_key_the_failure_terminal_reads`,
      `test_the_pre_identity_seeds_are_the_ones_the_error_replaced` and
      `test_every_failure_path_state_names_the_traceparent` are **green with no edit** — the
      traceparent threading and the 8/21/29 split are untouched by this spec, and a change to any of
      them is a signal the design drifted rather than a task.
- [ ] The state-size bound is **computed by a test** against the Step Functions maximum input/output
      size quota, read from the live service documentation at build time rather than from a number
      copied into this spec: worst-case `RecordFailure` = a maximum-size forwarded envelope plus the
      largest error object the fleet produces plus the plane's literals.
- [ ] If that bound does not clear the quota with headroom, `MAX_MESSAGE_BYTES` is lowered in the
      same PR until it does, and the constant's docstring names the failure state as its budget.
      The headroom chosen is stated in one line where the constant lives, with its reason.
- [ ] The four notify-failure verbs that recover an actor from `raw` behave identically — driven,
      not reasoned about, because their input now arrives from a different ASL path.

### FR-003: A pre-identity failure is driven end to end, and its notification is in the run's trace

#### Description:

`test_one_run_one_trace.py` drives failure runs on two planes today and both are post-identity. The
guard this spec owes drives a **pre-identity** failure — `validate-authorize` raising before it
returns — through the ASL's own `Parameters` blocks into `notify-failure`, and asserts the
notification's span carries the same `trace_id` as `validate-authorize`'s.

It runs on one plane from **each** half of the fleet: one that carried `raw` before this spec and
one that did not, because the two halves reach `RecordFailure` by different ASL edits and a drive
over one says nothing about the other.

#### Acceptance Criteria:

- [ ] A pre-identity failure driven on one plane that already carried `raw` and one that did not:
      `validate-authorize`'s span and `notify-failure`'s span share one `trace_id`, and
      `notify-failure`'s `parent_span_id` is non-null.
- [ ] The drive fails for the **right reason** when the FR-001 branch is removed — asserted on the
      failure message, not on an exit code, because a post-identity drive in the same file fails
      with the same shape.
- [ ] The drive raises inside `validate-authorize` rather than hand-shaping the state, so the
      `"error.$": "$"` replacement that defines a pre-identity seed actually happens.
- [ ] A **positive control**: the assertion is shown to be reachable by running it against the
      pre-change ASL and extractor and watching it fail, so a drive that silently collects nothing
      cannot pass by asserting over an empty set.

### FR-004: Every site that records the limit says what is now true

#### Description:

The limit is written down in six places, and one of them instructs a human to go and confirm it in
production. All of them are corrected — not annotated, and not left standing beside a superseding
sentence.

The sites: the `## Fences` clause in `docs/decisions/control-planes.md` ("Such a failure cannot join
the run's trace and is not meant to"); the SPEC-227 register entry in the same file; the arc
paragraph in `docs/specs/ARCS.md`; SPEC-227's own **Known limit** paragraph; SPEC-227's delivery
doc; and the `docs/testing/owed.md` row whose half (b) tells a human to confirm `notify-failure`
carries a **different** `trace_id` and says that one shared trace would mean the register is wrong.

The Fences clause is **replaced, not appended to**. Its first sentence — a pre-identity seed supplies
literals for everything its terminal reads, including `traceparent` — stays true and load-bearing;
the clause that follows it ("is not meant to … reachable nowhere ASL can read") is what this spec
falsifies, and leaving it under a new sentence is how a superseded claim goes on being read as
current.

#### Acceptance Criteria:

- [ ] All six sites state the current behaviour, and the two that carry the "reachable nowhere ASL
      can read" reasoning say instead that it is reachable nowhere **ASL** can read and is read in
      Python from the envelope on the state — the ASL half of SPEC-227's reasoning is preserved
      because it is still true and still the reason the machine is shaped as it is.
- [ ] The `owed.md` row's half (b) is rewritten to check the **new** invariant, and its "if (b) shows
      one shared trace, the register entry is wrong" sentence is removed rather than left inverted.
- [ ] A grep for the limit's distinctive phrasings over `docs/`, `infra/` and `lambdas/` returns only
      corrected text — the sweep is closed with a search, not with memory of which files were edited.
- [ ] No comment in `.tf`, `.tftpl`, `.py` or `.ts` added or edited by this spec names a spec, PR or
      issue number.

---

## Data Model

The shapes involved, as they exist on the wire. Nothing new is introduced; the fifth shape is an
existing one reached from a new place.

```ts
// The forwarded SQS batch — the Pipe's payload, and the value of `raw` on a failure state.
type ForwardedBatch = Array<{
  messageId: string;
  body: string;              // JSON: the message `enqueue.build_message` assembled
  attributes: Record<string, string>;
  messageAttributes: Record<string, unknown>;
}>;

// The state `notify-failure` receives, built by RecordFailure. Plane-specific fields omitted.
type FailureTerminalState = {
  traceparent: string | null;  // null on a pre-identity failure — unchanged by this spec
  requestId: string | null;    // null on a pre-identity failure — unchanged by this spec
  raw: ForwardedBatch;         // NEW on four planes; sourced from $$.Execution.Input on all eight
  status: "failed";
  error: { Error?: string; Cause?: string };
};
```

## API / Interface Contract

`_shape_values` keeps its signature and its contract — it never raises, and it yields unvalidated
values in shape order for a caller to judge.

```python
def _shape_values(event: object, key: str) -> Iterator[object]:
    """...

    FIVE shapes. The fifth is the forwarded batch carried on the state as ``raw``, which is how a
    failure terminal's verb reaches the run's traceparent when the seed had none to thread: the
    error replaced the state before an identity existed, but ``$$.Execution.Input`` did not go
    anywhere.
    """
```

The ASL edit, identical on all eight planes:

```json
"RecordFailure": {
  "Type": "Pass",
  "Parameters": {
    "traceparent.$": "$.traceparent",
    "raw.$": "$$.Execution.Input"
  }
}
```

## Environment Variables

None.

## File & Folder Structure

```
lambdas/control-plane-common/cpcommon/observability.py      # FR-001
lambdas/control-plane-common/test_observability_cpcommon.py # FR-001 guards
lambdas/control-plane-common/test_one_run_one_trace.py      # FR-003 drive
lambdas/control-plane-common/test_state_machines_cpcommon.py# FR-002 derived population
lambdas/api/apicommon/enqueue.py                            # FR-002, only if the bound requires it
infra/modules/{archive,data-quality,file-ops,file-send,
  results-conversion,shared-spaces,table-builder,
  table-share}/state-machine.asl.json.tftpl                 # FR-002
docs/decisions/control-planes.md                            # FR-004
docs/specs/ARCS.md                                          # FR-004
docs/specs/SPEC-227-the-failure-path-joins-the-trace.md      # FR-004
docs/spec-delivery/SPEC-227-the-failure-path-joins-the-trace.md # FR-004
docs/testing/owed.md                                        # FR-004
```

## Implementation Phases

### Phase 1: The extractor

- Add the `raw` shape to `_shape_values`, walked last, reusing the envelope branch rather than
  copying it.
- Write FR-001's guards, including the precedence case with two distinct values and the five
  malformed-input cases.
- Mutation-test the new branch, and name the plant that reddens it without reddening the
  pre-existing envelope branch.

### Phase 2: The machines and the bound

- Move the four `$.raw` reads on `RecordFailure` to `$$.Execution.Input`; add the key to the other
  four.
- Remove the now-dead `raw` keys from the failure seeds, derived from a parse that shows no state
  reads `$.raw`.
- Compute the failure-state bound against the live Step Functions quota; lower `MAX_MESSAGE_BYTES`
  and give it its budget if the bound does not clear with headroom.
- Confirm SPEC-227's three threading guards are green with no edit.

### Phase 3: The drive and the record

- Extend `test_one_run_one_trace.py` with a pre-identity failure drive on one plane from each half,
  with the positive control.
- Correct all six sites, replacing the superseded Fences clause rather than appending to it, and
  rewrite the `owed.md` row's half (b).
- Close the sweep with a grep for the limit's phrasings across `docs/`, `infra/` and `lambdas/`.
