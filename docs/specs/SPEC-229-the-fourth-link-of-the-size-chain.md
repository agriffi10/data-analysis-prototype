# Spec: The Fourth Link of the Size Chain, and the Cap That Is Measured Against the Wrong Limit

**ID:** SPEC-229
**Status:** Draft
**Last Updated:** 2026-09-09
**Depends On:** None

## Overview

A request travels a chain of four representations, each of which Step Functions caps at 256 KiB:
the caller's body; the Pipe's record, which carries that body as an **escaped** JSON string and is
what `StartExecution` receives; the validated state a verb returns; and — on a failure — the
`RecordFailure` state, which is the Pipe's record again plus an error object whose `Cause` Step
Functions permits up to 32 KB.

`archive-common` computes the first three and says in its own docstring why: file-send once shipped
a cap measured against the last link alone, "which would have permitted a request whose execution
could not start at all." **Nothing computes the fourth**, and four planes carry it in production
today.

The chain is bounded in exactly one place, and it is not where it looks. The API's
`MAX_MESSAGE_BYTES` is the only check upstream of `StartExecution` — the eleven enqueue handlers are
one factory with no per-route size validation — and it is derived from the **SQS** message limit,
which is the wrong budget: it bounds what the queue accepts, not what the execution can carry. Every
per-plane cap that looks like it bounds this (`ARCHIVE_MAX_ITEM_BYTES`, `SEND_MAX_ITEM_BYTES`,
`FILE_OPS_MAX_SELECTION_BYTES`) is enforced **inside** `validate-authorize` — that is, inside the
execution being bounded — so the request that overflows the chain is precisely the one those caps
would refuse, arriving before any of them can run.

The consequence is measurable and live: at today's cap a body of 261,632 bytes serialises into a
Pipe record over the 256 KiB limit — 523,340 bytes at worst-case escaping — so the API accepts
requests whose execution cannot start, and, in the band that does start, whose `RecordFailure` can
exceed the limit and raise `States.DataLimitExceeded` **outside every Catch**, killing the execution
before `NotifyFailure`. A user whose request failed is then told nothing at all.

This spec computes the fourth link, gives `MAX_MESSAGE_BYTES` the budget that actually sizes it, and
lands **before** SPEC-228, which widens the fourth link to the other four planes.

## Scope

### In Scope

- A declared worst-case request for every enqueue route, in one place, since five planes have no
  request cap of any kind and no worst case anyone has written down.
- The fourth link added to the size chain, computed for every route rather than for archive alone.
- `MAX_MESSAGE_BYTES` derived from the **Step Functions** limit instead of the SQS one, and lowered
  to what the chain permits.
- Recording the pre-existing overshoot where the guard lives, not only in a delivery doc.

### Out of Scope

- **Per-plane caps as the remedy.** Measured and rejected rather than assumed: every existing
  per-plane cap runs inside `validate-authorize`, so none of them can bound a link that is evaluated
  before the verb is invoked. Lowering one changes a guard's arithmetic and nothing in production.
- **Refusing anything a plane's own contract permits.** The fleet-wide cap this spec lands is above
  every plane's worst legal request — archive's, at its own 96 KiB item cap, serialises to roughly
  100 KB against a fleet cap near 114 KB — so no request that a plane would have accepted becomes a
  `PayloadTooLarge`. If the computed cap ever falls below a plane's own worst case, that is a
  conflict between two caps and it is escalated, not silently resolved by lowering the plane's.
- **The trace.** SPEC-228 is what puts a pre-identity failure into the run's trace, and it is the
  reason the fourth link is about to widen. This spec bounds; it adds no `raw` to any state.
- **The DLQ drain and messages already in flight.** A lowered cap bounds new messages only. What is
  already queued was accepted under the old cap and is bounded by nothing this spec adds.

---

## Functional Requirements

### FR-001: Every enqueue route has a declared worst-case request, in one place

#### Description:

The chain cannot be computed without an input, and for most routes no input exists: five planes have
no request byte cap at all, and their contracts are bare `TypedDict`s with unbounded `list` fields
(`recipients`, `partitionKeys`, `payload`) and unbounded strings (`location`). Archive's worst case
exists only as a literal hand-built inside its own chain test.

Each enqueue route gets one declared worst-case request — the largest body the route's contract and
its plane's own validation permit — built by a shared factory rather than copied per test, so the
guard's inputs are visible in one place and a contract that grows a field fails to build its worst
case rather than silently shrinking it.

**Routes, not planes.** There are ten: archive carries `archive.archive` and `archive.restore`, and
table-builder carries `tableBuild.create` and `tableBuild.refresh`, and the two members of each pair
do not have the same worst case.

#### Acceptance Criteria:

- [ ] Every enqueue route in the contract has a declared worst-case body, derived from the route's
      declaration rather than listed — a route added to `contract.py` without one fails the guard.
- [ ] Ten routes are covered, asserted as a count against the contract's own route table so a
      shortened enumeration fails rather than passing vacuously.
- [ ] Where a plane enforces a byte cap inside `validate-authorize`, the worst case is built **at**
      that cap and the constant is read from the plane's config, not restated.
- [ ] Where a plane enforces no cap, the worst case is the largest body the route's own field types
      admit under the fleet cap, and the guard says in one line that this is the reason the number is
      what it is.
- [ ] The factory's own defaults are mutation-tested: a field hard-coded to a small value where the
      contract permits a large one is the blind spot this shape has, so change one and watch the
      bound move.

### FR-002: The chain gains its fourth link, over every route

#### Description:

`test_the_byte_cap_survives_every_link_of_the_chain_it_bounds` computes three links for archive.
This adds the fourth — the Pipe's record plus a full 32 KB `Cause` plus the plane's `RecordFailure`
literals — and generalises all four links from one plane to every route.

The escaping is **measured by serializing**, never modelled with a factor: a quote-dense body
doubles and a sparse one barely grows, and the docstring on the existing guard already says why that
distinction is not a rounding error.

The guard moves out of one plane's config test. It spans every plane's ASL and every route's
contract, so it belongs with the fleet guards rather than in `archive-common`, whose `sys.path`
insert is deliberate and does not reach `shared-space-common` or `data-quality-common`.

#### Acceptance Criteria:

- [ ] All four links are computed for all ten routes against one `256 * 1024` constant, and archive's
      existing three-link assertions are subsumed rather than duplicated — the old test is replaced
      by its general form, not left beside it.
- [ ] Link four is `RecordFailure` as the ASL actually builds it, read from each plane's template
      rather than modelled, plus a `Cause` at the 32 KB ceiling `cpcommon.errors` documents.
- [ ] The guard is **mutation-tested against the link it adds**: restoring the three-link model
      reddens it. Name the plant, and assert on the failure message so the three older links cannot
      satisfy it.
- [ ] A route whose worst case fails any link names **which** link in the failure message, because
      the remedy differs per link — link two is a cap question and link four is a `Cause` question.

### FR-003: `MAX_MESSAGE_BYTES` is measured against the limit that actually binds

#### Description:

`MAX_MESSAGE_BYTES` is `SQS_MAX_MESSAGE_BYTES - MAX_IDENTITY_BLOCK_BYTES` — the SQS service limit
less the block the sender adds. That budget is wrong in kind: SQS accepting a message says nothing
about Step Functions being able to start an execution with it, and the gap between the two is the
escaping the Pipe applies.

The constant is re-derived from the chain: the largest body whose worst-case escaped record, plus a
32 KB `Cause`, plus a `RecordFailure` block, fits 256 KiB. Its docstring stops naming the SQS limit
as its budget and names this one, in the shape the register's Fences already require — a cap is
computed by a test against the budget that sized it, and it names that budget.

The pre-existing overshoot is recorded **where the guard lives** rather than only in a delivery doc:
before this spec the API accepted a body whose escaped record exceeded the limit outright, and that
is the defect the new derivation closes.

#### Acceptance Criteria:

- [ ] `MAX_MESSAGE_BYTES` is computed from `_STATE_PAYLOAD_LIMIT`, the `Cause` ceiling and the
      measured escaping, not from `SQS_MAX_MESSAGE_BYTES`; a test computes it and the module reads
      the same derivation, so the two cannot drift.
- [ ] `SQS_MAX_MESSAGE_BYTES` remains as a **second** ceiling the value must also respect — the queue
      still has its own limit — and the test asserts the effective cap is the lower of the two.
- [ ] Every plane's worst legal request still passes `_refuse_if_oversized` at the new cap, asserted
      per route, so the change refuses nothing a plane's own contract permits.
- [ ] `PayloadTooLarge` is still what a caller gets, with the same code and shape — the boundary
      moves, the contract does not.
- [ ] The overshoot that existed before is asserted as a **characterisation**: a body at the OLD cap
      is shown to produce a record over the limit, so the reason the cap moved is in the suite and
      not only in prose.

---

## Data Model

```ts
// One route's worst case, built by the shared factory. The guard's only input.
type WorstCaseRequest = {
  routeId: string;            // e.g. "archive.archive" — ten of them
  body: string;               // serialized, at the route's own permitted maximum
  cappedBy: string | null;    // the plane constant that bounds it, or null where none exists
};

// The four links, all measured against 256 * 1024.
type ChainLinks = {
  body: number;               // link 1 — the caller's serialized body
  record: number;             // link 2 — the Pipe's record, body escaped into it
  validated: number;          // link 3 — the state validate-authorize returns
  recordFailure: number;      // link 4 — the record again, plus a 32 KB Cause, plus literals
};
```

## Environment Variables

None.

## File & Folder Structure

```
lambdas/test_request_size_chain.py        # NEW — the four links, all ten routes (fleet guard)
lambdas/api/apicommon/enqueue.py          # MAX_MESSAGE_BYTES re-derived, docstring re-budgeted
lambdas/archive-common/test_config_arcommon.py  # the three-link test subsumed and removed
```

## Implementation Phases

### Phase 1: The inputs

- Build the worst-case request factory, derived from the contract's route table.
- Mutation-test its defaults.

### Phase 2: The chain

- Generalise the four links to every route in the new fleet guard; subsume archive's three-link test.
- Mutation-test link four.

### Phase 3: The cap

- Re-derive `MAX_MESSAGE_BYTES` from the state limit, keeping the SQS limit as a second ceiling.
- Assert every plane's worst legal request still passes, and characterise the old overshoot.
