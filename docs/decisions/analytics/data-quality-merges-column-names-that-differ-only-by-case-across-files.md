---
type: Decision
title: "Data-quality merges column names that differ only by case across files, and refuses them inside one (2026-09-16)"
description: "A data-quality check merges names differing only by case across files into one column under the first-seen spelling, disclosed as `otherSpellings`, and refuses a fold collision inside one file."
---

**The finding.** A check over a folder whose files spell one header two ways — `CustomerID,Name,Region`
in one CSV, `customerid,name,region` in another — was refused as `invalid_column_names`, naming all
six, although no file has a clash. `sql.union_columns` unioned by exact name, and the name rule then
saw two names folding to one. Table-builder, reading one sample header, builds the same folder.

**The ruling (Andrew's): merge them.** `union_columns` keys on `columns.fold`; the column is declared
once, under the first-seen spelling and with the first-seen type. The table, the profile and
duplicates queries and the report all read that one function, so the aliases stay numbered over one
list.

**Why it reads correctly in every format.** A CSV is read by position, so the name never reaches the
file. Parquet and JSON are matched by name, the catalog's lowercase against the file's own spelling,
and nothing in either storage clause maps or preserves case — so a SINGLE file with a mixed-case
column, accepted by both planes all along, already depends on that match; the merge only adds files
leaning on the same one. Confirmed on the deployed code, before the merge, through data-quality's
own readers (its JSON table uses the Hive SerDe; table-builder's OpenX one was not measured): a
check over one Parquet and one JSON file with `CustomerID` (integer), `Region` and an all-blank
`Notes` read 0%, 0% and 100% null or blank (reports `01751827-9c78-4798-9c4f-fc08af390d68` and
`fccdf86c-a992-4a33-921b-a11db4ce4b12` in `agriffith`, folder `dq_case_premise/`). The `Notes`
column is the control: a name the engine failed to match would read as 100% too. Trino's Parquet
reader tries the exact name and then `equalsIgnoreCase`; its JSON reader lowercases keys.

**A collision inside one file is still refused, and is now judged per file.** Merged by the union,
`Total,TOTAL` would be declared as one column, and a CSV read by position would take every later
column from its neighbour's field — so create-temp-tables runs `columns.check` on each file's header
and raises one refusal naming every file's offenders, first-seen. A name of the wrong shape is
judged exactly as before. In JSON the probe unions a file's sampled rows, so `CustomerID` in one row
and `customerid` in another is also refused; the engine would read those as one column, and the
refusal stands because the probe cannot tell them from both keys in ONE object, where Trino's JSON
reader keeps only the last value and drops the other without an error.

**What the report shows.** The column once, under its first-seen spelling — as a single mixed-case
file is reported — with `otherSpellings` on its entry and "Also spelled … in other files" beneath the
name. A disclosure, not a finding: it touches neither the verdict, the top issues nor cross-file
agreement, which compares folded names, naming a missing column in the union's spelling and an extra
one in the file's own. Absent when there is none, which is also how older reports read.

**Parquet type drift under two spellings** fails the profile query, as two same-named columns with
two types already did; it used to be refused by name first.

## History

### 2026-09-16

- **Settled:** entered the register.
