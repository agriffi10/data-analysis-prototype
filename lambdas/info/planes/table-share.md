# Table share — control plane

Shares a catalog table with other users: copies the underlying data into each recipient's space and
creates the table in their own Glue database.

## The machine

`infra/modules/table-share/state-machine.asl.json.tftpl`

`ValidateAuthorize → InspectSource → GuardRecipients (Map) → BuildTransferManifest →
TransferObjects (Map) → CollectTransferResults → FinishRecipients (Map) → ShapeSummary`

Three Maps: guard each recipient, move the bytes, then create each recipient's table.

## The fences

- **The share CLONES the source definition, it never re-infers it** — the recipient's table is the
  sender's table, not a fresh inference over the copied bytes.
- **It pushes without consent.** There is no accept step; the recipient finds the table already
  there.
- **Every DDL literal goes through `literal()`**, `TBLPROPERTIES` and `LOCATION` included, and the
  escapers split on two axes that are easy to conflate. For *values*: `cpcommon.ddl.literal`
  backslash-escapes (Hive/DDL) while `cpcommon.sql._literal_dml` doubles the quote (Trino/DML). For
  *identifiers*: `sqlDdlIdentifier` and `ddl.quote` are Hive (inner backtick doubled), `sqlIdentifier`
  is Trino. **The wrong one fails silently, as a predicate that never matches** — and a shared
  space's name is format-checked nowhere server-side.
- **A table's `LOCATION` is read recursively**, so the space root is not a data folder.

## The layer — `table-share-common/tscommon/`

| Module | Holds |
|---|---|
| `cognito` | user pool lookups for recipient validation |
| `config` | domain configuration |
| `copy_plan` | the copy plan, passed by pointer |
| `ddl` | renders the recipient `CREATE EXTERNAL TABLE` from the cloned source definition |
| `glue` | Glue catalog reads for the source |
| `messages` | user-facing outcome wording |
| `notify` | best-effort outcome notifications |

The verbs are listed in [`../INDEX.md`](../INDEX.md).
