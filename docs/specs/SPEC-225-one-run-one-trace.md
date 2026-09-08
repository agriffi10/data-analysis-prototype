# Spec: One Run, One Trace

**ID:** SPEC-225
**Status:** Draft
**Last Updated:** 2026-09-08
**Depends On:** SPEC-128 (Completed), SPEC-130 (Completed), SPEC-224

## Overview

A control-plane run is one user action carried out by nine or more Lambda invocations. Each of them
opens its own root span, and `log-foundry`'s trace context is per-process, so each mints its own
`trace_id` and every root span's `parent_span_id` is null. **One run is nine traces**, joined by a
`request_id` field that SPEC-128 added for exactly that reason. An operator asking "what happened to
this request" runs a field filter and reads nine unrelated traces in whatever order they come back;
the shape of the run — which verb followed which, and which one the time went to — is not in the
store at all.

This spec makes a run one trace. The W3C traceparent for the run is minted once, threaded through
the Step Functions state payload exactly as `requestId` is today, and adopted by every verb before
its span opens. `request_id` stays: it is the join key for anything outside the trace, and removing
a working correlation key while installing a new one is how a store retained forever ends up with a
window that has neither.

This was **deliberately deferred**, not overlooked — recorded in `docs/specs/ARCS.md` and
`lambdas/info/shared-layer.md` as "correlation now, stitching later" (user decision, 2026-07-22),
sequenced after the pipe was proven live. It is unblocked now for a specific reason: on
`log-foundry` 0.6.0 `continue_trace` is **sticky**, and a sticky adoption in a warm Lambda container
is worse than no adoption — measured during authoring, one call keeps every later root span in the
inbound trace, so the container's next, unrelated invocation silently joins the previous run's
trace and merges two users' work under one `trace_id`. SPEC-224's 1.0.0 makes it one-shot, which is
exactly the per-invocation shape Lambda needs.

## Scope

### In Scope

- Trace adoption inside `cpcommon.observability`, so no verb imports `log_foundry` to do it.
- Minting the run's traceparent at the API, where a run begins.
- Threading it through each plane's state payload, including Distributed Map children.
- A guard that a run is one trace, driven end to end rather than read off the source.

### Out of Scope

- **Removing `request_id`.** It stays, on both the boundary events and the narrative. The trace is
  additive.
- **Migrating existing records.** `logs/` is appended NDJSON retained forever, and rewriting a day
  object to backfill a `trace_id` would risk a day of logs to tidy a field boundary — the same call
  SPEC-130 made about the `function: "handler"` rename. Records before the cutover keep nine trace
  ids per run and are queried on `request_id`, which is why `request_id` stays.
- **Stitching the singleton and queue-consumer Lambdas** — the log sweep, the DLQ drain,
  `notifications-writer`, `feedback-writer`, `user-directory-build`, the Cognito triggers. They are
  not part of a state-machine run and have no state payload to thread. `notifications-writer` is the
  interesting one and is deliberately left: a notification is written *after* a run and reaching it
  means threading the traceparent through a queue body rather than a state payload, which is a
  second mechanism and belongs in its own spec if it is wanted.
- **Child spans.** SPEC-226.
- **Emitting a `traceparent` to the browser.** The API answers `{"requestId": …}` and continues to.

---

## Functional Requirements

### FR-001: `observability` adopts an inbound trace, and can hand its own on

#### Description:

`cpcommon.observability` gains two things and keeps its one-door rule — nothing outside the module
imports `log_foundry`.

`traced` adopts an inbound traceparent read from the handler's own event, mirroring
`_stamp_request_id`: done at the single point that already wraps every handler, because a
correlation mechanism added by hand in nine places is one a tenth verb will be added without. The
event shapes are the same two `_extract_request_id` already handles — the plain state payload, and
the EventBridge Pipe's raw SQS batch whose single record's body is a JSON string.

Order inside the wrapper is load-bearing: `_reset_baggage` clears the adopted context as well as
baggage (SPEC-224 FR-002), so adoption must come **after** it and **before** the span opens, since
`continue_trace` applies to the next root span and to no span already open.

A public `traceparent()` reader wraps `lf.current_traceparent()` so a verb can put the run's
traceparent into the payload it returns without reaching for the library.

Adoption never fails a verb. A missing traceparent, a malformed one, or a `ContinueResult` reporting
`ok=False` all mean "mint a fresh trace and carry on", warned to `logger` and never raised — the
same discipline every other emitter in the module follows.

#### Acceptance Criteria:

- [ ] A `@traced` handler invoked with a traceparent in its event emits a root span whose `trace_id`
      is the inbound one and whose `parent_span_id` is the inbound span id.
- [ ] The same holds for the Pipe envelope shape — a single-record list whose `body` is a JSON
      string carrying the traceparent.
- [ ] A handler invoked with **no** traceparent emits a root span with a freshly minted `trace_id`,
      and does not raise.
- [ ] A handler invoked with a **malformed** traceparent emits a root span with a freshly minted
      `trace_id`, does not raise, and logs a warning.
- [ ] **A second invocation on the same warm container, with no traceparent, mints a fresh
      `trace_id` and does not join the first invocation's trace.** This is the property 0.6.0 did
      not have; it is asserted directly, not inherited from the library's release notes.
- [ ] `observability.traceparent()` returns the current traceparent inside a span and `None` outside
      one, and no module outside `cpcommon.observability` imports `log_foundry`.

### FR-002: The run's traceparent is minted where the run begins

#### Description:

A run begins at the API: the browser calls a route, the router opens a span, and `enqueue` sends the
request onto its plane's queue. `enqueue.build_message` adds the API span's traceparent to the
message body, alongside the fields it already stamps. That makes the API's own span the root of the
run's trace, so the trace answers "what happened to this request" starting from the request, not
from the first Lambda that happened to pick it up.

The traceparent is a stamped value, **not** a caller-supplied one: a body field a caller could set
would let a client join or poison another run's trace, and the message body is untrusted input. It
is written from `observability.traceparent()` on the server and any inbound value of that name in
the caller's payload is overwritten, exactly as the gateway's `request_id` already wins over the
body's `requestId`.

#### Acceptance Criteria:

- [ ] Every message `enqueue` sends carries a `traceparent` whose trace id matches the API span's.
- [ ] A caller-supplied `traceparent` in the request body does not survive into the sent message.
- [ ] The message-size guard still measures the serialized body **after** stamping, so the added
      field is inside the cap rather than outside it.
- [ ] The API's existing route tests are green by exit code.

### FR-003: Every plane threads the traceparent through its state payload

#### Description:

Each plane's `validate-authorize` returns the run's traceparent in the state payload, and each
plane's state machine carries it forward. The survey below was done during authoring against all
eight templates rather than assumed from the archive machine's shape, because the planes differ
more than their shared idiom suggests.

**Most of the threading is free.** Every Task in every plane uses `"Payload.$": "$"` and either
`"OutputPath": "$.Payload"` or a `ResultPath`, so a Task-to-Task chain carries a new key with no
edit. Five planes — data-quality, file-ops, shared-spaces, table-builder, table-share — have **no
field-naming state on the threading path at all**, and need only their validator changed. There are
no `InputPath` and no `ResultSelector` blocks anywhere in the eight templates.

**Three kinds of site do drop it, and each is a different mechanism:**

1. **Field-naming `Pass` states on the threading path.** `Validated` in archive and file-send;
   `Validated`, `Described` and `Converted` in results-conversion. A key absent from one of these is
   dropped with no error.
2. **The failure terminals.** Every plane reshapes state into a failure seed before `RecordFailure`
   and `NotifyFailure`, and a seed that omits the traceparent puts the *failure* path — the run
   whose trace is most worth having — outside the trace. The seeds are in scope for that reason.
   The cost is stated rather than discovered: `test_state_machines_cpcommon.py`'s
   `test_a_failure_seed_supplies_every_key_the_failure_terminal_reads` requires every seed on a
   plane to supply every key its terminal reads, so adding the traceparent to a plane's
   `RecordFailure` obliges adding it to **all** of that plane's seeds — nine of them on archive.
3. **Distributed Map children.** Not through `ItemSelector` — **no Distributed Map in this repo has
   one**. All four read their dataset with `ItemReader` from a JSONL manifest, so a child's payload
   is a manifest line and the parent state is invisible to it. The mechanism that fixes this is
   `ItemBatcher.BatchInput`, a payload template evaluated against the parent state and delivered
   once per **batch**: all four Distributed Maps already declare an `ItemBatcher`, and **no template
   in the repo uses `BatchInput` today**. Writing the traceparent into the manifest instead would
   repeat it on every line of a dataset that can hold tens of thousands, which is the wrong unit.
   The two **inline** Maps (file-send's `GuardRecipients`, table-share's `GuardRecipients` and
   `FinishRecipients`) already carry `"request.$": "$"` in their `ItemSelector` and need no change.

The traceparent is threaded **unchanged**, not re-minted per verb. Every verb's root span therefore
shares the run's `trace_id` and names the same parent, which is what makes the run one trace. Having
each verb hand its own traceparent to the next would build a deeper tree and would require all
seventy-four verbs to change their return value; the flat shape buys the query for a change confined
to the validators, five `Pass` states, the failure seeds and four `ItemBatcher` blocks.

**A `BatchInput` changes the child's event shape**, so it is not a pure infra change: a Map child
currently receives `{"Items": [...]}` and will receive `{"BatchInput": {...}, "Items": [...]}`.
`Items` is untouched and every copy verb keeps working, but `_extract_traceparent` (FR-001) must read
that third shape as well as the two `_extract_request_id` handles.

#### Acceptance Criteria:

- [ ] Every plane's `validate-authorize` returns `traceparent`, including shared-spaces', whose
      return is the one validator in the fleet with a conditionally-shaped key set.
- [ ] The five field-naming `Pass` states on the threading path name `traceparent`.
- [ ] Every failure seed on every plane supplies it, and
      `test_a_failure_seed_supplies_every_key_the_failure_terminal_reads` is green.
- [ ] All four Distributed Maps carry `ItemBatcher.BatchInput` delivering the traceparent, and a
      Map child that receives one adopts it — asserted by driving a copy verb with a `BatchInput`
      event, not by reading the template.
- [ ] A sweep test enumerates **all eight** ASL templates and asserts that every state naming fields
      individually on a threading or failure path names `traceparent` — a population sweep, not a
      per-plane assertion list, so a plane added later cannot be missed. It carries a positive
      control that it found states at all.
- [ ] `test_the_whole_map_state_stays_under_the_payload_limit`'s hand-built state model includes the
      new key, so it keeps bounding the state that actually exists.
- [ ] `tofu -chdir=infra validate` passes.

### FR-004: The cross-check the archive machine claims it has

#### Description:

FR-003 leans on the field-naming states being held to their verbs' return values, and the archive
machine says in its own `Validated` comment that they are: *"a Pass naming each key fails the build
via `test_state_machine_archive.py`, which reads this block and the verb's real return value and
requires them to agree."* **It does not.** Verified during authoring: `test_state_machine_archive.py`
holds seven tests, all graph-walk and commit-gate checks, and no test anywhere in the repo reads
archive's `Validated`, `ArchiveComplete` or `RestoreComplete`. The same comment appears on
`ArchiveComplete` and makes the same claim.

The real coverage is three planes, not eight: results-conversion has three set-equality cross-checks,
file-send has a subset check, and file-ops has a subset check that scrapes the whole template. Five
planes — archive, data-quality, shared-spaces, table-builder, table-share — have none.

A comment asserting a guard that does not exist is worse than no comment: it is what a session reads
*instead* of checking, and this spec would have been one of them. The answer is the sweep FR-003
already requires rather than five hand-written per-plane tests — a recurring class of gap is closed
structurally, not one instance at a time — so this FR is the comment and the generalisation, and it
is deliberately small.

#### Acceptance Criteria:

- [ ] Both archive comments state what actually holds them, naming the sweep.
- [ ] The FR-003 sweep is generalised from `traceparent` to **every** key a field-naming state on a
      threading path reads, held against the producing verb's real return value, for all eight
      planes — so the property the archive comment claimed is true for the whole fleet.
- [ ] The sweep is mutation-tested per plane: renaming a key in one verb's return reddens it, and
      the failure names the plane and the key.
- [ ] The three existing per-plane cross-checks stay. They are narrower than the sweep in one
      direction and wider in another, and deleting a working guard because a new one overlaps it is
      how coverage is lost silently.

### FR-005: A run is one trace, proved end to end

#### Description:

The claim this spec exists to make is a property of a whole run, and every per-verb test can pass
while the run is still nine traces — a verb that adopts correctly still mints its own trace if the
state payload never delivered one. The guard therefore drives a run's verbs in sequence, feeding
each one the previous one's output the way the state machine does, and asserts one `trace_id` across
every span emitted.

It carries a positive control: an empty span list satisfies "all spans share a trace id" vacuously,
so the guard asserts the spans were collected and that more than one verb contributed.

#### Acceptance Criteria:

- [ ] For at least one plane end to end, and for the API-to-first-verb hop, every span emitted
      across the run carries one `trace_id`.
- [ ] The guard asserts a non-zero span count and a verb count above one before asserting the
      shared trace id.
- [ ] The guard is mutation-tested: dropping `traceparent` from the state payload reddens it, and
      dropping the adoption from `traced` reddens it, and the failure message distinguishes the two.
- [ ] `request_id` is still present on every span emitted by the run.

### FR-006: The claims this spec falsifies are retired where they are stated

#### Description:

"One run is nine traces" is stated as current fact in `lambdas/info/shared-layer.md`,
`docs/decisions/control-planes.md` and `docs/specs/ARCS.md`, each with the deferral that explains
it. A fence and a plane page that keep saying it after this ships are worse than silent: they are
the documents a session reads *instead* of the code.

Each site is **replaced**, not appended to — the completion ritual's rule. The deferral's reasoning
is worth one clause where the decision now reads the other way, because the reason it was deferred
(the pipe was not proven live; adoption was sticky) is the reason it is safe now.

#### Acceptance Criteria:

- [ ] Every live site claiming a run is nine traces is corrected, enumerated by repo-wide search.
- [ ] The `decisions/control-planes.md` Fences clause that carries "one run = nine traces" is
      **replaced** by the settled shape, not given a second clause beside it.
- [ ] `docs/specs/ARCS.md`'s observability-arc paragraph marks the superseded claim in place rather
      than being rewritten as though the deferral never happened.
- [ ] Completed spec files and delivery docs are left as history.
- [ ] `python3 scripts/validate_docs.py` is green.

---

## Data Model

The state payload gains one string key, threaded exactly as `requestId` is:

```ts
// The control-plane state payload, after validate-authorize
type StatePayload = {
  requestId: string;
  traceparent: string;   // W3C: "00-<32 hex trace id>-<16 hex span id>-<2 hex flags>"
  // …the plane's own fields, unchanged
};
```

The enqueued message body gains the same key:

```ts
type EnqueuedMessage = {
  // …the validated request body
  traceparent: string;   // stamped by the API; a caller-supplied value is overwritten
  identity: IdentityBlock;
};
```

## Interface Contract

```python
# cpcommon/observability.py — the two additions

def traceparent() -> str | None:
    """The current span's W3C traceparent, or None outside a span."""

# and, inside `traced`'s wrapper, in this order:
_reset_baggage()          # clears baggage AND any adopted context
_stamp_verb(verb)
_stamp_request_id(event)
_adopt_trace(event)       # continue_trace(...) — applies to the next root span
try:
    return span(*args, **kwargs)
finally:
    flush()
```

`_adopt_trace` never raises: a missing, malformed or rejected traceparent is a `logger.warning` and
a freshly minted trace.

## Implementation Phases

### Phase 1: The mechanism

- `_extract_traceparent`, `_adopt_trace` and the public `traceparent()` reader in
  `cpcommon.observability`; the wrapper ordering.
- FR-001's tests, including the warm-container isolation case, each mutation-tested.

### Phase 2: The producer and the payload

- `enqueue.build_message` stamps the traceparent; the caller-cannot-set test.
- Every plane's `validate-authorize` returns it; every field-naming ASL state and every Map
  `ItemSelector` names it; the population sweep over the ASL templates.

### Phase 3: The proof and the record

- FR-005's end-to-end one-trace guard with its positive control, mutation-tested both ways.
- FR-006's doc replacements; `validate_docs.py` green.
- Full local gates green by exit code, including `tofu validate`.
