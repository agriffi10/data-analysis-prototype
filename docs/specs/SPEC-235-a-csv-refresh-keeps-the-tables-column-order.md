---
type: Spec
id: SPEC-235
title: "A CSV Table's Refresh Keeps Its Column Order and Adds New Columns at the End"
description: "Makes a CSV table's refresh keep its existing column order and add new columns at the end, so older files are not read shifted, and updates the removal warning, Refresh dialog and Help guide, for users."
spec_status: Completed
depends_on: [SPEC-144, SPEC-145, SPEC-149]
---

**Dependency notes:** SPEC-144, SPEC-145, SPEC-149, and the Refresh table copy fix, #755 (see *Scope*)
## Overview

Athena reads a table built from CSV files by column position. The table's first column takes each
row's first value, whatever the file's header calls it. A refresh currently rewrites the table's
columns in the order of the folder's first file. So when a user adds a column in the middle of that
file's header, every older file is read shifted: its values land one column to the right of where
they belong. The same happens when a different file starts sorting first with the same columns in
another order, and a later refresh changes anything. Nothing raises an error. Every CSV column is a
string, so any value fits any column, and the refresh notification reports success.

This spec makes a CSV table's refresh keep the table's existing column order and add new columns at
the end, so a refresh never moves a column that the files already rely on. It also makes the
removal warning say what removing a column does to older CSV files, and brings the Refresh dialog
and the Help guide in line with both.

### What was checked, and how

Read from the code at `5391198d`, and reproduced with an in-memory fixture. The fixture calls the
real `compute_diff` and `_write_columns` and models OpenCSVSerde's read: skip the header line, then
map each row's fields to the table's columns by position.

- **One file decides the columns.** inspect-source keeps the first data key in the listing as the
  sample (`sample_by_format.setdefault`), and infer-schema reads only that file.
- **The diff ignores order.** `compute_diff` matches names through `cpcommon.columns.fold`, which
  lowercases, so a header with the same columns in another order is reported as unchanged.
- **The write takes the first file's order.** `_write_columns` iterates the inferred columns.
- **CSV is positional and untyped.** CSV tables use `ddl.CSV_OPEN_SERDE` with the header skipped,
  and every CSV column is `string` (`lambdas/info/planes/table-builder.md`), so a shifted value
  never fails a cast.
- **What the fixture showed**, for a table `a,b,c` with an older file `a,b,c / 1,2,3`:

  | First file | Today the refresh writes | Older file reads | Under this spec it writes | Misread under this spec |
  |---|---|---|---|---|
  | `a,new,b,c` | `a,new,b,c` | `new=2, b=3, c=NULL` | `a,b,c,new` | the first file, not the older one |
  | `c,a,b,d` | `c,a,b,d` | `c=1, a=2, b=3` | `a,b,c,d` | the first file, which was already misread |
  | `a,c` (removal allowed) | `a,c` | `c=2` | `a,c` | the older file, as today |
  | `a,b,c,d` | `a,b,c,d` | correct | `a,b,c,d` | nothing |

- **The format is already on the state.** inspect-source sets `format`. infer-schema and diff-schema
  pass the whole event on, and `ApplyRefresh` receives the whole state (`"Payload.$": "$"`).
  infer-schema refuses `format_changed` unless `format` matches the live table's SerDe, so on this
  path `format` is `csv` exactly when the table is OpenCSVSerde.
- **Nothing recorded the hazard.** A search of `docs/decisions/` and `lambdas/info/` for "position",
  "positional", "column order", "OpenCSV" and "first file" found nothing about a table refresh.

### The decisions, made while authoring

- **Keep the table's order and append, for CSV only** (Andrew, 2026-09-14). Two alternatives were
  put to him:
  - *Refuse a CSV refresh that would move an existing column.* This catches every harmful case in
    the fixture, including a mid-header insertion, but only if every existing column must keep its
    index. A check on the shared columns' relative order misses the insertion, because `a,new,b,c`
    keeps `a,b,c` in the same relative order. It was not chosen because it blocks the refresh.
  - *Record the first-file order as accepted*, with the Help copy as the only protection.
- **What this rule does not do, stated so the spec does not over-claim.** Keeping the order does
  not prevent a misread; it decides which files take it. A column inserted mid-header in a CSV file
  is now misread in that file, and in every file laid out like it, instead of in the older ones.
  The table's order is now stable, so the guide's rule (a new CSV column goes last) is enough to
  avoid it. Nothing can enforce that rule, because a refresh reads one file.
- **A middle-column removal the user opts into still goes through, and the warning says what it
  does** (Andrew, 2026-09-14). Keeping the order does not help here. Removing `b` from `a,b,c`
  leaves `a,c`, and an older file that still has `b` reads its `b` values as `c`. The opt-in stays
  the gate. The notification, the dialog and the guide each gain one sentence.
- **The removal sentence is unconditional for CSV.** It appears on every CSV removal refusal,
  including one that removes only the last columns, where it is true but has no effect. That
  keeps the rule to one line, and it matches the dialog, which cannot tell which columns are last.
- **One source for the format: the state's `format`, read as a required field in both verbs.** The
  live table's SerDe would be a second source for the same fact, and infer-schema has already
  refused any disagreement between the two. A missing `format` is a wiring defect, so it fails as
  `malformed_event` rather than quietly falling back to one branch.
- **JSON and Parquet keep today's order.** Both read by name, so there the order only affects how
  `SELECT *` lays out the columns, and changing it was not part of the decision.
- **The diff, its counts and the read-back are unchanged.** A column's position is not reported,
  and the post-condition keeps comparing name sets. The written order is asserted by the tests on
  what `update_table` receives.

## Scope

### In Scope

- apply-refresh: for a CSV table, the written column list is the live table's columns in their
  order, minus any removed column, followed by the new columns in the first file's order (FR-001).
- tbcommon messages and diff-schema: the `columns_removed` refusal on a CSV table carries one more
  sentence (FR-002).
- `RefreshTableDialog` and the Refresh guide in `helpContent.ts` (FR-003).
- Tests beside each verb and beside the dialog.
- **The copy FR-002 and FR-003 extend was reworded while this spec was written**, by #755 (the
  refresh says it reads the folder's first file). It edited the same lines: the `columns_removed`
  template, the guide's intro and removal paragraph, and the dialog's opt-in description. It landed
  first, so this build reconciles its copy rather than being overwritten by it on a later rebase,
  where prose that contradicts itself merges without a conflict. Both FRs are stated against the
  wording on `main` at build time. Any sentence quoted here from the earlier copy is context, not
  the target.
- At completion: an entry in `docs/decisions/analytics/`, with a Fences clause saying a CSV
  table's column list is a positional contract that a refresh never reorders. The live check in
  *Implementation Phases* is folded into `docs/testing/e2e.md`.

### Out of Scope

- **Refusing, or warning about, a first file whose column order differs from the table's.** Andrew
  decided against a refusal. A reordered first file with no other change still reports that the
  table was already up to date, even though that file is misread.
- **Files other than the first.** The refresh reads one file. Checking every CSV file's header would
  be a separate change.
- **Repairing a table whose order has already drifted.** A refresh keeps the order the table has.
- **JSON and Parquet ordering**, the create path, and rewriting any file.
- **Any API, request contract or state machine change.**

---

## Functional Requirements

### FR-001: A CSV refresh keeps the table's column order and adds new columns at the end

#### Description:

When the refreshed table is CSV, apply-refresh writes the live table's columns in their existing
order, leaving out any column the first file no longer has. After them it writes every column that
is new to the table, in the order the first file lists them. Columns are matched to the live table
through `cpcommon.columns.fold`, as today, and never through `casefold()`, which merges `ß` into
`ss` where Athena keeps them apart. Everything else `_write_columns` does is unchanged: names are
lowercased, comments and column parameters are carried from the live column, a data column that
collides with a partition key is written as `ddl.body_columns` declares it — kept under a new name
such as `year_in_file` in a CSV, left out in JSON and Parquet — and two names that fold to one are
refused with `update_failed`. The reorder applies to that declared list, so a renamed column is
matched to the live column of the same name like any other. For JSON and Parquet the written order
stays the first file's.

#### Acceptance Criteria:

- [x] CSV, live `a,b,c`, first file `a,new,b,c`: `update_table` receives the columns `a,b,c,new`.
  This criterion fails against the code at `5391198d`.
- [x] CSV, live `a,b,c`, first file `c,a,b,d`: `update_table` receives `a,b,c,d`.
- [x] CSV, live `a,b,c`, first file `y,a,x,b,c`: `update_table` receives `a,b,c,y,x`.
- [x] CSV, live `a,b,c`, first file `a,c` (a removal diff-schema has already let through):
  `update_table` receives `a,c`.
- [x] CSV, live `amount,region` with a comment on `region`, first file `Region,Amount,Notes`:
  `update_table` receives `amount,region,notes`, and `region` still carries its comment.
- [x] CSV, live `amount,region`, first file `Amount,region,amount,notes`: apply-refresh refuses it
  as `update_failed`, and `update_table` is not called. In the pipeline diff-schema refuses this
  header first, as `invalid_column_names`; apply-refresh's guard is the backstop.
  `test_columns_differing_only_by_case_are_refused_before_the_update` in `test_apply_refresh.py`
  already asserts exactly this; keep it green through the reorder rather than adding a second
  copy. It matters here because a reorder keyed on the folded name merges the two columns silently
  while every other criterion here still passes. The read-back cannot catch it either, because it
  compares name sets.
- [x] Parquet, live `a,b,c`, first file `a,new,b,c`: `update_table` receives `a,new,b,c`. The same
  holds for JSON. Both tests set `format` explicitly, because apply-refresh's test event factory
  defaults it to `csv`, so a test that leaves it unset exercises only the CSV branch.
- [x] An event with no `format` is refused as `malformed_event`, and `update_table` is not called.
  Already on main: `test_an_event_without_a_format_is_malformed_and_writes_nothing` in
  `test_apply_refresh.py` asserts it; keep it green rather than adding a second copy.

### FR-002: The removal refusal on a CSV table says what a removal does to older files

#### Description:

When diff-schema refuses a removal (`columns_removed`) on a CSV table, the notification keeps its
existing text and adds this sentence straight after the list of columns, before "Nothing was
changed": "Because this is a CSV table, any file that still has them would have the values after
them read into the wrong columns." The sentence is worded in `tbcommon.messages`: `removed_tokens`
takes the format and supplies it as a token the `columns_removed` template renders, empty for JSON
and Parquet. The reason code and the notification's link are unchanged, so the link still opens
the dialog with the columns named.

#### Acceptance Criteria:

- [x] A CSV refresh whose first file lacks `b`, without the opt-in, sends a notification whose text
  is the `columns_removed` text on `main` at build time with the new sentence after the column
  list, asserted as the whole string.
- [x] The same refusal on Parquet, and on JSON, sends today's text exactly, asserted as the whole
  string.
- [x] On the CSV refusal the reason is `columns_removed` and the link is identical to the one
  today's code builds for the same columns.
- [x] A diff-schema event with no `format` and no removal is refused as `malformed_event`. The
  format is read up front beside the other required fields, not only on the removal path. Already
  on main: `test_an_event_without_a_format_is_malformed` in `test_diff_schema.py` asserts it.
- [x] diff-schema's test event factory carries a format parameter. It already does, defaulting to
  `csv`; the removal tests this spec adds set it explicitly.

### FR-003: The Refresh dialog and the Help guide describe the kept order and the removal's effect

#### Description:

The browser does not know a table's format, so the copy names CSV rather than depending on it.

- The dialog's opt-in description, which its checkbox is described by, gains: "In a table built
  from CSV files, a file that still has a removed column will have the values after it read into
  the wrong columns."
- The guide "Refresh a table after the files change" says that in a CSV table a refresh adds new
  columns at the end of the table and never moves the existing ones, so a new column goes last in
  every CSV file that has it, and that a column placed anywhere else is read into the wrong
  columns in that file. Its removal paragraph gains the dialog's sentence.
- No guide or dialog text on `main` at build time may say any of three things this spec makes
  false: that a refresh reorders a CSV table to match the first file; that a CSV column placed
  anywhere but last misreads the OLDER files (it now misreads the file it is misplaced in;
  #755 added exactly this sentence to the guide's intro, true when it was written); or that
  the user should reorder a file to restore the table's order. The sweep is closed with a grep for
  "order", "position" and "older files" over `helpContent.ts` and
  `features/table-builder/*.tsx`, and the result is recorded in the PR body.

#### Acceptance Criteria:

- [x] The dialog's checkbox has an accessible description containing the new sentence, asserted
  in `tableBuilderUi.test.tsx`.
- [x] The Refresh guide's text contains the kept-order statement, the "goes last" instruction and
  the removal sentence. This is static copy, so the diff review checks it, not a test.
- [x] The PR body records the sweep's grep and what each hit was.

---

## API / Interface Contract

```python
# lambdas/table-builder-apply-refresh/apply_refresh.py
def _write_columns(
    columns: list[dict],
    live_partition_keys: list[dict],
    live_columns: list[dict],
    fmt: str,
) -> list[dict]: ...

# Already the signature on main: the partition-namesake rename added `fmt` to _write_columns and
# _table_input, and _apply already reads events.require(event, "format"). The kept order is
# decided inside from it — fmt in ddl.POSITIONAL_FORMATS — rather than by a second parameter.

# lambdas/table-builder-common/tbcommon/messages.py
def removed_tokens(names: list[str], fmt: str) -> dict: ...

# lambdas/table-builder-diff-schema/diff_schema.py: _diff already reads
#   fmt = events.require(event, "format")
# beside the other required fields; the removal refusal passes removed_tokens(removed_names, fmt)
```

The reorder keeps duplicate names, so the fold-collision refusal still sees them. A stable sort of
the kept columns on their index in the live table, followed by the new columns in the first file's
order, does this; a dict keyed on the folded name does not.

## File & Folder Structure

```
lambdas/table-builder-apply-refresh/apply_refresh.py        (FR-001)
lambdas/table-builder-apply-refresh/test_apply_refresh.py   (FR-001)
lambdas/table-builder-common/tbcommon/messages.py           (FR-002)
lambdas/table-builder-diff-schema/diff_schema.py            (FR-002)
lambdas/table-builder-diff-schema/test_diff_schema.py       (FR-002)
lambdas/test_child_spans_per_plane.py                       (already carries a format; no change)
apps/portal/src/features/table-builder/RefreshTableDialog.tsx       (FR-003)
apps/portal/src/features/table-builder/tableBuilderUi.test.tsx      (FR-003)
apps/portal/src/features/help/helpContent.ts                        (FR-003)
```

## Implementation Phases

### Phase 1: The two verbs

- `_write_columns` keeps the live order when `fmt` is positional; `fmt` and the required `format`
  read are already in place.
- `removed_tokens` takes the format; the `columns_removed` template renders the sentence token;
  diff-schema passes the format.
- Tests for FR-001 and FR-002, including the explicit Parquet and JSON cases.

### Phase 2: The browser copy

- The dialog sentence, the guide's kept-order statement and removal sentence, and the sweep.
- The live check, run from a signed-in session after deploy: upload `csvorder/part-001.csv`
  (`a,b,c` / `1,2,3`) and build the table `csvorder`; upload `csvorder/part-000.csv`
  (`a,new,b,c` / `10,99,20,30`) and refresh. The notification reports one column added. The rail
  lists `a,b,c,new`, and `SELECT "$path", a, b, c, new FROM <db>.csvorder` returns part-001's row as
  `a=1, b=2, c=3, new=NULL`. The part-000 row reads shifted, which is the cost this spec accepts.
  Then drop the table from the rail's ⋮ menu and delete the folder.
