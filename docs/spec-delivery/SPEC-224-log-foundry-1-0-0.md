# Completed Spec — SPEC-224: Log Foundry 1.0.0

## What was completed?

- The fleet's structured-logging pin moved `log-foundry==0.6.0` → `==1.0.0`, deployed and confirmed
  in the image build's own install line.
- `cpcommon/observability.py` stops reaching into the library's private context: `_reset_baggage`
  became `_reset_context` and calls the now-public `reset_context()`, which clears an adopted trace
  context as well as baggage. `PROHIBITED_FIELDS` is a new module mapping that `_emit` **reads**, so
  `fields` joins `echo` as a name a call site may not use.
- Both test harnesses — `lambdas/conftest.py`'s `captured_events` and `log-sweep`'s `_install_sink`
  — lost their hand-written worker retirement, and `conftest.py` lost a `_config` save/restore.
- New suite `lambdas/control-plane-common/test_observability_cpcommon.py`. The module had none, and
  neither the `echo` drop nor the per-invocation reset was tested at all.
- Five claims were corrected across six live files, and they are **three different kinds**: two the
  upgrade falsified, one that was **never true** (the one-door rule, stated absolutely), and two
  still true but dated to a superseded version. Only the first kind is a falsification. Conflating
  them is what let the never-true one survive in the register until a reviewer found it
  contradicting this spec's own new entry, thirty-four lines below it.

### Deliberate deviations

- **`health()` was not wired in.** 1.0.0 grows `Health` from three fields to twelve, but nothing
  reads it here and where liveness would be *reported* is a design question, not part of a bump.
- **Stack capture stays on.** Re-verified against 1.0.0: `Config` still offers only
  `max_stack_bytes`, whose validator still rejects a value below 1. The 2026-07-23 acceptance and
  SPEC-195's boundary scrub both stand. The claim is now asserted by a test rather than re-dated by
  hand, so a release that adds an opt-out reddens instead of silently outliving the decision.
- **The requirements comment was rewritten, not appended to**, and the check on that rewrite is a
  test rather than a count. The count of facts the block is the sole home of was wrong four
  times running — three, then five, then six, then seven — which is the
  signature of a missing mechanism, not three oversights. A test now asserts each fact against
  the file, anchored to an identifier rather than to wording, because the first attempt at a
  "derived" check was an authoring-time procedure that nothing in the repo ran — and the count
  went wrong a fourth time, spec against block, with nothing to catch it.

## What changed from earlier specs?

- **SPEC-130's `_reset_baggage` is renamed.** Two live register entries in
  `docs/decisions/control-planes/` named it and were updated in place.
- **SPEC-127's harness design is partly retired.** The worker retirement it needed is obsolete —
  measured, `configure(sink=…)` alone leaked to the replaced sink on 0.6.0 and redirects correctly
  on 1.0.0 — and could not have stayed regardless, since `log_foundry.decorator._worker` no longer
  exists and the reach had degraded to a silent no-op behind a `getattr` default.
- **A `_config` save/restore was deleted rather than kept.** 1.0.0 holds a live sink beside the
  stored config, so restoring the config left the library **reporting one sink while delivering to
  another** — measured on the span path, where the divergence lives; the orphan path agrees even
  when it is broken.

## What this unblocked, and what it did not

`continue_trace` is **one-shot** on 1.0.0 and **sticky** before it: measured, one call kept every
later root span in the inbound trace, so a warm container's next unrelated invocation silently
joined the previous run's trace. That is why SPEC-225 was not buildable earlier and is now. SPEC-225
FR-001's ordering depends specifically on this spec's `reset_context()`, and a test here asserts
that behaviour rather than leaving it to be assumed there.

## Verification

Green locally by exit code: `pytest lambdas/` (3238 passed, 90.13% coverage), mypy, ruff, Prettier,
ESLint, vitest, `npm run build`, `validate_docs.py` and its own corpus. Every version claim was
**executed against both 0.6.0 and 1.0.0** rather than read from the release notes.

Deferred to CI and settled on the green run: that the image builds and its install layer resolves
the pin — there is no Docker daemon on the authoring machine. Discharged with the build log's
`Successfully installed … log-foundry-1.0.0`.

Seven review passes: one on the spec, two on the plan, two on the diff, two on the close. Every finding was fixed and
verified by re-planting the reviewer's own reproducing mutation. Two are worth recording because
they were invisible to a green suite: `_emit`'s guard was covered by **nothing** — deleting the
whole `try` left the fleet suite green — and `PROHIBITED_FIELDS` was **inert**, hard-coded beside
while three docstrings named it as the mechanism, which is the same "reads load-bearing, is not"
defect this spec deletes elsewhere. The close's own reviews then found a third of the same shape:
the private-name guard examined exactly one file — its own — with nothing asserting it had reached
the tree.

A mutation battery also reported full coverage against a **red closing baseline**, because
`git checkout` cannot restore an untracked file and one plant stayed stuck. Bracketing on both
sides is what caught it, and clearing it revealed a guard that had genuinely survived.
