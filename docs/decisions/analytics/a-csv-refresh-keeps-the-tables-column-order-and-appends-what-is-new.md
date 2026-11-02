---
type: Decision
title: "A CSV refresh keeps the table's column order and appends what is new (SPEC-235)"
description: "**A CSV table's declared column order is a positional contract, so a refresh never moves a column the table already holds. This does NOT prevent a misread — it decides which file takes it**, now the one that misplaced the column rather than every older one. apply-refresh writes the LIVE table's order, minus what the first file dropped, then appends what is new; JSON and Parquet keep the first file's, where order only lays out `SELECT *`. Taking the first file's order shifted every older file by one whenever a column was inserted mid-header, or a different file sorted first, and **nothing errored**: every CSV column is `string`, the diff folds names and never compares positions, and the read-back compares name SETS. The sort is STABLE over a LIST, never a dict keyed on the fold — keyed on the fold two colliding names merge and no refusal fires, which reddens `test_columns_differing_only_by_case_are_refused_before_the_update`. A removal is the case this cannot help, and it does not heal: a removed column returns as a NEW one, at the end. So the `columns_removed` refusal says what a removal costs a file that still has the column, worded from `ddl.POSITIONAL_FORMATS` so the sentence and the write branch on one fact."
---

**The defect.** Athena reads a CSV by POSITION — OpenCSVSerde skips the header line and takes each
row's fields in order — and a refresh wrote the table's columns in the order of the folder's FIRST
file. So a user adding a column to the middle of that file's header made every older file read one
column across from where its values belong. The same happened when a different file started sorting
first with the same columns in another order. Nothing raised: every CSV column is `string`, so any
value fits any column; `compute_diff` matches names through `columns.fold` and reports a pure
reorder as unchanged; and the post-condition read-back compares name SETS. The refresh notification
reported success. Reproduced on an in-memory fixture over the real `compute_diff` and
`_write_columns`: live `a,b,c` with an older file `a,b,c / 1,2,3`, first file `a,new,b,c` — the
older file then read `new=2, b=3, c=NULL`.

**The rule (Andrew's ruling, 2026-09-14), in `apply_refresh._write_columns`.** For a format in
`ddl.POSITIONAL_FORMATS` the written list is the live table's columns in their order, minus any the
first file no longer has, followed by every column new to the table in the first file's order. It
is a STABLE sort of the declared list on each column's rank in the live table, new columns taking a
rank past the end. Everything else the write does is unchanged: names folded through `columns.fold`
and never `casefold()`, comments and column parameters carried from the live column of the same
folded name, a partition namesake declared as `ddl.body_columns` says, and a fold collision refused
as `update_failed`. JSON and Parquet are matched by name, where the order only decides how
`SELECT *` lays the columns out, and keep the first file's.

**Why a list and a stable sort, not a dict.** Keyed on the folded name, `Amount,region,amount`
would merge to one entry and the write would land a table silently short a column — the read-back
cannot catch it, because it compares name sets and both spellings collapse on each side. The sort
keeps both entries, adjacent, and the existing duplicate refusal still fires ahead of `update_table`.

**What this does NOT do, so the rule is not over-claimed.** Keeping the order does not prevent a
misread; it decides which file takes it. A column inserted mid-header is now misread in that file,
and in every file laid out like it, instead of in the older ones. What it buys is that the table's
order stops moving under the files that already agree with it, which makes the guide's rule — a new
CSV column goes last, in every file that has it — worth following. Nothing can enforce that rule,
because a refresh reads one file. A first file that merely reorders the table's columns still
reports "already up to date", and that file is still misread.

**A removal is the case the order cannot help, and it does not heal.** Removing `b` from `a,b,c`
leaves `a,c`, and a file that still has `b` reads its `b` values as `c`. **Putting `b` back in the
first file does not put the table back**: `b` is now new to the table, so it lands last and the
table becomes `a,c,b`, under which every file headed `a,b,c` has `b` and `c` swapped. The old
first-file-order write happened to repair that sequence, and this one does not — a lost repair,
not a new misread, since the opted-in removal is what shifted the table and the repair was an
accident of taking an order this rule exists to stop taking. Repairing a drifted table is Out of
Scope in the spec, and refusing the refresh was put to Andrew and rejected; what this build owes
instead is that the sequence is pinned by a test rather than argued about, and that the Refresh
guide says a removed column comes back at the end. Rebuilding the table is the repair.

**The refusal is where the user is told.** The opt-in stays the whole gate, so the
`columns_removed` refusal gained a sentence saying what the removal costs:
`tbcommon.messages.removed_tokens` takes the format and supplies a `removalEffect` token the
template renders, empty where the SerDe matches by name. The sentence is placed BEFORE the names
in the returned mapping, because the resolver substitutes by `str.replace` in mapping order and a
column literally named `{removalEffect}` would otherwise have it spliced into the column list. It is unconditional for the format rather than judged on which columns went — removing only
the last column is harmless, but a refusal that said so would have to know which columns are last,
which the dialog carrying the same sentence cannot. The wording names CSV while the code branches
on `POSITIONAL_FORMATS`; a test pins that set's membership, so a format joining it reddens there
rather than shipping a sentence calling Parquet a CSV.

**Data-quality cannot see this, and says so about the FILES only.** `dqcommon.report.cross_file`
judges each file against the declared union of the folder's headers, in first-seen order — never
against the live table, which it does not read. While a refresh took the first file's order the two
effectively agreed; now a table whose order has drifted from its folder reads a clean data-quality
report, because the files do agree with each other. The report's `shifted` finding is a claim about
the folder, not about the catalog.

**One source for the format.** Both verbs read `format` off the state as a required field — it is
already there, set by inspect-source and carried whole, and infer-schema has already refused any
disagreement between it and the live table's SerDe. A missing `format` is a wiring defect and fails
as `malformed_event` rather than quietly taking one branch.

**Rejected.**
- *Refuse a CSV refresh that would move an existing column.* It catches every harmful case, but
  only if every existing column must keep its INDEX — a check on the shared columns' relative order
  misses a mid-header insertion, since `a,new,b,c` keeps `a,b,c` in the same relative order. Not
  chosen because it blocks the refresh rather than doing the safe thing.
- *Record the first file's order as accepted*, with the Help copy as the only protection.
- *Reorder JSON and Parquet too.* Both read by name, so there the order is presentation only, and
  changing it was not part of the ruling.
- *Report the position change in the diff.* A column's position is not a diff class, the counts
  stay what they were, and the written order is asserted on what `update_table` receives instead.

Keying the sort on the fold, so that two colliding names merge and no refusal fires, reddens `test_columns_differing_only_by_case_are_refused_before_the_update`.

## History

### 2026-09-20

- **Settled:** SPEC-235.
