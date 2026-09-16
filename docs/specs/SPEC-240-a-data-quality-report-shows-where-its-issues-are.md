# Spec: A Data-Quality Report Shows Where Its Issues Are

**ID:** SPEC-240
**Status:** Draft
**Last Updated:** 2026-09-16
**Depends On:** SPEC-111, SPEC-112, SPEC-113

## Overview

A tester read a data-quality report that said a folder had duplicate rows, and asked which rows they
were. The report cannot say. It stores the number of duplicates and nothing about them. It also
stores two things that would help and never shows them: how many rows each file holds, and the
file and byte position of examples of invalid text encoding.

This spec shows both stored figures on the report page, corrects the page's type for the encoding
examples, and makes the check keep up to five of the most-repeated duplicate rows, each with how
many times it occurs, so the report can show them. The samples come from the query that already
counts duplicates, so nothing extra is scanned.

### What was checked, and how

Read from the code at `73c66eef`.

- **The page shows neither stored figure.** `DataQualityReport.exact.rowCountsByFile` and
  `approximate.encoding.sampleOffsets` are in `features/data-quality/dataQuality.types.ts`. No
  non-test file under `apps/portal/src` reads either field (grep for both names).
- **The page's type for the offsets is wrong.** `dataQuality.types.ts` types `sampleOffsets` as
  `number[]`, and `reportFixtures.ts` uses `[1024, 88123]`. The writer,
  `lambdas/data-quality-byte-scan/dq_byte_scan.py` `_scan_all`, emits
  `{"key": <object key>, "offset": <byte offset>}` entries, at most `config.DQ_OFFSET_SAMPLE` (10),
  and `dqcommon/report.py` `_encoding` passes them through unchanged. The mismatch never broke
  anything because nothing renders the field.
- **Duplicates are a count.** `dqcommon/sql.py` `build_duplicates_query` renders
  `SELECT COALESCE(SUM(cnt - 1), 0) AS duplicate_rows FROM (SELECT COUNT(*) AS cnt FROM <table>
  <path filter> GROUP BY <every column, partition keys last> HAVING COUNT(*) > 1)`, and
  `report.py` `_duplicates` reads one integer.
- **The report already stores the user's values.** Each typed column carries `sampleOffending`, up
  to five offending values, each cut at `MAX_SAMPLE_VALUE_CHARS` (200) with an ellipsis by
  `report.py`. `_sample_expr` in `sql.py` builds them with Trino's n-ary `max_by`, which keeps only
  n entries in its accumulator, keyed on the value so a retried query yields the same sample. It
  renders them as JSON, because Athena writes an array into its result CSV with unquoted elements.
- **Results travel by pointer.** assemble-report reads each query's result CSV from its
  `resultLocation` (`_result_rows`), not from the state.
- **The statement has a length budget.** `dqcommon.config` holds `DQ_MAX_COLUMNS = 200` and
  `DQ_MAX_QUERY_BYTES = 262_144`, and `_projection`'s docstring records a profile query that measured
  324 KB at the column limit before its columns were aliased, with a test pinning the rendered size.
- **Nested columns reach the check.** `cpcommon.type_mapping.map_dtype` maps Parquet lists and
  structs to `array<…>` and `struct<…>`. Trino's JSON documentation (read 2026-09-16) lists the types
  that cast to JSON as BOOLEAN, the integer types, REAL, DOUBLE and VARCHAR, and arrays and rows of
  those. It does not list DATE, TIMESTAMP or DECIMAL, and it says a JSON array cannot be cast to
  VARCHAR.
- **The report is read through a size cap.** The page reads it with `objects.readContent`, which
  refuses a document above `apicommon.s3_config.MAX_DOCUMENT_BYTES` (a Lambda response's 6 MiB,
  halved for JSON escaping). assemble-report does not measure what it writes.

### The decisions, made while authoring

- **The report stores up to five duplicated rows** (Andrew, 2026-09-16). The rejected options were
  showing only what is stored today, and deferring the samples to a later spec.
- **The samples come from the counting query, and the accumulator stays bounded.** Keeping all the
  duplicate groups to sort them would hold every column of every group in memory, on exactly the
  datasets with the most duplicates. An n-ary `max_by` holds five, the pattern `_sample_expr`
  already uses.
- **The sample is deterministic.** The five kept are the most-repeated rows, with ties broken by the
  row's own rendered text, so a retried query writes the same report. The key is a varchar: the
  repeat count left-padded to a fixed width, followed by the row's JSON. That orders the same way as
  "count, then text", and a varchar key's ordering is not in doubt the way an array's might be.
- **Each value is cut in SQL and again in Python.** `substr(..., 1, 201)` bounds what the
  accumulator holds. `report.py` then cuts to 200 characters with an ellipsis, as it does for the
  offending values, so a cut value looks the same in both places.
- **No output name of the statement is a source column's name.** The grouped columns are projected
  under positional aliases, so a source column named `cnt` or `duplicate_rows` cannot collide with
  the statement's own names.
- **NULL and the empty string stay distinct.** The sample is rendered as JSON, so NULL is `null`.
  The page shows them as `NULL` and `(empty)`, matching the Data Explorer.
- **The report stays under the cap it is read through.** If the serialized report with samples
  would exceed the document cap, assemble-report writes it without them and says why in the report.
  The number is not imported across the plane boundary. The data-quality config names it, and a
  test asserts it equals `apicommon.s3_config.MAX_DOCUMENT_BYTES`.
- **A source with a nested column keeps today's statement, and its samples are recorded as
  omitted.** Rendering an `array<…>` or `struct<…>` value as text needs a cast whose support for every
  element type is not documented, and a cast that fails would fail the whole statement and lose the
  duplicate count that works today. Flat columns cast to varchar, which every scalar type supports.
- **Files are not named per sample.** Grouping by every column erases which file a row came from,
  and recovering it means aggregating paths for every group or scanning a second time. The per-file
  row counts are the "where" this spec adds at the file level.

## Scope

### In Scope

- Per-file row counts on the report page (FR-001).
- The encoding examples on the page, and the corrected type and fixtures (FR-002).
- The duplicates statement keeps up to five samples (FR-003).
- `report.py` and assemble-report write the samples, within the document cap (FR-004).
- The page shows the samples (FR-005).
- The *Past data quality checks* guide in `helpContent.ts` says the report lists up to five
  duplicated rows and the rows in each file.
- At completion: an entry in `docs/decisions/control-planes.md` saying the report holds sampled
  rows of the user's data and is bounded by the document cap. `lambdas/info/planes/data-quality.md`
  gains the samples.

### Out of Scope

- **Every duplicate row**, or a download of them. Five are a sample. The Data Explorer's grouping
  with *duplicates only* finds all of them in a table.
- **Which file a duplicate is in** (see *The decisions*).
- **Samples of ragged rows.** The figure is approximate and counts well-formed multi-line records
  as ragged, so a sample would often show rows that are fine.
- **Line numbers.** Athena has none to give.
- **The notification.** Its text and link are unchanged, and it never carries a sample.
- **Changing what the duplicate count counts.**

---

## Functional Requirements

### FR-001: The report shows how many rows each file holds

#### Description:

When `exact.rowCountsByFile` has more than one entry, the page shows a closed disclosure titled
"Rows in each file (<n> files)". Inside is a two-column table with the file's path relative to the
checked location and its row count, in the report's order, with counts formatted as the summary tiles
format them. A single-file report shows no disclosure, because its one count is the report's row
count.

#### Acceptance Criteria:

- [ ] A report whose location is `alice/sales/` with `rowCountsByFile`
  `[{key: 'alice/sales/jan.csv', rows: 1200}, {key: 'alice/sales/feb/part-1.csv', rows: 0}]` renders
  a closed disclosure named "Rows in each file (2 files)". Opened, its rows read `jan.csv` `1,200`
  and `feb/part-1.csv` `0`.
- [ ] A report with one entry renders no such disclosure.
- [ ] A report whose `rowCountsByFile` is `[]` renders no such disclosure and does not throw.

### FR-002: The report shows where the invalid text encoding is

#### Description:

`EncodingFigure.sampleOffsets` becomes `{key: string; offset: number}[]`, and `reportFixtures.ts`
is corrected to that shape. When the figure is measured and `invalidUtf8Sequences` is above zero,
the encoding card lists each example as "<path relative to the checked location>, byte <offset>",
with the offset formatted with thousands separators, under the lead "Examples:". The card says the
list shows the first examples found, not all of them. A report written before the type change is the
same shape, since the writer never changed.

#### Acceptance Criteria:

- [ ] A report with 12 invalid sequences and `sampleOffsets` `[{key: 'alice/sales/jan.csv', offset: 4102}]`
  shows "jan.csv, byte 4,102" in the encoding card.
- [ ] A report with 0 invalid sequences shows no examples list.
- [ ] A skipped or not-computed encoding figure renders as today.
- [ ] `tsc -b` passes with the corrected type, and the fixture carries `{key, offset}` entries.

### FR-003: The duplicates statement keeps up to five samples

#### Description:

When no column's type starts with `array<` or `struct<`, `build_duplicates_query` groups exactly as
today and projects `COUNT(*)` as `cnt` and each grouped column under a positional alias. Over that,
it builds per group `sample`: an `array(varchar)` whose first element is `CAST(cnt AS varchar)` and
whose remaining elements are each grouped column's `substr(CAST(<alias> AS varchar), 1, 201)`, in
the grouped order. Over that, `sample_key`: the count left-padded to 19 digits followed by
`json_format(CAST(sample AS JSON))`. The outermost layer selects
`COALESCE(SUM(cnt - 1), 0) AS duplicate_rows`, as today, and
`json_format(CAST(max_by(sample, sample_key, DQ_DUPLICATE_SAMPLE) AS JSON)) AS duplicate_samples`.
The builder may use as many layers as it needs so that no expression is repeated. The path filter,
the partition-key ordering and the identifier quoting are unchanged. `DQ_DUPLICATE_SAMPLE = 5` is a
`dqcommon.config` constant.

When any column's type starts with `array<` or `struct<`, the statement is today's, byte for byte,
and its result has no `duplicate_samples` column.

#### Acceptance Criteria:

- [ ] The rendered statement for a table with columns `name`, `cnt`, `duplicate_rows` and partition
  key `year` is asserted as a whole string, and no layer's output names include `name`, or the
  source columns `cnt` and `duplicate_rows` under their own names.
- [ ] The statement contains `max_by(` exactly once in the duplicates query and no `array_agg(`.
- [ ] The count expression `COALESCE(SUM(cnt - 1), 0) AS duplicate_rows` and the `GROUP BY` and
  `HAVING COUNT(*) > 1` clauses are byte-identical to today's for the same inputs.
- [ ] With a path filter the `WHERE` clause is today's.
- [ ] For columns typed `string`, `bigint`, `date`, `timestamp` and `decimal(10,2)`, each is rendered
  through `CAST(… AS varchar)`.
- [ ] For a source with one `array<string>` column, the statement equals today's for the same inputs,
  asserted as a whole string.
- [ ] At `DQ_MAX_COLUMNS` columns, each named with 255 characters, the rendered statement is at most
  `DQ_MAX_QUERY_BYTES` UTF-8 bytes, pinned by a test in the shape of the profile query's.
- [ ] The live check in *Implementation Phases* passes. This criterion cannot settle before the
  push, so it is recorded as owed on the PR.

### FR-004: The report carries the samples, within the document cap

#### Description:

`report.py` reads `duplicate_samples` from the duplicates row and writes
`exact.duplicateSamples = {columns: [...], rows: [{repeats, values}]}` whenever `duplicateRows` is a
number and the source has no nested column. When it has one, `duplicateSamples` is
`{omitted: "<sentence>"}`, saying rows with nested values are not shown. `columns` is the grouped column order the statement used. Each row's `repeats` is its count,
and its `values` are the cells, each cut to `MAX_SAMPLE_VALUE_CHARS` with an ellipsis and `null`
kept as `null`. Rows are ordered most-repeated first, ties by rendered text. When `duplicateRows` is
0, `rows` is `[]`. An unparseable or absent `duplicate_samples` cell writes `rows: []`, and the count
stands. When `duplicateRows` is not computed, `duplicateSamples` is absent.

assemble-report serializes the report exactly as it writes it. If that is more than
`dqcommon.config.DQ_REPORT_MAX_BYTES` bytes, it writes the report with `duplicateSamples` replaced by
`{omitted: "<sentence>"}`, which says the samples were left out because the report would be too
large to open. If the report is still over the cap without them, it is written as today. That
defect predates this spec, and the log records the size. No sample value reaches a log line, a
span field, the notification or the runs index.

#### Acceptance Criteria:

- [ ] A duplicates row with `duplicate_rows` `7` and `duplicate_samples`
  `[["3","a","x"],["2",null,""]]`, over grouped columns `name, city`, produces
  `duplicateSamples` `{columns: ['name','city'], rows: [{repeats: 3, values: ['a','x']}, {repeats: 2, values: [null, '']}]}`.
- [ ] A 250-character value is written as its first 200 characters followed by `…`.
- [ ] `duplicate_rows` `0` with an empty samples cell writes `rows: []`. Unparseable JSON writes
  `rows: []` and `duplicateRows` stays the parsed count.
- [ ] A not-computed duplicates figure writes no `duplicateSamples`.
- [ ] A source with an `array<string>` column and 3 duplicates writes `duplicateRows` 3 and
  `duplicateSamples.omitted` with the nested-values sentence, asserted as a whole string.
- [ ] A report whose samples push it past `DQ_REPORT_MAX_BYTES` is written with
  `duplicateSamples.omitted` and every other figure unchanged, asserted by making the fixture's
  samples large rather than by lowering the constant.
- [ ] A test asserts `DQ_REPORT_MAX_BYTES` equals `apicommon.s3_config.MAX_DOCUMENT_BYTES`.
- [ ] The notification text, the runs-index entry and assemble-report's observability fields for a
  report with samples equal those for the same report without them.

### FR-005: The page shows the duplicate samples

#### Description:

`DataQualityReport.exact` gains `duplicateSamples?: DuplicateSamples`. When it has rows, the page
shows, below the summary tiles' duplicate figure, a section "Most repeated rows" with a
horizontally scrolling table: a *Repeats* column, then one column per `columns` entry. A NULL cell
reads `NULL` and an empty string reads `(empty)`, both in muted italic as the Data Explorer shows
them. A
cut value keeps its ellipsis, and a note says values longer than 200 characters are shortened. When
`duplicateSamples.omitted` is present, the section shows that sentence instead of a table. A report
with no `duplicateSamples`, from before this spec or with duplicates not computed, renders exactly as
today. The report's `isReport` check does not require the field.

#### Acceptance Criteria:

- [ ] The fixture from FR-004's first criterion renders a table named "Most repeated rows" whose
  header cells are Repeats, name, city and whose first row reads 3, a, x.
- [ ] The second row renders `NULL` and `(empty)` in its two cells.
- [ ] A report with `duplicateSamples: {omitted: 'The samples were left out…'}` shows that sentence
  and no table.
- [ ] A report without `duplicateSamples` renders no "Most repeated rows" section, and the existing
  report page tests pass unchanged.
- [ ] A report with `rows: []` renders no section.

---

## Data Model

```ts
// apps/portal/src/features/data-quality/dataQuality.types.ts

export type EncodingExample = {key: string; offset: number};

export type DuplicateSamples =
  | {columns: string[]; rows: {repeats: number; values: (string | null)[]}[]}
  | {omitted: string};

// EncodingFigure's measured arm: sampleOffsets: EncodingExample[];
// DataQualityReport['exact'] gains: duplicateSamples?: DuplicateSamples;
```

```python
# lambdas/data-quality-common/dqcommon/config.py
DQ_DUPLICATE_SAMPLE = 5
DQ_REPORT_MAX_BYTES = 6 * 1024 * 1024 // 2   # asserted equal to apicommon.s3_config.MAX_DOCUMENT_BYTES
```

## File & Folder Structure

```
lambdas/data-quality-common/dqcommon/sql.py, report.py, config.py, messages.py   (FR-003, FR-004)
lambdas/data-quality-common/ tests beside sql.py and report.py
lambdas/data-quality-assemble-report/dq_assemble_report.py (+ test)            (FR-004)
lambdas/info/planes/data-quality.md
apps/portal/src/features/data-quality/dataQuality.types.ts, reportFixtures.ts   (FR-002, FR-005)
apps/portal/src/features/data-quality/DataQualityReportPage.tsx (+ test)        (FR-001, FR-002, FR-005)
apps/portal/src/features/help/helpContent.ts
```

Other sessions were changing `dqcommon/sql.py` and the report page's tests when this spec was written.
Every criterion here is stated against `main` at build time.

## Implementation Phases

### Phase 1: The browser, over what is stored

- The corrected type and fixtures, the per-file disclosure and the encoding examples (FR-001,
  FR-002). This phase ships value on its own and needs no plane change.

### Phase 2: The plane

- The three-layer duplicates statement and its constant (FR-003).
- `report.py`'s samples, assemble-report's cap and omission, the equality test, and the log sweep
  (FR-004).
- The plane page.

### Phase 3: The samples on the page, Help and the live check

- The *Most repeated rows* section (FR-005) and the guide sentence.
- The live check, run from a signed-in session after deploy: upload `dupes/a.csv` with the header
  `name,city,note` and the rows `Ann,Leeds,` three times, `Bo,,x` twice and `Cy,York,z` once, plus
  `dupes/b.csv` with one `Ann,Leeds,` row. Check the folder. The report says 4 duplicate rows, lists
  `Ann, Leeds, (empty)` with 4 repeats first and `Bo, (empty), x` with 2 second, and the per-file
  disclosure shows `a.csv` 6 and `b.csv` 1. Blank CSV cells are empty strings, so no `NULL`
  appears. Fold it into `docs/testing/e2e.md` at completion.
