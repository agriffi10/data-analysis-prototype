# Completed Spec — SPEC-235: A CSV Table's Refresh Keeps Its Column Order and Adds New Columns at the End

## What was completed?

- **A CSV table's refresh no longer moves a column the table already holds.** `apply-refresh` writes
  the live table's columns in their order — minus any the folder's first file dropped — then appends
  every column new to the table, in the first file's order. Before this, the written order was the
  first file's, so a column inserted mid-header made every older file read one column across from
  where its values belong, silently: every CSV column is `string`, the diff folds names and compares
  no positions, the read-back compares name sets, and the notification reported success.
- `lambdas/table-builder-apply-refresh/apply_refresh.py` — `_write_columns` stable-sorts the declared
  list on each column's rank in the live table when `fmt in ddl.POSITIONAL_FORMATS`, new columns
  ranking past the end. A list and a stable sort rather than a dict keyed on the fold, so two names
  that fold together survive as two entries and still reach the `update_failed` refusal.
- **The removal refusal says what a removal costs a CSV file that still has the column.**
  `tbcommon.messages.removed_tokens` now takes the format and supplies a `removalEffect` token the
  `columns_removed` template renders — empty for JSON and Parquet, so their wording is byte-identical
  to what it was. `diff-schema` passes the `format` it already required.
- **The dialog and the Refresh guide describe both.** `RefreshTableDialog`'s opt-in description and
  the `refresh-table` guide's removal paragraph carry the same sentence; the guide's intro now says a
  refresh adds new CSV columns at the end and never moves the ones the table has, and that a column
  put anywhere else is misread **in that file** — not, as it said before, in the older ones.

### Deliberate deviations

- None from the spec. Two doc sites the spec did not name were amended because this decision made
  them false in part: `lambdas/info/planes/table-builder.md` and `lambdas/info/shared-layer.md` both
  said the partition-namesake rename is kept "in its place" on a refresh's **write**, which now holds
  only for a namesake the table already declares.

## What changed from earlier specs?

- **SPEC-149's apply** (the in-place `UpdateTable`): `_write_columns` gains the reorder. Its signature
  is unchanged — `fmt` was already a parameter, from the partition-namesake rename.
- **SPEC-144's removal refusal**: `removed_tokens(names)` becomes `removed_tokens(names, fmt)`. One
  call site, in `diff-schema`.
- **The partition-namesake rule (2026-09-16)**: still renames a CSV column naming a partition key in
  its place in the **declared** list, but a refresh's write no longer takes that list's order, so a
  namesake the table has not yet declared is new and lands last. The register entry and both
  `lambdas/info/` pages say so; the create path is untouched.
- **#755's copy**: reconciled rather than reverted. Its "first file in the table's folder" wording is
  kept everywhere; only the sentence about *which* files a misplaced column misreads is rewritten,
  because this spec is what made it false.

## Verification

Formatter, both linters, both suites, mypy, `npm run build` and `validate_docs.py` green locally by
exit code. The five guards this adds were mutation-tested: removing the sort, applying it to every
format, ranking new columns first, and forcing the removal sentence empty or unconditional each
redden, bracketed by green baselines. Deferred to a signed-in session after deploy: the live
column-order check, folded into `docs/testing/e2e.md` §4.4 as refresh step 10.
