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
carry, and here neither run deletes anything. **— Superseded 2026-09-15: the group id did not change
this.** The Pipe starts executions `FIRE_AND_FORGET`, so two restores of one archive still run at
once — and "neither run deletes anything" no longer holds: the first to finish sweeps the vault, and
the second's copy-back can overwrite a file the user edited after the first restored it.
`docs/decisions/archive-and-restore.md` (*The group id orders the STARTS, not the runs*) has what
follows.

## What changed from earlier specs

- **SPEC-169's `test_no_restore_verb_requires_the_manifest` fired twice, as designed.** First for
  the cross-check in `arcommon/restore.py`, then again for the collision guard review added to
  `arcommon/plan.py`. Both exemptions are LAYER modules and both are sound because each has one
  tested behaviour — the tolerance (absent, unreadable, malformed all proceed; only a disagreement
  refuses) and the refusal. A companion test keeps the other half shut: the only **verb** that may
  name the basename is the one that writes it, including against SPEC-171's.
- **SPEC-169 wrote the record inside the user's own key namespace**, which is where finding 1 below
  comes from. The layout is unchanged — FR-003 AC2 specifies the exclusion, so the record staying at
  the archive root is the spec's own model — and the collision is refused up front instead.
- `RestorePlaceholder` is gone, replaced exactly as its own comment predicted — the restore arm's
  **target**, not the branch.

## What review changed

A fresh-context review of the implementation commit found six real defects. All six are fixed; two
of them are the kind this arc exists to prevent.

1. **A user's own `_manifest.json` at the SPACE ROOT destroyed itself and bricked the archive.**
   An object's archive key is `{archivePrefix}{relKey}` and the record's is
   `{archivePrefix}_manifest.json`, so a file at `{spaceRoot}_manifest.json` maps to exactly the
   record's key. `assert_not_reserved` refuses selecting the space root as a *folder*, but naming
   that file directly passed containment, the reserved rule and the marker rule. The copy would
   land, `write-manifest` would **overwrite** it, `delete-source` would then delete the original —
   versioning is off — and **the run would report success**. The archive was also permanently
   unrestorable: the restore excludes that key as the record, counts one fewer than the record
   claims, and refuses `restore_archive_incomplete` for everything archived alongside it; alone, it
   restores as `archive_not_found` against a receipt the user is holding. Now a whole-request
   refusal (`reserved_object_name`) in `plan._assert_not_the_record`, reachable through both
   selection kinds, and **exactly as narrow as the collision** — `reports/_manifest.json` still
   archives and restores like any other file.
2. **The guard did not short-circuit in the case FR-004 AC3 names.** The sample check sat after a
   full round *and* required `RESTORE_CONFLICT_SAMPLE` collisions, so fewer than five meant no
   short-circuit at all: **measured, 20,000 heads to report a collision at index 3** — and one
   re-created file is the likeliest real conflict there is. It now stops at the round that finds
   the first one. The test that named this property could not fail: its fixture used 64
   *consecutive* collisions, which fills the sample inside the first round. It now uses one.
3. **A malformed *restore* was worded as an archive failure** — the exact case the two-prefix
   design exists for. `mode` came from `_check_contract`'s return, so every refusal raised *inside*
   it (bad request id, unknown field, non-string actor) was reported before the mode existed. The
   wording mode is now seeded from the untrusted body first, which is safe because the value
   selects between two fixed prefixes and reaches nothing else.
4. **The EventBridge `TIMED_OUT` door never passed `mode`.** Unreachable today — nothing on the
   restore arm waits — but SPEC-171's 3–5 hour retrieval makes the timeout *predominantly* a
   restore event, and the archive sentence promises "nothing was deleted and your files are exactly
   where they were", which says nothing true about a restore. The door now reads the mode out of
   the same raw body the actor comes from, and `restore_timed_out` ships with it.
5. **`derive_destinations` hand-rolled the paginator this plane already shares.** It is the third
   listing of the same prefix; `list_data_objects` takes an `ignore` predicate for exactly this
   (SPEC-165). The argument against reuse applied to the *default predicate*, not to the paginator.
6. **The restore's `MessageGroupId` rule was recorded nowhere.** `sqs.tf` documented only the
   archive-mode rule, so nothing would have told SPEC-172 that restores key on the *archive*. Now
   written where its reader will be standing, marked as unenforced.

Two tests were also strengthened: the manifest-record sweep's companion test was a strict **subset**
of the test above it and could not fail on its own — it now asserts the exemption *list* — and a
verb test asserted `ThreadPoolExecutor` completion order as if it were a property.

## Verification

`ruff check lambdas/`, `mypy` (zero over the shared layers, `arcommon` included), `pytest lambdas/`
and `tofu validate` + `tofu fmt`. No portal file changed, so the React suite and `npm run build` are
untouched. **No user-facing surface, so no Help & guides change** — SPEC-172 owns the UI and the
wording a user will actually read.

### Live check — OWED

Script: `docs/testing/e2e.md` §4.11 Archive and restore. It runs on the archive SPEC-169's own
live check produces, so **do the two in one session, 169 first**.

The assertion that matters is a **negative** one: after the `destination_occupied` refusal,
`head-object` on an archived object must show **no `Restore` header**. A refusal that had already
initiated retrieval looks identical from the UI and costs the user hours and money.
