# Spec: The Failure Path Joins the Trace, and the Cross-Check Nobody Wrote

**ID:** SPEC-227
**Status:** Completed
**Last Updated:** 2026-09-09
**Depends On:** SPEC-225 — **for FR-002 and FR-003 only.** FR-001 is test-only over
failure-path states SPEC-225 never edited, and lands green against an unthreaded tree.

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

The **nine** it cannot see: archive's `RollbackReturnedSeed`, `NothingToArchiveSeed`,
`RestoreIncompleteReturnedSeed`, `RestoreTimedOutSeed`, `NothingToRestoreSeed` and
`UnknownModeSeed`; file-ops' `GiveUpFailureSeed`; results-conversion's `ConvertRefusedSeed`; and
**shared-spaces' `RefusedSeed`**, a replacing `Pass` with a literal `error` object, structurally
identical to `ConvertRefusedSeed`. (Authoring counted eight and missed the last; re-derived by
parsing all eight templates.)

Recognition gains a second test based on a state's **position in the graph**, and the exact
predicate matters — three plausible readings were built and two are wrong:

- *"can reach a failure terminal"* is **unsatisfiable**: every Task with a `Catch` can, so it
  selects almost everything. Authoring recorded 349 violations; that figure does not reproduce and
  the number is not the point. Re-measured with a per-container walk: **129 violations across 48
  selected `Pass` states**. Same conclusion, different arithmetic — state the predicate and your own
  measurement rather than carrying either number forward.
- The predicate that works is *"**every** reachable terminal is a `Fail`"*, with a terminal
  identified structurally rather than by a name like `*NotifyFailure*` — a name test is what this FR
  is moving away from. **"Terminal" means a state that hands control nowhere**, and the definition is
  load-bearing: read instead as *a `Succeed`/`Fail` state*, an `ItemProcessor` contains neither and
  `all([])` is `True`, so the graph half vacuously selects **35** states fleet-wide including success
  leaves such as `table-share/FinishRecipients/RecipientSucceeded`. **Two independent things prevent
  that and the guard keeps both, because either alone would make the other read as decorative**: the
  terminal definition, and a non-empty check on the terminal set. Measured — the type reading *with*
  the emptiness check gives 29, and the hands-control-nowhere reading gives 29 with or without it; 35
  needs both mistakes at once.
- A selected state must also have **no `ResultPath`**. A merging `Pass` does not replace the state,
  so "the seed supplies everything downstream reads" is false for it; without this discriminator
  four states are selected and produce **seven findings that are not defects**.

**The graph test is added to the structural one, not substituted for it.** Measured: the graph half
alone **loses three seeds** — `file-send/GuardRecipients/RecipientFaulted`,
`table-share/GuardRecipients/RecipientRefused`, `table-share/FinishRecipients/RecipientFailed` —
because they live in `ItemProcessor` containers that hold no `Fail` state at all, a branch failure
propagating to the parent Map's `Catch`, which is not a walkable state. Obeying "recognition moves
to the graph" literally trades nine gained seeds for three lost ones. Measured across the eight
templates: structural **23**, graph **29**, union **32**.

**A latent bug in the existing guard has to be fixed for any of this to mean anything.** It
flattens nested states to qualified keys (`GuardRecipients/RecipientFaulted`) while `Next` names
siblings unqualified, so **every nested walk dead-ends on its first hop and asserts nothing today**.
The walk runs per container.

#### Acceptance Criteria:

- [ ] The guard recognises all **nine** states above, plus the three it already recognises on
      archive, **and the three nested ones the graph half alone would lose**, by taking the union of
      the two recognitions rather than replacing one with the other. The population is **derived by
      parsing and pinned as a membership** — **32** `(plane, state)` pairs — so a discriminator that
      widened in one place and narrowed in another fails here rather than keeping the count.
- [ ] The nested walk runs per container and is asserted to traverse more than one hop, so the
      dead-ending bug cannot return unnoticed. **This cannot be asserted against a production
      template and is met with a synthetic fixture, said out loud:** all three nested seeds are
      `End: true` with no `Next`, so even with the per-container fix every nested walk still reaches
      **zero** states and fixing the bug buys no new assertion over the real fleet. The fixture
      asserts both halves — that the per-container walk finds a nested violation, and that the old
      flattened lookup finds none.
- [ ] Violations are collected and asserted once, so a red run names every seed missing the key
      rather than the first.
- [ ] The guard carries a positive control asserting it found seeds on every plane that has one, so
      a recognition change that quietly matches nothing cannot pass.
- [ ] **Mutation-tested with the plant that exposed this**: add a key to archive's `RecordFailure`
      and to only the two seeds the old guard recognised (`RequestFailureSeed` and
      `ValidateFailureSeed` — archive's third structural match is `RecordFailure` itself). The
      widened guard must fail, naming the **six** graph-only archive seeds that do not supply it,
      **and the old structural-only recognition must pass on the same plant**, so the test cannot go
      quiet if the plant stops landing.
- [ ] Every plane's existing state-machine tests stay green by exit code.

### FR-002: The failure path carries the traceparent

#### Description:

With FR-001's guard in place, the traceparent is added to every failure seed and to every
`RecordFailure`, so a failed run's terminal and its notification sit in the run's trace.

**The pre-identity seeds cannot read `$.traceparent`, and authoring's remedy for that is
impossible.** Each plane's `ValidateFailureSeed` is the pre-identity catch: the error **replaced**
the state (`"error.$": "$"`), so it supplies literal `requestId`/`mode`/`actor` values because the
validated state does not exist yet. Authoring said such a seed should read `$$.Execution.Input`
instead — "the raw Pipe envelope … and the same shape exists on every plane". Both halves are false,
verified rather than reasoned about:

1. **The value cannot be extracted in ASL.** No Pipe carries an `input_template` (checked: zero
   occurrences across the eight `infra/modules/*/pipe.tf`), so `$$.Execution.Input` is the raw SQS
   batch and the traceparent sits inside `[0].body`, a **JSON string**. Pulling a field out of it
   needs `States.StringToJson`, which `test_no_state_uses_a_throwing_intrinsic` forbids fleet-wide,
   for exactly the uncatchable `States.Runtime` this arc exists to avoid. Independently:
   `cpcommon.observability._shape_values` walked the event's top level, `BatchInput` and `request` —
   it never walked `raw`, so even a parsed envelope would not be adopted. **That second half was the
   repair rather than the reason, and SPEC-228 took it**: the extractor gained `raw` as a fifth
   shape and the envelope reaches it on the state, so nothing has to be parsed in ASL.
2. **"The same shape exists on every plane" is false — it exists on four.** `"raw.$":
   "$$.Execution.Input"` is carried by archive, file-ops, file-send and results-conversion. The other
   four planes' pre-identity seeds carry no envelope at all.

**Resolution: accept the limit.** A pre-identity seed supplies `traceparent` as a **literal
`null`**, exactly as it already supplies `requestId: null`. This is required rather than cosmetic:
`RecordFailure` reads `$.traceparent` unconditionally, and a seed that simply omitted the key would
raise the uncatchable `States.Runtime` on the failure path itself.
`cpcommon.observability._extract_traceparent` documents a null traceparent as normal and warns on
neither absent nor null, so the literal costs nothing at runtime.

**The known limit, recorded here, in the delivery doc and in the register entry — SUPERSEDED by
SPEC-228, which closed it:** a failure occurring before `validate-authorize` returns could not join
the run's trace, because the only place the value exists at that moment is inside a JSON string the
machine may not parse. That ASL reasoning stands. What it missed is that the value need not be read
in ASL at all: SPEC-228 carries the envelope to `RecordFailure` from `$$.Execution.Input` and
`notify-failure` parses it in Python, exactly as `validate-authorize` already did on the way in. The
class is also wider than "pre-identity" describes — every validate-authorize failure lands on that
seed, whether or not an actor was verified.

#### Acceptance Criteria:

- [ ] Every failure seed **on the run-level failure path** and every `RecordFailure`, on all eight
      planes, names `traceparent` — **29** states, derived rather than listed: 13 post-identity seeds
      read `$.traceparent`, 8 pre-identity seeds supply a literal `null`, and 8 `RecordFailure`
      states read `$.traceparent`.
- [ ] **The three nested seeds are excluded by rule, and the rule is asserted rather than the
      exclusion being silent.** `file-send/GuardRecipients/RecipientFaulted`,
      `table-share/GuardRecipients/RecipientRefused` and
      `table-share/FinishRecipients/RecipientFailed` are `End: true` inside an `ItemProcessor` and
      cannot reach `RecordFailure`; their output becomes one element of their Map's result array.
- [ ] **The two independent derivations of the failure-path population are asserted to agree.**
      SPEC-225's `_blocks_that_name_their_fields` already excludes exactly these 29 states by a
      completely different mechanism — its discriminator 3, `not _reaches_a_success_terminal` — and
      its docstring already says "29 of them, which SPEC-227 owns". Holding the two to each other is
      nearly free and it fences a discriminator that drifts in one place only.
- [ ] The pre-identity/post-identity split is **derived, not listed**: a seed whose
      `Parameters["error.$"]` is `"$"` had the error **replace** the whole state, so nothing from
      before the failure survives. A test asserts in **both** directions — every pre-identity seed
      supplies a literal `null`, and none reads `$.traceparent`.
- [ ] A failure run is driven end to end on archive and on file-ops, and every span — including
      `notify-failure`'s — carries the run's `trace_id`. **This is the largest single piece of new
      work in the spec and it is sized here rather than left to the build.**
      `test_one_run_one_trace.py` drives archive and file-send **success** paths only, imports no
      `*notify_failure` module, and mentions file-ops solely in a template scan — so archive needs a
      new failure drive and file-ops needs its first appearance in the harness at all. What makes it
      tractable: the **ASL door** into `ar_notify_failure.handler` and `fo_notify_failure.handler`
      needs **no AWS stubbing whatsoever** (only `notify.emit_notification`), because only the
      EventBridge door reaches a client; ready-made event fixtures already exist in each verb's own
      suite; the span sink is `lambdas/conftest.py`'s `captured_events`, whose readers drain
      log-foundry on every read. **One hole to plug:** that harness's `_apply`/`_resolve` strips
      `$.` only, and `"$$.Execution.Input"` also begins with `$`, so it resolves to `None`
      **silently** instead of tripping the loud assert beside it — building a seed's event through
      it would fabricate `raw: None` and the drive would prove nothing.
- [ ] The `notify-failure` verb still receives every field it reads; FR-001's guard is green.
- [ ] **No verb changes and no inert-then-live split.** Verified: all eight validators already
      return `traceparent`, so no state reads a key a verb must first return; and no
      `notify-failure` handler holds a strict envelope check — each reads its fields with `.get()` —
      so the added key is additive. The two deploy workflows can therefore race harmlessly here.
- [ ] Every edited template passes `aws stepfunctions validate-state-machine-definition`.
- [ ] **The premise FR-002 rests on is stated as the invariant it actually is, and guarded.** The
      tempting justification — "every validator returns `traceparent`" — does **not** support the
      conclusion: 21 of the 29 threaded states take their object from a **non-validator** Task whose
      absent `ResultPath` replaces the state (`archive/RequestFailureSeed` alone can be entered with
      the return of **13** different Tasks). What actually makes it safe is the fleet's **echo
      convention**: every replacing Task on a failure-reachable path returns `{**event, …}`,
      `dict(event)` or `return event`, so it cannot drop a key it was never told about. That is the
      real invariant, it was verified verb by verb across roughly thirty modules, and **nothing in
      the tree checks it**.
- [ ] **One guard for that invariant, derived rather than listed**, because two separate blind spots
      turned out to be the same one. Derive the set of verbs whose Task replaces the state on a
      failure-reachable path and assert each echoes its event. This subsumes the narrower hole in
      SPEC-225's `test_the_two_verbs_that_filter_their_echo_keep_the_runs_trace`, whose population is
      a **hard-coded parametrisation of two** rather than a derivation — so a third verb adopting the
      `{k: v for k, v in event.items() if k not in (…)}` idiom would drop the traceparent silently.
      Measured: exactly two files in `lambdas/` use `event.items()` outside a test, so the pinned
      list is right today and what is missing is the derivation, not a fix.

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
failure. One sweep, asserting both.

**But bare set equality is false on five of the eleven pairs, by design, and the form has to allow
for it.** Measured by driving `archive-write-receipt` for real: it returns ten keys and
`ArchiveComplete` reads five. The five dropped are dropped deliberately — `ArchiveComplete` is the
whole-request success terminal, and its own comment says it drops everything the run no longer needs
rather than carrying it into the execution output. The form that keeps **both** directions without
weakening to a subset is **`reads == returns - declared_drops`, with the drop set pinned per pair**:
a key a state drops becomes a written decision rather than a silent one, and either adding a key to
a verb's return or removing one reddens the guard until somebody decides.

**`traceparent` gets a rule of its own**, which ties this FR to the machinery SPEC-225 already
built: it may appear in a pair's drop set **only** where `_blocks_that_name_their_fields` already
excludes that state as a **success terminal** — a `Pass` whose `Next` is a `Succeed`, or a Map
branch's `End: true` leaf, whose output no state reads. Anywhere else, dropping the traceparent is
exactly the silent failure this arc exists to stop. Five of the eleven pairs qualify
(`archive/ArchiveComplete`, `archive/RestoreComplete`, `data-quality/RecordSuccess`,
`table-share/GuardRecipients/RecipientCleared`, `table-share/FinishRecipients/RecipientSucceeded`);
the other six are threaded states and may drop nothing.

The three existing per-plane checks stay. They are narrower in one direction and wider in another —
file-ops' scrapes `Variable` paths the sweep does not — and deleting a working guard because a new
one overlaps it is how coverage is lost quietly.

#### Acceptance Criteria:

- [ ] The sweep covers every plane that **has** a Task-to-replacing-`Pass` pair, deriving the list
      by parsing rather than naming planes. **The population was re-derived and authoring had it
      wrong in both directions.** Eleven pairs across **five** planes:

      | Plane | pairs (`Pass` ← producing Task) |
      |---|---|
      | archive | `Validated`←ValidateAuthorize, `ArchiveComplete`←**WriteReceipt** |
      | data-quality | `RecordSuccess`←DropTempTables |
      | file-send | `Validated`←ValidateAuthorize, `ShapeSummary`←CollectTransferResults |
      | results-conversion | `Validated`←ValidateAuthorize, `Described`←DescribeResults, `Converted`←Convert |
      | table-share | `ShapeSummary`←CollectTransferResults, `GuardRecipients/RecipientCleared`←CheckTargetAbsent, `FinishRecipients/RecipientSucceeded`←CreateTable |

      **Three** planes are "nothing to check", not two, and they are reported explicitly rather than
      passed over silently: shared-spaces, file-ops and table-builder. **table-share has three
      pairs**, where authoring said it had none.
- [ ] **Every exclusion falls out of ONE rule, rather than a list of reasons.** A pair is usable
      only where **every inbound path converges on exactly one replacing Task**, so the `Pass`
      provably reads that verb's return and nothing else. Three edge semantics decide it: a
      `Next`/`Default`/`Choices` edge carries the source's **output**; a `Catch` edge carries the
      failing Task's **input** plus the error; and a state replaces only when it has **no
      `ResultPath` key at all**, merging when it is non-null and discarding when it is `null`.
      Applying it, each exclusion is derived rather than asserted:

      - **file-ops** and **shared-spaces** have no success-path replacing `Pass` at all — file-ops'
        success tail is `FinaliseOutcomes → ReleaseLock → NotifyOutcomes → Succeeded`, every one a
        Task. (Authoring's stated reason, that both file-ops edges carry `"ResultPath": null`, is
        the wrong reason for the right answer.)
      - **table-builder/RecordSuccess** has **three** possible producers — `ApplyRefresh`,
        `DiffSchema`, `ExecuteDdl` — because `ReleaseRefreshLock` merges under `$.released` and the
        walk passes through it rather than stopping there.
      - **archive/RestoreComplete** has three — `UpdateReceipt`, `DeleteArchived`,
        `CollectRestoreResults`. `UpdateReceipt`'s own `Catch` carries `ResultPath: "$.receiptError"`
        and lands on `NotifyRestored` too, so on that path the state is `UpdateReceipt`'s *input*,
        not its return. Set equality against that verb would have been a claim about one of three
        runtime paths. `ArchiveComplete` is unaffected — single producer, verified.
      - **table-share/FinishRecipients/RecipientCarried** resolves to no single Task producer.
- [ ] Set equality is asserted only where it is meaningful. `file-ops/ReleaseLockOnFailure` has
      `ResultPath: null` (the result is discarded, so the next `Pass` reads the incoming state) and
      `table-builder/ReleaseRefreshLock` nests its return under `$.released`; equality against the
      verb's return is meaningless for both, and they are excluded **by rule with the rule
      asserted** — the rule tests `"ResultPath" in state`, because an absent `ResultPath` and an
      explicit `null` both parse as `None` and only that test tells them apart.
- [ ] The "producing verb" is derived from the graph by walking **back** from the `Pass` **through**
      every Task carrying an explicit `"ResultPath": null`, because such a Task discards its own
      result and the `Pass` reads what the Task *before* it left. A "nearest Task predecessor" rule
      is wrong on archive: `NotifyArchived` and `NotifyRestored` both carry `"ResultPath": null`, so
      it would name *archive-notify* as `ArchiveComplete`'s producer when the answer is
      **write-receipt** — which the state's own comment already says. data-quality's producer is
      *drop-temp-tables*. **Neither file-ops nor table-builder has a producer at all**, so the
      authoring clause naming *release-lock* for them is struck: it contradicted the exclusion the
      criterion above states.
- [ ] It asserts `reads == returns - declared_drops` between each field-naming state's reads and its
      producing verb's **real return value**, driving the verb rather than reading its source.
      **Authoring's cost estimate here was wrong and the exclusion escape hatch it bought is not
      needed.** The claim that the fixtures "do not exist" traces to a docstring in
      `lambdas/test_plane_envelope_agreement.py` that **contradicts itself in consecutive
      sentences** — it justifies a source read because the fixtures do not exist, then says the value
      is asserted by *"each plane's own suite … against its driven handler"*. Surveyed: **all eight
      producing verbs already have a green success-return call in their own test file**, each with
      its fixture and its stub set, the largest being three lines (`archive-write-receipt` needs one
      `put_object` fake; `data-quality-drop-temp-tables` needs one seam, `cpcommon.athena.run_ddl`).
      `lambdas/conftest.py`'s autouse `_restore_shared_layer_modules` makes raw attribute assignment
      safe without teardown. **That docstring is corrected by this FR**, on the same obligation as
      the two archive comments: this sweep is what falsifies it.
- [ ] Mutation-tested per plane in both directions: renaming a key in a verb's return must fail, and
      removing a key from a state's `Parameters` must fail, each naming the plane and the key.
- [ ] ~~shared-spaces' conditionally-shaped validator return is handled explicitly.~~ **Struck:**
      shared-spaces has **no** usable pair, so there is nothing for this criterion to attach to —
      `RefusedSeed` hands control to `NotifyFailure` and `UnknownActionSeed` carries
      `ResultPath: "$.error"`. Its conditional return is harmless for a different reason, checked:
      `traceparent` is set **before** the refusal branch (`lambdas/shared-space-validate/validate.py:235`),
      so every arm carries it.
- [ ] The three existing per-plane cross-checks are still present and green.
- [ ] **Both archive comments state what actually holds them**, naming this sweep. They currently
      cite `test_state_machine_archive.py` as reading the `Validated` and `ArchiveComplete` blocks
      against the verb's real return value; spot-checked — that file exists and holds exactly seven
      tests, and none of them is a cross-check of either block. The
      correction belongs to this FR because the sweep is the thing that finally makes the claim
      true — for all eight planes rather than the one the comment spoke for.


## Implementation Phases

Two PRs, and the cut is load-bearing.

### Phase 1 — **PR A**: the guard, before anything is threaded through it

- Widen failure-seed recognition to the **union** of the structural and graph tests; fix the
  per-container walk; derive-and-pin the 32-seed population; positive control; the synthetic nested
  fixture; the reviewer's plant as a test.
- It must land **green against an unthreaded tree** (measured: 32 seeds, 0 violations) — that is
  what proves the guard can see the invisible seeds *before* anything is threaded through it. Folded
  in with FR-002, nothing distinguishes "the guard works" from "the guard agrees with the edit
  beside it". It also fixes a latent bug of unknown blast radius, which is a revert-boundary
  argument. **PR A depends on SPEC-225 not at all.**

### Phase 2 — **PR B**: the failure path and the cross-check, together

- The traceparent into every run-level failure seed and `RecordFailure`; a literal `null` on the
  pre-identity seeds; the derived echo-filter population; driven failure runs on archive and
  file-ops.
- The eleven-pair cross-check across five planes, `reads == returns - declared_drops`,
  mutation-tested per plane in both directions; three planes reported "nothing to check".
- The two archive comments and the self-contradicting `test_plane_envelope_agreement.py` docstring,
  corrected to name it.
- Full local gates green by exit code.

FR-003's sweep is what makes FR-002's claim checkable on all eight planes, so splitting them would
land a sweep that immediately needs amending.
