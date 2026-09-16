# Spec: An Export Leaves Out the Columns the Grid Hides

**ID:** SPEC-239
**Status:** Draft
**Last Updated:** 2026-09-16
**Depends On:** SPEC-185, SPEC-221, SPEC-222, SPEC-223, SPEC-229

## Overview

A tester hides columns in the Data Explorer "to then export". Today that does not work: hiding a
column only changes what the grid draws, and *Save results to my files* saves the query's whole
result, so every hidden column is in the file. This spec makes a Data Explorer export save only the
columns the grid shows, in the order it shows them, with no second query and nothing extra billed.

It does that in the results-conversion plane, which already reads the finished result rather than
the source table. The plane learns to keep a chosen list of columns, and gains a CSV writer. A CSV
export with nothing hidden and nothing reordered stays the instant copy it is today. One that leaves
columns out goes through the plane, like Parquet, JSON and Excel, and a notification says when the
file is ready.

### What was checked, and how

Read from the code at `73c66eef`.

- **Hiding is presentation only.** `renderProjection` in
  `features/data-explorer/renderExplorationSql.ts` always renders `SELECT *` when not grouping, and
  says why: narrowing to the visible columns would make un-hiding a column a billed re-run.
- **Export saves the execution's result object.** `ExportExplorationDialog` mounts
  `features/catalog/useSaveResults`. There, `doSaveCopy` copies the CSV Athena wrote, and
  `doConvert` returns early for `csv` and enqueues every other format. `SaveResultsDialog` labels the
  button *Save here* for CSV and *Convert and save* otherwise.
- **The plane has no CSV and no column choice.** `rccommon.config.FORMATS` is `parquet`, `json`,
  `xlsx`. `ResultsConversionEnqueueRequest` in `lambdas/api/apicommon/contract.py` types `format`
  as those three and says CSV is excluded on purpose, because the synchronous path copies it.
  `rc_convert._write` dispatches to three writers.
- **The state already has a `columns` key.** describe-results emits `columns` (the described result
  columns) and `resultsBytes`, and convert reads `columns` with `events.require`. describe-results
  refuses `too_many_columns` above `rccommon.config.MAX_RESULT_COLUMNS` (1,500) and refuses two
  columns whose names collide once case-folded.
- **The typed read reformats values.** `_frame` reads the CSV with `schema_overrides` built by
  `types.schema_of`, so a CSV written from that frame would reformat numbers and timestamps, and a
  column type `schema_of` refuses would refuse the whole export.
- **Every caller-controlled enqueue field declares a bound.** `lambdas/api/apicommon/bounds.py`
  holds a `Bound` per field, with `measured` naming the unit (`wire`, `value` or `items`) and
  `enforced_at` saying whether the API applies it before the message is built.
  `lambdas/test_request_size_chain.py` measures each route's chain against the state limit.

### The decisions, made while authoring

- **The converter leaves hidden columns out** (Andrew, 2026-09-16). The rejected options were
  re-running a narrowed `SELECT` at export, which is a second billed scan, and exporting every
  column with a note saying so.
- **The request names columns by their position in the result.** The Data Explorer resolves each
  visible column's name to its index in the execution's own column list. An index is unambiguous,
  because describe-results already refuses a result whose names collide once case-folded, and a
  list of at most 1,500 small integers cannot strain any link of the size chain.
- **The field is `columnIndexes`, never `columns`.** `columns` is the described column list that
  convert already reads from the state. A request field of that name would be overwritten by it, or
  overwrite it.
- **A list is sent whenever the visible columns, in grid order, differ from the result's full
  column list in its own order.** Hiding a column, or moving one, sends a list. Otherwise no list is
  sent, and a CSV export stays a copy.
- **The CSV writer does not type anything.** It reads every column as text and writes the kept
  columns' text as Athena wrote it, so a CSV export through the plane contains the same values as
  one made by copying. Only the quoting can differ: polars quotes a field only when it has to.
  NULL stays an unquoted empty field and an empty string stays `""`, which is Athena's own encoding
  and what `_frame`'s docstring says polars reads by default.
- **Typing and every type refusal consider kept columns only.** A column left out of the file
  cannot be a reason the file is refused.
- **The CSV format's disk entries are measured, not argued.** `OUTPUT_EXPANSION["csv"]` and
  `RESULTS_MAX_BYTES["csv"]` are derived from the same model and the same generated CSVs as
  Parquet's and JSON's, and `MEASURED_ON` records the run. Arguing that projected CSV is never
  longer than its input is exactly the kind of unmeasured claim the plane's config refuses.
- **The Query workspace is unchanged.** Its grid has no hidden columns, so it never sends a list.

## Scope

### In Scope

- The request contract, the API bound and validate-authorize for `columnIndexes` and `csv` (FR-001).
- describe-results checks the indexes against the described columns (FR-002).
- convert keeps only the listed columns, in list order, for every format (FR-003).
- A CSV writer in convert (FR-004).
- The Data Explorer's export, `useSaveResults`, `SaveResultsDialog`, and the *Copy or save what you
  found* guide (FR-005).
- At completion: an entry in `docs/decisions/control-planes.md` saying a conversion can keep a
  subset of the result's columns. The Fences clause *A conversion's input is the EXECUTION'S RESULT
  OBJECT* gains "and it may keep a subset of its columns", and the contract docstring's "deliberately
  excludes CSV" sentence is replaced where it stands.

### Out of Scope

- **Changing the Data Explorer's SQL.** `SELECT *` stays, and hiding a column still costs nothing.
- **Hidden columns in the Query workspace**, and any change to its Save results.
- **Copying cells.** *Copy…* already takes the selected cells, which are what the grid shows.
- **Renaming columns in the file.** The header is the result's own column names.
- **The percentage column** a grouped exploration adds. It is computed in the browser and is not in
  the result, so it is never exported, as today.
- **Any new infrastructure, IAM or queue.** The plane's role already reads the result and writes the
  destination.

---

## Functional Requirements

### FR-001: The request can carry `columnIndexes`, and `csv` is a conversion format

#### Description:

`ResultsConversionEnqueueRequest` gains an optional `columnIndexes: list[int]`, and `format` gains
`"csv"`. `bounds.py` declares a `Bound` on `columnIndexes` for `resultsConversion.enqueue`,
enforced at the `api`, measured in `items`, with a number of 1,500. Its budget sentence names
describe-results' column cap, and a test asserts the number equals
`rccommon.config.MAX_RESULT_COLUMNS`. `rccommon.config` gains `csv` in `FORMATS`
and `FORMAT_LABELS` (`"CSV"`), and measured `csv` entries in `OUTPUT_EXPANSION` and
`RESULTS_MAX_BYTES`. validate-authorize adds `columnIndexes` to `_ALLOWED_FIELDS`. When the field is
present it must be a non-empty list, of at most `MAX_RESULT_COLUMNS` entries, of distinct integers
that are at least 0. `True` and `False` are not integers here, although Python's `bool` subclasses
`int`. Anything else is refused with a new reason, `invalid_columns`, before any verb reads Athena.
A valid list is carried on the state unchanged.

#### Acceptance Criteria:

- [ ] The enqueue route accepts a body with `format: "csv"` and `columnIndexes: [2, 0]`, and a body
  with neither field's new values, exactly as before.
- [ ] The route refuses a body whose `columnIndexes` has 1,501 entries, before any message is sent.
- [ ] `test_request_size_chain.py` covers the route with `columnIndexes` at 1,500 entries and stays
  green.
- [ ] validate-authorize refuses each of `[]`, `[0, 0]`, `[-1]`, `[1.5]`, `["0"]`, `[true]` and
  `"0,1"` with reason `invalid_columns`, and the refusal notification's text is asserted as a whole
  string.
- [ ] `[3, 1]` passes validate-authorize and reaches describe-results' input unchanged.
- [ ] A test asserts the bound's 1,500 equals `rccommon.config.MAX_RESULT_COLUMNS`.

### FR-002: describe-results refuses an index outside the result

#### Description:

After describing the columns, describe-results refuses `invalid_columns` when any index in
`columnIndexes` is greater than or equal to the number of described columns. It carries
`columnIndexes` forward beside `columns` and `resultsBytes`. A request without the field is
unchanged.

#### Acceptance Criteria:

- [ ] A 4-column result with `columnIndexes: [0, 4]` is refused `invalid_columns`, and convert is
  not invoked.
- [ ] A 4-column result with `[3, 0]` emits a state carrying `columns` (all four), `resultsBytes`
  and `columnIndexes: [3, 0]`.
- [ ] A request without `columnIndexes` emits exactly the state it emits today.

### FR-003: convert keeps only the listed columns, in list order, for every format

#### Description:

When `columnIndexes` is present, convert writes only those columns, in that order, for Parquet,
JSON, Excel and CSV. `types.schema_of` and every type refusal it raises see only the kept columns.
Excel's cell cap counts rows times kept columns. The header check in `_frame` still compares the
whole CSV header against the whole described column list, because the object is still the whole
result. Without the field, every format writes every column, as today.

#### Acceptance Criteria:

- [ ] A result `a, b, c` converted to Parquet with `[2, 0]` produces a file whose schema is `c, a`
  and whose rows carry the matching values.
- [ ] The same for JSON: every line's keys are exactly `c, a`, in that order.
- [ ] The same for Excel: the header row is `c`, `a`.
- [ ] A result whose column `b` is a `decimal` with no readable scale, which convert refuses today,
  converts to Parquet with `[0, 2]`.
- [ ] A result of 500,000 rows and 20 columns, which Excel's cell-count check refuses today, passes
  that check with `columnIndexes` of 8 entries (4,000,000 cells). The check is asserted on its own,
  not the write, since the byte cap is a separate check on the unchanged input.
- [ ] Every existing convert test passes unchanged.

### FR-004: A CSV writer that writes the result's text

#### Description:

For `format: "csv"`, convert reads the result with every column as a string, keeps the listed
columns (or all of them), and writes a CSV with the kept columns' names as its header. A NULL is an
unquoted empty field, an empty string is `""`, and every other value is Athena's text exactly,
quoted only where the CSV format requires it. The upload, the conflict handling, the notification
and the refusals are the plane's existing ones, with the format label `CSV`.

#### Acceptance Criteria:

- [ ] A result holding a double `1.50`, a timestamp `2026-09-16 10:00:00.000`, a string
  `He said "hi", then left` with a newline inside, a NULL and an empty string round-trips: reading
  the written file back through `_frame`'s string read gives exactly those five values, NULL and
  empty still distinct.
- [ ] With `[1]` on a result `a, b`, the file's header is `b` alone.
- [ ] A `csv` conversion onto an occupied destination with `onConflict: "refuse"` is refused the way
  a Parquet one is today.
- [ ] The success notification names the format `CSV`, asserted as a whole string.
- [ ] `MEASURED_ON` names the run that measured the `csv` expansion, and the plane's existing size
  corpus includes `csv`.

### FR-005: The Data Explorer exports what the grid shows

#### Description:

`useSaveResults` takes a new parameter, `columnIndexes: number[] | null`. The Query workspace always
passes `null`. The Data Explorer passes the index, in the execution's result columns, of each
visible column in grid order, leaving out any column not in the result (the percentage column). It
passes `null` when that list is every index in order. With a list:

- a CSV save goes through the conversion path with `format: 'csv'` and the list, instead of copying;
- a Parquet, JSON or Excel save sends the list;
- `SaveResultsDialog` labels the button *Convert and save* for every format and shows
  "Only the <n> columns shown are saved, in the order shown." above the button.

With `null`, every path is exactly today's. The *Copy or save what you found* guide says a save from
the Data Explorer leaves out hidden columns and keeps the order shown, and that doing so makes a CSV
save a conversion with a notification.

#### Acceptance Criteria:

- [ ] Result columns `a, b, c`, `b` hidden: a CSV save enqueues one conversion with
  `format: 'csv'` and `columnIndexes: [0, 2]`, and the copy service is not called.
- [ ] Result columns `a, b, c`, `c` dragged first, none hidden: the conversion carries `[2, 0, 1]`.
- [ ] Result columns `a, b, c`, none hidden, none moved: a CSV save calls the copy service and
  enqueues nothing, and the dialog shows *Save here* and no column sentence.
- [ ] A grouped exploration with the percentage column visible sends indexes for the result's own
  columns only.
- [ ] With `b` hidden the dialog shows "Only the 2 columns shown are saved, in the order shown."
  and *Convert and save* while CSV is selected.
- [ ] The Query workspace's save enqueues no `columnIndexes`, asserted in its existing save test.
- [ ] The guide carries the two sentences. This is static copy, so the diff review checks it.

---

## Data Model

```python
# lambdas/api/apicommon/contract.py
class ResultsConversionEnqueueRequest(TypedDict):
    requestId: str
    queryExecutionId: str
    format: Literal["parquet", "json", "xlsx", "csv"]
    destination: ConversionDestination
    onConflict: Literal["refuse", "overwrite"]
    submittedAt: str
    columnIndexes: NotRequired[list[int]]
```

```ts
// apps/portal/src/features/catalog/resultsConversion.service.ts — the enqueue body gains
columnIndexes?: number[];
```

## API / Interface Contract

```ts
// apps/portal/src/features/catalog/useSaveResults.ts — Params gains
/** Result-column positions to keep, in order; null keeps every column and lets CSV copy. */
columnIndexes: number[] | null;

// apps/portal/src/features/data-explorer — a pure helper, beside the export wiring
export function exportColumnIndexes(resultColumns: string[], visibleInOrder: string[]): number[] | null;
```

## File & Folder Structure

```
lambdas/api/apicommon/contract.py, bounds.py, test_bounds.py         (FR-001)
lambdas/test_request_size_chain.py                                   (FR-001)
lambdas/results-conversion-common/rccommon/config.py, reasons.py, messages.py
lambdas/results-conversion-validate-authorize/rc_validate_authorize.py (+ test)   (FR-001)
lambdas/results-conversion-describe-results/rc_describe_results.py (+ test)       (FR-002)
lambdas/results-conversion-convert/rc_convert.py (+ test)                          (FR-003, FR-004)
lambdas/info/planes/results-conversion.md                            (the envelope and the fourth writer)
apps/portal/src/features/catalog/useSaveResults.ts, SaveResultsDialog.tsx, resultsConversion.service.ts
apps/portal/src/features/data-explorer/ExportExplorationDialog.tsx host wiring, the helper (+ tests)
apps/portal/src/features/help/helpContent.ts
```

## Implementation Phases

### Phase 1: The plane

- The contract, the bound and its equality test, the config entries, `invalid_columns` and its
  wording, validate-authorize and describe-results (FR-001, FR-002).
- convert's projection and the CSV writer (FR-003, FR-004), and the measurement run for the `csv`
  config entries.
- The plane page's envelope and writer list.

### Phase 2: The browser

- `exportColumnIndexes`, `useSaveResults`, `SaveResultsDialog`, the Data Explorer host, the Query
  workspace's `null`, and the guide (FR-005).
- The live check, run from a signed-in session after deploy: explore a CSV table with columns
  `a, b, c`, hide `b`, drag `c` first, and save as CSV. The notification arrives, and the file's
  header is `c,a`, with the same row count the pager shows. Then show `b` again, put the columns
  back in order, and save as CSV. The file lands at once with all three columns. Fold it into
  `docs/testing/e2e.md` at completion.
