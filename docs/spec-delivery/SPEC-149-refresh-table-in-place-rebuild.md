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
- **`ConcurrentModificationException` is transient.** It is Glue's own guard on two simultaneous
  modifications, and a re-invocation simply re-reads and writes again — the recovery a lost race
  wants, and safe in a way SPEC-144's destructive pair never was.
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

`ruff check lambdas/` clean; **1746 tests pass, 2 skipped**; `tofu fmt -check -recursive` and
`tofu validate` clean; portal `format:check`, `lint` and **1216 tests** pass.

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

**SPEC-144's owed "casing premise" check is now settled by documentation** rather than belief — AWS
states plainly that Athena lowercases column names created through DDL, which confirms FR-001's
reversal and is the basis for lowercasing on this path. A live `GetTable` read-back would still be
the empirical confirmation and rides along with the check above.
