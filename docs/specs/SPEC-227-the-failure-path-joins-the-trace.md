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
- Correcting the archive comments that claim a cross-check that does not exist, and a gate so no
  comment in this repo can name a test that does not exist.

### Out of Scope

- **Writing the missing cap-and-timeout guards.** The gate in FR-004 finds seventeen citations in
  live source naming tests that were never written — `arcommon/config.py` alone claims three that
  compute cap chains against `infra/modules/archive/locals.tf` and "fail the build", and none
  exists. Those are memory and timeout budgets, not observability, and establishing whether each
  guard is missing or merely renamed is investigative work with its own risk. The gate lands with a
  **ratchet** at the measured level, exactly as `SPEC_OVERSIZE_MAX` does: a new false citation fails
  CI, the existing ones do not, and whoever pays one down lowers the constant in the same PR.
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

Recognition moves from the shape of a state's `error` field to its **position in the graph**: any
state whose forward walk reaches a failure terminal is a seed, whatever it looks like. That is the
property the guard is named for, and it cannot go stale as a plane adds a seed of a new shape.

#### Acceptance Criteria:

- [ ] The guard recognises all eight states above, plus the three it already recognises on archive,
      derived by walking each template's graph rather than from a list in the test.
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

- [ ] One sweep covers all eight planes, deriving the plane list by globbing the templates so a
      ninth is included automatically, with a positive control that it found a state on each.
- [ ] It asserts set equality between each field-naming state's reads and its producing verb's real
      return value, driving the verb rather than reading its source.
- [ ] Mutation-tested per plane in both directions: renaming a key in a verb's return must fail, and
      removing a key from a state's `Parameters` must fail, each naming the plane and the key.
- [ ] shared-spaces' conditionally-shaped validator return is handled explicitly — its optional keys
      are declared, not silently absorbed by a subset comparison.
- [ ] The three existing per-plane cross-checks are still present and green.

### FR-004: No comment in this repo names a test that does not exist

#### Description:

The archive machine's `Validated` and `ArchiveComplete` comments both say a `Pass` naming each key
"fails the build via `test_state_machine_archive.py`, which reads this block and the verb's real
return value and requires them to agree." That file holds seven tests, all graph-walk and
commit-gate checks, and no test in the repo reads any of those blocks. SPEC-225 was drafted leaning
on that claim, which is what a false comment costs: it is what a session reads *instead* of checking.

It is not one comment. A sweep during authoring, over tracked files with wrapped citations rejoined,
found **23 citations in live source** naming tests that do not exist and **21 in current-tier docs**
— across `arcommon/config.py`, `fscommon/config.py`, `tscommon/config.py`,
`infra/modules/archive/locals.tf`, `infra/modules/file-send/locals.tf`, both module READMEs, four
`decisions/` files and two plane pages. `arcommon/config.py` claims three tests that compute cap
chains against `locals.tf` and "fail the build"; none exists, and the one real guard of that shape —
`test_the_copy_timeout_constant_matches_the_deployed_verb` — is hard-coded to table-share.

The archive comments are corrected here because this spec's own subject is the cross-check they
claim. The rest are held by a **gate**, not fixed here: a recurring class is closed structurally, and
a count ratchet at the measured level lets the existing ones be paid down deliberately.

#### Acceptance Criteria:

- [ ] Both archive comments state what actually holds them, naming FR-003's sweep.
- [ ] `scripts/validate_docs.py` gains a check that every `test_*` name cited in a tracked source
      file or current-tier doc resolves to a test that exists, excluding `docs/specs/` and
      `docs/spec-delivery/` by tier, with wrapped citations rejoined before matching.
- [ ] The check carries a **fixture corpus**, not a run against this repo's own docs: one case per
      construct — a resolving citation, a non-existent one, a wrapped one, a citation inside an
      excluded tier — each asserting the specific failure text, and cases asserting silence.
      Running the gate over the repo proves the repo passes, not that the gate works.
- [ ] The ratchet constant is set to the measured count with its derivation recorded beside it, and
      a new false citation fails CI.
- [ ] The gate is mutation-tested: each of its checks is broken once and must redden.

---

## Implementation Phases

### Phase 1: The guard, before anything is threaded through it

- Widen failure-seed recognition to a graph walk; positive control; the reviewer's plant as a test.

### Phase 2: The failure path

- The traceparent into every seed and `RecordFailure`; `$$.Execution.Input` for the pre-identity
  seeds; driven failure runs on archive and file-ops.

### Phase 3: The cross-check and the citation gate

- The eight-plane set-equality sweep, mutation-tested per plane in both directions.
- The archive comments; the `validate_docs.py` citation check with its fixture corpus and ratchet.
- Full local gates green by exit code.
