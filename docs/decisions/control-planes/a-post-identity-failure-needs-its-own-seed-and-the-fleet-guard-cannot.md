---
type: Decision
title: "A post-identity failure needs its own seed, and the fleet guard cannot see it (SPEC-165)"
description: "**A post-identity failure needs its own seed.** A `Pass` hard-fails on an ABSENT key — an uncatchable `States.Runtime`, raised *before* the notifier — so a catch may only route to a state whose every read its seed supplies, whatever the key is called. Nothing reads `$.raw` any more, which is what retired the instance of this that used to bite; the rule is the general one, and a fleet guard walks every seed's forward path to hold it."
---

**Decision.** The file-send machine carries **two** failure seeds. `InspectSource`'s catch uses
`ResultPath: "$.error"` and routes to `InspectFailureSeed`, which supplies `raw` from
`$$.Execution.Input` and the actor from `$.actor`.

**Why not route the catch straight to `RecordFailure`,** which is what every other plane does. This
plane's `RecordFailure` reads `$.raw`, and `raw` exists on **no** post-validate state — SPEC-164
deliberately did not thread the request through, because the Pipe record carries the selection
again as an escaped string. A Pass state's JSONPath hard-fails on an absent key with an uncatchable
`States.Runtime`, so the direct route kills the execution **before** `NotifyFailure`: the sender
hears nothing, on exactly the failures SPEC-152 exists to report.

**Why the fleet guard does not cover it.**
`test_a_failure_seed_supplies_every_key_the_failure_terminal_reads` identifies a seed
**structurally**, as a Pass whose `error.$` is `"$"` — the shape a catch has when the error
*replaced* the state. A catch carrying a `ResultPath` produces `"$.error"` instead, and the fleet
walk skips it entirely. Widening that detection is a fleet-wide change to a guard, on five machines,
and was **rejected as out of scope for this spec**; the plane's own suite compensates with a walk
that derives from the machine what Step Functions actually leaves on the state at each catch
(`ResultPath: "$.x"` ⇒ the task's input plus `x`; no `ResultPath` ⇒ nothing addressable). Verified
by mutation — and the first version of that walk **passed vacuously** on the exact mutation it
existed for, because it treated the catch target as a seed instead of as a reader.

Nothing reads `$.raw` any more, which is what retired the instance of this that used to bite; the rule is the general one, and a fleet guard walks every seed's forward path to hold it.

## History

### 2026-08-10

- **Settled:** SPEC-165.
