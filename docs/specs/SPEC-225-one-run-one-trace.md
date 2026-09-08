# Spec: One Run, One Trace — the Mechanism and the Success Path

**ID:** SPEC-225
**Status:** In Progress
**Last Updated:** 2026-09-08
**Depends On:** SPEC-128 (Completed), SPEC-130 (Completed), SPEC-224

## Overview

A control-plane run is one user action carried out by many Lambda invocations — ten for a
data-quality run, twenty-five Task states on the archive machine. Each opens its own root span, and
`log-foundry`'s trace context is per-process, so each mints its own `trace_id` and every root span's
`parent_span_id` is null. A run is therefore as many traces as it has verbs, joined only by a
`request_id` field that SPEC-128 added for that reason.

**And the join key is missing on nine verbs**, for two different reasons that need different fixes.
The three inline-Map children receive the parent state nested under `request`, which the extractor
does not read — a shape fix reaches them. The six Distributed-Map copy verbs receive
`{"Items": [...]}`, which contains **no request id at all**, so no extractor change can reach them;
only putting the value into the Map's `BatchInput` does. Three of the nine sit on table-share, whose
validator returns no `requestId` anywhere, so they stay unjoinable by request after this spec and
that is recorded rather than quietly missed.

This spec makes a run one trace on the **success path**: the traceparent is minted once at the API,
threaded through the state payload as `requestId` is, and adopted by every verb before its span
opens. `request_id` stays — it is the join key for anything outside the trace.

This was **deliberately deferred**, not overlooked — "correlation now, stitching later" (user
decision, 2026-07-22), sequenced after the pipe was proven live. It is unblocked now because on
`log-foundry` 0.6.0 `continue_trace` is **sticky**: one call keeps every later root span in the
inbound trace, so a warm container's next, unrelated invocation silently joins the previous run's
trace. SPEC-224's 1.0.0 makes it one-shot. **The load-bearing part of that dependency is SPEC-224
FR-002** — the reset must call `reset_context()`, which clears an adopted context; the current
private `_baggage.set({})` does not, so on the old reset adoption survives into the next invocation
and 0.6.0's stickiness is back by another route. Built against the old reset, this spec's ordering
is not merely unproven, it is wrong.

## Scope

### In Scope

- Trace adoption inside `cpcommon.observability`, over the event shapes a verb actually receives.
- **Closing the correlation hole at the API**: the extractor must never read a caller's HTTP body.
- Closing the `request_id` hole on the inline-Map children, and on the Distributed-Map children
  where the plane has an id to give.
- Minting the run's traceparent at the API, where a run begins.
- Threading it along the **success** path: the six Distributed Maps and the ten states that name
  their fields individually.
- A guard that a run is one trace, driven end to end rather than read off the source.

### Out of Scope

- **The failure path.** SPEC-227, and separated for a measured reason: the guard that would police
  it identifies a seed structurally and **cannot see eight of the fleet's seed states**. A reviewer
  planted this spec's prescribed edit on archive and the whole suite stayed green while six archive
  failure paths would hit an absent `$.traceparent` — a `States.Runtime` that is neither retriable
  nor catchable, killing the run *before* `NotifyFailure`, so a user whose archive failed would hear
  nothing. A literal reading of FR-004's sweep pulls those 28 failure-path states into scope; FR-004
  excludes them explicitly for that reason.
- **Giving table-share a `requestId`.** Its validator returns none and no downstream state carries
  one. Adding one is a contract change to a plane this spec is otherwise only threading through.
- **Removing `request_id`**, and **migrating existing records**.
- **Stitching the singleton and queue-consumer Lambdas.** `notifications-writer` is excluded on cost
  and sequencing, not mechanism: FR-002 builds queue-body threading, but a notification is written
  after a run and its queue is fed by seven planes.
- **Child spans.** SPEC-226.

---

## Functional Requirements

### FR-001: The extractor reads the shapes a verb receives, and never a caller's body

#### Description:

**The shape list is a security boundary, not a convenience.** `_extract_request_id` today tries a
top-level `requestId`, then falls back to `record = event` for a non-list event and parses
`record["body"]`. For an API Gateway payload-2.0 request that `body` is **the caller's HTTP body**,
so a caller can put `{"requestId": "…"}` in it and have it stamped as the API span's correlation key.
Verified by execution against `main`.

On `main` this is **latent rather than live**: `_stamp_correlation` runs at the top of dispatch,
before both early returns, and overwrites it with the gateway's id — and because SPEC-015 backfills
the boundary events from the baggage live at close, every stored record carries the gateway's value.
Also verified. It is a hazard, not a leak, and this spec must not turn it into one — which a
four-shape traceparent extractor would, because **nothing overwrites an adopted trace**. A reviewer
building this spec as first drafted demonstrated a caller setting the API span's `trace_id` and
`run_traceparent()` returning the caller's value, ready to be stamped into the outbound message.

So the body branch is narrowed to a **list** — the EventBridge Pipe envelope and nothing else.
Production always delivers the array, and the API is the only verb in the fleet with a top-level
`body`. That single narrowing closes the traceparent vector and the latent `request_id` hazard
together, and it is why this FR leads the spec.

| Shape | Where the value sits | Which verbs |
|---|---|---|
| State payload | top-level `traceparent` | every Task-invoked verb |
| Pipe envelope — **a list only** | `[{"body": "<json string>"}]` | the eight `validate-authorize` verbs |
| Distributed-Map batch | `BatchInput.traceparent` beside `Items` | the six copy/retrieve verbs (FR-003) |
| Inline-Map child | `request.traceparent` | file-send and table-share `check-target-absent`, table-share `create-table` |

`_extract_request_id` is widened to the same shapes in the same change — same walk, same event.

**`run_traceparent()` needs its own state.** The library's only accessor,
`context.get_adopted_context()`, returns `(trace_id, parent_span_id)` — version and flags are
already discarded, so a string rebuilt from it is not the string that arrived, and an inbound
unsampled `-00` would be re-emitted as `-01`. It is also absent from `lf.__all__`. So adoption
records the traceparent verbatim in a module `ContextVar`, set by `_adopt_trace` and cleared by the
reset, and `run_traceparent()` returns that; the current span's only when nothing was adopted, which
is the API.

**A missing traceparent is normal and is not warned.** The API is the root and has none by
definition, so warning on absence would write a `logger.warning` to CloudWatch on every HTTP
request. Malformed and rejected are warned; absent is not.

#### Acceptance Criteria:

- [ ] A `@traced` handler invoked with a traceparent emits a root span whose `trace_id` is the
      inbound one and `parent_span_id` the inbound span id — asserted once per shape, parametrised
      over the table so a fifth shape cannot be added unnoticed.
- [ ] **An API Gateway payload-2.0 event whose caller-supplied `body` carries a `traceparent` and a
      `requestId` yields neither.** Both halves asserted. This test fails against the current
      extractor for `requestId`, which is what makes it a fix rather than a restatement.
- [ ] `_extract_request_id` returns the id for the inline-Map shape, which it does not today.
- [ ] A handler with **no** traceparent mints a fresh `trace_id`, does not raise, and logs **no**
      warning. The three malformed forms mint a fresh one and **do** warn.
- [ ] A second invocation on the same warm container, with no traceparent, mints a fresh `trace_id`.
- [ ] `run_traceparent()` returns the adopted value **byte-for-byte**, asserted with an inbound
      traceparent whose flags are `-00`, so a rebuild-from-parts implementation fails.

### FR-002: The run's traceparent is minted where the run begins

#### Description:

`enqueue.build_message` adds the API span's traceparent to the message body, making the API's own
span the root of the run's trace. It is written **unconditionally**, `None` included: a conditional
write would hand a caller's value straight through whenever no span is open, which is the failure
FR-001 exists to close.

The threat model FR-001 handles is the inbound half. This FR is the outbound half: `build_message`
spreads `**dict(payload)` first, so a stamped value overwrites a caller's key of the same name.

**Adding the field is not one line, and this was found by execution during the build rather than
by either review.** Four planes REFUSE an unknown top-level body field — archive (per mode, plus
`arcommon/restore.ALLOWED_FIELDS`), file-send, file-ops and results-conversion — and
`test_plane_envelope_agreement.py` holds each of the five constants to **set equality** against
what the API may send, which is the route's declared fields, `identity`, and `route.stamped`.
Stamping without widening them answers every archive request with `malformed_event`. So
`traceparent` is declared on all **eleven** enqueue routes' `stamped` term and returned by
`_stamped_values`, which keeps that guard's `set(_stamped_values(route)) == set(route.stamped)`
exact rather than weakened; the guard pinning "only four routes stamp a field" splits in two, so
`mode` — the one that chooses behaviour — stays pinned to four while the traceparent is required
on all eleven.

#### Acceptance Criteria:

- [ ] Every message `enqueue` sends carries a `traceparent` whose trace id matches the API span's.
- [ ] A caller-supplied `traceparent` in the request body does not survive into the sent message.
      Assert it at **both** doors — the extractor (FR-001) and the stamp — because the route
      contract refuses an undeclared body key today, so a send-level assertion alone would pass for
      a reason that has nothing to do with this spec and would stop holding the day a route declares
      a free-form block.
- [ ] The added field is inside the message-size cap, asserted by building a maximum-size payload
      and showing the refusal still fires.

### FR-003: The six Distributed Maps carry the traceparent to their children

#### Description:

**Six**, not four: archive alone has three — `TransferObjects`, `RetrieveObjects`,
`CopyBackObjects` — beside one each on file-ops, file-send and table-share. Counted by parsing all
eight templates. The two on archive's restore arm are the largest data movement in the repo.

None has an `ItemSelector`; all six read a JSONL manifest through `ItemReader`, so the parent state
is invisible to a child. All six already declare an `ItemBatcher`, and **no template uses
`BatchInput`** — a payload template evaluated against the Map state's input and delivered once per
**batch**. Writing the traceparent into the manifest instead would repeat it on every line of a
dataset that can hold tens of thousands.

**`BatchInput` carries `requestId` only where the plane has one.** table-share's validator returns
no `requestId` and no downstream state holds one, so `"requestId.$": "$.requestId"` there is an
uncatchable `States.Runtime` on every share. The key is per-plane, derived from what the plane's
state actually carries — not a fixed pair.

**The mechanism is proved by execution, not citation.** AWS documents `BatchInput`'s shape and that
its `.$` paths resolve against the Map state's input, but every documented example uses an inline
array through `ItemsPath`; no page pairs `ItemReader` with `BatchInput`, and all six Maps here use
`ItemReader`. `aws stepfunctions test-state` cannot test a Map's child in isolation, so this needs a
real execution.

The three **inline** Maps need no ASL change — they already carry `"request.$": "$"` — but their
children receive the parent state nested under `request`, which is FR-001's fourth shape.

#### Acceptance Criteria:

- [ ] A recorded one-off execution shows `BatchInput` reaching a child of an `ItemReader`-fed
      Distributed Map with `Items` unchanged beside it: deploy one machine with the block, drive it
      with a two-line JSONL manifest, and read the child's input from the Map Run export or the
      child's `ExecutionStarted` history event. Recorded on the PR. **This is the one criterion that
      cannot be discharged locally**, and the ASL edits are written before it only at the risk of
      rewriting them.
- [ ] All **six** Distributed Maps carry `ItemBatcher.BatchInput` with the traceparent, the count
      derived by parsing the templates in the test rather than written as a literal.
- [ ] `BatchInput` carries `requestId` on every plane whose state has one, and on table-share
      carries the traceparent alone. A test asserts no `BatchInput` reads a path its plane's state
      does not supply.
- [ ] A copy verb driven with a `{"BatchInput": {...}, "Items": [...]}` event joins the inbound
      trace, and carries the request id on the planes that supply one.
- [ ] `test_the_whole_map_state_stays_under_the_payload_limit`'s model includes the new key **and
      its headroom is re-derived**, not just re-run — it modelled a ~95%-of-limit peak historically.

### FR-004: Every success-path state that names fields individually names the traceparent

#### Description:

Most threading is free: a Task using `"Payload.$": "$"` with `"OutputPath": "$.Payload"` carries a
new key untouched. **Ten** states do not, and the sweep that finds them needs **five**
discriminators that a plain "names its fields" rule gets wrong — each established by building the
sweep and reading what it returned. (Four was this spec's own count and it is wrong: implemented
literally, the first four select **21** states.)

1. **A `Pass` with a `ResultPath` merges** under that path and drops nothing. Without this, five
   `StampExecution`-style states join the population as false positives.
2. **A Task's `Parameters.Payload` block *is* its Lambda's input**, so a field-naming one drops a
   key exactly as a `Pass` does. Four qualify.
3. **Failure-path states are excluded** — a state that cannot reach a success terminal except
   through a `Catch` edge. Without this the sweep demands the key on **29** states SPEC-227 owns
   (28 was this spec's count; re-derived by parsing).
4. **A Map branch's success terminal is `End: true`, not `Succeeded`.** No `Succeed` state exists
   inside a Map branch, so a literal walk-to-`Succeeded` excludes every inline-Map state.

5. **A `Pass` that is ITSELF a success terminal is excluded**, for two reasons worth keeping
   apart. A Map branch's leaf becomes one ELEMENT of the Map's result array, merged back under the
   Map's own `ResultPath` into a state that still carries the traceparent, so nothing is lost. A
   `Pass` whose `Next` is a `Succeed` produces the EXECUTION's output, which no state reads. It
   applies to `Pass` states only: a Task's `Payload` is its Lambda's input, read wherever it sits.

A walk-to-`Succeeded` rule **on its own is wrong in the other direction too**: `archive:NotifyArchived`
and `NotifyRestored` reach `Succeeded` and would be classified terminal — excluding two of the four
Task blocks this FR requires. That is why the fifth discriminator asks whether a state IS a
terminal, one hop, rather than whether it can reach one.

The ten: archive `Validated`, `NotifyArchived`, `NotifyRestoreStarted`, `NotifyRestored`; file-send
`Validated`, `ShapeSummary`; results-conversion `Validated`, `Described`, `Converted`; table-share
`FinishRecipients/CreateTable`. **table-share therefore does have a field-naming state** — an
earlier draft listed it among the planes needing only a validator change, and that was wrong.
`FinishRecipients/CreateTable` already passes `"request.$": "$.request"`, so its child already
receives the value through FR-001's fourth shape; naming the key there is a second copy, kept for
uniformity of the sweep rather than because the child would otherwise miss it.

**Two intermediate verbs must return it too.** results-conversion's `Described` and `Converted` are
cross-checked against `describe-results`' and `convert`'s real returns, so naming the key in ASL
alone reddens those tests. Each reads it from `run_traceparent()` rather than from a required
carried field, so a missing traceparent is never a `TerminalError` on a logging value.

**Five exact-equality fixtures change, not six** — measured by running the suite against the
change rather than counted by reading. **Four** validators' returns and one describe-results return
are asserted with `==` against a literal dict (file-send, results-conversion, shared-space and
table-share; archive, data-quality, file-ops and table-builder assert field by field and are
unaffected). A minted traceparent is non-deterministic, so each pops it and asserts it separately.
**Three further tests move that the count did not anticipate**: results-conversion's three ASL↔verb
cross-checks are set-equality, and set equality forbids the only deploy order that is safe — the
verb has to return the key in a release where no state reads it. They compare domain keys and
assert the run key on the verb side directly.

#### Acceptance Criteria:

- [ ] Every plane's `validate-authorize` returns `traceparent`, including shared-spaces', whose
      return is the one conditionally-shaped key set in the fleet.
- [ ] The ten states above name it, and `describe-results` and `convert` return it.
- [ ] A sweep over all eight templates derives that population by parsing, applying the four
      discriminators, and returns **exactly** those ten. A test pins the count and the membership,
      so a discriminator that silently widens or narrows the population fails.
- [ ] It carries a positive control that it found states at all, and is mutation-tested per state —
      removing the key from any one must fail and name the plane and the state.
- [ ] The six exact-equality fixtures are updated and still assert the rest of the return.

### FR-005: A run is one trace, proved end to end

#### Description:

Every per-verb test can pass while the run is still many traces. The guard drives a run's verbs in
sequence, feeding each the previous one's output the way the state machine does.

**The planes are named, not chosen at build time.** A guard against data-quality, shared-spaces or
table-builder exercises no Map hop, no field-naming state and no inline-Map nesting, and passes. It
runs against **file-send** — a Distributed Map, an inline Map, two field-naming `Pass` states and a
notify verb — and **archive**, with three Distributed Maps and three field-naming Task states.

#### Acceptance Criteria:

- [ ] For file-send and archive end to end, and for the API-to-first-verb hop, every span carries
      one `trace_id`.
- [ ] The guard asserts a non-zero span count and more than one contributing verb first.
- [ ] Mutation-tested three ways — dropping `traceparent` from the state payload, from a Map's
      `BatchInput`, and dropping the adoption from `traced` — with the failure distinguishing them.
      A plant that only breaks JSON parsing does not count: three Map plants initially reddened for
      that reason during authoring, never reaching the guard.
- [ ] `request_id` is present on every span of both runs **except** table-share's three Map-child
      verbs, which have no id to carry; that exception is asserted explicitly so it cannot widen
      silently.

---

## Data Model

```ts
type StatePayload = {
  requestId: string;        // absent on table-share, which has never carried one
  traceparent: string;      // "00-<32 hex>-<16 hex>-<2 hex flags>"
};

type MapChildEvent = {
  BatchInput: { traceparent: string; requestId?: string };   // requestId only where the plane has one
  Items: TransferItem[];                                     // unchanged
};
```

## Interface Contract

```python
def run_traceparent() -> str | None:
    """The traceparent identifying THIS RUN — the adopted value verbatim, or the current
    span's where nothing was adopted (the API, which is the root)."""

# inside `traced`'s wrapper, in this order:
_reset_context()          # clears baggage AND any adopted context (SPEC-224 FR-002)
_stamp_verb(verb)
_stamp_request_id(event)
_adopt_trace(event)       # continue_trace(...) — applies to the next root span
try:
    return span(*args, **kwargs)
finally:
    flush()
```

## Implementation Phases

### Phase 1: The extractor, narrowed

- Narrow the body branch to a list; `_extract_traceparent`; `_adopt_trace`; the adopted-traceparent
  `ContextVar` and `run_traceparent()`; the wrapper ordering.
- FR-001's per-shape tests and the API-Gateway-poison test, each mutation-tested.

### Phase 2: The producer, the Maps and the field-naming states

- `enqueue.build_message`; the six `ItemBatcher.BatchInput` blocks; the ten states; the two
  intermediate verb returns; the six fixtures.
- The parsing sweep with its five discriminators, pinned to a membership list.

### Phase 3: The proof and the record

- FR-005's file-send and archive guards, mutation-tested three ways.
- Replace "one run is nine traces" at `lambdas/info/shared-layer.md:184`,
  `docs/decisions/control-planes.md:235` (the **entry**; the Fences say nothing about trace counts)
  and `docs/specs/ARCS.md`.
- Full local gates green by exit code, including `tofu validate`, `tofu fmt -recursive -check` and
  `validate_docs.py`.
