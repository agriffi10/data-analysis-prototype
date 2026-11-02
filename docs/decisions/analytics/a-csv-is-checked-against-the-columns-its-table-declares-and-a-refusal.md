---
type: Decision
title: "A CSV is checked against the columns its table declares, and a refusal is for the misread a report cannot show (2026-09-16)"
description: "A data-quality report checks each CSV file against the columns the table declares, by the files' names, never against the other files; a misread caused by files disagreeing is reported, and a refusal is only for a misread no report could show."
---

> **Superseded in part (2026-09-16): the refusal this entry judged is gone.** A CSV column named
> after a partition is declared under a new name, so no file is refused and `shifted` compares each
> file with the declared columns by the name the FILES give them. The cross-file ruling — report a
> misread caused by files disagreeing, and compare each file with the table, not with the others —
> stands. See *A CSV column named after a partition keeps its values under a new name* below.

**The finding.** Data-quality's `partition_column_not_last` is judged on `sql.union_columns`, the
folder's columns in first-seen order, not on each file's header. Driving create-temp-tables with
`a.csv` = `id,amount` and `b.csv` = `id,Year,amount` under `year=2025/` gave the union
`[id, amount, Year]`, no refusal, and a temp table of `(id, amount)` over OpenCSVSerde, so `b.csv`'s
`Year` is profiled as `amount`.

**The premise under it was half false.** The finding took for granted that files whose headers
disagree are already reported by cross-file agreement. `report.cross_file` compared each file's
**sorted** names, so it caught `b.csv`'s extra `Year` but read `id,amount,Year` beside
`id,Year,amount`, and `id,amount` beside `amount,id` with no partition at all, as agreement. The
refusal and cross-file agreement were both clean for the first pair, and a layer test pinned the
second as agreeing, while a table over either reads a file under the wrong names.

**The ruling (Andrew's): report it, and keep the union.** A per-file refusal was the other option.
It would have refused only the folders with a partition-named column, traded a report that names
the odd file for a refusal that names only the column, and left the plain swap silent. The rule
recorded instead: **a refusal is for the misread no report could show** — every file agreeing, so
cross-file agreement is clean and every later column is wrong — and **a misread caused by files
disagreeing is reported**. The union is then the right unit, because a file whose own header puts a
partition column before a kept one while the union does not is always a file the report flags.

**What is checked: each file against the columns the table DECLARES, not against the other
files.** OpenCSVSerde reads field `i` of every file as declared column `i` — `sql.profiled_columns`
over the union, the same list the profile and the per-column figures use — ignores trailing fields
past the last one, and reads nulls for a short row. So a file is `shifted` exactly when a field it
has lands under a column of another name, and Parquet and JSON, matched by name, never are. Two
designs came first, and both leaked:
- *Relative order of the shared columns against the modal header* could not see a column inserted
  mid-header — `discount` added between `id` and `amount` from July on shifts every later column
  and read only as an extra column.
- *Prefix agreement with the modal header, after trimming trailing partition columns,* caught that,
  and still missed two files adding DIFFERENT trailing columns: beside `id,amount`, `id,amount,note`
  and `id,amount,region` build `(id, amount, note, region)`, so `region` is read as `note`, while
  each file lines up with the modal header.

Both compared files with each other, which is a proxy for the table; comparing with the table has
no residual case and needs no partition trimming, since a trailing partition column is simply past
the declared columns. Missing and extra still come from the modal SET, unchanged, because they name
the minority, which is the repair.

**The files named as shifted are the ones this report misreads, which is not always the minority.**
The declared order is first-seen across the files as listed, so when the first file is the odd one
out the other files are shifted and it is not. That is the honest reading of the figures the user
is looking at. The issue points at the report's own Columns section, which is the declared order,
rather than at another file.

**One issue line for all of them.** A folder whose export changed part-way through splits in two,
and a line per shifted file filled the five-line cap with one sentence, each wrongly saying it
differed from "the other 11 files" when five of them matched it. The line counts the shifted files
and names the first.

**Deploy window.** An SPA older than the field shows a shifted file with no missing or extra columns
under the disagreement heading with no detail line; the field is optional in the portal type.

**Table-builder asks a different question.** It has no union: infer-schema reads ONE sample file's
header, judges the refusal on it, and reads no other header. A file in another order is read under
the sample's names there too, and a data-quality check over the folder is what reports the
disagreement.

## History

### 2026-09-16

- **Settled:** entered the register.
- **Changed:** The refusal this entry judged is gone, since a partition-named column is declared under a new name; the cross-file ruling stands.
