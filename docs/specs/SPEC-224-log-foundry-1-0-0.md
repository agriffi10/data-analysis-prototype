# Spec: Log Foundry 1.0.0

**ID:** SPEC-224
**Status:** Draft
**Last Updated:** 2026-09-08
**Depends On:** SPEC-127, SPEC-130 (both Completed)

## Overview

The fleet's structured logging runs on `log-foundry` 0.6.0, pinned exactly because one image
carries it to every function in the fleet. Upstream has released `1.0.0` — the first release under
semantic versioning, and a reliability release rather than a feature one: it closes paths where the
library could lose an event, fail its caller, block forever, or report health it could not back up.
Several of its changes are deliberately silent, and two of them land on code this repo has written
*around* 0.6.0's limitations.

This spec moves the pin and settles what moving it means. It is not a feature: nothing a user can
see changes, and no new event is emitted. What it buys is a fleet running a supported version, two
test harnesses that stop pretending to do something the library now does properly, and — because
1.0.0 makes `continue_trace` one-shot — the precondition for SPEC-225's trace stitching, which
would have been unsafe to build on 0.6.0 in a warm container.

**The upgrade spans four minor releases, not one.** 0.7.0 through 0.10.1 are in the jump, and the
release notes' *Upgrading* section is written for a reader on 0.10.x. The intermediate releases
were read for changes reaching this repo's surface; the ones that do are named in FR-005.

## Scope

### In Scope

- The pin: `log-foundry==0.6.0` → `==1.0.0`, and the requirements comment that explains it.
- `cpcommon.observability` adopting the public API 1.0.0 exposes in place of a private one.
- The two test harnesses whose hand-written worker retirement 1.0.0 made both obsolete and silent.
- Correcting every claim in this repo that 1.0.0 falsifies, at every site that states it.
- Guards for the two behaviours the upgrade could have changed without a test noticing.

### Out of Scope

- **Trace stitching.** `continue_trace` becoming one-shot is what makes stitching buildable, and
  this spec does not build it. SPEC-225 does.
- **Child spans in the flat planes.** SPEC-226.
- **`health()`.** 1.0.0 grows `Health` from four fields to twelve and freezes it as a dataclass.
  Nothing in this repo calls `health()` today, and wiring liveness reporting into the fleet is a
  feature with its own design question (where would it be read?) rather than part of a version bump.
- **Turning stack capture off.** Re-checked against 1.0.0's `Config` during authoring: it still
  offers only `max_stack_bytes`, so the 2026-07-23 acceptance and SPEC-195's boundary scrub both
  stand unchanged. FR-004 re-anchors the claim to the version it was re-verified against; it does
  not reopen the decision.
- **Any new `log-foundry` sink or extra.** The core package and `SQSSink` alone, as today.

---

## Functional Requirements

### FR-001: The fleet runs 1.0.0

#### Description:

`lambdas/control-plane-common/requirements.txt` pins `log-foundry==1.0.0`. The comment above the
pin is **rewritten, not appended to** — it is currently a version history running 0.2.0 → 0.6.0,
four paragraphs of which explain floors that a 1.0.0 pin makes unreachable. What a reader needs is
why the pin is exact, why it is the core package rather than `[aws]`, and what 1.0.0 is the floor
*for*; the superseded floors go, rather than becoming a fifth paragraph.

`lambdas/Dockerfile` names `log-foundry ==0.6.0` in the comment explaining why the image's
constraint check demands *a* constraint rather than an exact pin. That example moves with the pin.

#### Acceptance Criteria:

- [ ] `lambdas/control-plane-common/requirements.txt` contains `log-foundry==1.0.0` and no other
      `log-foundry` constraint.
- [ ] The comment above the pin states why it is exact and why it is the core package, and names no
      version floor below 1.0.0 except where it is explaining a decision still in force.
- [ ] `lambdas/Dockerfile`'s constraint-check comment names `==1.0.0`.
- [ ] The image builds, and its install layer resolves `log-foundry` to 1.0.0.
- [ ] `pytest lambdas/` is green by exit code against 1.0.0 on Python 3.12 — the fleet's runtime,
      not the ambient interpreter.

### FR-002: `observability` stops reaching into log-foundry's private context

#### Description:

`observability._reset_baggage` clears trace baggage by setting the library's private context
variable, `log_foundry.context._baggage`. Its docstring says why: *"Uses the library's private
context variable because there is no public clear — `set_baggage` only merges."* 1.0.0 exports
`reset_context()`, so that sentence is no longer true and the private reach is no longer needed.

`reset_context()` clears an adopted trace context as well as baggage. That is a superset of what
this repo needs today and is the right primitive for SPEC-225, which will adopt one.

The reach is currently guarded — a failure degrades to a `logger.warning` rather than failing the
verb — which is correct and stays. The guard is also why this could not be left alone: a private
name that disappears fails **silently**, and baggage that stops being cleared between invocations
does not produce an error, it produces a warm container stamping one invocation's `request_id` onto
the next one's events. The module's own docstring calls that out as worse than a missing key,
because a fabricated correlation key merges unrelated runs and nothing about the output looks wrong.

#### Acceptance Criteria:

- [ ] `_reset_baggage` calls `log_foundry.context.reset_context()`; no module in this repo
      references `_baggage` or any other underscore-prefixed `log_foundry` name.
- [ ] The docstring no longer claims there is no public clear.
- [ ] A test drives two consecutive invocations of a `@traced` handler through a capturing sink,
      the first stamping a `request_id` the second does not, and asserts the second invocation's
      events carry **no** `request_id` — not a different one, and not the first one's.
- [ ] That test is mutation-tested: with the `reset_context()` call removed, it fails.

### FR-003: The obsolete worker retirement goes, and a positive control replaces it

#### Description:

Two test harnesses swap the process sink and then retire log-foundry's worker by hand —
`lambdas/conftest.py`'s `captured_events` fixture and `lambdas/log-sweep/test_log_sweep.py`'s
`_install_sink`. Both carry the same explanation: the worker is built lazily from whichever sink
was configured at the first flush and cached for the process, so reconfiguring alone would send
every later event to the sink the test just replaced.

That was true, and measured on both versions during authoring: on 0.6.0, `configure(sink=B)` alone
leaves delivery pointed at `A`; on 1.0.0 it drains, closes `A` and redirects to `B`. So the library
now does the thing the harnesses were written to do.

It also no longer *can* be done by hand: `log_foundry.decorator._worker` does not exist in 1.0.0
— the lifecycle moved to `log_foundry._lifecycle`. Both harnesses reach for it through
`getattr(lf_decorator, "_worker", None)`, so both now silently do nothing while their docstrings
assert they are doing something load-bearing. That is the shape this repo has paid for before: a
guard that stopped guarding and reads as though it still does.

The retirement is deleted rather than re-pointed at the new internals. What replaces it is a
**positive control** — the harness is not merely simplified, it is proved. A sink swap that quietly
stopped redirecting would empty every `captured_events` assertion in the suite, and an empty
collector satisfies every absence assertion written over it.

#### Acceptance Criteria:

- [ ] Neither harness references `log_foundry.decorator`, `_worker`, or any other private
      log-foundry lifecycle name; each swaps with `lf.configure(...)` alone.
- [ ] Both docstrings describe what the code now does.
- [ ] A test asserts, against the real library: after `configure(sink=A)` and one traced call,
      `A` holds the events; after `configure(sink=B)` and another traced call, **`A` grew by zero**
      and `B` holds that call's events. Both halves are asserted — a swap that delivered nothing
      anywhere would pass the first half alone.
- [ ] That control is mutation-tested by pointing the swap at a stale sink, and it fails.
- [ ] The control lives in one place, not once per harness.

### FR-004: Every claim 1.0.0 falsified is corrected wherever it is stated

#### Description:

Three claims in this repo were true of 0.6.0 and are not true of 1.0.0, and one is true of both but
is written version-anchored to 0.6.0. Each is stated at more than one site, and a fix at one site
leaves the others reading as settled fact.

1. **`_emit`'s orphan-path rationale.** Its docstring says swallowing matters most on the orphan
   path because "a sink that raises raises here, in the middle of business logic, rather than on the
   worker thread where the span path absorbs it." 1.0.0 absorbs an `Exception` from the sink on
   **both** paths and reports it as a stderr line plus a `health()` counter. Executed during
   authoring against a sink whose `emit` raises, with no span open: on 0.6.0 the `RuntimeError`
   reaches the caller; on 1.0.0 the call returns and the library writes
   `absorbed a failure while emitting an orphan log (RuntimeError); the event was lost`. The `try`
   stays — it guards this repo's own code as well as the library's — but the reason has to say what
   is now true. (`KeyboardInterrupt` and `SystemExit` are still propagated, which is why the guard
   is not redundant.)
2. **`_reset_baggage`'s "there is no public clear."** Covered by FR-002's code change; this FR
   covers the same claim where it is restated in prose.
3. **The stitching note in `lambdas/info/shared-layer.md`** says `lf.continue_trace(traceparent)`
   is "shipped as of log-foundry 0.3.0". It was, and on 0.6.0 it is **sticky** — measured during
   authoring: one call keeps every later root span in the inbound trace, so a warm container's
   second, unrelated invocation silently joins the first one's trace. 1.0.0 makes it one-shot. A
   note recommending a future fix must not leave a reader to discover that the version it names
   would have made the fix wrong.
4. **"`log-foundry` 0.6.0 exposes no way to turn stack capture off."** Stated at
   `docs/decisions/control-planes.md`, `docs/decisions/identity-and-access.md` and
   `docs/testing/owed.md`. Re-verified against 1.0.0's `Config` during authoring and **still true**,
   so the decision stands; the version it names does not. Each site already says "if a later
   `log-foundry` offers an opt-out, this is revisited", which is an instruction that goes stale
   silently unless the version is moved with the check.

Completed spec files and delivery docs under `docs/specs/SPEC-1*.md` and `docs/spec-delivery/` are
**history and are not edited** — they record what was true when they shipped.

#### Acceptance Criteria:

- [ ] Each of the four claims is corrected at every live site that states it, and the sites are
      enumerated by a repo-wide search rather than from memory.
- [ ] No live doc, docstring or comment outside `docs/specs/` and `docs/spec-delivery/` names a
      `log-foundry` version below 1.0.0 except where it is deliberately describing history.
- [ ] The stack-capture claim's re-verification is recorded as re-derived against 1.0.0 — not
      copied forward with the number changed.
- [ ] `python3 scripts/validate_docs.py` is green.

### FR-005: The two behaviours that could change silently are pinned

#### Description:

Two 1.0.0 changes reach this repo's surface and neither would redden an existing test.

**`fields` became a reserved parameter name on the emitters.** The signature went from
`info(message, *, echo=False, **fields)` to `info(message, *, echo=False, fields=None, **kv)`.
`observability._emit` splats a call site's fields into that call, so a call site writing
`observability.info("m", fields={"a": 1})` is now **reinterpreted** rather than rejected. Executed
against both versions during authoring: 0.6.0 lands `{"fields": {"a": 1}}`, 1.0.0 lands `{"a": 1}`.
A non-mapping — `observability.info("m", fields="x")` — is **dropped** with every counter at zero.
No call site passes `fields` or `echo` today, confirmed by an AST walk of every
`observability.info`/`warning`/`error`/`stamp` call in `lambdas/`; the point is that nothing stops
one, and the failure is silent in both directions. `_emit` already drops-and-warns a
prohibited `echo` for exactly this reason, and `fields` joins it: the escape hatch, if a field
genuinely needs that name, is the keyword form the library now provides.

**The emitters no longer let a sink failure reach the caller.** FR-004 corrects the docstring; this
criterion asserts the contract still holds from this repo's side, on the orphan path — an emitter
called with no span open — which is where a raising sink used to land in the middle of business
logic. The assertion is that the *verb* survives, which is the invariant the module exists to
protect, and it must be asserted rather than inherited from the library's promise.

#### Acceptance Criteria:

- [ ] `_emit` drops a field named `fields`, warns naming the message, and emits the remaining
      fields — mirroring the existing `echo` handling.
- [ ] A test asserts the drop **and** that the surviving fields still land, so a guard that dropped
      everything would fail.
- [ ] A test asserts that `observability.info`/`warning`/`error` called with **no span open**
      against a sink whose `emit` raises does not propagate, and that the caller continues.
- [ ] The existing `test_ACCEPTED_the_span_error_stack_may_carry_file_contents` tripwire still
      passes against 1.0.0 — it asserts `error.stack` carries the cause's text, and 1.0.0 clips
      stacks at 32 KB.
- [ ] `test_instrumentation_coverage.py`'s fleet-wide gate is still green: every Lambda in the repo
      calls `observability.init` and carries `@observability.traced`.

---

## Interface Contract

`cpcommon.observability`'s public surface is **unchanged** by this spec — `init`, `flush`, `traced`,
`step`, `stamp`, `info`, `warning`, `error`. No call site outside the module changes.

What changes inside it:

```python
# _reset_baggage — before
from log_foundry import context as lf_context
lf_context._baggage.set({})

# _reset_baggage — after
from log_foundry import context as lf_context
lf_context.reset_context()
```

```python
# _emit — the prohibited-name set widens from one name to two
_PROHIBITED = ("echo", "fields")
```

The library surface this repo consumes, confirmed against 1.0.0 during authoring:

```python
lf.configure(*, service, version, env, sink, defaults, max_stack_bytes)  # unchanged for our args
lf.flush(timeout: float | None = 5.0) -> FlushResult   # was -> bool; the return is discarded
lf.trace(*, name: str)                                  # unchanged
lf.set_baggage(**kv)                                    # unchanged
lf.info(message, *, echo=False, fields=None, **kv)      # `fields` newly reserved
SQSSink(queue_url, *, client, message_group_id)         # `client` now keyword-only; already is here
StdoutSink()                                            # unchanged
```

## Implementation Phases

### Phase 1: The pin and the module

- Move the pin to `1.0.0`; rewrite the requirements comment; update the Dockerfile's example.
- `_reset_baggage` → `reset_context()`; widen `_emit`'s prohibited-name set to include `fields`.
- Add the FR-002 baggage-isolation test and the FR-005 tests, and mutation-test each guard.

### Phase 2: The harnesses

- Delete the worker retirement from both harnesses; simplify each to `lf.configure(...)`.
- Add the single shared sink-swap positive control; mutation-test it.
- Run the full suite on Python 3.12 against 1.0.0, green by exit code.

### Phase 3: The claims

- Enumerate every live site stating one of FR-004's four claims by repo-wide search.
- Correct each; leave `docs/specs/` and `docs/spec-delivery/` as history.
- `validate_docs.py` green; formatter, both linters, both suites, mypy and `npm run build` green.
