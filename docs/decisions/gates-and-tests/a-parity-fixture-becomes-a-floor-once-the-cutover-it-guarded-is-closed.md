---
type: Decision
title: "A parity fixture becomes a floor once the cutover it guarded is closed (2026-09-05)"
description: "A parity fixture stays frozen after its cutover and acts as a floor: every captured function must keep its captured fields, additions are named and accepted, and the environment comparison is retired in favour of deriving each function's variables from its code."
---

The container cutover froze a capture of every Lambda's settings and held the planned fleet
**equal** to it in both directions — the right shape while 86 functions were being replaced and
nothing else was allowed to move. The cutover closed, the fixture stayed frozen (regenerating it
would make it agree with whatever the code says), and the first plane added afterwards was refused
locally, before any PR existed, by the offline test that holds the capture equal to `fleet.py`'s
derivation — and `lambda_plan_guard.py` in `deploy-infra.yml`'s plan job would have refused it the
same way, since its equality loop had no other branch: a function the fixture never saw, and a
queue URL added to the API's environment, both read as drift. No PR between the cutover and that
plane had added a function or an environment variable, so a gate that ran on every infra PR had
never been exercised on the case it now refused.

**The guard is a floor.** Every captured function must still exist with every captured field
intact, and every captured environment variable must still be set to its captured value; a
function the fixture never captured is an addition, named on stderr and accepted, and a variable it
never captured is allowed. The offline test names the additions explicitly
(`ADDED_SINCE_THE_CUTOVER`), so an accidental function still fails by name rather than shrinking
into a tolerated difference. Each edge of the floor was mutation-tested: refusing an addition,
ignoring a vanished function, ignoring a removed or changed variable, and refusing an added
variable each reddened exactly one test. Not retired: the floor still holds what the cutover
promised, and the packaging, population and permission-by-ARN checks beside it are untouched.

**The floor was half the answer, and CI found the rest one refusal at a time.** Three more things
in the same machinery refused a plane that had done nothing wrong, and none was reachable until
one was added — so each arrived on its own CI run, after the local gates were green.

- The **extractor** — a step whose own comment says it is not the gate — ran `capture` under
  `set -e` on every plan, and `capture` correctly refuses a plan carrying an unknown value. A
  plan that creates a queue always carries one. It now says why it could not extract and
  continues.
- The **unknown-parity-field refusal** demanded the attribute be "declared explicitly", which is
  a remedy that exists for a memory tier and not for a role ARN belonging to a role created in
  the same plan. It now applies in full to the functions the fixture CAPTURED, where a skipped
  comparison is the promise going quiet, and to an ADDITION only for the three fields
  `docker-lambda` sets as literals. Both directions mutation-tested.
- The **`environment` leg is RETIRED**, not patched again. Two attempts to keep it — a
  per-variable floor, then a reader for all four shapes Terraform marks an unknown with — each
  passed locally and each was refused by the next real plan, the second one crashing on a shape
  its hand-built fixture did not have. What finally settled it was reading what the leg
  PROMISED: "the cutover changed no function's environment" is a claim about one apply, and held
  as an eternal floor it refuses a plane joining the DLQ drain's list, which is a change the
  plane exists to make. It is retired with its replacement named, per the fence — 
  `test_fleet_environment.py` derives every variable each function's code can reach and asserts
  its environment supplies it, which is both stronger and live where the fixture is frozen.

The lesson is about gates rather than about this gate: **a check written for a one-time event
keeps running afterwards**, and its preconditions quietly become claims about every future
change. Every refusal here was right for the cutover and wrong for the first ordinary growth
after it, and none could be observed until something grew. The second lesson is the cost of
patching instead of reading: two rounds went into keeping a comparison whose promise had already
been kept, and the question that ended it — *what did this leg actually promise, and is that
still a thing that can be true?* — was available at the start.

## History

### 2026-09-05

- **Settled:** entered the register.
