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
Several of its changes are deliberately silent, and three of them land on code this repo has
written *around* 0.6.0's limitations.

This spec moves the pin and settles what moving it means. It is not a feature: nothing a user can
see changes, and no new event is emitted. What it buys is a fleet running a supported version, two
test harnesses that stop pretending to do something the library now does properly, and — because
1.0.0 makes `continue_trace` one-shot — the precondition for SPEC-225's trace stitching, which
would have been unsafe to build on 0.6.0 in a warm container.

**The upgrade spans four minor releases, not one.** 0.7.0, 0.7.1, 0.8.0, 0.9.0, 0.10.0 and 0.10.1
are in the jump, and the release notes' *Upgrading* section is written for a reader already on
0.10.x. Every behavioural claim below was **executed against both versions** during authoring
rather than read out of those notes. Two of the three changes that reach this repo's surface —
`configure()` swapping properly, and the emitters absorbing a sink failure — are 1.0.0's own; the
third, `context.reset_context()` becoming public, is also 1.0.0's. Nothing in 0.7.0 → 0.10.1
touches the surface this repo consumes, which is why no requirement below is attributed to them.

## Scope

### In Scope

- The pin: `log-foundry==0.6.0` → `==1.0.0`, and the requirements comment that explains it.
- `cpcommon.observability` adopting the public API 1.0.0 exposes in place of a private one.
- The two test harnesses whose hand-written worker retirement 1.0.0 made both obsolete and silent,
  and the third private reach in `conftest.py` that 1.0.0 turns into a reported/live divergence.
- Correcting every claim in this repo that 1.0.0 falsifies, at every site that states it.
- Guards for the two behaviours the upgrade could have changed without a test noticing.

### Out of Scope

- **Trace stitching.** `continue_trace` becoming one-shot is what makes stitching buildable, and
  this spec does not build it. SPEC-225 does.
- **Child spans in the flat planes.** SPEC-226.
- **`health()`.** 1.0.0 grows `Health` from **three** fields (`queued`, `dropped`,
  `failed_batches`) to twelve, and makes it a frozen dataclass rather than a `NamedTuple` — so it
  was already immutable, and what changed is that it can no longer be unpacked or indexed. Nothing
  in this repo calls `health()` today, and wiring liveness reporting into the fleet is a feature
  with its own design question (where would it be read?) rather than part of a version bump.
- **Turning stack capture off.** Re-checked against 1.0.0's `Config` during authoring: it still
  offers only `max_stack_bytes`, whose validator still rejects any value below 1, so the
  2026-07-23 acceptance and SPEC-195's boundary scrub both stand unchanged. FR-004 re-anchors the
  claim to the version it was re-verified against; it does not reopen the decision.
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

**A rewrite can lose a fact as easily as an append can bury one, and this block is the only live
home of three.** It carries the sole current statement that `error.stack`'s ceiling is a 32 KB
tail-preserving clip — which is what makes the SPEC-110 tripwire's premise checkable — and the
only record of the two dispositions that keep this repo out of 1.0.0's `MultiSink` re-raise change
and its non-JSON datetime change (the sink here is `SQSSink` alone; no mongo/postgres/sqlite/
clickhouse sink is used). Those three survive the rewrite. The version *floors* go; the
*dispositions* do not.

`lambdas/Dockerfile` names `log-foundry ==0.6.0` in the comment explaining why the image's
constraint check demands *a* constraint rather than an exact pin. That example moves with the pin.

#### Acceptance Criteria:

- [ ] `lambdas/control-plane-common/requirements.txt` contains `log-foundry==1.0.0` and no other
      `log-foundry` constraint.
- [ ] The comment states why the pin is exact and why it is the core package, and names no version
      floor below 1.0.0.
- [ ] The rewritten comment still states the 32 KB tail-preserving `error.stack` clip, the
      `SQSSink`-alone disposition against `MultiSink`, and the no-non-JSON-sink disposition against
      the datetime change. Checked by diffing the removed lines against those three claims, not by
      reading the new text.
- [ ] `lambdas/Dockerfile`'s constraint-check comment names `==1.0.0`.
- [ ] `pytest lambdas/` is green by exit code against 1.0.0 on Python 3.12 — the fleet's runtime,
      not the ambient interpreter — and `mypy` is green, which is not implied by it:
      `warn_unused_ignores` is on, so a type-ignore the upgrade made redundant fails there and
      nowhere else.
- [ ] **Owed to CI, not settled locally:** that the image builds and its install layer resolves
      `log-foundry` to 1.0.0. There is no Docker daemon on the authoring machine, so this criterion
      is recorded on the PR's *Owed* list and discharged on the green `Deploy Lambda image` run.

### FR-002: `observability` stops reaching into log-foundry's private context

#### Description:

`observability._reset_baggage` clears trace baggage by setting the library's private context
variable, `log_foundry.context._baggage`. Its docstring says why: *"Uses the library's private
context variable because there is no public clear — `set_baggage` only merges."* 1.0.0 exports
`reset_context()`, so that sentence is no longer true and the private reach is no longer needed.

`reset_context()` clears an adopted trace context **as well as** baggage. That is strictly more
than the function's name advertises, so the function is renamed to say what it does. It is the
right primitive regardless: SPEC-225 adopts a trace context, and a clear that missed it would
leave a warm container joining a trace whose run has ended.

The reach is currently guarded — a failure degrades to a `logger.warning` rather than failing the
verb — which is correct and stays. The guard is also why this could not be left alone: a private
name that disappears fails **silently**, and baggage that stops being cleared between invocations
does not produce an error, it produces a warm container stamping one invocation's `request_id` onto
the next one's events. The module's own docstring calls that out as worse than a missing key,
because a fabricated correlation key merges unrelated runs and nothing about the output looks wrong.

**The test that proves this has one shape that works and several that cannot fail.** 1.0.0 scopes
baggage to the span, so a `request_id` stamped from *inside* the handler body is popped at span
close whether or not the reset runs — measured during authoring, and it makes the obvious test
unfalsifiable. The leak only survives when the value is bound **outside** the span, which is
exactly where `traced` binds it: `_reset_baggage`, `_stamp_verb` and `_stamp_request_id` all run
before `span(...)` is entered. So the test must drive `observability.traced` with the request id
arriving **on the event**.

#### Acceptance Criteria:

- [ ] `_reset_baggage` is renamed to name what it clears, calls
      `log_foundry.context.reset_context()`, and its docstring states that it clears an adopted
      trace context as well as baggage.
- [ ] A test asserts the adopted-context half **behaviourally**, not just in the docstring: adopt a
      trace, call the renamed function, run a `@traced` handler, and assert the span carries a
      freshly minted `trace_id` with a null `parent_span_id`. SPEC-225 places its adoption *after*
      this call on the strength of that behaviour, so it is asserted here rather than assumed there.
- [ ] No module in `lambdas/` outside `cpcommon/observability.py` and the two test harnesses named
      in FR-003 references any underscore-prefixed `log_foundry` name.
- [ ] A test drives **two consecutive invocations of a `@traced` handler**, the first with a
      `requestId` **on its event** and the second with none, and asserts the second invocation's
      events carry **no** `request_id` — not a different one, and not the first one's.
- [ ] That test is mutation-tested: with the `reset_context()` call removed, it fails. A test that
      stamps from inside the handler body instead does **not** satisfy this criterion, because it
      passes under that mutation.

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

**`conftest.py` makes a second private reach, and this one the upgrade actively breaks.** The
fixture saves `lf_config._config` and assigns it back on teardown. 1.0.0 keeps a `_live_config`
beside `_config`, so the assignment no longer re-points delivery — measured: after the restore,
`lf.get_config().sink` is the saved sink while events land in the sink configured before it. On
0.6.0 the same three lines diverge the other way. Either way the teardown leaves the library
**reporting one sink and delivering to another**, which is a defect the upgrade introduces into the
harness that every plane's tests depend on. It is in scope here because it is the same private-reach
class as the worker, in the same fixture, made newly wrong by the same bump.

The retirement is deleted rather than re-pointed at the new internals. What replaces it is a
**positive control** — the harness is not merely simplified, it is proved. A sink swap that quietly
stopped redirecting would empty every `captured_events` assertion in the suite, and an empty
collector satisfies every absence assertion written over it.

#### Acceptance Criteria:

- [ ] Neither harness references `log_foundry.decorator`, `_worker`, `_config`, `_live_config`, or
      any other private log-foundry name; each swaps with `lf.configure(...)` alone.
- [ ] Both docstrings describe what the code now does.
- [ ] A test asserts, against the real library: after `configure(sink=A)` and one traced call,
      `A` holds the events; after `configure(sink=B)` and another traced call, **`A` grew by zero**
      and `B` holds that call's events. Both halves are asserted — a swap that delivered nothing
      anywhere would pass the first half alone.
- [ ] A test asserts that after the fixture's teardown, `lf.get_config().sink` **is** the sink
      events are actually delivered to. This is the criterion the `_config` restore fails today;
      it must fail against the current teardown and pass against the replacement.
- [ ] The swap control is mutation-tested by pointing it at a stale sink, and it fails.
- [ ] The control lives in one place, not once per harness.

### FR-004: Every claim 1.0.0 falsified is corrected wherever it is stated

#### Description:

Three claims in this repo were true of 0.6.0 and are not true of 1.0.0, and one is true of both but
is written version-anchored to 0.6.0. Each is stated at more than one site, and a fix at one site
leaves the others reading as settled fact.

1. **`_emit`'s orphan-path rationale.** Its docstring says swallowing matters most on the orphan
   path because "a sink that raises raises here, in the middle of business logic, rather than on the
   worker thread where the span path absorbs it." 1.0.0 absorbs an `Exception` from the sink on
   **both** paths. Executed during authoring against a sink whose `emit` raises, with no span open:
   on 0.6.0 the `RuntimeError` reaches the caller; on 1.0.0 the call returns and the library writes
   `absorbed a failure while emitting an orphan log (RuntimeError); the event was lost`.

   The `try` stays, and the corrected docstring must say why — **not** because
   `KeyboardInterrupt`/`SystemExit` propagate, which would be wrong twice over, since `except
   Exception` does not catch them either. It stays because a failure raised *inside `_emit` itself*
   never reaches the library's absorb at all: `_emit` splats the caller's fields into
   `level_fn(message, echo=False, **fields)`, so a field colliding with a reserved keyword raises
   `TypeError: log_foundry.api.info() got multiple values for keyword argument 'echo'` at the call
   boundary. Measured on **both** versions. That is the live failure the guard catches, and it is
   the one FR-005 widens.

2. **The stitching note in `lambdas/info/shared-layer.md`** says `lf.continue_trace(traceparent)`
   is "shipped as of log-foundry 0.3.0". It was, and on 0.6.0 it is **sticky** — measured: one call
   keeps every later root span in the inbound trace, so a warm container's second, unrelated
   invocation silently joins the first one's trace. 1.0.0 makes it one-shot. A note recommending a
   future fix must not leave a reader to discover that the version it names would have made the fix
   wrong.

3. **"`log-foundry` 0.6.0 exposes no way to turn stack capture off."** Re-verified against 1.0.0's
   `Config` during authoring and **still true**, so the decision stands; the version it names does
   not. Each site already says "if a later `log-foundry` offers an opt-out, this is revisited",
   which is an instruction that goes stale silently unless the version moves with the check.

`_reset_baggage`'s "there is no public clear" is **not** listed here: a repo-wide sweep during
authoring found no restatement of it outside the docstring FR-002 already replaces, and an FR
covering an empty population is a criterion that cannot fail.

**The population of sub-1.0.0 version references is enumerated here rather than left to a
judgement call at build time**, because "except where it is describing history" is a carve-out a
builder discharges by classifying whatever is left as history. Live sites, all of which move:
`lambdas/control-plane-common/requirements.txt` (the block FR-001 rewrites),
`lambdas/Dockerfile:58`, `lambdas/info/shared-layer.md:188`,
`docs/decisions/control-planes.md:235` and `:253`, `docs/decisions/identity-and-access.md:595`,
`docs/testing/owed.md:336`, and `infra/modules/observability/README.md:22`. Completed spec files
and delivery docs under `docs/specs/` and `docs/spec-delivery/` are history and are **not** edited.

#### Acceptance Criteria:

- [ ] Each of the three claims is corrected at every live site listed above.
- [ ] `_emit`'s corrected docstring names the in-`_emit` `TypeError` as the reason the guard stays,
      and does not attribute it to `KeyboardInterrupt`/`SystemExit`.
- [ ] A repo-wide search for a `log-foundry` version below 1.0.0, excluding `docs/specs/` and
      `docs/spec-delivery/`, returns only the eight sites listed above before the change and none
      after it.
- [ ] A test asserts that on the **installed** version, `max_stack_bytes` is the only `Config`
      field controlling stack capture and its validator still rejects a value below 1 — so the
      "no opt-out" claim is re-derived by the suite on every run rather than re-dated by hand, and
      a future release that adds an opt-out reddens the decision instead of silently outliving it.
- [ ] `python3 scripts/validate_docs.py` is green.

### FR-005: The three behaviours the upgrade changes are pinned

#### Description:

Three 1.0.0 changes reach this repo's surface. Two are silent; the third is the opposite, and is
the reason it belongs here rather than in a later spec.

**`@trace` now refuses a generator function at decoration.** On 0.6.0 it accepts one and traces the
*call* rather than the iteration — the span opens and closes before the body runs, reporting
`status: "ok"` and a duration of microseconds for work that has not happened yet and may still
raise. 1.0.0 makes it `TypeError: @trace cannot trace the iteration of the generator function …`
**at decoration**, which for this fleet means at module import, which means a cold start that
fails. Executed against both versions during authoring.

No function currently decorated with `@observability.traced` or `@observability.step` is a
generator — 112 decorated functions checked by AST walk during authoring, zero hits — so the bump
is safe as it stands. It is pinned anyway, because the cost of getting it wrong later is a whole
plane failing to start, and because SPEC-226 instruments `cpcommon.s3_listing`, whose two listers
**are** generators. A guard here means that spec meets a build failure on its own branch rather
than a cold start in production.

**`fields` became a reserved parameter name on the emitters.** The signature went from
`info(message, *, echo=False, **fields)` to `info(message, *, echo=False, fields=None, **kv)`.
`observability._emit` splats a call site's fields into that call, so `observability.info("m",
fields={"a": 1})` is now **reinterpreted** rather than rejected. Executed against both versions:
0.6.0 lands `{"fields": {"a": 1}}`, 1.0.0 lands `{"a": 1}`. A **non-mapping** — `fields="x"` — is
not dropped as a whole event: measured on 1.0.0 the event still lands with `fields: {}`, every
counter stays at zero, and the library writes `absorbed a failure while merging the fields=
argument (TypeError); the fields= argument was ignored`. So the value is lost, not the event, and
only the mapping direction is genuinely silent.

No call site passes `fields` or `echo` as an explicit keyword today, confirmed by an AST walk of
every `observability.info`/`warning`/`error`/`stamp` call in `lambdas/`. That walk cannot see
through a `**kwargs` splat, and there are seventeen of those — six in `cpcommon/lock.py`, four in
`dq_check_query.py`, four in `dlq_drain.py`, and three more — so each was **read individually**
during authoring; all pass fixed keys. `cpcommon/lock.py` separately maintains its own, narrower
reserved-name set through `assert_fields_are_free`, which this FR does not merge with `_emit`'s:
they guard different collisions, and one list covering both would be right about neither.

**The emitters no longer let a sink failure reach the caller.** FR-004 corrects the docstring; the
criterion below asserts what is still *this repo's* to guarantee. It deliberately does not assert
that a raising sink is absorbed — 1.0.0 absorbs that before `_emit`'s `try` is ever entered, so
such a test passes with the guard deleted and proves nothing about this code.

#### Acceptance Criteria:

- [ ] `_emit` drops a field named `fields`, warns naming the message, and emits the remaining
      fields — mirroring the existing `echo` handling.
- [ ] A test asserts the drop **and** that the surviving fields still land, so a guard that dropped
      everything would fail.
- [ ] A test asserts that `observability.info("m", fields=…, echo=…)` — the collision that raises
      `TypeError` inside `_emit` on both versions — does not propagate and the caller continues.
      Mutation-tested by removing the drop: the test must fail, which is what makes it a test of
      this repo's guard rather than of the library's.
- [ ] The existing `test_ACCEPTED_the_span_error_stack_may_carry_file_contents` tripwire still
      passes against 1.0.0.

---

## Interface Contract

`cpcommon.observability`'s public surface is **unchanged** by this spec — `init`, `flush`, `traced`,
`step`, `stamp`, `info`, `warning`, `error`. No call site outside the module changes.

What changes inside it:

```python
# the private reset — before
from log_foundry import context as lf_context
lf_context._baggage.set({})

# after (and renamed, because it clears more than baggage)
from log_foundry import context as lf_context
lf_context.reset_context()          # clears baggage AND any adopted trace context

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

`max_stack_bytes` defaults to 32768 on both versions — the 32 KB clip is not new, and FR-001's
rewrite must not present it as though it were.

## Implementation Phases

### Phase 1: The pin and the module

- Move the pin to `1.0.0`; rewrite the requirements comment, carrying the three live dispositions
  across; update the Dockerfile's example.
- The private reset → `reset_context()`, renamed; widen `_emit`'s prohibited-name set.
- FR-002's event-borne baggage-isolation test and FR-005's tests, each mutation-tested.

### Phase 2: The harnesses

- Delete the worker retirement and the `_config` save/restore from both harnesses.
- Add the single shared sink-swap positive control and the reported-versus-delivering assertion;
  mutation-test both.
- Run the full suite on Python 3.12 against 1.0.0, green by exit code, plus `mypy`.

### Phase 3: The claims

- Correct the three claims at the eight enumerated live sites.
- Add the `max_stack_bytes`-is-the-only-control test, so the claim maintains itself.
- `validate_docs.py` green; formatter, both linters, both suites, mypy and `npm run build` green.
