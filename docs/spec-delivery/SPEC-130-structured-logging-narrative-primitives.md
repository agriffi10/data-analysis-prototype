# Completed Spec — SPEC-130: Narrative Primitives and Function Identity

## What was completed?

Four names added to `cpcommon.observability`, which now exports seven:

- **`info` / `warning` / `error`** `(message, **fields)` — never-raise passthroughs to `lf.*`, so
  nothing outside this module imports `log_foundry` and bypasses the discipline it is built
  around. Messages are **literals**; everything variable is a field.
- **`step(name)`** — a child span around one named internal step, with its own `function`,
  `duration_ms` and `status`. A **thin** alias for `lf.trace`, deliberately kept thin: the library
  decorator is non-swallowing, and `@traced` sits outermost above `@notifies_on_failure`, so a
  step that swallowed would cost the user their failure notification.

**No call site changed.** `cpcommon` attaches to every control-plane verb; SPEC-131/132 spend the
primitives.

## What changed from earlier specs?

Two identity defects in SPEC-127's `traced`, fixed here because instrumenting on top of them would
have multiplied the damage rather than exposed it:

| SPEC-127 shipped | Now |
|---|---|
| `lf.trace(...)` with no `name` → every root span in the fleet reads `function: "handler"` (the library falls back to `fn.__qualname__`, and every Lambda entry point here is named `handler`) | `name=verb` — `function` is the verb |
| `verb` as `lf.trace(defaults={"verb": …})` — a **span** default, which reaches that span's own events and nothing nested | `verb` as **baggage**, stamped after `_reset_baggage()` so the clear cannot wipe it |

The rename is a **discontinuity in a store retained forever** (SPEC-127 FR-009): the day object
spanning the cutover holds `"handler"` before and the verb after. Accepted without migration —
rewriting appended NDJSON would risk a day of logs to save a `WHERE` clause — and `fields.verb`
stays populated on both sides, so a query filtering on the verb spans it either way.

The `defaults=` → baggage move is what makes `step` useful: with a span default, the first child
span would have carried `request_id` (baggage) but not the verb that produced it — joinable to its
run and unattributable to the verb.

## The rules, and why there is no filter

The module docstring now carries the permitted-field list (file names, S3 keys, usernames,
database/table/column names, counts and durations), the absolute line (**no data from inside a
file** — column *names* are schema, column *values* are contents), and the token/email exclusion.

There is deliberately **no runtime redaction filter**, and the docstring says so, so its absence
reads as a decision. The rule turns on *provenance* — did this value come from inside a user's
file — and no filter over a field name or a value shape can see provenance; one that looked like
enforcement would be worse than none, because it would be trusted. Enforcement is review plus the
per-call-site criteria in SPEC-131/132/133.

`echo` is **dropped and warned**, never forwarded: `**fields` would otherwise make it a silent
no-op that emits a field named `echo`. A test greps all of `lambdas/` — broader than the spec's
"four instrumented trees" so it cannot rot as SPEC-134→137 land.

## Verification

`ruff check lambdas/` clean; `pytest lambdas/` 1172 passed / 2 skipped (51 in
`test_observability_cpcommon.py`). No infra, IAM, environment variable or SPA change.

Green was not the claim. Eight mutations run against a pristine-restore harness, **all killed**:
dropping `name=verb`; dropping `set_baggage(verb=…)`; stamping the verb *before* the baggage
reset; `step` as a no-op; `step` re-raising a **new** exception of the same class (caught only by
the identity assertion, not a `pytest.raises` type assertion); removing the emitter's `try`;
forwarding `echo`; dropping `echo` without the warning.

One test-design note worth carrying forward: the failing-sink test runs on the **orphan** path on
purpose. With a span open, the batch goes to `log-foundry`'s background worker, which absorbs sink
failures itself — so a span-path test would pass with the module's own guard deleted.
