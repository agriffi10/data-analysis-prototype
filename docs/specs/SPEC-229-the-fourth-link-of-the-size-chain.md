# Spec: The Fourth Link of the Size Chain, and the Cap That Is Measured Against the Wrong Limit

**ID:** SPEC-229
**Status:** Draft
**Last Updated:** 2026-09-09
**Depends On:** None

## Overview

A request travels a chain of representations, each of which Step Functions caps at 256 KiB: the
caller's body; the Pipe's record, which carries that body as an **escaped** JSON string and is what
`StartExecution` receives; the validated state a verb returns; and — on a failure — the
`RecordFailure` state, which is the Pipe's record again plus an error whose `Cause` Step Functions
caps at 32 KB.

Three planes compute some of that chain and they disagree with each other. `archive-common` computes
the first three and says in its docstring why: file-send once shipped a cap measured against the last
link alone, "which would have permitted a request whose execution could not start at all."
`file-ops-common` computes the same three. `file-send-common` computes a **fourth** — and allows the
error 4 KB where Step Functions permits 32. So the fourth link is not unmeasured; it is measured on
one plane out of eight, against a model eight times too small, while three other planes carry it and
compute nothing.

The chain is bounded in exactly one place, and it is not where it looks. The API's
`MAX_MESSAGE_BYTES` is the only check upstream of `StartExecution` — the eleven enqueue handlers are
one factory with no per-route size validation, and `validate_request` checks shape, not length — and
it is derived from the **SQS** message limit, which is the wrong budget: it bounds what the queue
accepts, not what the execution can carry. Every per-plane cap that looks like it bounds this
(`ARCHIVE_MAX_ITEM_BYTES`, `SEND_MAX_ITEM_BYTES`, `FILE_OPS_MAX_SELECTION_BYTES`,
`SHARE_MAX_RECIPIENTS`) is enforced **inside** `validate-authorize` — inside the execution being
bounded — so the request that overflows the chain is precisely the one those caps would refuse,
arriving before any of them can run.

Two consequences are live today, both measured while authoring. At the current cap a quote-dense
body of 261,632 bytes reaches the Pipe as 523,328 bytes, so the API accepts requests whose execution
cannot start at all. And data-quality's `RecordFailure` names `location`, a caller-controlled string
bounded by nothing anywhere, so its failure state already breaches 256 KiB by 32,143 bytes on a
`Pass` with **no `Catch`** — `States.DataLimitExceeded`, thrown where nothing can catch it, so
`NotifyFailure` never runs and a user whose request failed is told nothing at all.

This spec bounds the fields that nothing bounds, computes all four links for every route against one
model, and gives `MAX_MESSAGE_BYTES` the budget that actually sizes it. It lands **before** SPEC-228,
which widens the fourth link to the four planes that do not yet carry it.

## Scope

### In Scope

- Bounding the caller-controlled fields a failure state carries **beside** the envelope, which is
  what makes a worst case exist at all.
- A declared worst-case request for every enqueue route, in one place, since most routes have none.
- Links one, two and four computed for every route in one guard, subsuming the parts of the three
  per-plane chain guards that currently disagree. Link three stays per-plane, because it models what
  a verb returns and no generic version of it would be as strong.
- `MAX_MESSAGE_BYTES` derived from the **Step Functions** limit instead of the SQS one.
- Recording the two live overshoots where the guard lives, not only in a delivery doc.

### Out of Scope

- **Per-plane caps as the remedy for the chain.** Measured and rejected: every existing per-plane cap
  runs inside `validate-authorize`, so none can bound a link evaluated before the verb is invoked.
  Lowering one changes a guard's arithmetic and nothing in production. They stay as what they are —
  bounds on what a verb will *do* — and FR-004's criteria hold the fleet cap above all of them.
- **Lowering any existing plane cap.** The derived fleet cap sits above every plane's worst legal
  request, so none has to move. If a future model puts the fleet cap below a plane's own, that is a
  conflict between two caps and it is escalated, not resolved by quietly lowering the plane's.
- **The trace.** SPEC-228 puts a pre-identity failure into the run's trace and is the reason the
  fourth link is about to widen. This spec bounds; it adds `raw` to no state.
- **Treating the cap as a substitute for a pointer.** The Fences say everything unbounded travels by
  pointer and a cap is not a substitute, and this spec's remedy is a cap — so it says why the fence
  permits it here rather than stepping around it. The value on the state is `$$.Execution.Input`,
  which Step Functions has already bounded by admitting the execution and which no pointer exists
  to, because nothing wrote it anywhere a verb could fetch it from. The fence binds a value the
  system chose to put on a state; this is the one value the system did not choose.
- **Messages already in flight.** A lowered cap bounds new messages only. What is already queued or
  on a DLQ was accepted under the old cap and nothing here bounds it.
- **The SPA's mirrored limits.** The browser mirrors the three plane item caps, not
  `MAX_MESSAGE_BYTES`, and none of those moves.

---

## Functional Requirements

### FR-001: No failure state names a caller-controlled field that nothing bounds

#### Description:

The fourth link can only be computed if its inputs are bounded, and one is not. data-quality's
`RecordFailure` names `location` — a caller string that `contract.validate_request` checks the shape
of and the length of never, that `router` does not size, and that `dq_validate_authorize` neither
normalises nor bounds. It rides the failure state at whatever length the fleet cap admits, and after
SPEC-228 it would ride it **twice**: escaped inside `raw`, and plain beside it.

The durable form of this is not "cap `location`" but the rule that makes a fourth link computable at
all: a failure state may name a caller-controlled field only if that field has a declared bound. The
guard derives the population from the templates and the contract rather than from a list, so a field
added to a `RecordFailure` later cannot arrive unbounded.

#### Acceptance Criteria:

- [ ] Every caller-controlled field named on any plane's `RecordFailure` has a declared byte bound,
      enforced at the API where it is upstream of `StartExecution` — not in `validate-authorize`,
      which is inside the execution the bound exists to protect.
- [ ] The population is **derived**: the guard reads each template's `RecordFailure` block, resolves
      which of its keys trace back to a caller-supplied value, and fails on any that has no bound.
      A hand-listed set of field names does not satisfy this.
- [ ] The rule is **mutation-tested by addition**: add an unbounded caller field to one template's
      `RecordFailure` and the guard reddens, naming the plane and the field.
- [ ] `location`'s bound is set from what the plane actually needs — the longest S3 prefix the
      data-quality flow can produce — and its constant names that as its budget, not a round number.
- [ ] A request exceeding the bound is refused with `PayloadTooLarge` at the API, the same code and
      shape every other size refusal uses.

### FR-002: Every enqueue route has a declared worst-case request, in one place

#### Description:

The chain cannot be computed without an input, and for most routes no input exists: four planes have
no request byte cap at all, and the contracts are bare `TypedDict`s with unbounded `list` fields and
unbounded strings. Archive's worst case exists only as a literal hand-built inside its own chain
test, and file-send's and file-ops' as two more.

Each enqueue route gets one declared worst-case request, built by a shared factory rather than
copied per test, so the guard's inputs are visible in one place and a contract that grows a field
fails to build its worst case rather than silently shrinking it.

**Routes, not planes, and there are eleven** — nine queues plus archive's second route
(`archive.restore`) and table-builder's second (`tableBuild.refresh`), and the members of each pair
do not share a worst case. Four *planes* have no cap of their own, which is five *routes*; the two
counts are different and the guard asserts against the route table rather than either number.

#### Acceptance Criteria:

- [ ] Every route in `contract.ROUTES` has a declared worst-case body, and the coverage is asserted
      as **set equality against the route table's own ids** — not as a count, which a substitution
      satisfies.
- [ ] Where a plane enforces a byte cap inside `validate-authorize`, the worst case is built **at**
      that cap, with the constant read from the plane's config rather than restated.
- [ ] Where a route has no cap, its worst case is the largest body its field types admit under the
      fleet cap, and the factory says in one line that this is why the number is what it is.
- [ ] The factory's own defaults are mutation-tested: a field hard-coded small where the contract
      permits large is this shape's blind spot, so change one and watch the derived bound move.

### FR-003: One chain guard, four links, every route, one model

#### Description:

Three plane guards compute overlapping parts of this chain and disagree about the fourth link. They
are replaced by one fleet guard computing all four links for all eleven routes. Replacing rather than
adding is the point: the same rule stated three times with a 4 KB / 32 KB disagreement in the middle
is how a fence goes quiet.

**The three modelling choices are pinned here, because leaving them to the build is what would make
this an acceptance criterion demanding a bound while supplying none of its inputs.**

1. **The record model is the realistic SQS record**, built from the shape AWS documents for a Pipes
   SQS source — `messageId`, `receiptHandle`, the FIFO `attributes` block, `md5OfBody`,
   `eventSourceARN` and the rest — not the 64-byte minimal stub archive's test uses. All eight pipes
   are `batch_size = 1` with no `input_template`, so the realistic record is what production sends.
2. **The `Cause` ceiling is 32 × 1024 bytes measured as it sits in the state**, and it is *not*
   doubled for escaping. The documented cap is on the `Cause` value itself; treating it as 32 KB of
   pre-escape content that then doubles would spend 32 KB of budget on a reading the service does not
   state. Because that reading is load-bearing, it is not merely asserted: the guard is fed a `Cause`
   captured from a real driven Lambda failure and checks the model is not exceeded, so a wrong
   reading reddens a test instead of killing an execution.
3. **Escaping is measured by serializing**, never modelled with a factor. Measured while authoring,
   the worst case for a `json.dumps` body re-embedded as a JSON string is exactly 2.0 — a run of
   quotes or backslashes — and no control character or non-ASCII byte beats it, because `json.dumps`
   emits none of them raw.

Link three — the validated state — is the one link with no machine-readable source, since it is what
a verb *returns*. It stays **per-plane**: the three plane guards keep their link-three assertions and
give up only links one, two and four. A generic model would be strictly weaker than the real ones —
file-ops' carries one outcome record per item — and dropping it would lose coverage that exists
today.

#### Acceptance Criteria:

- [ ] Links one, two and four are computed for all eleven routes in one fleet guard, against one
      `256 * 1024` constant, with the record and `Cause` models above.
- [ ] Link four is `RecordFailure` **as each template actually builds it**, parsed from the template
      rather than modelled, so a plane naming a new field is included without anyone remembering to.
- [ ] The three plane guards keep link three and lose links one, two and four; no assertion any of
      them makes today is lost — proved by listing what each asserted before and after, not by
      assuming.
- [ ] The guard is mutation-tested **on the derivation, not by deleting an assertion**: set the cap
      to the three-link value and link four breaches, red by a stated margin. A plant that only
      removes a line proves nothing, because a removed assertion never reddens.
- [ ] A route failing any link names **which** link, because the remedy differs — link two is a cap
      question and link four is a `Cause` question.
- [ ] The `Cause` model is checked against a real captured Lambda failure `Cause`, so the reading in
      point 2 is falsifiable by a test rather than by production.

### FR-004: `MAX_MESSAGE_BYTES` is measured against the limit that actually binds

#### Description:

`MAX_MESSAGE_BYTES` is `SQS_MAX_MESSAGE_BYTES - MAX_IDENTITY_BLOCK_BYTES` — the SQS service limit
less the block the sender adds. That budget is wrong in kind: SQS accepting a message says nothing
about Step Functions starting an execution with it, and the gap between them is the escaping the Pipe
applies.

The constant is re-derived from the chain: the largest body whose worst-case escaped record, plus the
`Cause` ceiling, plus a `RecordFailure` block, fits 256 KiB. Its docstring stops naming the SQS limit
as its budget and names this one, in the shape the register's Fences require — a cap computed by a
test against the budget that sized it, naming that budget.

The two overshoots are recorded **where the guard lives**, not only in a delivery doc, and both as
characterisations so the reason the cap moved is in the suite: a body at the old cap produced a
record over the limit, and data-quality's failure state breached without anyone having added `raw` to
it.

#### Acceptance Criteria:

- [ ] `MAX_MESSAGE_BYTES` is computed from the state limit, the `Cause` ceiling and the measured
      escaping. `SQS_MAX_MESSAGE_BYTES` stays as the queue's own ceiling and the effective cap is the
      lower of the two — asserted as a rule, with the note that the SQS arm is currently unreachable
      so nobody later reads its passing as evidence it fires.
- [ ] The derivation lives in **production code, not in a test that the module then mirrors** — an
      `X == X` assertion proves nothing. `cpcommon` is the home: `apicommon` already imports it and
      it imports nothing back, so the state limit and the `Cause` ceiling move there as named
      constants and `enqueue.py` reads them.
- [ ] Every route's worst legal request still passes `_refuse_if_oversized` at the new cap, asserted
      per route — the claim is "nothing at a plane's own declared bounds is refused", and it is
      stated that way rather than as "nothing is refused", which is false for an unbounded field
      before FR-001 bounds it.
- [ ] `test_the_size_cap_is_derived_from_what_the_queue_takes_and_what_is_stamped_on` in
      `api/test_enqueue_routes.py` is rewritten — it asserts the old derivation and narrates it in
      its docstring — and `MAX_IDENTITY_BLOCK_BYTES`, now a term of nothing in this derivation, is
      either given its remaining purpose in its own docstring or removed with its readers.
- [ ] Both overshoots are asserted as characterisations against the OLD constants, so the suite
      carries the reason rather than the prose.

---

## Data Model

```ts
// One route's worst case, built by the shared factory. The chain guard's only input.
type WorstCaseRequest = {
  routeId: string;            // eleven of them, set-equal to contract.ROUTES
  body: string;               // serialized, at the route's own permitted maximum
  cappedBy: string | null;    // the plane constant that bounds it, or null where none exists
};

// The links this guard owns. Link three stays with the three plane guards.
type ChainLinks = {
  body: number;               // link 1 — the caller's serialized body
  record: number;             // link 2 — the realistic Pipes SQS record, body escaped into it
  recordFailure: number;      // link 4 — link 2, plus a 32 KiB Cause, plus the plane's literals
};
```

## Environment Variables

None.

## File & Folder Structure

```
lambdas/test_request_size_chain.py                  # NEW — links 1/2/4, all eleven routes
lambdas/control-plane-common/cpcommon/errors.py     # STATE_PAYLOAD_LIMIT_BYTES, CAUSE_LIMIT_BYTES
lambdas/api/apicommon/enqueue.py                    # MAX_MESSAGE_BYTES re-derived and re-budgeted
lambdas/api/apicommon/contract.py                   # FR-001's bound on `location`
lambdas/api/test_enqueue_routes.py                  # the old derivation's test rewritten
lambdas/archive-common/test_config_arcommon.py      # keeps link three, loses 1/2/4
lambdas/file-send-common/test_config_fscommon.py    # keeps link three, loses 1/2/4 incl. its 4 KB model
lambdas/file-ops-common/test_config_focommon.py     # keeps link three, loses 1/2
lambdas/data-quality-validate-authorize/dq_validate_authorize.py  # reads the bounded `location`
```

## Implementation Phases

### Phase 1: The unbounded field

- Bound `location` at the API, sized from the longest prefix the flow produces.
- Write the derived guard that no `RecordFailure` names an unbounded caller field, and mutation-test
  it by addition.

### Phase 2: The inputs

- Build the worst-case request factory over `contract.ROUTES`, set-equal rather than counted.
- Mutation-test its defaults.

### Phase 3: The chain

- Move the state limit and `Cause` ceiling into `cpcommon` as named constants.
- Write the fleet guard for links one, two and four with the three pinned models, including the
  captured-`Cause` check; strip those links from the three plane guards, listing what each asserted
  before and after.
- Mutation-test the derivation.

### Phase 4: The cap

- Re-derive `MAX_MESSAGE_BYTES` in production code; rewrite the test that asserts the old
  derivation; settle `MAX_IDENTITY_BLOCK_BYTES`.
- Assert every route's worst legal request still passes, and characterise both old overshoots.
