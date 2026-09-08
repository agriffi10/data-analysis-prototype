# Completed Spec — SPEC-225: One Run, One Trace — the Mechanism and the Success Path

## What was completed?

A control-plane run's success path is now **one distributed trace** instead of one per verb.

- **`cpcommon.observability` adopts an inbound traceparent.** `_shape_values` walks the four
  shapes a verb can be entered by — the state payload, the EventBridge Pipe envelope, a
  Distributed Map's `ItemBatcher.BatchInput`, and an inline Map's `request` block — and
  `_adopt_trace` runs after `_reset_context` and before the span opens. New public name:
  `run_traceparent()`, the module's ninth.
- **The producer.** `traceparent` is declared on all eleven enqueue routes' `stamped` term and
  written by `_stamped_values`, so `build_message` sends it on every message.
- **Every plane's `validate-authorize` returns it**, including archive's separate restore return
  in `arcommon/restore.py`; `describe-results` and `convert` return it from `run_traceparent()`
  rather than carrying it, because their `_CARRIED` tuple is read through `events.require` and a
  logging value must never be a `TerminalError`.
- **The machines carry it**: six `ItemBatcher.BatchInput` blocks and ten field-naming states.
- **Guards**: a parsing sweep pinned to the ten by membership, a path-resolution guard, and
  `test_one_run_one_trace.py`, which drives file-send and archive with events built from the
  deployed ASL blocks.

### Deliberate deviations

- **The extractor's body branch is narrowed to a LIST.** `_extract_request_id` used to parse a
  bare dict's `body`, which for an API Gateway payload-2.0 request is the caller's own HTTP body —
  verified by execution against `main`, which returned the caller's id. Latent for the request id
  (the router overwrites it with the gateway's), **not** latent for a traceparent, since nothing
  overwrites an adopted trace. Narrowing closed both.
- **`requestId` is per-plane in `BatchInput`, not a fixed pair.** table-share's validator returns
  none and no state downstream holds one, so an unconditional `"requestId.$": "$.requestId"` there
  would be an uncatchable `States.Runtime` on every share. Its three Map-child verbs stay
  unjoinable by request id, which is recorded rather than quietly missed.
- **Two PRs, not one** ([#690](https://github.com/agriffi10/data-analysis-prototype/pull/690) inert,
  [#694](https://github.com/agriffi10/data-analysis-prototype/pull/694) live). `Deploy
  Infrastructure` applies the ASL while `Deploy Lambdas` repoints the functions, and both gate on
  the same ECR signal — so one PR would reliably apply an ASL reading `$.traceparent` off a state
  the still-live old image does not produce.
- **The spec's own counts were wrong in four places** and are corrected in it: the sweep needs
  **five** discriminators (four select 21 states, not ten); the failure-path exclusion is **29**
  states, not 28; **five** exact-equality fixtures change, not six; and FR-002 needed the five
  allowlist constants widened, which the spec did not mention at all — four planes refuse an
  unknown top-level body field, and stamping without widening them answers every archive request
  with `malformed_event`.

## What changed from earlier specs?

- **SPEC-128's "one run is nine traces" is retired** on the success path, at all four live sites.
  The `request_id` join key it added **stays** — it is what joins anything outside the trace, and
  table-share carries no id at all.
- **SPEC-224's `reset_context` becomes load-bearing.** It clears an adopted context as well as
  baggage, which is why adoption must come after it; built the other way round, the reset erases
  the adoption.
- Three results-conversion ASL↔verb cross-checks moved from set equality to domain-key equality,
  because set equality forbids the only safe deploy order. The verb side is asserted directly.

## Verification

Local, green by exit code: `pytest lambdas/`, ruff, mypy, the six CI validators, contract
regeneration, `tofu validate` / `fmt -recursive -check`, and the portal's build, lint, format and
suite. Test names collected from the runner on both refs — nothing removed.

**24 mutations planted and run, all caught**, each re-planted from a reviewer's own reproduction.
Two frames on each PR's diff found five guards that could not fail, including a fleet sweep
satisfied by a **hard-coded constant traceparent** and an end-to-end guard that drove the
Distributed-Map shape flat.

The payload-limit headroom was **re-derived**, not re-run: 32.7% and 35.5% of the 256 KiB limit
against a 50% bar, control at 58.3%. The child-input cap likewise: 26,403 → 26,546 bytes.

**Owed:** FR-003 AC-1 — a real execution showing `BatchInput` reaches an `ItemReader`-fed Map's
child. Deferred by decision; the row and its recipe are in [`owed.md`](../testing/owed.md).
Partly discharged — all eight definitions return `OK` from `validate-state-machine-definition`,
and `ItemBatcher.BatchInputTypo` is refused as *"not supported"*, so the field is real and a red
first apply is ruled out. Runtime delivery is what remains.
