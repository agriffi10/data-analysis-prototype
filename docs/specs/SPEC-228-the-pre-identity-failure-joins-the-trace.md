# Spec: The Pre-Identity Failure Joins the Trace, from the Envelope the State Already Carries

**ID:** SPEC-228
**Status:** In Progress
**Last Updated:** 2026-09-09
**Depends On:** SPEC-227 (Completed), SPEC-229 (Completed) — **SPEC-229 landed first.** It bounds the
state this spec makes bigger, and the window between widening and bounding is a reachable silent
failure rather than a tidiness concern.

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

**"Pre-identity" names the catch shape, not the absence of an identity, and the register's wording
is too narrow.** A live data-quality refusal on 2026-09-09 — actor verified, `location` refused as a
reserved prefix — produced `validate-authorize` records on the run's trace and a `notify-failure` on
a different one with a null `parent_span_id`. That failure had an identity; it lands on
`ValidateFailureSeed` anyway, because the seed is defined by the error having **replaced** the state
(`"error.$": "$"`), which is what every `validate-authorize` failure does whatever it knew by then.
The class this spec fixes is therefore every validate-authorize failure, not only the ones occurring
before an actor exists — the mechanism is unchanged, the description of who it reaches is wider than
SPEC-227 wrote it, and FR-004 corrects that wording along with the rest.

Every guard SPEC-227 built stays **green and unchanged**: seeds still supply a literal `null`,
`RecordFailure` still reads `$.traceparent`, and the pre-identity/post-identity split is still
derived the same way. Adoption moves to the place that can already do it.

**Carrying the envelope has a byte cost, and it is SPEC-229's, not this spec's.** A request travels
a four-link chain, each link capped at 256 KiB, and the fourth — `RecordFailure`, which is the Pipe's
record plus an error whose `Cause` may reach 32 KB — is computed on **one** plane out of the four
that carry it, against a model that allows the error 4 KB where the service permits 32. This spec
widens it to eight. That is why the bound lands first: between the widening and the
bound there is a band of request sizes where `RecordFailure` raises `States.DataLimitExceeded`
**outside every Catch**, so `NotifyFailure` never runs and a user whose request failed is told
nothing — the exact silent failure this arc exists to close, introduced by a change meant to close
it.

## Scope

### In Scope

- A fifth shape in `cpcommon.observability._shape_values`: the forwarded SQS envelope carried on
  the state as `raw`.
- `raw` on all eight planes' `RecordFailure`, read from the **context object** so no seed has to
  supply it and the failure-seed guard is not disturbed.
- Retiring the `raw` keys on failure seeds that this change makes dead, and correcting the
  per-plane guards, docstrings and ASL comments that describe where `raw` comes from.
- Nothing about the size chain, which is SPEC-229 and lands first. Bounding the exposure rather
  than deferring it is a user decision (2026-09-09); putting the bound in its own spec **ahead** of
  this one is how that decision is honoured, because a per-plane remedy turned out not to exist —
  every plane's cap is enforced inside the execution it would have to bound.
- Driving a pre-identity failure end to end on one plane from each half, and asserting
  `notify-failure`'s span carries the run's `trace_id`.
- Correcting every site that records the limit — the population derived by a search, not by a list.

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
  where `run_traceparent()` returns `None`. `$$.Execution.Input` cannot be absent.
- **Giving the four planes that gain `raw` an identity recovery from it.** `archive`, `file-ops`,
  `file-send` and `results-conversion` recover the actor out of `raw` when the state has none;
  `cpcommon.notify.actor_of` reads only `event["actor"]`, so the four planes gaining the envelope do
  not start using it by accident. Whether their notifiers *should* is a per-plane notification
  question with its own recipients and wording.
- **Giving `table-share` a `requestId`.** Its contract declares none and the route refuses undeclared
  keys, so FR-001 cannot give it one. Still SPEC-225's exclusion rather than this one's.
- **The success path.** `raw` reaches no success-path state on any plane, and this spec adds it to
  none.
- **Putting `raw` on the seeds instead — the pre-identity seed supplying the envelope and the 13
  post-identity seeds a literal `null`, with `RecordFailure` still reading `$.raw`.** Weighed and
  rejected rather than passed over. It is attractive for two real reasons: it keeps the envelope off
  every post-identity failure state, and it engages the failure-seed guard rather than being exempt
  from it. It is rejected because the byte argument is the weaker half of its own case — a
  post-identity failure's body is the **validated** one, already under its plane's cap, so the state
  it saves bytes on is not the state that overflows — and because SPEC-229 bounds the chain before
  this lands, which is what the byte argument was for. What is left is 21 seed edits against 8, and
  an exemption that is pinned either way.

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
      or holds a body that is not valid JSON returns `None` from **both extractors** and raises
      nothing — one case each. Asserted on the extractors rather than on `_shape_values`, which
      always yields the top-level value first and so never yields an empty sequence for a dict.
- [ ] The security narrowing is unchanged and asserted: a **bare dict** carrying a top-level `body`
      string still yields nothing from that `body`, so an API Gateway payload-2.0 event cannot name
      either key.
- [ ] The new branch is **mutation-tested**: deleting it reddens a named test, and the test's failure
      message is asserted so the pre-existing envelope branch cannot satisfy it. Name the plant that
      reddens the new branch and not the old one.

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
property both rejected alternatives lack. That exemption is deliberate and load-bearing, so it is
pinned rather than depended on silently.

**This is an argued exception to a Fences clause, and it says so rather than slipping past it.**
"Everything unbounded travels by pointer, never on the state, and a cap is not a substitute" is the
rule, and an envelope on a state is what this FR adds. The exception is that the envelope **is**
`$$.Execution.Input` — a value Step Functions has already bounded by admitting the execution, and
one there is no pointer to, because nothing wrote it anywhere a verb could fetch it from. FR-004
records the exception in the clause itself; SPEC-229 supplies the cap the clause says is not a
substitute, which is why it is not one here either.

Once no state reads `$.raw`, the `raw` keys on the failure seeds are dead and are removed. That
falsifies a set of claims spread across two per-plane guards, several ASL comments and about a dozen
docstrings, all of which say the **seed** is where the envelope comes from. Two of those guards go
red, and one of them matters more than its redness: file-send's
`test_no_failure_seed_carries_the_selection_twice` is a 256 KiB fence, not a tidiness check — its
subject is that the seed must not carry the selection *beside* the envelope. Only half of it moves:
the envelope is now on `RecordFailure`, so that is where the sum lives and where the `raw`-presence
half re-points — but the `source.$` absence half stays over all three states, because the seeds are
where a `source` key would be re-added. Dropping either would leave a future `source` looking free.

#### Acceptance Criteria:

- [ ] All eight `RecordFailure` states carry `raw` as `$$.Execution.Input` — the population derived
      from the templates, not listed, and asserted to be exactly eight.
- [ ] **No state on any plane reads `$.raw`**, derived by parsing rather than by grep, and no failure
      seed supplies a `raw` key.
- [ ] The `_read_keys` exemption is **pinned by its own fixture**: a `Pass` reading `$$.Execution.Input`
      is not reported by `_seed_violations`, with the reason recorded where the fixture lives —
      a context-object read is exempt *because the context object cannot be absent*.
- [ ] `test_a_failure_seed_supplies_every_key_the_failure_terminal_reads`,
      `test_the_pre_identity_seeds_are_the_ones_the_error_replaced` and
      `test_every_failure_path_state_names_the_traceparent` are green **with no edit** — a change to
      any of them is a signal the design drifted rather than a task.
- [ ] The two per-plane guards this breaks are corrected rather than relaxed:
      `results-conversion-common/test_state_machine_results_conversion.py`'s seed key-set equality
      and its `RecordFailure ⊆ RequestFailureSeed` containment, and
      `file-send-common/test_config_fscommon.py`'s `test_no_failure_seed_carries_the_selection_twice`.
      The latter asserts two things over three states, and only one of them moves: the `raw`-presence
      half re-points to `RecordFailure`, and the **`source.$` absence half stays over all three**,
      because the seeds are where a `source` key would be re-added.
- [ ] **Every claim that the failure SEED is where `raw` comes from is corrected**, in ASL comments,
      verb and test docstrings, and `file-ops-validate-authorize`'s `created_later` mapping. The
      sweep is closed with a search over `infra/` and `lambdas/`, not with memory of which files were
      edited.
- [ ] The four notify-failure verbs that recover an actor from `raw` are **driven**, not reasoned
      about, because their input now arrives by a different ASL path.

### FR-003: A pre-identity failure is driven end to end, and its notification is in the run's trace

#### Description:

`test_one_run_one_trace.py` drives failure runs on two planes today and both are post-identity. The
guard this spec owes drives a **pre-identity** failure — `validate-authorize` raising before it
returns — through the ASL's own `Parameters` blocks into `notify-failure`, and asserts the
notification's span carries the same `trace_id` as `validate-authorize`'s.

It runs on one plane from **each** half of the fleet: one that carried `raw` before this spec and
one that did not, because the two halves reach `RecordFailure` by different ASL edits and a drive
over one says nothing about the other.

**This is the largest piece of new work in the spec and it is sized here rather than left to the
build**, because `_drive_a_failure` does not model a pre-identity failure today and two things stop
it. It puts `__execution_input__` on the state to model the context object, and a pre-identity
seed's `"error.$": "$"` resolves to the *whole* state — so the harness's synthetic key would land
inside the `error` object, a shape no real run produces, on the very state this FR asks be built
faithfully. And the harness models seed → `RecordFailure` directly, which holds for shared-spaces
and table-share but not for `data-quality`, whose seed goes through `DropTempTablesOnFailure`, or
`table-builder`, whose seed goes through `ReleaseRefreshLockOnFailure` — each an intervening Task
needing a stub. Choosing the pair to drive is part of this FR, and the choice is bounded by those
two facts rather than free.

#### Acceptance Criteria:

- [ ] A pre-identity failure driven on one plane that already carried `raw` and one that did not:
      `validate-authorize`'s span and `notify-failure`'s span share one `trace_id`, and
      `notify-failure`'s `parent_span_id` is non-null.
- [ ] The context-object model does not leak into the error: the `error` object the drive produces
      carries no harness-only key, asserted rather than assumed.
- [ ] The drive raises inside `validate-authorize` rather than hand-shaping the state, so the
      `"error.$": "$"` replacement that defines a pre-identity seed actually happens.
- [ ] The drive fails for the **right reason** when the FR-001 branch is removed — asserted on the
      failure message, not on an exit code, because a post-identity drive in the same file fails with
      the same shape.
- [ ] A **positive control that ships**, not a one-time act during the build: the new drive carries
      a floor on the spans it collected, the way the existing drive's `len(spans) >= expected` does,
      so a drive that collected nothing cannot satisfy a one-trace assertion vacuously.

### FR-004: Every site that records the limit says what is now true

#### Description:

The limit is recorded in more places than a list can be trusted to hold, and one of them instructs a
human to go and confirm it in production. The population is therefore **derived by a search** over
`docs/`, `infra/` and `lambdas/`, and the sites found while authoring are a floor rather than the
total: the register's `## Fences` clause and its SPEC-227 entry — and a third mention inside the
SPEC-225 entry; **two** far-apart paragraphs in `ARCS.md`; SPEC-227's own known-limit paragraph and
its delivery doc; `lambdas/info/shared-layer.md`; the module docstring of
`cpcommon/observability.py` itself; and the `docs/testing/owed.md` row whose half (b) tells a human
to confirm `notify-failure` carries a **different** `trace_id`.

Two further clauses in the same Fences block are touched. "Everything unbounded travels by pointer,
never on the state, and a cap is not a substitute" gains the exception FR-002 argues, naming the
envelope and naming SPEC-229 as the cap. And the clause about a catch routed to a state reading
`$.raw` describes a hazard that becomes unreachable — no state reads `$.raw` after FR-002 — so it is
**generalised** to the trap that is still live and still general: a `Pass` hard-fails on an absent
key, whatever the key is called.

The pre-identity clause is **replaced, not appended to**. Its first sentence — a pre-identity seed supplies
literals for everything its terminal reads, including `traceparent` — stays true and load-bearing;
the clause that follows it ("is not meant to … reachable nowhere ASL can read") is what this spec
falsifies, and leaving it under a new sentence is how a superseded claim goes on being read as
current. The clause immediately above it loses its referent for a different reason — it explains that
a catch must not route to a state reading `$.raw`, and after FR-002 no state reads `$.raw` — so it is
re-pointed at the context read rather than deleted.

#### Acceptance Criteria:

- [ ] The population is **derived**: a search over `docs/`, `infra/` and `lambdas/` for the limit's
      phrasings returns only corrected text, and the spec's list above is treated as a floor that the
      search may exceed.
- [ ] Every corrected site keeps the **ASL half** of SPEC-227's reasoning, which is still true and is
      still why the machines are shaped as they are: the value is reachable nowhere ASL can read, and
      is now read in Python from the envelope on the state.
- [ ] The `owed.md` row is rewritten **whole** — its title and its middle column assert the falsified
      claim too, not only half (b) — and the "if (b) shows one shared trace, the register entry is
      wrong" sentence is removed rather than left inverted. Its 2026-09-09 data-quality evidence is
      **kept and re-pointed**, not deleted with the row's old claim: it is the observation that the
      class was wider than "pre-identity", and it predicted this spec's result before this spec
      existed.
- [ ] Every site is corrected on the **class**, not just the mechanism: a `validate-authorize`
      failure reaches `ValidateFailureSeed` whether or not an actor was verified, so "pre-identity"
      is replaced wherever it is used to mean "before an identity exists" rather than "the error
      replaced the state".
- [ ] The `$.raw` Fences clause is **generalised** rather than re-pointed or deleted: its subject
      becomes the absent-key hard failure, which is still reachable, rather than a construct that
      provably cannot trip it.
- [ ] The "everything unbounded travels by pointer" clause names the envelope exception and the spec
      that supplies its cap.
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
  error: { Error?: string; Cause?: string };  // Cause is capped by Step Functions at 32 KB
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
lambdas/control-plane-common/cpcommon/observability.py       # FR-001, and its module docstring (FR-004)
lambdas/control-plane-common/test_observability_cpcommon.py  # FR-001 guards
lambdas/control-plane-common/test_one_run_one_trace.py       # FR-003 drive
lambdas/control-plane-common/test_state_machines_cpcommon.py # FR-002 derived population, `_read_keys` fixture
lambdas/results-conversion-common/test_state_machine_results_conversion.py  # FR-002
lambdas/file-send-common/test_config_fscommon.py             # FR-002, the 256 KiB fence re-pointed
lambdas/file-ops-validate-authorize/test_file_ops_validate_authorize.py     # FR-002 `created_later`
lambdas/test_request_size_chain.py                           # FR-002 — SPEC-229's chain guard reads
                                                             #   `"raw" in keys` off the templates,
                                                             #   so four more planes now measure the
                                                             #   envelope. Re-derived, not re-checked.
infra/info/control-plane-shape.md                            # FR-004 — carries the `$.raw` Fences
                                                             #   clause VERBATIM beside the register's
lambdas/{archive,file-ops,file-send,results-conversion}-notify-failure/*.py # FR-002 docstrings
infra/modules/{archive,data-quality,file-ops,file-send,
  results-conversion,shared-spaces,table-builder,
  table-share}/state-machine.asl.json.tftpl                  # FR-002
lambdas/info/shared-layer.md                                 # FR-004
docs/decisions/control-planes.md                             # FR-004 (three sites)
docs/specs/ARCS.md                                           # FR-004 (two paragraphs)
docs/specs/SPEC-227-the-failure-path-joins-the-trace.md       # FR-004
docs/spec-delivery/SPEC-227-the-failure-path-joins-the-trace.md # FR-004
docs/testing/owed.md                                         # FR-004
```

## Implementation Phases

### Phase 1: The extractor

- Add the `raw` shape to `_shape_values`, walked last, reusing the envelope branch rather than
  copying it.
- Write FR-001's guards, including the precedence case with two distinct values and the five
  malformed-input cases asserted on the extractors.
- Mutation-test the new branch, and name the plant that reddens it without reddening the
  pre-existing envelope branch.

### Phase 2: The machines, and everything that described the old shape

- Move the four `$.raw` reads on `RecordFailure` to `$$.Execution.Input`; add the key to the other
  four; remove the now-dead `raw` keys from the seeds.
- Pin the `_read_keys` context-object exemption with its own fixture.
- Correct the two per-plane guards, re-pointing file-send's 256 KiB fence at `RecordFailure`.
- Sweep the ASL comments, verb docstrings and `created_later` mapping that name the seed as the
  envelope's source, and close the sweep with a search.

### Phase 3: The drive and the record

- Extend `test_one_run_one_trace.py` with a pre-identity failure drive on one plane from each half,
  with the positive control and the error-shape assertion.
- Correct the derived population of limit sites, replacing the superseded Fences clause and
  re-pointing the `$.raw` one, and rewrite the `owed.md` row's half (b).
