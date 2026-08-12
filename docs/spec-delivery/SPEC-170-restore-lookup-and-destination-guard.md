# SPEC-170 — Restore: Request Contract, Archive Lookup & the Destination Guard

**Completed:** 2026-08-12
**Spec:** `docs/specs/SPEC-170-restore-request-lookup-and-destination-guard.md`

## What shipped

The archive read backwards, stopping deliberately short of the bill. A `mode: "restore"` request
names its space and a pasted archive id; the plane authorizes the space, rebuilds every destination
from the archived keys themselves, and then refuses the **whole** restore if any one of those
destinations is already occupied. It ends at `RestoreReady`, which is where SPEC-171 picks up.

Delivered in **one PR**, not the grants-first split 168 and 169 needed: this spec adds **no IAM at
all** (see *Deliberate deviations*).

**Lambdas — two new verbs** (the plane is now eleven functions)

- `archive-inspect-archive` — lists the archive prefix, rebuilds each destination, cross-checks the
  count, writes the restore plan to the admin bucket and returns its **key**.
- `archive-check-destination-clear` — reads the plan back, proves it is this run's, and heads every
  destination.

**`arcommon` — two new modules**

- `restore.py` — the restore request's contract and resolution, the paginated lookup, and the
  manifest cross-check with its three tolerances.
- `guard.py` — the bounded, short-circuiting existence check and its bounded refusal sample.

**`arcommon` — extended**

- `paths.validated_archive_id` — the pasted id, held to `validated_request_id`'s **same compiled
  regex**. One UUID rule, differing only in the refusal's wording.
- `plan.restore_plan_key` / `write_restore_plan` / `load_restore_plan` — the fourth admin-bucket key
  layout, in the module that owns the other three.
- `messages` — three refusal bodies, and a **second resolver** over the same body table.
- `config.RESTORE_HEAD_CONCURRENCY` / `RESTORE_CONFLICT_SAMPLE`.

**ASL** — the restore arm's two states plus `RestoreReady`, and `mode` threaded onto every failure
seed and `RecordFailure`.

### The bounds, and what sizes each

| Constant | Value | Measured against |
|---|---|---|
| `RESTORE_HEAD_CONCURRENCY` | 8 | **botocore's default `max_pool_connections` (10)** — not the thread count |
| `check-destination-clear` timeout | 600 s | 20,000 heads, 8 at a time, at a pessimistic 100 ms each ≈ 250 s |
| `inspect-archive` memory | 1024 MB | the restore plan held live — recomputed, not inherited: an entry carries **two** keys |
| `RESTORE_CONFLICT_SAMPLE` | 5 | a presentation bound: one collision is not a pattern, twenty is not a sentence |

**The concurrency's first value was wrong and its own test caught it.** "Workers × timeout /
latency" says to widen the pool until the arithmetic fits, and 32 read as comfortable. But
`boto3.client("s3")` takes botocore's default pool of 10: threads past that do not each get a
connection, they contend, and urllib3 opens and discards sockets rather than reusing them. A pool of
32 buys throughput the client cannot deliver *while every bound computed from it reads as
satisfied*. The fix was to accept 8 and buy the **time** instead, and
`test_the_guards_pool_fits_inside_the_clients_connection_pool` reads the ceiling off botocore —
because that is the term a later "just raise the concurrency" would skip.

### Deliberate deviations

1. **`restore_archive_incomplete`, not FR-005's `archive_incomplete`.** That code was already
   SPEC-169's, for a copy that fell short; its body promises "nothing was deleted and your files are
   exactly where they were" — meaningless about a restore — and the ASL seeds the literal in
   `RollbackReturnedSeed`. Behaviour unchanged; the spec is amended in place.
2. **FR-006 required no IAM change.** `SourceDataRead` already grants the `s3:GetObject` a
   `HeadObject` authorizes against, and `ArchiveVaultList`/`ArchiveVaultWrite` already cover the
   vault — all SPEC-169's. Both are now **asserted** rather than assumed
   (`test_the_destination_guard_reads_with_GetObject_and_never_with_ListBucket`), because the
   failure mode of the wrong grant is a *false pass*: a role holding only `ListBucket` gets a 403 on
   every head, and a guard reading 403 as "clear" would silently overwrite everything.
3. **"validate-authorize-restore" is a BRANCH of the existing front door, not a second Lambda.**
   `ChooseMode` sits downstream of validate-authorize and reads `$.mode` off the parsed request; in
   the raw Pipe record that field is inside an escaped JSON string ASL cannot look into. A separate
   restore validator would need the branch to happen before anything had parsed the body. Both modes
   therefore return the **same five keys** — a shared `Validated` Pass naming a path one mode lacks
   would raise an uncatchable `States.Runtime` — so `source` is the authorized SPACE in both, minus
   the selection.
4. **`mode` now rides the failure path.** One body table under **two prefixes**: the codes only one
   mode can reach are unambiguous, but `forbidden`, `malformed_event` and `invalid_request` are
   reachable by both and are exactly what a single "Couldn't archive that" prefix gets wrong.
   `ValidateFailureSeed` supplies a literal `null` — its input is the raw error, so a `$.mode` there
   would raise on the failure path itself.

### Not met by this spec, deliberately and not silently

**FR-001 AC3 and AC4** — the FIFO `MessageGroupId` (SHA-256 of `{archiveBucket}/{archiveRoot}`) and
`MessageDeduplicationId` (`requestId`) are properties of the **producer**, and the producer is the
browser, which SPEC-172 builds. Nothing here enqueues, so there is no Python home for either rule
and a test could only restate it. **SPEC-172 owes both.** Until then two concurrent restores of one
archive are not serialized and both could pass the guard — the same TOCTOU table-share and file-send
carry, and here neither run deletes anything.

## What changed from earlier specs

- **SPEC-169's `test_no_restore_verb_requires_the_manifest` fired, as designed.** The cross-check
  reads `_manifest.json`, which the sweep forbade. The exemption is `arcommon/restore.py` **only**,
  and it is sound because the tolerance is now pinned three ways (absent, unreadable, malformed all
  proceed; only a disagreement refuses). A companion test keeps the other half shut: **no verb** may
  name the basename, including SPEC-171's.
- `RestorePlaceholder` is gone, replaced exactly as its own comment predicted — the restore arm's
  **target**, not the branch.

## What review changed

_(fresh-context review ran on the implementation commit; findings and their disposition below)_

## Verification

`ruff check lambdas/`, `mypy` (zero over the shared layers, `arcommon` included), `pytest lambdas/`
and `tofu validate` + `tofu fmt`. No portal file changed, so the React suite and `npm run build` are
untouched. **No user-facing surface, so no Help & guides change** — SPEC-172 owns the UI and the
wording a user will actually read.

### Live check — OWED

Script: `docs/testing/archive-restore-e2e.md` → *SPEC-170*. It runs on the archive SPEC-169's own
live check produces, so **do the two in one session, 169 first**.

The assertion that matters is a **negative** one: after the `destination_occupied` refusal,
`head-object` on an archived object must show **no `Restore` header**. A refusal that had already
initiated retrieval looks identical from the UI and costs the user hours and money.
