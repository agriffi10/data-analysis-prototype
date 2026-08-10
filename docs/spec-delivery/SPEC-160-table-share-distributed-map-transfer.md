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
- **The per-recipient entry gained `reason` and `failedItems`.** Nothing downstream reads them;
  they exist because the finish Map's pass-through references every field **by path**, and an absent
  path in a `Pass` raises an uncatchable `States.Runtime` — so the shape had to be uniform, not
  merely correct.
- **No `component-inventory` row.** That inventory is explicitly `apps/portal/src/` and lists no
  Lambda layer; `cpcommon.transfer` is recorded in `architecture.md`'s *Layers* bullet instead,
  where `cpcommon`'s modules are already enumerated.
- **No new reason code for a failed batch beyond `copy_failed`**, plus one new whole-request code,
  `transfer_results_unreadable`, for an export that cannot be read, attributed **or reconciled**.
- **A whole-batch failure fails every recipient in that batch.** Items batch recipient-major, so a
  batch spans recipients only when one has fewer objects than the batch size — but then a child
  that dies outright takes all of them down. Fail-closed on purpose (the batch reported nothing per
  item, so which of its items landed is unknown), and a real narrowing of the pre-160 isolation,
  where each recipient had its own invocation and retry budget. Recorded in `decisions.md`.
- **The per-recipient entry drops the raw `{Error, Cause}` and carries the decoded `reason`.** The
  final summary therefore reads `{kind, name, status, reason}` for a guard refusal where it used to
  read `{kind, name, status, error}`; a *create* failure still carries the raw error, unchanged.
  Nothing reads the execution output, and the raw object stays in the execution history at the
  state that produced it. This is a payload decision, not tidying — see the review section below.
- **`collect-transfer-results` consumes `guardResults`** rather than passing it on.

### The review that changed the shipped code

The fresh-context review found four things worth recording, all fixed on the branch before merge:

1. **A 256 KB payload breach in the ordinary case.** Carrying `guardResults` forward *and*
   re-emitting the raw error put three copies of every refusal on the state by the time the finish
   Map merged — **108% of the limit** at 50 conflicting recipients, i.e. re-sharing a table most
   recipients already have. `States.DataLimitExceeded` lands **on a Map**, outside every `Catch`, so
   the sender would have heard nothing at all. Fixed by consuming `guardResults` and decoding the
   error; both peaks are now modelled (42% / 45%) where the old test still described the pre-160
   single-Map shape and certified a bound that no longer existed.
2. **Silent-success paths in the results reader.** An entry naming no object, a result file that
   was not a list, and a manifest listing no files all returned "no failures". They raise now — and
   the reader returns the **item count** it accounted for, which the collector reconciles against
   the manifest's own `itemCount`, closing the well-formed-but-partial export that no shape check
   can catch.
3. **Attribution keyed on the recipient name alone**, dropping the `kind` the manifest carries. A
   user and a shared space can share a name, so one failed object in space `acme` denied user
   `acme` a table they had received. Now keyed on `(kind, name)`.
4. **The instrumentation guard's skip.** `copy-objects` legitimately has no `notifies_on_failure`,
   but the guard *skipped* any verb without one — so an accidental removal was indistinguishable
   from a deliberate one. It now asserts against a named `_NO_NOTIFIER` list, which immediately
   surfaced `release_refresh_lock` (SPEC-157) sitting in that position undeclared.

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

## User-facing docs sweep

Nothing in **Help & guides** changed. The share flow, its wording, its caps and its notifications are
identical; the only new user-visible string is a failure notification
(`transfer_results_unreadable`), and `helpContent.ts` documents flows rather than enumerating
failure messages.

## Verification

`ruff`, `mypy` (the five layers, at zero), `pytest lambdas/` (2,297 passed, coverage 97%) and
`tofu validate`/`fmt` all green locally. `states:DescribeExecution` on
`execution:{machineName}:*` was **checked against the current AWS docs** — it is their documented
least-privilege form verbatim; the `execution:{name}/{mapRunLabel}:*` variant belongs to
`RedriveExecution`, which is not granted. New guards: the ASL/IAM suite
(`test_state_machine_table_share.py`, 21 tests) covers the top-level-Map property, the batcher
sizing against `cpcommon`'s constants, both `IsPresent`-before-value Choices, and the
`states:`-on-the-wrong-role swap.

**DISCHARGED (2026-08-10): the Map Run `manifest.json` shape.** A real one from the first live
share is transcribed byte-for-byte into `test_transfer_cpcommon.py` (`_LIVE_MANIFEST`) and parsed
by the shipped reader. It settles the one assumption the docs could not: `ResultFiles` is a mapping
of group name to a list of `{Key, Size}`, empty groups are present as empty arrays, and **`Key` is
an absolute key from the bucket root** — which is what the reader assumes when it hands it straight
back to `get_object`. Had it been relative, every share would have failed
`transfer_results_unreadable` for the wrong reason. It also shows Step Functions appending
`{mapRunUuid}/` under the configured prefix; nothing depends on that, because the manifest's own key
comes from `ResultWriterDetails`.

**Still owed live: the SCALE half of Phase 4.** The run above exercised one small batch (its
`SUCCEEDED_0.json` is 1,011 bytes — a single child execution), so what is still unproven is a table
of **several hundred objects** to two recipients where one conflicts: several child executions, the
conflicting recipient refused with `conflict` and **no child execution of its own**, the other
receiving every object at the correct key, and `logs/service=table-share/` carrying one
`batch copied` event per child. The batching arithmetic and the per-recipient attribution across
more than one batch are what that run tests and this one did not.
