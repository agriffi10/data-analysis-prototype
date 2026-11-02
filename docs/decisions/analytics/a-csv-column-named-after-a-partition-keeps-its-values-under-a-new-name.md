---
type: Decision
title: "A CSV column named after a partition keeps its values under a new name, instead of being refused (2026-09-16)"
description: "**A CSV is read by POSITION, so a column naming a partition key is kept under a new name, never dropped or refused.** `ddl.declare_columns` renames it `<fold>_in_file` in its place — in a create, a refresh's diff and write, and data-quality's temp table and figures — because dropping it answers every later column with its neighbour's values; Parquet and JSON are matched by name and leave it out. **\"In its place\" is the DECLARED list's place, and a CSV refresh's write does not take that list's order** (the CSV refresh's own fence), so on a refresh a namesake keeps the TABLE's position for it, and one the table does not yet declare is new and lands last. In a CSV, cross-file agreement checks each file against the columns the table DECLARES, by the files' names — comparing files with each other read a swap as agreement."
---

**The ruling (Andrew's).** The refusal above stopped a common export shape: a pandas groupby written
out with its index puts the key first, so `sales/year=2025/` holds files headed `year,id,region`. Create table had no way through it — inspect-source refuses leaving the
keys out when the files sit in `key=value` folders — so the only repairs were rewriting every file
or renaming every folder. A reviewer driving the real code found it refusing, with the same
message, a folder whose older files had `year` last and whose later export added a column after
it. A CSV is read by POSITION, so the file's column is kept, under a name that cannot collide, and the folder's
partition stays the partition. Nothing shifts and nothing is refused.

**The rule, in `ddl.declare_columns`.** For a format in `POSITIONAL_FORMATS`, a data column whose
fold equals a partition key's is kept in its place, in EVERY position including last, as
`<fold>_in_file`, then `_in_file_2`, `_3`… until the candidate's fold is free of every kept column,
every partition key and every rename earlier in the pass; the name is cut from the right, whole
characters, to Glue's 255-byte ceiling. Each part is there for a reason:
- *The fold as the base*, because Athena lowercases the name anyway and the name rule has already
  held a create's header to `[a-z0-9_]`, so the result passes the same rule.
- *Every position*, rather than dropping a trailing one as before: one rule to explain, and the
  data-quality report then profiles the column wherever it sits. A table built under the old drop
  gains `year_in_file` as an added column on its next refresh — **added, not moved into place**,
  since a refresh keeps the table's order, so that table stays shifted and repairing it is a
  rebuild.
- *The taken set includes kept columns and the keys*, or `year` beside a header's own
  `Year_In_File`, or beside a second key named `year_in_file`, renders a repeated column Athena
  refuses.
- *A pure function of the columns, keys and format*, so a create and every later refresh of the
  same header agree on the name.

Parquet and JSON are matched by name, so a renamed column would read NULL there; they keep the drop.

**Every reader of the table's columns moved with it.** A create renders the renamed body. A refresh
compares (diff-schema) and writes (apply-refresh) `ddl.body_columns` for the event's `format`,
which both now require: renamed at create but dropped at refresh, the next refresh reported
`year_in_file` removed and refused without the opt-in. The refresh's fold-collision check reads the
FILES' names of the declared columns, because renamed, `Year` and `year` would become two distinct
columns and pass where a create and a check refuse that header. Data-quality's temp table, profile,
duplicates grouping and report all read `sql.profiled_columns` with one format, so the figures sit
under `year_in_file`; the report's cross-file `shifted` check compares each file with the declared
columns by the files' names through the fold, or every file carrying the column in its place would
read as misread.

**What the user is told.** Create table's ready notification appends one sentence naming each
rename (`"Year" is "year_in_file"`), derived from the state the DDL was built from and omitted,
never raised, when that state cannot be read — the table already exists. The data-quality report
carries `partitionNamedColumns`, one `{name, outcome: "renamed", as}` or `{name, outcome:
"omitted"}` per such column, and the report page says which above Columns; the omitted half closes
the gap where a JSON or Parquet column simply vanished from Columns with nothing saying why. The
field is optional in the portal type, so an older report renders as before. A refresh says nothing
extra: a renamed column it adds belongs to a table built before this rule, or to the known limit
below, and either way its count already says a column was added. The earlier objection to renaming
— a new name no longer matches the file's own header — is met by naming both, in the ready
notification and in the report. A single-file check detects no partitions, so there the column
keeps its own name.

**A known limit, not refused.** A header that later gains its OWN `year_in_file` column pushes the
rename to `year_in_file_2` on refresh, and the diff reports that name added. WHICH file column the
live `year_in_file` then reads is decided by the table's order, not the file's, since the refresh
keeps the live order: live `year_in_file,id` against a header `Year,id,year_in_file` writes
`year_in_file, id, year_in_file_2`, so the live column reads the file's `Year` and the new
`year_in_file_2` reads the file's own `year_in_file` — the other way round before the order was
kept. Either way the live column keeps the Glue comment it had, since comments are carried by
name. It needs a user to name a column after the rename, and the refresh notification does report
a change.

**Rejected.**
- *Keep refusing, and word it better.* It leaves Create table with no path for the commonest shape,
  which is what the ruling overturned.
- *Drop a trailing column and rename only a mid-header one.* Two rules for one collision, a
  report that profiles the column in one position and not the other, and a table whose shape
  changes when an export appends a column.
- *Map the file's name through the SerDe.* OpenCSVSerde has no column-name mapping; it never reads
  the header at all.
- *Rename the partition instead.* Its name is the one the user writes in every `WHERE`, and the
  folder is what it is named after.
- *A bare number, `year_1`.* It says nothing about where the values came from.

## History

### 2026-09-16

- **Settled:** entered the register.
- **Changed:** The `partition_column_not_last` refusal was overturned: the column is kept in every position as `<fold>_in_file`.
