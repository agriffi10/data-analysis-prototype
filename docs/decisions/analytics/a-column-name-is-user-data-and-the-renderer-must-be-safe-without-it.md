---
type: Decision
title: "A column name is user data, and the renderer must be safe without it being validated (2026-08-19)"
description: "**A column name is user data.** Creates refuse empty, non-`[a-z0-9_]`, over-255 and fold-collision names. A data-quality check judges a fold collision **per file** and merges one across files into one column, as Athena reads it — judged on the union, a collision inside one file merges too and shifts a CSV. A refresh skips the check, or it would strand pre-rule tables, but its diff still refuses a fold collision. **Every step of a refresh, and the DDL builder's partition-key match, folds through `columns.fold`, which is `lower()` and never `casefold()`**: the second merges `ß` into `ss`, so a diff and a write folding differently removed a column without the opt-in, and a match by exact name left a header `Year` beside the key `year`, which Athena refuses as a repeated column."
---

Column names are the one part of a schema this portal does not choose — they are read out of a
file's own header or Parquet footer. Nothing judged them, and Glue accepts what Athena then cannot
read: the result is not a failed build but a table that is CREATED, appears in the rail, and fails
or returns nothing when queried.

`cpcommon.columns` is one rule shared by both planes that infer a schema. It refuses an empty name
(a blank CSV header cell), leading or trailing whitespace, anything outside `[a-z0-9_]` after the
fold, over Glue's 255, and two names that fold to the same lowercase string — the last being the
one that reads as a portal bug rather than a file bug, because `Total` and `TOTAL` are two columns
to every tool the user has and one column to Athena. It ALLOWS a leading digit, a leading
underscore and a reserved word: those are what the quoters exist for.

**The blanket `[a-z0-9_]` is stricter than AWS documents, and that is a product decision, not an
oversight.** `Order ID` builds and queries today. It is refused so that one rule holds everywhere
rather than a narrower one holding until someone writes a query by hand without the quoting this
app applies for them. Reversing it is a change to one regex.

**Creates only.** A refresh re-derives the columns of a table that already exists, so refusing one
would break every refresh of a table built before the rule and leave rewriting the source files as
the only repair. It selects on the storage descriptor, not on `mode` — a tripwire forbids the
shared verbs reading that field, because the moment one does, "a refresh reuses these verbs
unchanged" stops being true.

**On a refresh, a fold collision is refused by the diff, in a create's words.** diff-schema raises
`invalid_column_names` naming every colliding name before it classifies anything. Until then a
collision was the write's to refuse, and the write runs only when the diff reports a change, so
`Amount,region,amount` against a live `amount,region` read as unchanged, and with anything else
changed it reached the user as "couldn't be updated, try again", which cannot help. Refusing it
strands nothing: the write already refused every definition carrying one. The write keeps its
own guard, because nothing after its fold would notice a column collapsed. The mechanism is on
the [table-builder plane page](../../../lambdas/info/planes/table-builder.md#the-fences).

**The fold is Athena's, `lower()`, and one function applies it to every name a refresh
compares.** diff-schema matched on `casefold()` while apply-refresh wrote and refused on `lower()`.
Full case folding maps `ß` to `ss`, so against a live `strasse` the header `Straße,notes` reported
only `notes` added. The write then landed `straße` in place of `strasse`, removing a column without
the opt-in, and the read-back passed because it compared casefolded sets. AWS documents that
Athena lowers names, and Hive normalises an identifier with Java's `toLowerCase`, which, like
Python's `lower()`, is Unicode lowercasing and keeps `ß`. So `cpcommon.columns.fold` is `lower()`,
and the create rule, the diff's match and partition-key exclusion, the write's names, comment carry
and refusal, and both catalog reads around the update all call it, as does results-conversion's
duplicate check. The two folds differ only on non-ASCII characters, which the name rule keeps out
of a create; a refresh skips that rule, and results-conversion never applies it to a query's
column names. The evidence that Athena keeps `ß` is the documentation and the Hive source, not a
live Athena run.

> **Superseded in part (2026-09-16): a CSV no longer drops the column, anywhere.** A CSV column
> naming a partition key is kept in its place under a new name, in every position, by a create, a
> refresh and a data-quality check; Parquet and JSON still drop it. The fold match and the
> measurements below still stand and are why; the drop-from-the-END rule and the
> `partition_column_not_last` refusal are gone. Full entry: *A CSV column named after a partition
> keeps its values under a new name, instead of being refused (2026-09-16)*, below.

**A column naming a partition key is dropped on the fold, and in a CSV only from the END — the
drop that reads correctly is a narrower thing than the drop that builds.** `build_create_table_ddl`
leaves such a column out of the body so the DDL stays valid, and it matched by exact name. Both
halves were measured live through the portal, and the second is why this entry exists.

*The match.* A CSV header `Year,id,region` under `year=2025/` with the key `year` rendered
`` (`Year` string, …) PARTITIONED BY (`year` string) ``, and Athena failed it with
`SemanticException [Error 10035]: Column repeated in partitioning columns`, not retryable — the
user read "creating the table failed. Please try again or contact the Administrator", which no
retry can fix. Hive's `CreateTableDesc.validate` compares the two with `equalsIgnoreCase`. A
data-quality check over the same folder failed on its temp table the same way. So the match folds.

*The drop.* Folding alone would have turned that failure into something worse. **CSV is read by
POSITION** — OpenCSVSerde takes fields in order and only skips the header — so leaving a column
out shifts every later one onto its neighbour's field, and every CSV column is a string, so
nothing errors. The exact-case drop had been doing this since the builder was written: the control
table built from `year,id,region` over the row `2025,1,south` read `id` as `2025` and `region` as
`1`, with `south` unreachable, while the rail looked right. Dropping is safe only when nothing the
table keeps follows — `id,region,year` built and read `1, south, 2025` — and Athena matches Parquet
and JSON by name, so there the drop is always safe.

So a CSV column naming a partition key anywhere but at the end is **refused**, by table-builder as
`partition_column_not_last` and by data-quality under its own reason of the same name, each naming
the column and asking for it to be moved last or taken out. `ddl.shifting_partition_columns` is the
one place that decides, and `build_create_table_ddl` raises rather than render a shifted statement,
because a renderer safe only because a caller validated first is one refactor from not being safe.
Data-quality's queries and report read the columns the drop keeps, `ddl.body_columns`, so its
duplicates grouping and its profile name only the columns its temp table has, and a column naming a
partition gets no per-column figures. The profile once projected it anyway, and Athena bound the
name to the partition column, reporting the folder's value under the user's column name. Refusing
beats renaming the column for the user: a rewritten name no longer matches the file's own header,
which is the same reason the name rule refuses rather than repairs. The refresh path drops the same
way and is NOT covered here — it writes Glue columns directly rather than through this builder, so
a CSV refresh can still shift a live table.

**The rule is not what makes the renderer safe.** `cpcommon.ddl.quote` now doubles an embedded
backtick, as `quote_dml` always did for the double quote. A renderer that is safe only because
someone else validated first is one refactor from not being safe — and data-quality proved it:
its partition keys are derived from S3 path segments, so a folder named ``ab`c=eu`` put a backtick
straight into `PARTITIONED BY`. Those keys are checked too, under their **own** reason code: the
repair is renaming a folder, and a user told to fix a column name goes looking in the wrong place.

## History

### 2026-09-16

- **Changed:** A CSV no longer drops a column naming a partition key; it is kept under a new name and `partition_column_not_last` is gone.

### 2026-08-19

- **Settled:** entered the register.
