# Completed Spec — SPEC-228: The Pre-Identity Failure Joins the Trace

Landed as [#712](https://github.com/agriffi10/data-analysis-prototype/pull/712), one PR, after
SPEC-229 supplied the bound its widening needed.

## What was completed?

A `validate-authorize` failure — the shape where the error **replaced** the state — now joins its
own run's trace, and recovers the caller's request id besides. Before this it did neither: the seed
supplies `traceparent: null` and `requestId: null`, so `notify-failure` opened a fresh trace and
correlated on nothing at all. That is the failure an operator is most likely to open.

- **A fifth shape in `cpcommon.observability._shape_values`** — the forwarded SQS envelope carried
  on the state as `raw`. Walked **last**, so a threaded top-level value stays authoritative and the
  JSON parse is not paid for when one is present. The envelope walk moved into a new
  `_envelope_values`, shared with the Pipe branch.
- **All eight `RecordFailure` states carry `raw` from `$$.Execution.Input`.** Sixteen now-dead `raw`
  keys left the failure seeds, and **no state reads `$.raw` anywhere**.
- **Guards** in `test_state_machines_cpcommon.py`: the derived eight-terminal population, a
  fleet-wide "no state reads `$.raw`" walk, and the `_read_keys` context-object exemption pinned by
  its own fixture with a `$.raw` positive control.
- **Two end-to-end drives** in `test_one_run_one_trace.py` — a failure that replaced the state,
  driven from a raising validator through the real ASL into `notify-failure`, on archive and
  shared-spaces. Plus a shipped drive of the four notifiers that recover an actor from the envelope.

### Why the limit SPEC-227 recorded was closable

It rested on two claims. **The ASL one is true and stands**, and is still why the machines are
shaped this way: the traceparent sits inside `[0].body` as a JSON string, and prising it out needs
`States.StringToJson` — banned fleet-wide for the uncatchable `States.Runtime`. **The second was
the repair rather than the reason**: `_shape_values` never walked the `raw` the state already
carries. So the value is not read in ASL at all; it is read in Python, from a state field.

**The context object is what kept this small.** `_read_keys` matches `$.<key>`, so a `$$.` read is
not a read any seed must supply — 8 states changed instead of 29, and the failure-seed guard was
never disturbed. That exemption is load-bearing, so it is pinned rather than depended on silently.

### Deliberate deviations

- **The spec's stated reason for rewriting the drive harness was not live.** It said
  `_drive_a_failure`'s `__execution_input__` key would land inside the error object. After the seed
  stops reading the context object that cannot happen, and all nine existing tests pass untouched —
  measured. The rewrite was kept on the honest ground (structural beats asserted, and it removes a
  foot-gun for the next drive reading `"$"`), not on the ground that a live leak was being fixed.
- **The spec's file list was short by two.** `lambdas/test_request_size_chain.py` — SPEC-229's chain
  guard — reads `"raw" in keys` off the templates, so four more planes now measure the envelope; and
  the `$.raw` Fences clause exists **verbatim in two files**, so generalising only the register's
  copy would have left `infra/info/control-plane-shape.md` stale.
- **`owed.md`'s named sentence was already gone.** FR-004 asks that "if (b) shows one shared trace,
  the register entry is wrong" be removed; `git log -S` puts that removal in #710, an ancestor of
  this branch. Recorded as discharged by a prior PR rather than claimed as this spec's work. The
  row's *title* did still assert the falsified claim, and that was corrected.
- **A dated live-check record is not rewritten.** `owed.md` row 38 and the `sessions.md` entry are
  records of what was measured on 2026-09-09 and stay verbatim; what was superseded in place is
  every sentence reading as a claim about what is true *now*.

## What changed from earlier specs?

- **SPEC-227's known limit is closed**, and is marked superseded in place in the spec, its delivery
  doc, the register entry, `ARCS.md` and `shared-layer.md`. The ASL half of its reasoning is kept
  verbatim everywhere, because it is still true.
- **The `$.raw` Fences clause is generalised, not deleted** — its hazard became unreachable, so its
  subject is now the still-live trap: a `Pass` hard-fails on an absent key, whatever it is called.
- **"Pre-identity" was too narrow, fleet-wide.** It names the CATCH SHAPE, not the absence of an
  identity: every plane's validator catches `States.ALL` with no `ResultPath`, so any raise lands on
  that seed whatever it had verified. Seventeen ASL comments across seven planes said otherwise and
  were corrected — the register had already been fixed by #710, so the two disagreed.
- **The shape count moved from four to five** in 13 places across 6 files.
- **`test_the_shape_table_covers_every_shape_the_extractor_walks`** now counts `yield from` as well,
  since extracting the shared helper moved a `yield` out of its view.

## Verification

All 16 gates green locally by **exit code** before the push — prettier, eslint, vitest,
`npm run build`, `pytest lambdas/` (3,643 passed, 90.50% coverage), ruff, mypy, `tofu validate`,
`tofu fmt -recursive`, the API-contract regen and all six CI validators. CI, Deploy Infrastructure,
Lambda image and Security all green on the head SHA before merge.

**The byte chain was re-derived, not re-checked**, because a structural change invalidates a
threshold rather than merely testing it. The four planes gaining the envelope move from ~66–68 KB
to 75,336 (shared-spaces), 76,977 (table-share), 85,470 (data-quality) and **155,000**
(table-builder refresh, 59.1% of the 262,144-byte limit). The binding link is unchanged at
`archive.archive` 247,009 (94.2%), on a plane that already carried it. Nothing is near the limit.

**Nothing is owed as a live check.** The behaviour is asserted by driving the real verbs through the
real templates, and the production shape it fixes was already measured — `owed.md` row 38's
2026-09-09 evidence is what the repair was derived from, and it is kept and re-pointed rather than
deleted.

### What the reviews cost, and the class they found

Two fresh-context diff reviews in different frames, both before the push. They **converged
independently** on one defect: the consolidated list-only narrowing — a security boundary, since a
caller's own HTTP body sits at `body` for an API Gateway event — had no test that could see it.
Restoring the pre-SPEC-225 fallback passed the entire suite, because the fixture's body was empty
and returns `None` whether the guard holds or not.

Both frames also found the same **class** three times, all in work authored here: a guard that
cannot fail — an assertion comparing an object with itself, that empty-body fixture, and a pair of
assertions made unreachable by matching a qualified state name exactly. Rather than a third round,
the class was closed structurally: **all six guards in the new walk were mutated one at a time,
bracketed by baseline runs, and three survived the whole suite.** Their fixtures now discriminate —
a bare JSON string as the record, a `bytes` body (`json.loads` accepts it, so the guard is the only
refusal), and a body parsing to a list, whose `.get` would raise — and all six are caught, each by
its own named case. The test's docstring records that derivation so the next case added has a bar.
