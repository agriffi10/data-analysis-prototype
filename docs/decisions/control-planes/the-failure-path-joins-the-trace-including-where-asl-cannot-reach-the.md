---
type: Decision
title: "The failure path joins the trace, including where ASL cannot reach the value (SPEC-227, SPEC-228)"
description: "**A PRE-identity seed — `\"error.$\": \"$\"`, where the error REPLACED the state — supplies LITERALS for everything its terminal reads, including `traceparent`.** Omitting the key instead of supplying a literal `null` makes `RecordFailure`'s read the uncatchable error this whole rule exists to prevent. Everything post-identity reads `$.traceparent`. **Such a failure DOES join the run's trace, and not through ASL:** the value is still reachable nowhere ASL can read — that half stands and is why the machines are shaped this way — so `RecordFailure` carries the forwarded envelope from `$$.Execution.Input` and `notify-failure` parses the traceparent and the request id out of it in Python. **\"Pre-identity\" names the CATCH SHAPE, not the absence of an identity**: every validate-authorize failure lands on that seed, an authorized actor's refused request included."
---

SPEC-225 put a run's **success** path into one trace. The half an operator actually opens after an
incident is the other one: `notify-failure` is a **separate invocation**, reached from
`RecordFailure` through `"Payload.$": "$"`, so unless every state between the failure and the
notification names the traceparent, that span belongs to a trace of its own. Twenty-nine states now
carry it — 13 post-identity seeds and 8 `RecordFailure` states read `$.traceparent`, 8 pre-identity
seeds supply a literal `null`.

**The limit was real and was not a shortcut, and the obvious repair does not work.** A seed
reading `$$.Execution.Input` cannot get at the value: with no `input_template` on any Pipe that
path is the raw SQS batch, the traceparent is inside `[0].body` as a JSON string, and extracting it
needs `States.StringToJson` — banned in ANY intrinsic-evaluating field on any state, not only on
`$.error.Cause`, for the same uncatchable `States.Runtime`. Independently,
`observability._shape_values` walked four inbound shapes — top level, the SQS envelope,
`BatchInput` and `request` — but never `raw`. **That second half was the repair rather than the
reason, and SPEC-228 took it:** the envelope does not need parsing in ASL at all, because it is
already on the state. The extractor gained `raw` as a fifth shape, every `RecordFailure` carries
`$$.Execution.Input`, and the failure that replaced the state now joins the run's trace AND
recovers the caller's request id. The ASL half above stands unchanged and is still why the
machines are shaped this way.

**The guard had to be widened before anything was threaded through it, and that ordering was the
point.** Recognition of a "failure seed" was structural (`Parameters["error.$"]`), which missed
**nine** states that replace the state with a literal `error` object. Proved rather than argued: the
obvious edit — the traceparent onto archive's `RecordFailure` and the two seeds the guard could
see — left the whole suite green while six archive failure paths would have hit an absent key inside
a `Pass`. Recognition is now the **union** of the structural test and a graph test (every reachable
terminal is a `Fail`), because the graph half alone loses the three nested seeds whose
`ItemProcessor` contains no `Fail`. "Terminal" means **a state that hands control nowhere**; under
the other reading an `ItemProcessor` has none, `all([])` is true, and the sweep selects success
leaves.

**The cross-check's own limit is the interesting part.** Driving a verb answers the question only
for a verb that **builds** its return. One returning `{**event, …}` inherits its key set from its
input, so driving it with a hand-built mid-chain state compares the fixture with itself and agrees
with any state at all. Seven of eleven pairs qualify; for three of the other four a faithful drive
is impossible rather than expensive, because a Distributed Map sits in the chain and the state after
it comes from a Map Run export no drive can produce. Exclusions are recorded, and a test reads each
excluded verb's source to confirm it really does echo — so the escape hatch cannot be used to
silence a failing pair.

**And the sweep's own producer guard is a DETECTOR, which is worth knowing before anyone leans on
it.** Whether a verb's return still carries its input's keys is not decidable from source: five
drafts of the classifier were each defeated — a bare `return <name>`, a `**<name>` spread, an
`event`-anchored version, `dict(event)` then `.pop`, and a genuine echo trimmed afterwards by a
helper. Binding to the handler's return and failing closed was measured and rejected — it flags
most of the fleet's verb directories, because most verbs build their return rather than echoing
it. What it catches is the shapes that occur, plus a fleet-wide tripwire on the one shape
that names nothing — a verb that reshapes a mapping. Production correctness today rests on the
traced analysis rather than on the test — but that analysis was a one-time review artifact over the
eight graphs as they stood, so the day a ninth producer lands the detector is the only live thing
left. Its job is to make the next change to one of those verbs loud; weakening it removes the only
standing check.

Do **NOT** add a second copy of a plane's fixture to drive its verb: import the plane's own suite.
Do **NOT** hold a state's reads to a verb that echoes its event — the answer is your fixture.
Do **NOT** glob `lambdas/*/*.py` for a fleet-wide source sweep — it sees the handler modules only,
and misses the `*-common` packages, the API tree and the files at `lambdas/` top level. A key
dropped in any of them is invisible to it.

Detail, the corrected populations, and the residual first-segment gap: `spec-delivery/SPEC-227`.

## History

### 2026-09-09

- **Settled:** SPEC-227, SPEC-228.
