# Completed Spec — SPEC-160: Table Share at Scale — Transfer Manifest & Distributed-Map Copy

## What was completed?

The copy stage stopped being one Lambda's problem. Sharing a table now writes a flat
`(recipient × object)` JSON Lines manifest and hands it to a **top-level Step Functions Distributed
Map**, which batches items into the same server-side copy code as before. **Nothing a user can see
changed** — same push, same conflict rules, same notifications, same `SHARE_MAX_*` caps. That was
the point: SPEC-161 moves the ceiling, and a regression in a new engine must not be able to hide
behind a new limit.

- **`cpcommon/transfer/`** — the shared engine, because SPEC-164→167 (send files) is its second
  caller and SPEC-168→172 (archive) its third. `manifest.write_manifest` (JSONL, no trailing
  newline), `copy.copy_batch` (moved from `tscommon.copy`, reshaped), `results.read_failed_items`
  (Map Run export → per-item failures), `config` (`MAX_ITEMS_PER_BATCH`, `MAP_MAX_CONCURRENCY`).
- **`table-share-build-transfer-manifest`** — expands the copy plan across the recipients the guard
  cleared. Its key is **execution-unique** (`table-share/{digest}/{executionName}/…`), unlike the
  copy plan beside it; `copy_plan.transfer_manifest_key` / `transfer_results_prefix` own that layout.
- **`table-share-copy-objects`, rewritten as a batch verb** — reads `{"Items": […]}`, resolves
  nothing, imports no `tscommon`, and **succeeds while reporting per-item failures** so one bad key
  never costs its 49 siblings their copy. A transient fault still raises for a whole-batch retry.
- **`table-share-collect-transfer-results`** — reads the `ResultWriter` export and decides who gets
  a table. **Both groups**: `SUCCEEDED_n` for the per-item failures a succeeded batch carries, and
  `FAILED_n`/`PENDING_n` for whole-batch failures, attributed from the child's *input*.
- **The machine** — guard `Map` → build manifest → `IsPresent`-guarded `Choice` → Distributed Map →
  collect → finish `Map`. `ToleratedFailurePercentage: 100`, `STANDARD` children, bounded
  `MaxConcurrency`, `ResultWriter` export.
- **The Map's IAM landed on the state-machine role** (`sfn-permissions.json.tftpl`):
  `states:StartExecution`/`DescribeExecution` + the manifest read and results write. The Lambda
  execution role gained **nothing**.

Full reasoning: `decisions.md` → *The copy is a top-level Distributed Map, and attribution is a
verb*. Sizing evidence: `lambda-rationale.md` → *`cpcommon/transfer/config.py`*.

### Deliberate deviations

- **`tscommon/copy.py` was deleted, not left as a re-export.** The spec's Phase 1 kept it importing
  from `cpcommon` "so nothing else moves yet"; by the end of Phase 2 nothing imported it, and a shim
  is exactly the deliberate twin SPEC-156 exists to prevent.
- **`copy-objects` lost `@notifies_on_failure`** and its `tscommon` layer attachment
  (`tscommon: false` in the deploy matrix). A batch carries no actor and no single recipient, so the
  decorator's emit would resolve to nothing — a decoration that reads like a guarantee while
  providing none. The sender is told about a copy failure by the collector, via a new
  `notify.emit_recipient_failure`, which renders the sentence the decorator would have.
- **The manifest line carries `size`**, which the spec's data model does not list. The copy plan
  already measured it, and the alternative is a `HeadObject` per item to decide the multipart
  threshold.
- **The collector's output key is `outcomes`, not `recipients`** — `$.recipients` is already the
  validated request's recipient list, and overwriting it with a different shape is a trap.
- **The per-recipient entry gained `reason` and `failedItems`.** The summary's existing fields
  (`kind`/`name`/`status`/`error`) are unchanged and nothing downstream reads the new ones; they
  exist because the finish Map's pass-through references every field **by path**, and an absent path
  in a `Pass` raises an uncatchable `States.Runtime` — so the shape had to be uniform, not merely
  correct.
- **No `component-inventory` row.** That inventory is explicitly `apps/portal/src/` and lists no
  Lambda layer; `cpcommon.transfer` is recorded in `architecture.md`'s *Layers* bullet instead,
  where `cpcommon`'s modules are already enumerated.
- **No new reason code for a failed batch beyond `copy_failed`**, plus one new whole-request code,
  `transfer_results_unreadable`, for an export that cannot be read or attributed.

## What changed from earlier specs?

- **SPEC-091's `tscommon.copy` is gone**; `cpcommon.transfer.copy` replaces it and `copy_prefix`
  (whole prefix, one recipient) became `copy_batch` (mixed batch, per-item outcomes).
- **SPEC-092's recipient `Map` split into three states.** `create-table` is unchanged and still
  receives `{recipient, request}` — the finish Map builds that `Payload` explicitly.
- **SPEC-090's `plan_key` is untouched** and still deliberately not execution-unique; its docstring
  now says why that argument does not carry to the manifest.
- **A rolling-deploy window is accepted.** An execution in flight when the new code lands calls the
  new batch verb with the old event and fails its recipients (notified). Pre-production, no users;
  the spec's FR-003 forbids the recipient-shaped fallback that would have covered it.
- **`test_state_machines_cpcommon.py`'s `_load` now stubs numeric placeholders.** This is the
  fleet's first `${…}` in a value position; stubbing it to a bare word produced invalid JSON and
  failed every check in that file at once, which reads like a broken machine rather than a broken
  parser.
- **`test_instrumentation_coverage.py`'s table-share `verb_count` 6 → 8.**

## Verification

`ruff`, `mypy` (the five layers, at zero), `pytest lambdas/` (2,289 passed, coverage 97%) and
`tofu validate`/`fmt` all green locally. New guards: the ASL/IAM suite
(`test_state_machine_table_share.py`, 21 tests) covers the top-level-Map property, the batcher
sizing against `cpcommon`'s constants, both `IsPresent`-before-value Choices, and the
`states:`-on-the-wrong-role swap.

**Owed live (Phase 4):** share a table of several hundred objects to two recipients where one
conflicts — confirm the conflicting recipient gets `conflict` with no child execution for it, the
other receives every object at the correct key, and `logs/service=table-share/` carries the run.
**The Map Run `manifest.json` shape is corroborated, not demonstrated**: `ResultWriterDetails`
`{Bucket, Key}`, the `SUCCEEDED_n`/`FAILED_n`/`PENDING_n` grouping and the record fields are read
from the current AWS docs, but the `ResultFiles` object itself is not shown in them. The reader
fails **loudly** on any shape it does not recognise rather than reporting success, which is the
right failure direction — but the live run is what settles it.
