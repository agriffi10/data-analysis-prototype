# Completed Spec — SPEC-149: Refresh Table — In-Place Rebuild via `glue:UpdateTable`

## What was completed?

`apply-refresh` stopped rebuilding the table and started **updating** it. One `glue:UpdateTable`
replaces two Athena statements, as a read-modify-write on the live definition. The diff, the removal
opt-in, the eligibility checks, the notifications and the state machine's shape are unchanged — a
reader comparing the two versions sees the mechanism change and nothing else. **Still not
user-reachable**; SPEC-145 owns the browser surface, and sequencing this before it was the point.

- **`table-builder-apply-refresh`** — `_table_input` (the read-modify-write), the `UpdateTable` call
  with `SkipArchive=False`, the post-condition `GetTable`, and `update_failed`.
- **`refresh_athena.py` DELETED**, along with the per-verb runner, the shared poll budget, the
  idempotency tokens and this verb's use of `tbcommon.results`. No Athena on this path.
- **The machinery that existed only to serve it, deleted too** (review-driven, beyond the spec's
  enumerated list): `cpcommon.ddl.storage_from_definition` and its `_clause_matches_capture` /
  `_serde_properties` / `_INCIDENTAL_SERDE_PARAMETERS` helpers, `build_create_table_ddl`'s
  `table_properties=` and `if_not_exists=` parameters, and `load-table-definition`'s
  `tableProperties` threading — ~110 net lines. All were SPEC-144 additions with no remaining
  production caller. FR-001 AC4 and FR-007 AC4 both set the standard that removed things must be
  *gone*, not merely unreferenced; tested-but-uncalled code reads to the next reader as a live path,
  which is exactly the argument the spec makes about `recreate_failed`.
- **`cpcommon.ddl.mark_managed`** — a three-line door onto the `portal.managed` marker (see below).
- **Message layer:** `update_failed` in; SPEC-144's two rebuild reasons **deleted**, not reworded.
- **IAM:** `glue:UpdateTable` in, **`glue:DeleteTable` out** — the refresh path loses a destructive
  permission rather than gaining one.
- **Help & guides:** the create-table guide now tells users to keep column names in their files
  lowercase (user request; the *create* flow is shipped, so SPEC-074 FR-005 is satisfied).

### Decisions worth carrying forward

- **The `TableInput` is an ALLOWLIST projection of the live `Table`, not a denylist strip.**
  `UpdateTable` replaces the whole definition, so the input must carry everything a refresh does not
  own — but `GetTable` returns 25 members and `TableInput` accepts 14, and a denylist naming the 11
  extras goes stale the next time AWS adds a field. That drift is already visible:
  `IcebergTableMetadata`, `Status`, `IsMultiDialectView` and `IsMaterializedView` all postdate the
  obvious `CreateTime`/`CreatedBy` set the spec listed. A test pins the tuple against **botocore's
  own service model**, so the list is verified against the API on every run, not once during a build.
- **Column names are lowercased on write.** AWS documents that "Athena automatically lowers any upper
  case names in DDL queries when it creates databases, tables, or columns" — so the create path folds
  for free and this path, which bypasses Athena entirely, has to do it in code. Without the fold an
  `UpdateTable` would leave a mixed-case catalog entry the create path could never have produced.
- **`portal.managed` is written through `ddl.mark_managed`, never by name.** SPEC-143's tree-wide test
  forbids any verb naming the marker, because a verb that can name it can branch on it and the
  property is user-writable through `ALTER TABLE`. FR-002 needs the marker re-asserted, so the write
  moved behind a helper next to the constant — the marker still has exactly two homes and the guard
  stays strict, rather than the allowlist being widened to admit a whole verb.
- **Glue's retryable faults are classified at this call site, because the shared classifier misses
  them by a word.** `cpcommon.errors._TRANSIENT_CODES` is spelled for S3/Athena/generic throttles: it
  lists `InternalError` and `InternalServerException`, but Glue raises `InternalServiceException`,
  and it has no entry at all for `OperationTimeoutException` — Glue's most routine transient.
  Unclassified, those fall through to the terminal branch and kill a request permanently with
  "Nothing was changed", on faults the state machine's `Retry` would very likely have survived.
  `_GLUE_RETRYABLE` (read off `UpdateTable`'s own modelled error shapes) covers them, plus
  `ResourceNotReadyException`, `FederationSourceRetryableException` and
  `ConcurrentModificationException`. Handled **here** rather than widened in `cpcommon`, because that
  set is shared by every control plane and this is the repo's only Glue **write** — the one call
  where a spurious terminal failure is user-visible. `InvalidInputException` stays terminal, pinned
  by a test, so the classifier has not become a catch-all. **The gap is pre-existing and still
  applies to the Glue reads on other planes.**
- **Two columns differing only by case are refused before the write.** SPEC-144 got this guard for
  free — Athena rejects a `CREATE` with duplicate column names — but `UpdateTable` performs no such
  validation, and once the write folds case a header of `Amount,amount` becomes one Glue column. The
  post-condition could not catch it either: it compares **name sets**, so both spellings collapse on
  each side and compare equal, and the verb would report success on a table that quietly lost a
  column and then fails at query time. Now a terminal `update_failed` naming the collapsed names,
  raised before any write — so "Nothing was changed" stays true.
- **The post-condition read stays terminal.** The update is committed, so a Retry would re-read a
  table that has already changed and write it again. Unlike SPEC-144 that repeat is no longer
  *destructive*; it is still pointless.

### FR-004 — the rollback path

Glue archives the previous definition unless asked not to, and `SkipArchive=False` is passed
explicitly so a future SDK default cannot quietly take it away. To inspect and roll back by hand:

```bash
aws glue get-table-versions --database-name <db> --name <table>
aws glue update-table --database-name <db> --table-input file://<previous-version-TableInput>.json
```

No automatic rollback is built: a failed update leaves the old definition standing, so there is
nothing to roll back on the failure path, and reverting a *successful but unwanted* refresh is a user
decision.

### FR-005 — what was retired, and what was not

- **The replacement window is GONE.** There is no moment at which the table does not exist.
- **"Committed drop then silence" is RETIRED.** A failed update changes nothing, so an exhausted
  retry leaves the table exactly as it was — the outcome a silent failure would have hidden no longer
  differs from the starting state.
- **The concurrent-refresh race is REDUCED, NOT CLOSED.** The Pipe still invokes `StartExecution` as
  `FIRE_AND_FORGET`, so two refreshes on one database still overlap. **Glue offers no compare-and-set
  on `UpdateTable`** — established during build, as FR-005 required: `VersionId` is documented only
  as *"The version ID at which to update the table contents"*, alongside `TransactionId` and
  `ViewUpdateAction`, with no precondition-failure error in the operation's error list. The severity
  degrades from "one run sees no table" to last-write-wins between two definitions.

## What changed from earlier specs?

- **SPEC-144:** its apply is superseded. `DROP` + `CREATE`, the two reason codes, the replacement-
  window language and the idempotency tokens are all gone. Its `_with_carried_comments` behaviour
  survives, now sourced from the live table rather than the threaded capture (which is what the
  spec's own `_table_input` signature implied).
- **SPEC-143:** `clone_definition`'s capture is untouched and still drives the format cross-check and
  the diff. It simply stops being what the apply rebuilds from.
- **SPEC-070:** the create path is unchanged — `execute-ddl` still runs `CREATE EXTERNAL TABLE`
  through Athena. Only the refresh changed.
- **The threaded state** loses `ddl` (there is no statement) and keeps `status` and
  `appliedColumnCount`.

## Verification

`ruff check lambdas/` clean; **1745 tests pass, 2 skipped** (net of 8 tests deleted with the dead
code they covered); `tofu fmt -check -recursive` and `tofu validate` clean; portal `format:check`,
`lint` and **1216 tests** pass.

A fresh-context review raised six findings and **all six were acted on**: the Glue transient-
classification gap, the case-duplicate column regression, the dead code above, an exemption in
`test_messages.py` that had left two live SPEC-144 bodies pinned by nothing (`columns_removed` and
`removals_flag_not_applicable` are now in the byte-for-byte table; the exemption is down to the one
body this spec added), a vacuous `assert not hasattr(...)` in the no-delete test replaced by fake
`delete_table` / `batch_delete_table` tripwires that raise, and the CLAUDE.md wording that called the
casing premise *discharged* on documentary evidence.

**FR-006's policy simulation was run against the rendered template** (pre-deploy — the post-deploy
repeat is the live check below):

| action | resource | decision |
|---|---|---|
| `glue:UpdateTable` | `table/alice/sales_2026` | **allowed** |
| `glue:DeleteTable` | `table/alice/sales_2026` | **implicitDeny** |
| `glue:CreateTable` / `glue:GetTable` | `table/alice/sales_2026` | allowed (create path unaffected) |
| `s3:DeleteObject` | user-space / shared-space / admin | **explicitDeny** (all three) |

**Lake Formation needed no change, verified rather than assumed:** the `portal-managed` table tag
policy already grants `ALTER` — the LF permission `UpdateTable` requires —
(`infra/modules/analytics/lakeformation.tf`, `control_plane_tag_table`). A comment records it.

The Help & guides change was verified in the browser: the new guidance renders in the *Create a table
from a folder* card with its inline markup resolved to `<strong>`, no console errors. Reaching
`/help` needed the repo's documented local dev bypass (`VITE_S3_DEV_UNAUTH`), which was restored to
unset immediately after.

**One live check is owed** and cannot be settled from a unit test, because every fixture here is
authored on both sides:

> Refresh a table that carries a `Description` and a column comment. Confirm from `GetTable` that
> both survive, that the columns changed, and that `get-table-versions` shows a previous version.

**SPEC-144's owed "casing premise" is CORROBORATED, not discharged.** AWS states plainly that Athena
lowercases column names created through DDL, which confirms FR-001's reversal and is the basis for
lowercasing on this path — but documentation is the same class of evidence that had FR-001 reversed
mid-build, and this spec raises the stakes: the fold is now **ours**, hard-coded, and asserted to
users in the help content. If the premise is wrong, the first refresh of an existing table silently
re-cases its columns while `diff-schema` reports them unchanged — a mutation no test and no
notification would surface. The `GetTable` read-back above settles it.
