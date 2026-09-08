# Completed Spec — SPEC-226: Child Spans for the Seven Flat Planes

## What was completed?

- Seven control planes that reported one flat duration per invocation now emit child spans, so
  "the verb took 8 s and failed" becomes "the copy took 40 ms, the upload took 7.9 s and raised".
- **Three shared operations** carry a step. They are not the only bounded functions in `cpcommon`
  — `transfer.results.results_location` is bounded too and carries none — they are the bounded ones
  whose cost is worth a span: each does the I/O that dominates its verb.
  `transfer.copy.copy_batch` (`copy-batch`),
  `transfer.manifest.write_manifest` (`write-transfer-manifest`),
  `transfer.results.read_failed_items` (`read-failed-items`). They reach archive, file-ops,
  file-send and table-share.
- **Three planes get their spans in their own code**, because the shared layer offers them no
  bounded function to step. For shared-space that is because everything durable it does runs
  through a function its callers invoke per recipient or per member; results-conversion and
  table-builder simply reach none of the shared transfer engine at all. shared-space:
  `write-roster` on `cache.write_roster_to_all`, `notify-members` around each notification loop.
  results-conversion: `download-results`, `write-conversion`, `upload-conversion`. table-builder:
  `athena-run-ddl`, `infer-columns`, `glue-get-table`, `glue-update-table`, `glue-read-back-table`.
  `diff-schema` gets none — its body does no I/O — asserted so a later author does not add one.
- **New guards.** `lambdas/test_child_spans_per_plane.py` holds each of the seven planes to a named
  verb and a named span, reddenable one plane at a time.
  `control-plane-common/test_observability_transfer.py` holds the instrumented set exactly, the five
  shared functions that must never carry a step, the call bounds, and span count independence of N.
  `test_observability_cpcommon.py` gains a fleet-wide sweep refusing a step name that any verb
  already uses for its own span.
- **`lambdas/conftest.py`'s `_CapturingSink` drains on every read**, so an absence assertion over it
  means "nothing was emitted" rather than "nothing has been flushed yet", plus a
  `child_spans(parent, name)` reader every per-plane case uses.

### Deliberate deviations

- **Four of the spec's own claims were false and the spec was corrected, not worked around.**
  `table-builder-execute-ddl/athena_run.py` does not exist (the runner is a bound *instance* shared
  with two other planes, so its method must not be decorated); `apply-refresh` makes **three** Glue
  round trips, not four; `execute-ddl`, `infer-schema` and `load-table-definition` were already
  those verbs' own root span names; and `write_manifest`/`read_failed_items` are bounded at **most**
  once, not once, so a test asserting exactly one call fails on an empty transfer.
- **`write-manifest` was renamed to `write-transfer-manifest`.** It named three different things
  across the fleet — `archive-write-manifest`'s whole verb, a pre-existing data-quality step, and
  this spec's new one. Checking each span against its *own* verb cannot see that, which is why the
  guard added here sweeps every step name against every verb name. The pre-existing collision is
  named in that guard as an item, with a companion test that fails if the exemption goes stale.
- **FR-005 ships a conservative budget and owes its precision.** The day-object ceiling is derived
  from `log_sweep.LARGE_OBJECT_WARN_BYTES` over a measured event size, but that constant is a
  detector deliberately sized to fire early rather than the true ceiling, and there is no invocation
  rate on a fleet with no traffic. Both are in [`owed.md`](../testing/owed.md). A rate-free
  alternative was built and rejected: as a share of each plane's per-invocation volume the rate
  cancels, but the denominator is the quantity this spec inflates.
- **The notification loops were extracted per verb, not hoisted into a shared emitter.** The dedup
  ids are FIFO deduplication keys on notifications a user sees and the three verbs build them
  differently; `delete_space`'s failure-path notification is deliberately outside its helper.
- **The drain repairs nothing that pre-existed.** Measured with every step applied: removing it
  reddens only the two tests written for the drain itself, and no test that existed before. The
  spec's "thirteen broken tests" are history about `lock.py`, which this spec forbids stepping. It
  is a forward guard — what it buys is that an absence over the shared sink means "nothing was
  emitted". (An earlier draft of this bullet said "exactly one test", which was true when written
  and went stale the moment the second drain test was added two commits later. The property is the
  claim; the count is not.)

## What changed from earlier specs?

- `cpcommon/transfer/`'s three entry points now open a span. Nothing about what they do to an object
  changed, and none of them narrated before, so no existing event's delivery timing moved.
- `lambdas/conftest.py`'s `_CapturingSink.events` became a draining property over a private list.
  Every existing reader is unaffected; the list it returns is the same object.
- SPEC-130's `step` is untouched and still a thin alias — the property that keeps a failure
  propagating under `@notifies_on_failure`.

## Verification

`pytest lambdas/` 3343 passed exit 0, ruff, mypy, `validate_docs.py` and its corpus, feature flags,
app-managed paths and its corpus, the API contract, and the portal's build / `check:bundle` / eslint
/ prettier / vitest — all green locally on the rebased branch, then green in CI.

Every guard was mutation-tested; the seven per-plane cases redden one plane at a time. The four
transfer planes are planted by moving the verb off the instrumented path rather than by removing the
shared step, which would redden all four and prove nothing per plane. What is **not** verified is
that a span reaches the real log store with its parent intact — that is a browser-drivable check,
in [`e2e.md`](../testing/e2e.md) beside the archive rows that already read the same store.
