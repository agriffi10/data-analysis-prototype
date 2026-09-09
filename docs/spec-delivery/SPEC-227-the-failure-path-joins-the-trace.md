# Completed Spec — SPEC-227: The Failure Path Joins the Trace, and the Cross-Check Nobody Wrote

## What was completed?

- **The failure-seed guard can see every state that feeds a failure terminal.** Recognition in
  `test_a_failure_seed_supplies_every_key_the_failure_terminal_reads` is now the **union** of the
  old structural test and a graph test — a `Pass` with no `ResultPath` whose every reachable
  terminal is a `Fail`. Measured across the eight templates: structural 23 seeds, graph 29 seeds, **union 32**.
  A union rather than a replacement, because the graph half alone loses the three nested seeds
  whose `ItemProcessor` holds no `Fail` at all.
- **A latent walk bug is repaired.** The guard flattened states to qualified names while ASL `Next`
  names siblings unqualified, so every nested walk dead-ended on its first hop. It walks per
  container now, and checks **every** state's reads rather than only a `Pass` — `NotifyFailure` is
  a Task and sits between the seed and `Failed` on all eight planes.
- **The failure path carries the traceparent**, across 29 states: 13 post-identity seeds and 8
  `RecordFailure` states read `$.traceparent`, and 8 pre-identity seeds supply a literal `null`.
  New guards: `_failure_path_threading` derives the split, and driven end-to-end **failure** runs on
  archive and file-ops assert every span — `notify-failure`'s included — shares one `trace_id`.
- **One ASL/verb cross-check over the fleet**, `test_state_reads_match_verb_returns.py`: eleven
  pairs derived from one rule, seven driven against the verb's real return in both directions,
  three planes reported as having nothing to check.
- **The invariant the whole failure path rests on is DETECTED, where it used to be merely stated.**
  `test_every_producer_of_a_failure_path_traceparent_read_carries_it_through` walks back from every
  failure-path `$.traceparent` read to the Task whose return it reads, resolves that Task to its
  Lambda, and requires the verb to carry the key — **49** producers derived from the templates, with
  one pinned exemption whose premise has its own test (`archive-rollback` always raises, so it
  returns no state to drop from). Beside it, a fleet-wide tripwire pins the nine directories that
  RESHAPE a mapping — the one shape that drops keys while naming none.
- Both archive comments, and a self-contradicting docstring in `test_plane_envelope_agreement.py`,
  now say what actually holds them.

### Deliberate deviations

- **FR-002's stated mechanism was impossible and was replaced.** The spec had each pre-identity seed
  read the traceparent from `$$.Execution.Input`. No Pipe carries an `input_template`, so that is
  the raw SQS batch and the value sits inside a JSON string only `States.StringToJson` could open —
  forbidden fleet-wide for exactly the uncatchable `States.Runtime` this arc exists to avoid. The
  envelope the spec said "exists on every plane" exists on four. **Andrew's decision: accept the
  limit.**
- **KNOWN LIMIT, since CLOSED by SPEC-228 — a failure raised before `validate-authorize` returns
  could not join the run's trace.** It has no traceparent on the state, so its seed supplies a
  literal `null` (which it still does, and must — a `Pass` hard-fails on an absent key) and
  `notify-failure` opened a trace of its own. The ASL half of the reasoning was right; what was
  wrong was the claim that the extractor could not reach the value either. SPEC-228 walks the
  forwarded envelope the state carries, so the notification now sits in the run's trace and
  recovers the caller's request id besides.
- **FR-003 drives seven of its eleven pairs, not all eleven.** Driving a verb only answers the
  question for a verb that BUILDS its return; one returning `{**event, …}` inherits its key set from
  its input, so driving it with a hand-built mid-chain state compares the fixture with itself. For
  three of the four excluded pairs a faithful drive is not merely expensive but impossible: a
  Distributed Map sits in the chain and the state after it comes from a Map Run export no drive can
  produce without hand-shaping the state under test. Each exclusion is recorded, and a test reads
  the verb's source to confirm it really does echo — so a failing pair cannot be silenced by moving
  it into the exclusion list.
- **FR-003's AC-6 was struck**: shared-spaces has no usable pair, so its conditionally-shaped
  validator return had nothing to attach to. (Checked separately: `traceparent` is set before the
  refusal branch, so every arm carries it.)
- **AC-2 — which asked that the nested walk be asserted to traverse more than one hop — is met by a
  SYNTHETIC fixture, and the guard says so.** All three nested seeds are `End: true` with no `Next`,
  so even with the walk repaired their walks reach zero states: the repair buys no assertion over
  today's fleet, only over the day a nested seed gains a successor.
- **Three spec measurements did not reproduce** and were corrected in place before building: the
  graph half gains nine seeds, not eight (`shared-spaces/RefusedSeed` was missed); "349 violations"
  does not reproduce; and FR-003's population was wrong in both directions, with two criteria that
  contradicted each other.

### The limit of the producer detector, stated where it will be read

Whether a verb's return still carries its input's keys is **not decidable from source**. Five drafts
of the classifier were each defeated by a reviewer: a bare `return <name>`; a `**<name>` spread; an
`event`-anchored version; `dict(event)` followed by `.pop`; and a genuine echo trimmed afterwards by
a helper. The reviewer's own remedy — bind to the handler's return and fail closed — was measured
and rejected: it flags **most** of the fleet's verb directories, because most verbs build their
return rather than echoing it, so it would need exactly the exemption list the guard refuses. (An
earlier draft gave a count. It was measured against a throwaway prototype that no longer exists, so
nobody could re-derive it — and its denominator did not match any population in the tree.)

So it is a **detector, not a fence**, and the docstring says so. It catches the shapes that occur and
makes the next change to one of those verbs loud. **Production correctness does not rest on it**: the
deploy-safety review traced all eight graphs with an abstract interpreter — itself mutation-tested —
and found zero states reachable with the key absent, because no producer can carry `requestId` and
drop `traceparent`.

### Known residual

The seed guard compares a downstream read's **first path segment**. A seed supplying `"space": null`
while a later state reads `$.space.database` would pass. Not a live defect — `table-builder` and
`table-share` both supply nested literals, and a full-path check measures **zero** violations today —
so the hardening is free and is owed to the next change in that guard.

## What changed from earlier specs?

- SPEC-225's pinned traceparent-read count moves from 16 to 37 (21 new reads; the eight literals are
  not reads, which is why it is not 45).
- SPEC-225 pinned the two echo-filtering verbs as a hard-coded pair; that population is now
  **derived**, so a third verb adopting the idiom fails rather than silently dropping the trace.
- `results-conversion`'s `_RUN_KEYS` block said no ASL template named `traceparent` and that the ASL
  side would come later — written while SPEC-225 was minting the key with nothing reading it, and
  false since #694. Retired in place.

## Verification

Local, green by exit code: `ruff`, `mypy`, `pytest lambdas/` (3531 passed, coverage 90.38%),
`npm run format:check|lint|test|build|check:bundle`, the contract regen and its no-diff check, all
five doc/flag/path validators, and `pre_push_test.py`. Every edited template passes
`aws stepfunctions validate-state-machine-definition`.

**39 mutations across three batteries** (20 on FR-001, 8 on FR-002, 11 on FR-003), each caught by
the test that owns it and keyed on **which test** reddened rather than on an exit code, bracketed
with green baselines and re-run after the review fixes to confirm no guard weakened. Every battery
had a survivor on its first run; each was a guard that could not fail rather than a bug, and each
was pinned directly before the battery was re-run.

**A third review frame was spent, deliberately over budget, and it earned it.** Two full frames ran
(adversarial execution; production and deploy safety) and their findings are fixed — but the producer
guard was ADDED in response to the first, so neither had seen it. The third frame, scoped to that
guard alone, broke it four ways, two blocking: both source globs stopped one directory short of the
shared layer (**134 of the fleet's 242 non-test modules invisible**), and the echo check was an OR
over a whole directory rather than bound to the return. The exit finding — a determined enough
indirection still gets past the detector — is one that does not change the built result, which is
what ended the rounds.

**Production safety was reviewed as its own frame**, not inferred from the tests. An abstract
interpreter over all eight graphs — modelling a Task's `OutputPath` replacement, `ResultPath` merge
and discard, and a `Catch` handing on the failing Task's INPUT — reports **zero** states reachable
with `traceparent` absent, and was itself mutation-tested twice. The structural reason it is cheap
to re-check, re-measured independently: of the **27** states reading `$.traceparent` at top level,
**none** reads it as its only state key — every one already reads `$.requestId`, `$.actor` or
`$.error` off the same state. So the new read is a new failure mode only if a producer could carry
those and drop the traceparent, and none can: every producer either mints the key or echoes the
whole event.
Payload headroom is not restated here, and that is deliberate: an earlier draft of this paragraph
carried a byte figure taken from a review and never re-derived, and neither half of it matched the
model the repo already owns. `test_the_whole_map_state_stays_under_the_payload_limit` derives the
traceparent's cost — 55 bytes as a value, **73** with its key and comma — against the 256 KB state
limit, and a reader who needs the number should re-measure there rather than trust a copy.

Deferred to deploy: nothing. No verb changed, every validator already returned `traceparent` on the
live image, and no `notify-failure` handler holds a strict envelope — so the two deploy workflows
can race here harmlessly and no inert-then-live split was needed.
