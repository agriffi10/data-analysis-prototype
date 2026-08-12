# SPEC-169 — Archive: Source Resolution, Glacier Transfer & Source Deletion

**Completed:** 2026-08-12
**Spec:** `docs/specs/SPEC-169-archive-transfer-and-source-deletion.md`

## What shipped

The archive plane now archives. A validated request is expanded into a copy plan, copied into the
vault at `GLACIER` by a top-level Distributed Map, **checked against a commit gate**, and only then
does anything get deleted — followed by a receipt the user can read.

Delivered in **three PRs**, grants first, because SPEC-168's merge apply went red when a role's
grants and the resources they authorize shipped together.

- **PR1 (#437)** — `cpcommon.transfer.copy_batch` gained an optional **per-item** `storageClass`.
  Absent means the argument is *not passed*, so table share and file send issue byte-identical
  `CopyObject` calls; it is set on `CreateMultipartUpload` as well, because a single-path
  implementation would archive everything under 5 GiB to `GLACIER` and everything over it to
  `STANDARD`, silently.
- **PR2 (#438)** — the deploy role's `events:` grant for the timeout rule, and the admin bucket's
  `archive/` lifecycle rule.
- **PR3 (this one)** — everything else.

**Lambdas — seven new verbs**

`inspect-source`, `build-transfer-manifest`, `copy-objects`, `collect-transfer-results`,
`rollback`, `write-manifest`, `delete-source`, `write-receipt` (the plane is now nine functions
including validate-authorize and notify-failure).

**`arcommon` — four new modules**

- `plan.py` — the expansion (paginated, per-key containment re-check, overlap collapse, the caps)
  and **all three** admin-bucket key layouts: the plan and the results prefix keyed by the request
  alone, the manifest keyed by the **execution** as well.
- `delete.py` — the batched deleter both delete verbs use, with SPEC-151's per-item `Errors`
  discipline and a pre-check that refuses the whole list before issuing anything.
- `receipt.py` — the renderer, the writer, and a Python `human_bytes` mirroring the file browser's
  `formatSize` (binary units, one decimal, TB ceiling — SPEC-155 FR-007).
- `manifest.py` — `_manifest.json`, the integrity record.

**The state machine**

`InspectSource → StampExecution → BuildTransferManifest → HasTransferItems → TransferObjects
(Distributed Map) → CollectTransferResults → **CommitOrRollback** → WriteManifest → DeleteSource →
WriteReceipt → ArchiveComplete`, with `Rollback` on the gate's other arm. Plus the top-level
`TimeoutSeconds` (10,800), the EventBridge `TIMED_OUT` rule, `ar_notify_failure`'s second door and
its 15s → 60s raise — all in one PR, because a ceiling that cannot notify is SPEC-152 satisfied on
paper and silent in practice.

**IAM** — the execution role gained the source list/read, the receipt write scoped to
`*/archive/*`, the vault, `{admin}/archive/*`, `states:DescribeExecution` for the timeout door, and
`DeleteObject` on the two space buckets **with an explicit Deny** under `athenaresults/`,
`user_settings/`, `archive/` and on any `DO_NOT_DELETE.txt`. The Distributed Map's own grants went
to the **state-machine** role (SPEC-160 FR-006).

### The caps, and what sizes each

Each is computed by a test that reads `locals.tf` back, never asserted as a number.

| Constant | Value | Bounded by |
|---|---|---|
| `ARCHIVE_MAX_OBJECTS` | 20,000 | the copy plan held in memory by inspect-source **and** delete-source |
| `ARCHIVE_MAX_BYTES` | 3 TiB | the machine's ceiling at a **makespan** rate (500 MB/s), plus child overhead and the seven serial verbs (worst run ~8,100s against 10,800s) |
| `ARCHIVE_MAX_OBJECT_BYTES` | 10 GiB | `COPY_TIMEOUT_SECONDS` — one object is one worker (429s against 900s) |

### Deliberate deviations

- **`ARCHIVE_MAX_OBJECT_BYTES` is not in the spec.** FR-001 names two caps; the arithmetic needs a
  third. A batch is one round of the worker pool and **one object is one worker**, so nothing else
  bounds a single object: S3 accepts 5 TiB, which is ~220,000s at the conservative rate — 240× the
  batch timeout. Without it the makespan model certifies the distributed case only, which is
  SPEC-166's recorded finding.
- **The rollback deletes by listing the archive prefix**, where FR-004 AC3 says "the objects the
  collector reports as successfully copied". The engine reports counts, never keys (deliberately),
  and the prefix is this request's alone — so the listing yields exactly that set *and* catches
  objects a batch copied before it died and never reported. Every key is asserted to sit under the
  archive root before deletion.
- **The receipt's "Original path" is the SPACE root, not the selected folder** the spec's
  illustrative sample shows. `archived_key` keeps every object's path relative to the space root, so
  naming the selection would pair it with an archive prefix that does not correspond to it — and a
  200-item selection has no single original path. Rooted this way the two lines are exact inverses
  for every object. The em dash placeholder is an ASCII hyphen, matching the plane's wording rule.
- **The empty-transfer branch refuses rather than succeeding.** FR-002 AC7 asks for the Map to be
  skipped; the skip arm leads to a failure seed, because a receipt claiming zero files archived is
  worse than a refusal (FR-001 AC6) and FR-001 already makes the branch unreachable.
- **No `component-inventory/` row**, which the spec's Phase 6 asks for. That inventory documents
  `apps/portal/src/` only — no file in it names a Lambda layer — so a Python row would be a new
  area, and the router's own rule is that a new row appears only when a whole area does. The
  `cpcommon.transfer` extension is recorded in `decisions.md` and `architecture.md` instead.
- **A collector fault (unreadable export) does not roll back.** It is a whole-request terminal with
  the source untouched; a collector that cannot read the export cannot say what there is to roll
  back, and the residue is swept by the bucket's own expiry — the same disposition FR-004 AC4
  already accepts for a partially failed rollback.

## What changed from earlier specs

- **`test_archive_bucket_isolation.py`'s `..._holds_no_grant_on_any_data_bucket_yet` is gone**,
  replaced by positive assertions: the receipt write is the only write into a user's space, the
  delete is scoped to the space buckets, and each of the four Deny patterns has its own case.
- **Two tripwires in `test_state_machine_archive.py` fired as designed** and were replaced by their
  positive twins (the ceiling + its rule; the Task set is the nine verbs).
- `ar_notify_failure` grew a second door; its `test_there_is_no_eventbridge_timeout_door_yet` is
  replaced by the door's own suite.

## What review changed

Three defects, found by a fresh-context review of the finished branch and fixed before the PR.

- **A reused request id could get the wrong data deleted.** The id is browser-supplied and keys
  the plan, the archive prefix, the record and the receipt; the queue's dedup window is five
  minutes against a three-hour ceiling. `plan.load` now takes the request and refuses a plan that
  does not describe it (`plan_superseded`), so a run cannot pass its own commit gate and then
  delete another execution's selection. And inspect-source refuses a request whose archive prefix
  already holds anything (`request_id_reused`) — without it, a later run's ROLLBACK would delete an
  EARLIER completed archive out of a bucket with versioning off. Both are in `decisions.md`.
- **An object under an `archive/`, `athenaresults/` or `user_settings/` folder at ANY depth would
  have been copied to Glacier and then failed mid-delete.** The IAM Deny cannot be anchored at the
  space root (`*` matches `/`), where the code's reserved-folder rule deliberately is. Refused at
  expansion now, whole rather than silently excluded, naming the folder.
- **`assert_deletable` accepted `alice/../bob/secrets.csv`**, because keys are rebuilt from a root
  and a stored relative key and that string *does* start with `alice/`. Containment is both of
  `cpcommon.paths`' rules now. Not exploitable — S3 resolves nothing — but this is the consumer
  that deletes.

Three smaller ones, same pass: the two 2048 MB verb rows claimed a memory bound no test held (one
exists now); `receipt.write` recomputed a key validate-authorize had already resolved, leaving
`archive.receiptKey` riding the whole run unread; and `Rollback`'s `Next` pointed at a seed reading
`$.error`, which a *returning* verb would not leave on the state — an uncatchable `States.Runtime`
on the failure path. Two test docstrings that overstated what they held were corrected rather than
left to read as guarantees.

## Verification

`ruff`, `mypy` (zero over the shared layers), `pytest lambdas/` — **3,313 passed, 97.5% coverage**
— and `tofu validate`. No portal file changed, so the React suite and `npm run build` are
untouched. No user-facing surface yet, so no Help & guides change (SPEC-172 owns the UI).

### Live check — OWED, and it is the one this spec exists for

Nothing offline can prove the copy lands at `GLACIER`, that the source goes, or — the important one
— that a **partial** transfer leaves the source intact. Run in one session:

1. **Personal, happy path.** Archive a folder of at least a few hundred objects from your own
   space. Confirm: objects under `s3://{archive-bucket}/personal/{you}/archive/{uuid}/` with
   `head-object` reporting `StorageClass: GLACIER` (**by `head-object`, not by inference**); the
   source folder gone from the file browser; `{you}/archive/{uuid}/receipt.txt` readable and its
   counts matching; `_manifest.json` at the archive root; the run in `logs/service=archive/` with
   one `batch copied` event per child.
2. **Shared.** Repeat from a shared space you are an active member of. The archive key must carry
   `shared/`, and the receipt must land in the shared bucket under the space name.
3. **The partial failure — the check this whole spec exists for.** Archive a folder while a Deny is
   temporarily in place on ONE key (a bucket-policy statement on that key is the cheapest way).
   Expect: the run FAILS, the notification says how many copied of how many and that nothing was
   deleted, **every source object is still there**, and the archive prefix is empty (the rollback
   removed it). Then remove the Deny and re-archive to confirm the same request id is not required
   — a failed archive is re-submitted as a **new** request.
4. **The timeout door** is not worth provoking (three hours); its EventBridge wiring is asserted in
   the suite and its Python has its own tests.

Identity note, inherited from SPEC-168's script: a laptop IAM user cannot read or write
`dat-prod-user-space` at all — the bucket policy allowlists the portal, deploy and execution roles
— so every step touching a user's space needs an assumed role or the portal UI.
