---
type: Spec
id: SPEC-229
title: "Bound the Fields Nothing Bounds, and Measure the Cap Against the Limit That Binds"
description: "Bounds every caller-controlled field in the control-plane request chain and re-derives the message cap from the Step Functions 256 KiB limit, so no request can overflow a state and silence its failure notice."
spec_status: Completed
depends_on: []
---

## Overview

A request travels a chain of representations, each capped by Step Functions at 256 KiB: the caller's
body; the Pipe's record, which carries that body as an **escaped** JSON string and is what
`StartExecution` receives; the validated state a verb returns; and — on a failure — the
`RecordFailure` state, which is the Pipe's record again plus an error `Cause`.

The chain is bounded in one place, and it is not where it looks. `MAX_MESSAGE_BYTES` is the only
size check upstream of `StartExecution` — `validate_request` checks shape and never length, and the
eleven enqueue handlers are one factory with no per-route validation — and it is derived from the
**SQS** message limit, which is the wrong budget: it bounds what the queue accepts, not what the
execution can carry. Every per-plane cap that looks like it bounds this (`ARCHIVE_MAX_ITEM_BYTES`,
`SEND_MAX_ITEM_BYTES`, `FILE_OPS_MAX_SELECTION_BYTES`) runs **inside** `validate-authorize`, so the
request that overflows the chain arrives before the cap that would refuse it.

**The deeper problem is that most of the chain's inputs are unbounded, so no worst case exists to
measure.** `requestId` is declared `str` on every enqueue request, spread onto the wire verbatim by
`build_message`, and put straight onto the state by every validator; the only clip anywhere is
`MAX_LOGGED_REQUEST_ID`, which bounds a log field and says so. **It is bounded in one place after
all, and this spec was wrong to say otherwise**: nine of the eleven routes make the id the SQS
deduplication key verbatim, and `fifo._checked` refuses a derived key over 128 printable-ASCII
characters — after `build_message`, but before the send. So no route carrying a `requestId` could
put an over-long one on a queue. What that leaves genuinely unbounded is `archive.restore`'s
`archiveId`, which is a prior request's id and reaches no FIFO key at all. Seven planes' `RecordFailure` name it.
data-quality's names `location` and shared-spaces' names `space`, both caller strings bounded
nowhere. Two of those are already live failures: a ~260 KB `location` or `space` reaches a
`RecordFailure` that breaches 256 KiB on a `Pass` with **no `Catch`** — `States.DataLimitExceeded`,
thrown where nothing can catch it, so `NotifyFailure` never runs and a user whose request failed is
told nothing at all. After SPEC-228 puts the envelope on all eight, an unbounded `requestId`
reproduces that on every plane.

What exists of the chain today disagrees with itself. `archive-common` and `file-ops-common` compute
links one to three; `file-send-common` computes a **fourth** and allows the error 4 KB where the
service permits 32 KB of characters. So the fourth link is not unmeasured — it is measured once,
against a model an order of magnitude too small.

This spec bounds the fields, then measures. It lands **before** SPEC-228, which widens the fourth
link to the four planes that do not yet carry the envelope.

## Scope

### In Scope

- A declared bound on every caller-controlled field, derived from the contract rather than by
  tracing values through ASL and eight verbs.
- A declared worst-case request per enqueue route, built once and shared.
- Links one, two and four computed for every route that traverses a Pipe, subsuming the parts of
  three plane guards that disagree.
- `MAX_MESSAGE_BYTES` re-derived from the **Step Functions** limit, and the two plane caps the new
  derivation puts it below.
- Recording the three live overshoots where the guard lives, not only in a delivery doc.

### Out of Scope

- **Per-plane caps as the remedy for links one and two.** Every existing plane cap runs inside
  `validate-authorize`, so none can bound a link evaluated before the verb is invoked. They stay as
  bounds on what a verb will *do*. The asymmetry is stated deliberately: a verb-level bound **can**
  bound link four, because a `RecordFailure` key holds only what the verb returned or a seed
  literalled — which is why FR-001 admits `tableName`'s existing in-verb bound rather than reporting
  it as missing.
- **The trace.** SPEC-228 puts a pre-identity failure into the run's trace and is why the fourth
  link is about to widen. This spec bounds and measures; it adds the envelope to no state.
- **Messages already in flight.** A lowered cap bounds new messages only. What is queued or on a DLQ
  was accepted under the old cap and nothing here bounds it.
- **Treating the cap as a substitute for a pointer.** The Fences say everything unbounded travels by
  pointer and a cap is not a substitute; the remedy here is a cap, so the exception is argued rather
  than stepped around. The value SPEC-228 puts on the state is `$$.Execution.Input`, which Step
  Functions has already bounded by admitting the execution and which no pointer exists to, because
  nothing wrote it anywhere a verb could fetch it. The fence binds a value the system *chose* to put
  on a state. It does not generalise: FR-001 is what stops it, because every other field on that
  state must now declare a bound.

---

## Functional Requirements

### FR-001: Every caller-controlled field declares a bound

#### Description:

The chain cannot be measured while its inputs are unbounded, and most are. The bound is declared
**on the contract**, which is the only place the population is derivable: a template read cannot tell
a caller's value from a stamped one — archive's `RecordFailure` reads `$.mode`, which looks exactly
like `$.location` and is written by `_stamped_values`; table-builder's reads `$.space.database`,
which `validate-authorize` built. Resolving those needs data flow across ASL and eight verbs. Reading
the contract needs neither: **every declared string or list field on an enqueue request either
carries a byte bound or is a finding**, unconditionally, and that is strictly stronger, because it
catches a field before any template names it.

The mechanism has to be built, and this says so rather than implying it exists.
`contract.validate_request`'s `_matches` has no length node, and its vocabulary is closed and shared
with `scripts/generate_api_contract.py`, whose output is asserted equal to committed TypeScript. So
the bound is a **separate table beside the request types**, consumed by a validator pass after shape
validation — not a new node kind, which would drag the generator and the generated client into a
size concern that is not the client's.

The template side is checked from the other direction: every `RecordFailure` key must be a stamped
literal, an identity-block field, or a contract field that now has a bound. That is decidable by name
against three known sets, and it catches a plane naming something new.

#### Acceptance Criteria:

- [ ] Every string and list field on every enqueue request type has a declared bound, and the guard
      **derives the population from the request types** — a field added later with no bound fails.
- [ ] `requestId` is bounded on every route, `location` on data-quality and `space` on
      shared-spaces; each bound is sized from what the flow actually needs and its declaration names
      that as its budget, not a round number.
- [ ] A field already bounded inside `validate-authorize` and named only on a `RecordFailure`
      satisfies the rule — `tableName`'s `CATALOG_IDENTIFIER_RE` is the case — and the guard records
      **where** each bound lives, because a link-two bound and a link-four bound are not
      interchangeable.
- [ ] Every `RecordFailure` key across the eight templates resolves to a stamped literal, an
      identity-block field, or a bounded contract field; anything else fails, naming plane and key.
- [ ] The rule is **mutation-tested in both directions**: add an unbounded field to a request type
      and the guard reddens; add an unresolvable key to a template's `RecordFailure` and it reddens
      with a *different* message. Assert the messages, so one plant cannot satisfy both checks.
- [ ] An over-long field is refused at the API with `PayloadTooLarge` carrying `ErrorParams.limit`,
      so the caller is told which bound and what it is — the existing whole-body refusal sends no
      limit, and "the request is too large" is the wrong sentence for one bad field.

### FR-002: Every enqueue route has a declared worst-case request, in one place

#### Description:

With FR-001's bounds in place a worst case exists for every route. It is declared once, by a shared
factory, so the guard's inputs are visible in one place and a contract that grows a field fails to
build its worst case rather than silently shrinking it. Archive's, file-send's and file-ops' worst
cases exist today as three hand-built literals inside three plane tests, which is where the
disagreement between them started.

**Three counts, all easy to get wrong and two of which an earlier draft of this spec did get wrong.**
`contract.ROUTES` holds 34 routes, of which **11** are `EnqueueRoute`. Of those eleven, **ten**
traverse a Pipe and a state machine — `notifications.enqueue` drives a Lambda directly and there are
exactly eight `pipe.tf` files — so links two and four apply to ten, not eleven. And **three** planes
have a request byte cap, leaving five planes and seven routes with none.

#### Acceptance Criteria:

- [ ] Coverage is asserted as **set equality against `contract.ENQUEUE_ROUTES`'s ids** — the derived
      tuple already exists, so nothing re-derives it — not a count, which a substitution satisfies,
      and not against `ROUTES` whole, which holds 34.
- [ ] The subset that traverses a Pipe is derived from the presence of a `pipe.tf`, not listed, so
      `notifications.enqueue` is excluded by rule and a ninth pipe would be included by rule.
- [ ] Where a plane enforces a byte cap in `validate-authorize`, the worst case is built **at** that
      cap, with the constant read from the plane's config.
- [ ] Where a route has none, the worst case is built at **FR-001's field bounds** — not "the largest
      body the fleet cap admits", which would make FR-004's check `X ≤ X` on seven of eleven routes.
- [ ] The fill is the **escape-worst character**: two bodies of equal serialized length escape to
      records differing by nearly 2×, so a factory filling with `k` would build a record half the
      real worst case and every link-two assertion over it would pass vacuously. Pinned, with the
      measurement beside it.
- [ ] The factory's defaults are mutation-tested — a field hard-coded small where its bound permits
      large is this shape's blind spot.

### FR-003: One guard, three links, every piped route, one model

#### Description:

Three plane guards compute overlapping parts of this chain and disagree about the fourth link. Links
one, two and four move into one fleet guard over the ten piped routes. **Link three stays
per-plane**: it models what a verb *returns*, file-ops' real model carries one outcome record per
item, and a generic version would be strictly weaker than the three that exist.

**Two modelling choices are pinned; the third was pinned wrongly in an earlier draft and is corrected
here.**

1. **The record is the realistic Pipes SQS record** — `messageId`, `receiptHandle`, the FIFO
   `attributes` block, `md5OfBody`, `eventSourceARN` and the rest — not the 64-byte stub archive's
   test uses. All eight pipes are `batch_size = 1` with no `input_template`, so that is what
   production sends.
2. **Escaping is measured by serializing**, never modelled with a factor. The worst case for a
   `json.dumps` body re-embedded as a JSON string is exactly 2.0 — a run of quotes or backslashes —
   and nothing beats it, because `json.dumps` emits no control character or non-ASCII byte raw.
3. **The `Cause` is reserved at 65,536 bytes.** 32,768 is not a Step Functions state quota — the
   service quota page carries only the 256 KiB input/output row. It is a **maximum length in
   characters** on the execution-history event shapes, and a `Cause` is a JSON document sitting
   inside a JSON string on the state, so it is escaped there like everything else. Reserving it
   unescaped exempts the one value in the model most certainly escaped, which is what choice 2
   forbids. Worst case is 2 × 32,768.

That correction is what puts the derived cap below two plane caps, and FR-004 owns the consequence.
It is written down because the temptation to reach for the smaller reservation will recur, and its
only support was that it made the arithmetic comfortable.

#### Acceptance Criteria:

- [ ] Links one, two and four are computed for all ten piped routes in one fleet guard against one
      `256 * 1024` constant, with the three models above.
- [ ] Link four is `RecordFailure` **as each template actually builds it**, parsed from the template,
      so a plane naming a new field is included without anyone remembering to.
- [ ] The **escape ratio and bytes-per-character of a real captured Lambda `Cause`** are measured and
      asserted, because that is the falsifiable part — a captured `Cause` runs to a couple of
      thousand characters and passes a 32 KiB, 36 KiB or 66 KiB reservation identically, so asserting
      one fits proves nothing about the model.
- [ ] Three assertions that exist today survive the strip, named individually because a general guard
      does not imply them: file-send's **counterfactual tripwire** (that carrying the selection
      *beside* the envelope would exceed the limit — the arithmetic SPEC-228's own
      `test_no_failure_seed_carries_the_selection_twice` rests on), file-send's **positive control**
      on the record model, and file-ops' two-caps-bind-different-cases test.
- [ ] Each plane guard's assertions are listed before and after, and the list is in the PR — this FR
      does not get to assert that nothing was lost; it has to show it.
- [ ] The guard is mutation-tested **on the derivation**: set the cap to the three-link value and
      link four breaches by a stated margin. Deleting an assertion proves nothing, because a removed
      assertion never reddens.
- [ ] The four other `256 * 1024` literals in the tree are either read from the new constant or
      deliberately left, with the reason, in one line — a fleet constant with four private copies is
      the rule-written-twice failure.

### FR-004: `MAX_MESSAGE_BYTES` is measured against the limit that binds, and two plane caps follow it down

#### Description:

`MAX_MESSAGE_BYTES` is `SQS_MAX_MESSAGE_BYTES - MAX_IDENTITY_BLOCK_BYTES` — the SQS limit less the
block the sender adds. Wrong in kind: SQS accepting a message says nothing about Step Functions
starting an execution with it. It is re-derived as the largest body whose worst-case escaped record,
plus the `Cause` reservation, plus **the largest plane's `RecordFailure` literals**, fits 256 KiB.
That third term is not a rounding error and is easy to drop; without it the fleet cap and FR-003's
per-plane link four disagree by kilobytes.

Under FR-003's corrected reservation the derived cap lands **below archive's and file-send's worst
legal requests**, so those two plane caps come down with it. Measured on the branch, with the
headroom below and the corrected units, that is **96 KiB to 89 KiB for archive (−7.3%) and 96 KiB
to 84 KiB for file-send (−12.5%)** — larger than the 1.8% and 5.3% this spec first estimated,
because those were the zero-headroom answer to a model that also counted a recipient list as one
recipient. That is decided here rather than escalated: it is a few dozen object keys per request, the
alternative is a reservation chosen because it was comfortable, and a cap that is too generous fails
in the direction where a user hears nothing about a request that failed.

The cap keeps **headroom** rather than sitting at the measurement, because SPEC-228 is the next
addition and is already written — a budget pinned exactly at today's number leaves the next
legitimate change nothing to spend and makes the gate cause the damage it exists to prevent.

`MAX_IDENTITY_BLOCK_BYTES` **stays**. It is not a term of nothing: the test this FR rewrites asserts
the largest identity block fits inside it, and the reservation is deliberate on the safe side.

#### Acceptance Criteria:

- [ ] `MAX_MESSAGE_BYTES` is computed from the state limit, the `Cause` reservation, the measured
      escaping **and the largest plane's `RecordFailure` literals**, with stated headroom and the
      headroom's reason where the constant lives.
- [ ] The derivation lives in **production code**, not in a test the module mirrors — an `X == X`
      assertion proves nothing. `cpcommon.config` is the home: `apicommon` already imports `cpcommon`
      and `cpcommon` imports nothing back, so the state limit and the `Cause` reservation become
      named constants there and `enqueue.py` reads them. `errors.py` narrates the two facts today and
      keeps the narration, pointing at the constants.
- [ ] `SQS_MAX_MESSAGE_BYTES` stays as the queue's own ceiling and the effective cap is the lower of
      the two, with a line saying the SQS arm is currently unreachable so nobody later reads its
      passing as evidence it fires.
- [ ] `ARCHIVE_MAX_ITEM_BYTES` and `SEND_MAX_ITEM_BYTES` are lowered to what the new cap admits, each
      naming the chain as its budget, and the SPA's mirrored copies move with them — the browser
      mirrors the item caps even though it does not mirror `MAX_MESSAGE_BYTES`.
- [ ] Every route's worst legal request passes `_refuse_if_oversized` at the new cap, asserted per
      route against FR-002's factory.
- [ ] `test_the_size_cap_is_derived_from_what_the_queue_takes_and_what_is_stamped_on` is rewritten —
      it asserts the old derivation and narrates it — and its identity-block assertion is kept.
- [ ] The three live overshoots are asserted as **characterisations against the old constants**, so
      the suite carries the reason the caps moved: a body at the old cap producing a record over the
      limit, and data-quality's and shared-spaces' failure states breaching with nothing added to
      them.
- [ ] The register entry names the cap's new budget and the two plane caps that moved, and the
      Fences clause on caps is checked against what shipped rather than assumed to still hold.

---

## Data Model

```ts
// The declared bound for one caller-controlled field. FR-001's table, beside the request types.
type FieldBound = {
  routeId: string;            // one of the eleven EnqueueRoute ids
  path: string;               // a declared string or list field, dotted, `[]` for a list element
  maxBytes: number | null;    // null for a verb bound, whose number lives in the plane
  enforcedAt: "api" | "verb"; // a verb bound covers link four only; link two needs the API
  owner: string;              // where a verb bound's number lives, as module.CONSTANT
  measured: "wire" | "value" | "items";  // WHICH question the number answers
  budget: string;             // the sentence naming what sized it — FR-001's second criterion
};

// One route's worst case, built by the shared factory from those bounds.
type WorstCaseRequest = {
  routeId: string;
  body: string;               // serialized at the route's bounds, at each fill in the sweep
};

// The links this guard owns. Link three stays with the three plane guards.
type ChainLinks = {
  body: number;               // link 1 — the caller's serialized body
  record: number;             // link 2 — the realistic Pipes SQS record, body escaped into it
  recordFailure: number;      // link 4 — link 2, plus the Cause reservation, plus plane literals
};
```

## Environment Variables

None.

## File & Folder Structure

```
lambdas/api/apicommon/bounds.py                     # NEW — FR-001's field bounds and its validator pass
lambdas/api/router.py                               # the pass wired in after shape validation
lambdas/api/apicommon/contract.py                   # ErrorParams already carries the limit
apps/portal/src/lib/errorMessages.ts                # the limit rendered rather than dropped
lambdas/api/apicommon/enqueue.py                    # MAX_MESSAGE_BYTES re-derived and re-budgeted
lambdas/api/test_enqueue_routes.py                  # the old derivation's test rewritten
lambdas/test_request_size_chain.py                  # NEW — links 1/2/4, the ten piped routes
lambdas/control-plane-common/cpcommon/config.py     # STATE_PAYLOAD_LIMIT_BYTES, CAUSE_RESERVATION_BYTES
lambdas/control-plane-common/cpcommon/errors.py     # narration re-pointed at the constants
lambdas/archive-common/arcommon/config.py           # ARCHIVE_MAX_ITEM_BYTES lowered
lambdas/file-send-common/fscommon/config.py         # SEND_MAX_ITEM_BYTES lowered
lambdas/archive-common/test_config_arcommon.py      # keeps link three, loses 1/2
lambdas/file-send-common/test_config_fscommon.py    # keeps link three, tripwire, positive control
lambdas/file-ops-common/test_config_focommon.py     # keeps link three and its two-caps test
apps/portal/src/features/{archive,file-send}/*.service.ts  # the mirrored item caps
```

## Implementation Phases

### Phase 1: The bounds

- Build the field-bounds table and its validator pass; bound `requestId`, `location` and `space`.
- Write the derived guard over the request types and the `RecordFailure` key resolution, and
  mutation-test both directions.

### Phase 2: The worst cases

- Build the factory from those bounds, set-equal to the `EnqueueRoute` ids, the piped subset derived
  from `pipe.tf`, filled with the escape-worst character.
- Mutation-test its defaults.

### Phase 3: The chain

- Move the state limit and `Cause` reservation into `cpcommon.config`; measure a captured `Cause`'s
  escape ratio and assert the reservation against it.
- Write the fleet guard for links one, two and four; strip those from the three plane guards,
  carrying the tripwire, the positive control and the two-caps test across, and list every assertion
  before and after in the PR.
- Mutation-test the derivation.

### Phase 4: The caps

- Re-derive `MAX_MESSAGE_BYTES` in production code with headroom; lower `ARCHIVE_MAX_ITEM_BYTES` and
  `SEND_MAX_ITEM_BYTES` and their SPA mirrors; rewrite the old derivation's test keeping its
  identity-block assertion.
- Characterise all three overshoots against the old constants, and write the register entry.
