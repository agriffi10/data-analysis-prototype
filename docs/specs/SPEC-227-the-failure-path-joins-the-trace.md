# Spec: The Failure Path Joins the Trace, and the Cross-Check Nobody Wrote

**ID:** SPEC-227
**Status:** Draft
**Last Updated:** 2026-09-08
**Depends On:** SPEC-225

## Overview

SPEC-225 puts a run's success path into one trace. The failure path is left out, and it is the half
worth having: the invocation whose trace an operator actually goes looking for is the one that
raised. This spec finishes the job.

It is a separate spec because threading the failure path is **not** the same shape of work. Every
plane reshapes its state into a failure seed before `RecordFailure` and `NotifyFailure`, and the
guard that is supposed to keep a seed and its terminal in agreement —
`test_a_failure_seed_supplies_every_key_the_failure_terminal_reads` — identifies a seed
*structurally*, by `Parameters["error.$"] in ("$", "$.error")`. Eight states across the fleet
replace the whole state with a literal `error` object and hand control to a field-naming
`RecordFailure`, so the guard never treats them as seeds and never walks them.

**That was proved, not reasoned about.** A reviewer added the traceparent to archive's
`RecordFailure` and to the two seeds the guard recognises — the obvious edit — and the suite stayed
green: the failure-seed tests, the whole file, and every archive state-machine test. Six archive
failure paths would then have hit an absent `$.traceparent` inside a `Pass`, which is a
`States.Runtime` error that is **neither retriable nor catchable**, killing the execution *before*
`NotifyFailure` runs. A user whose archive failed would have been told nothing at all, and no test
in the repo would have objected.

So the guard is widened before anything is threaded through it. And once that is being done, the
adjacent gap is worth closing in the same spec: **five of the eight planes have no ASL↔verb
cross-check at all**, and the archive machine says in its own comments that it does.

## Scope

### In Scope

- Widening the failure-seed guard so it can see every state that feeds a failure terminal.
- Threading the traceparent along the failure path, including the seeds that carry literals.
- One cross-check, over all eight planes, holding a field-naming state and its verb's real return
  value to agreement — in **both** directions.
- Correcting the two archive comments that claim a cross-check that does not exist.

### Out of Scope

- **The false test citations, and the gate that would police them — both.** A sweep during
  authoring found **23 citations in live source** and **21 in current-tier docs** naming tests that
  do not exist; `arcommon/config.py` alone carries seven, and every one of them points into a
  single file. They have **one root cause**, verified
  here rather than inferred: `a41bda69` (#540, "Cut the test suites to how a caller drives the
  code") deleted **53 test files** — `lambdas/archive-common/test_config_arcommon.py` among them,
  which held six of `arcommon/config.py`'s seven cited guards and *is* the seventh — and left every
  citation standing. It is one sweep's
  collateral damage, not scattered rot, and every cited guard is **recoverable** from `a41bda69^` — all 21, confirmed
  by the arc that owns the paydown after it recovered and ran the deleted files against the current
  tree.

  A separate arc is paying this down, and the **citation gate belongs to that arc, not this one** —
  the gate is what verifies its own paydown is complete, and building it there lets each paydown PR
  lower the ratchet. Its glob will need to reach beyond `.py`/`.tf`/`.tftpl`:
  `apps/portal/src/features/table-share/TableShareDialog.tsx` cites a Python test name that #540
  also deleted.
- **The success path.** SPEC-225.
- **`docs/specs/` and `docs/spec-delivery/`.** They are history and legitimately cite tests that
  were later deleted — `test_deploy_matrix.py`, retired by SPEC-214, accounts for much of it. The
  gate excludes them by tier.

---

## Functional Requirements

### FR-001: The failure-seed guard can see every state that feeds a failure terminal

#### Description:

`test_a_failure_seed_supplies_every_key_the_failure_terminal_reads` walks forward from each state it
recognises as a seed and requires every downstream `Pass`'s `$.x` reads to be supplied. Its
recognition test is `Parameters["error.$"] in ("$", "$.error")`, which misses every state that
replaces the state with a literal `error` object instead of forwarding one.

The eight it cannot see: archive's `RollbackReturnedSeed`, `NothingToArchiveSeed`,
`RestoreIncompleteReturnedSeed`, `RestoreTimedOutSeed`, `NothingToRestoreSeed` and
`UnknownModeSeed`; file-ops' `GiveUpFailureSeed`; results-conversion's `ConvertRefusedSeed`.

Recognition gains a second test based on a state's **position in the graph**, and the exact
predicate matters — three plausible readings were built and two are wrong:

- *"can reach a failure terminal"* is **unsatisfiable**: every Task with a `Catch` can, so it
  selects almost everything. Measured at **349 violations** across the eight templates.
- The predicate that works is *"**every** reachable terminal is a `Fail`"*, with a terminal
  identified structurally as a `Fail` state rather than by a name like `*NotifyFailure*` — a name
  test is what this FR is moving away from.
- A selected state must also have **no `ResultPath`**. A merging `Pass` does not replace the state,
  so "the seed supplies everything downstream reads" is false for it; without this discriminator
  four states are selected and produce **seven findings that are not defects**.

**The graph test is added to the structural one, not substituted for it.** Measured: the graph half
alone **loses three seeds** — `file-send/GuardRecipients/RecipientFaulted`,
`table-share/GuardRecipients/RecipientRefused`, `table-share/FinishRecipients/RecipientFailed` —
because they live in `ItemProcessor` containers that hold no `Fail` state at all, a branch failure
propagating to the parent Map's `Catch`, which is not a walkable state. Obeying "recognition moves
to the graph" literally trades eight gained seeds for three lost ones.

**A latent bug in the existing guard has to be fixed for any of this to mean anything.** It
flattens nested states to qualified keys (`GuardRecipients/RecipientFaulted`) while `Next` names
siblings unqualified, so **every nested walk dead-ends on its first hop and asserts nothing today**.
The walk runs per container.

#### Acceptance Criteria:

- [ ] The guard recognises all eight states above, plus the three it already recognises on archive,
      **and the three nested ones the graph half alone would lose**, by taking the union of the two
      recognitions rather than replacing one with the other.
- [ ] The nested walk runs per container and is asserted to traverse more than one hop, so the
      dead-ending bug cannot return unnoticed.
- [ ] Violations are collected and asserted once, so a red run names every seed missing the key
      rather than the first.
- [ ] The guard carries a positive control asserting it found seeds on every plane that has one, so
      a recognition change that quietly matches nothing cannot pass.
- [ ] **Mutation-tested with the plant that exposed this**: add a key to archive's `RecordFailure`
      and to only the two seeds the old guard recognised. The widened guard must fail, and its
      message must name the seed states that do not supply it. This exact edit passes today.
- [ ] Every plane's existing state-machine tests stay green by exit code.

### FR-002: The failure path carries the traceparent

#### Description:

With FR-001's guard in place, the traceparent is added to every failure seed and to every
`RecordFailure`, so a failed run's terminal and its notification sit in the run's trace.

**Two seeds cannot read `$.traceparent` and must not be written as though they can.** Archive's
`ValidateFailureSeed` is the pre-identity catch: it replaces the state with literal
`requestId`/`mode`/`actor` values because at that point the validated state does not exist. Reading
`$.traceparent` there is the `States.Runtime` failure this spec exists to avoid. It reads
`$$.Execution.Input` instead — the raw Pipe envelope, which is where the traceparent arrived — and
the same shape exists on every plane, so each plane's pre-identity seed is treated the same way.

#### Acceptance Criteria:

- [ ] Every failure seed and every `RecordFailure` on all eight planes names `traceparent`.
- [ ] Each pre-identity seed reads it from `$$.Execution.Input`, not from `$`, and a test asserts
      that no seed unreachable from a validated state reads `$.traceparent`.
- [ ] A failure run is driven end to end on archive and on file-ops, and every span — including
      `notify-failure`'s — carries the run's `trace_id`.
- [ ] The `notify-failure` verb still receives every field it reads; FR-001's guard is green.

### FR-003: One cross-check, over all eight planes, in both directions

#### Description:

Three planes have an ASL↔verb cross-check: results-conversion has three **set-equality** checks
against the driven handler, file-send has a **subset** check, and file-ops has a subset check that
scrapes the whole template — and that one lives in
`lambdas/file-ops-validate-authorize/test_file_ops_validate_authorize.py`, not in the plane's
state-machine test file, which is where a reader looks for it. Archive, data-quality, shared-spaces,
table-builder and table-share have none.

**Direction matters, and the subset form is the wrong one for this.** `reads ⊆ returns` catches a
state reading a key its verb does not return — a `States.Runtime` at execution. It cannot catch a
verb returning a key the state **drops**, which is silent, and which is precisely the traceparent
failure. One sweep, set-equality, asserting both.

The three existing per-plane checks stay. They are narrower in one direction and wider in another —
file-ops' scrapes `Variable` paths the sweep does not — and deleting a working guard because a new
one overlaps it is how coverage is lost quietly.

#### Acceptance Criteria:

- [ ] The sweep covers every plane that **has** a Task-to-replacing-`Pass` pair, deriving the list
      by globbing rather than naming planes. **shared-spaces and table-share have none** —
      `Validate → Route` is a Choice and `ValidateAuthorize → InspectSource` is Task-to-Task — so the
      sweep must report them as "nothing to check" explicitly rather than passing silently over two
      planes, which is how a population claim rots.
- [ ] Set equality is asserted only where it is meaningful. `file-ops/ReleaseLockOnFailure` has
      `ResultPath: null` (the result is discarded, so the next `Pass` reads the incoming state) and
      `table-builder/ReleaseRefreshLock` nests its return under `$.released`; equality against the
      verb's return is meaningless for both, and they are excluded by rule with the rule asserted.
- [ ] The "producing verb" is derived from the graph, not assumed to be the validator: file-ops' and
      table-builder's field-naming states are produced by *release-lock*, data-quality's by
      *drop-temp-tables*.
- [ ] It asserts set equality between each field-naming state's reads and its producing verb's real
      return value, driving the verb rather than reading its source. **Driving all eight validators
      to a success return needs eight bespoke request fixtures and eight fake installations that do
      not exist** — `shared-space-common/fakes.py` is the only shared one in the tree and is
      plane-specific; driven with a generic envelope every validator refuses with a domain terminal
      before touching AWS. Building those fixtures is part of this FR, and if a plane's cannot be
      built its exclusion is recorded rather than left as a silently skipped case.
- [ ] Mutation-tested per plane in both directions: renaming a key in a verb's return must fail, and
      removing a key from a state's `Parameters` must fail, each naming the plane and the key.
- [ ] shared-spaces' conditionally-shaped validator return is handled explicitly — its optional keys
      are declared, not silently absorbed by a subset comparison.
- [ ] The three existing per-plane cross-checks are still present and green.
- [ ] **Both archive comments state what actually holds them**, naming this sweep. They currently
      cite `test_state_machine_archive.py` as reading the `Validated` and `ArchiveComplete` blocks
      against the verb's real return value; that file holds seven tests and none of them does. The
      correction belongs to this FR because the sweep is the thing that finally makes the claim
      true — for all eight planes rather than the one the comment spoke for.


## Implementation Phases

### Phase 1: The guard, before anything is threaded through it

- Widen failure-seed recognition to a graph walk; positive control; the reviewer's plant as a test.

### Phase 2: The failure path

- The traceparent into every seed and `RecordFailure`; `$$.Execution.Input` for the pre-identity
  seeds; driven failure runs on archive and file-ops.

### Phase 3: The cross-check

- The eight-plane set-equality sweep, mutation-tested per plane in both directions.
- The two archive comments, corrected to name it.
- Full local gates green by exit code.
