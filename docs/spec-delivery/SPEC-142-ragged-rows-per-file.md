# Completed Spec — SPEC-142: Ragged Rows Counted Per File, Not Against the Union

## What was completed?

- `dqcommon.sql.build_ragged_query` takes `expected_by_path: dict[str, int]` (was
  `header_column_count: int`) and renders a `CASE` over Athena's `"$path"` pseudo-column, so each
  raw line is compared against **its own file's** header column count.
- `dq_start_profile_query._expected_by_path` builds that mapping from the manifest, keyed
  `s3://{bucket}/{key}` — the form `"$path"` returns, and the inverse of `report._strip_scheme`.
- `sql.RaggedQueryTooLargeError` + `sql.RAGGED_QUERY_TOO_LARGE` + `config.DQ_MAX_QUERY_BYTES`
  (262,144 — Athena's documented query-string cap, now named rather than repeated as a magic
  number; the profile query's size test uses it too).
- `dq_start_profile_query._ragged_block` turns the guard's refusal into a `not_computed` block;
  `report.NOT_COMPUTED_RAGGED_QUERY_TOO_LARGE` is its user-facing sentence.
- One PR: #340.

The bug: the check compared every physical line against the **union** column count across the
folder, so on files that disagreed about their columns every data row of a narrower file came back
ragged — and so did **every file's header**, since a header only carries the union's field count
when the files already agree. The user saw one problem reported twice: once correctly as
`crossFile` naming the odd file out, and once again as a large ragged number describing nothing.
`report.py` says a green result the data did not earn is worse than no result; a **red** one it did
not earn is the same defect wearing different clothes.

### Decisions worth carrying forward

- **The guard refuses rather than truncates.** One `CASE` branch per file against
  `DQ_MAX_OBJECTS = 1000` and arbitrarily long S3 keys can outgrow the cap. Dropping the branches
  that did not fit would reproduce *this spec's own bug* on a subset, invisibly — so
  `build_ragged_query` measures its **rendered bytes** (a file count is a poor proxy for key
  length) and raises. Ragged degrades to `not_computed`; the rest of the report still lands
  (SPEC-111 FR-003).
- **`reasonCode`, not text-matching.** The degraded block carries a machine-readable
  `reasonCode` that `report._ragged` checks **before** the line-too-long branch. That branch reads
  Athena's own wording and is a guess; this one is a string this codebase wrote. `reason` stays raw
  operator-facing text, as it already does on a block degraded by check-query.
- **`ELSE false` is the FR-004 rule, not an oversight.** The raw-line table scans the folder while
  the mapping comes from the manifest, so the two can disagree. An unjudgeable line is never counted
  ragged — it still counts toward `total_lines`, which counts physical lines.
- **Branches render in sorted path order.** Every submission carries a `ClientRequestToken` derived
  from the requestId, and Athena rejects a token replayed with different query text — a Retry that
  re-rendered in another order would fail the resubmission instead of re-attaching to the original
  execution.
- **Trino literal quoting is doubling, not backslashes.** `_literal_dml` deliberately diverges from
  `tscommon.ddl._lit`, which is Hive's DDL rule. The Hive form would render a backslash into the
  path being matched, and a branch that never matches produces no error — just a file's lines
  silently falling to the `ELSE` and going uncounted. Pinned by a test on a key containing `'`.

### Deliberate deviations

- **`ragged_started` is a new narrative field**, beyond what the spec asked for. The old code
  derived `started` from `if out["ragged"]`, which a degraded block satisfies — so a guard-refused
  query would have been logged as started. Applicable and started are now separate fields; a CSV
  whose query the guard refused is applicable and not started.
- **A file with no probed columns is omitted from the mapping**, not mapped to `0`. Zero would make
  every one of its lines ragged, which is exactly the fabricated-finding class this spec removes;
  omission routes it to the `ELSE` instead.

## What changed from earlier specs?

- **SPEC-111's `build_ragged_query` signature changed** — scalar to mapping. Its golden-string tests
  were rewritten against the new SQL.
- **SPEC-112's `report._ragged`** gained the `reasonCode` branch and a third `not_computed` reason.
- `report.cross_file` (SPEC-112 FR-002) is **untouched** and remains the single source of truth for
  "these files disagree." This spec only stops ragged rows from restating it.
- The two documented approximations — `split(line, ',')` over-reporting on a quoted comma and on an
  embedded newline — are unchanged, and the count keeps its `approximate` tag and `NOTE_RAGGED`.

## Verification

`ruff check lambdas/` clean; **1541 tests pass, 2 skipped**. New coverage:

- Golden strings for the rendered `CASE`, per the module's convention that a subtly wrong query does
  not crash — it reports wrong numbers about a user's data.
- The size guard's trip is proved by **constructing a manifest with keys long enough to breach it**,
  not by monkey-patching the constant (FR-003), plus the negative: 1000 files with realistic keys
  still render inside the cap.
- `test_a_folder_whose_files_disagree_reports_ZERO_ragged_rows` — the FR-005 regression test, in
  `test_sql_dqcommon.py` where the rule is emitted. It parses the rendered `CASE` back into
  `{path: expected count}` and applies it to physical lines the way Athena would, asserting both
  that each file gets **its own** count and that the folder yields zero ragged rows. **Verified to
  fail against the pre-fix commit** (`200e338`) in a scratch worktree — see the correction below for
  why that check matters.

### Correction — the first FR-005 test was a tautology

The fresh-context review caught it, and proved it by running the test against the pre-fix commit,
where it **passed**. The original test asserted `raggedRows.count == 0` from `report.build` — but
`report.build` does not compute that number, it reads `ragged_rows` out of the Athena result rows
the test itself supplies. It asserted that the report renders a zero when handed a zero, which is
true of the buggy builder too.

It is now two tests with honest scopes: the real regression lives in `test_sql_dqcommon.py` and
fails against the old code; the report-level test is renamed
`test_a_disagreeing_folder_with_no_ragged_rows_reports_the_disagreement_ONCE` and its docstring
states outright that it cannot pin the fix, so nobody reads it as coverage it is not.

The general shape, worth remembering: **a test whose fixture supplies the value under test proves
nothing.** The cheap check is to run a new regression test against the commit before the fix — if it
passes there, it is not a regression test.

Four smaller review findings were also fixed: the `not_computed` wording no longer blames the file
count (the guard measures rendered bytes, and a count is a poor proxy for key length — 300 files
with 800-character keys trip it while 900 short-named files do not); the warning event carries both
`files` and `files_mapped` rather than one field holding whichever number was in scope; FR-004 has a
real test that feeds an unmapped path's malformed lines through the emitted rule instead of
substring-matching `ELSE false END`; and the "a header is never ragged" docstring now names the one
case that defeats it — a quoted comma in a header, which polars counts as one column and `split`
counts as two.

**Deferred to a live run (the spec's Phase 4, still owed):** a data-quality check from the UI over a
folder whose files deliberately disagree, confirming the report shows the cross-file finding with no
fabricated ragged count — and a folder whose files agree producing the same numbers as before. No
unit test can cover the one assumption underneath all of this: that Athena's `"$path"` on the
raw-line table returns the same `s3://bucket/key` form the manifest is keyed to. The profile query
already relies on that for per-file row counts, which is the evidence for it, not a proof.

No Help & guides change: `helpContent.ts:114` already describes ragged counts as estimates and
`Not computed` as a figure the check couldn't make — both still true, with one more cause. No
component-inventory row: nothing new and reusable in `apps/portal/`.
