# Spec: An Export Leaves Out the Columns the Grid Hides

**ID:** SPEC-239
**Status:** Draft
**Last Updated:** 2026-09-20
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
- **The machine names every key it passes on.** `Validated` and `Described` in
  `infra/modules/results-conversion/state-machine.asl.json.tftpl` are Pass states listing each key,
  and `test_state_machine_results_conversion.py` holds those lists equal to what the verbs really
  return. A key the lists do not name never reaches the next verb, and a Pass state naming a key the
  state lacks fails with an uncatchable `States.Runtime` (control-planes Fences).
- **The overwrite path routes separately.** `useSaveResults.confirmOverwrite` sends `csv` to
  `doSaveCopy` on its own, beside `save`.
- **The visible order lives in the region.** `useColumnGeometry`, called in
  `ExplorationResultsRegion.tsx`, orders columns with the pinned block first and carries each
  column's result index. Until the results land, the column set falls back to the Glue schema.
  `useSaveResults` is called in `DataExplorerWorkspace.tsx`, which passes `onExport` down.
- **polars' fast row count is wrong on a split file.** The plane page's Traps record
  `select(pl.len())` on a CSV scan miscounting quoted newlines once the file is split across
  threads. The Excel path counts through one projected column instead. The JSON writer counts
  newline bytes, which is only right because JSON escapes a newline.
- **The config's expansion figures have no script.** `MEASURED_ON` records Parquet and JSON measured
  over generated Athena-shaped CSVs of four sizes. `test_plane_results_conversion.py` pins the format
  set to three and holds a per-format throughput table for Parquet and JSON only.
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
- **Every verb emits `columnIndexes`, as `null` when the request had none.** The Pass states must
  name the key for it to reach convert, and a Pass state reading an absent key is an uncatchable
  failure, so the key is always present. The template change is part of this spec.
- **The API bound is the list's one length cap.** validate-authorize checks the list's shape and
  describe-results checks each index against the result. A second length check in the verb could
  never fire behind the API's, and a refusal that denies nobody misleads the next reader.
- **The Data Explorer hands the list over when export opens.** `onExport` takes the list, computed
  in the region from `useColumnGeometry` over the execution's result columns only, never the Glue
  fallback. The workspace keeps it in state and passes it to `useSaveResults`. "Grid order" is the
  order the grid draws, pinned columns first.
- **Showing no result column refuses the save.** A grouped view's percentage column is not in the
  result, so hiding every real column would send an empty list. *Save results to my files* is
  refused with "Show at least one of the result's columns to save it." instead. **The build found
  a second way in**, and the spec said "only" where it should not have: a stored hide is never
  pruned, deliberately, so one naming every column of a re-executed result reaches the same
  state. The refusal is right in both; what was wrong was the claim about reachability.
- **A list is sent whenever the visible columns, in grid order, differ from the result's full
  column list in its own order.** Hiding a column, or moving one, sends a list. Otherwise no list is
  sent, and a CSV export stays a copy.
- **The CSV writer does not type anything and streams.** It skips `types.schema_of`, reads every
  column as text, and writes the kept columns' text with `sink_csv`, as Athena wrote it, so a CSV export through the plane contains the same values as
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
- describe-results checks the indexes against the described columns, and the state machine carries
  them (FR-002).
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
- **Any new resource, IAM grant or queue.** The plane's role already reads the result and writes the
  destination. The existing state-machine template changes (FR-002), and nothing else in `infra/`.

---

## Functional Requirements

### FR-001: The request can carry `columnIndexes`, and `csv` is a conversion format

#### Description:

`ResultsConversionEnqueueRequest` gains an optional `columnIndexes: list[int]`, and `format` gains
`"csv"`. `apiContract.generated.ts` is regenerated from it with `scripts/generate_api_contract.py`,
never edited by hand. `bounds.py` declares a `Bound` on `columnIndexes` for
`resultsConversion.enqueue`, enforced at the `api`, measured in `items`, with a number of 1,500. Its
budget sentence names describe-results' column cap, a test asserts the number equals
`rccommon.config.MAX_RESULT_COLUMNS`, and the list in `test_bounds.py` of bounds it cannot judge by
name gains it. `rccommon.config` gains `csv` in `FORMATS` and `FORMAT_LABELS` (`"CSV"`), and measured
`csv` entries in `OUTPUT_EXPANSION` and `RESULTS_MAX_BYTES`. `rc_convert.CONTENT_TYPES` gains
`csv: text/csv`.

validate-authorize adds `columnIndexes` to `_ALLOWED_FIELDS`. When the field is present, the verb
first checks it is a list, then that every entry is an `int` and not a `bool` (Python's `bool`
subclasses `int`), then that the list is non-empty, then that entries are distinct and at least 0.
Anything else is refused with a new reason, `invalid_columns`, before any set is built from the
entries and before any verb reads Athena. Its wording is "the columns chosen for this file don't
match the query's results, so nothing was saved." — lower-cased in the build, as every other
body on this plane is, because the resolver renders it after the prefix `Couldn't save the query
results{asFormat}: ` and a capital there reads as two half-sentences. The verb emits
`columnIndexes`, as `null` when the request had none.

#### Acceptance Criteria:

- [ ] The enqueue route accepts a body with `format: "csv"` and `columnIndexes: [2, 0]`, and a body
  without `columnIndexes`, exactly as before.
- [ ] The route refuses a body whose `columnIndexes` has 1,501 entries, before any message is sent.
- [ ] `test_request_size_chain.py` covers the route with `columnIndexes` at 1,500 entries and stays
  green.
- [ ] validate-authorize refuses each of `[]`, `[0, 0]`, `[-1]`, `[1.5]`, `["0"]`, `[true]`,
  `[[0]]` and `"0,1"` with reason `invalid_columns`, raising no `TypeError`, and the refusal
  notification's text is the sentence above, asserted as a whole string.
- [ ] `[3, 1]` passes validate-authorize and is emitted unchanged, and a request without the field
  emits `columnIndexes: null`.
- [ ] A test asserts the bound's 1,500 equals `rccommon.config.MAX_RESULT_COLUMNS`.

### FR-002: describe-results checks the indexes, and the machine carries them

#### Description:

After describing the columns, describe-results refuses `invalid_columns` when any index in
`columnIndexes` is greater than or equal to the number of described columns. It emits `columnIndexes`
beside `columns` and `resultsBytes`, `null` included. The `Validated` and `Described` Pass states in
`state-machine.asl.json.tftpl` each gain `"columnIndexes.$": "$.columnIndexes"`, and the plane's
state-machine test keeps holding both lists equal to the verbs' real return values.

#### Acceptance Criteria:

- [ ] A 4-column result with `columnIndexes: [0, 4]` is refused `invalid_columns`, and convert is
  not invoked.
- [ ] A 4-column result with `[3, 0]` emits a state carrying `columns` (all four), `resultsBytes`
  and `columnIndexes: [3, 0]`.
- [ ] A request without `columnIndexes` emits today's state plus `columnIndexes: null`.
- [ ] `test_state_machine_results_conversion.py` passes with `columnIndexes` named in both Pass states,
  and fails when either state omits it or either verb stops emitting it.

### FR-003: convert keeps only the listed columns, in list order, for every format

#### Description:

When `columnIndexes` is not null, convert writes only those columns, in that order, for Parquet,
JSON, Excel and CSV. For Parquet, JSON and Excel, `types.schema_of` and every type refusal it raises
see only the kept columns. Excel's row and cell check is given the kept column count. The header
check in `_frame` still compares the whole CSV header against the whole described column list,
because the object is still the whole result. With `null`, every format writes every column, as
today.

#### Acceptance Criteria:

- [ ] A result `a, b, c` converted to Parquet with `[2, 0]` produces a file whose schema is `c, a`
  and whose rows carry the matching values.
- [ ] The same for JSON: every line's keys are exactly `c, a`, in that order.
- [ ] The same for Excel: the header row is `c`, `a`.
- [ ] A result whose column `b` is a `decimal` with no precision, which `schema_of` refuses today,
  converts to Parquet with `[0, 2]`.
- [ ] `_convert` over a described result of 20 columns and 500,000 rows, with `columnIndexes` of 8
  entries and the workbook build stubbed, raises no `excel_cell_limit` refusal. The same call with
  `columnIndexes: null` does.
- [ ] Every existing convert test passes unchanged.

### FR-004: A CSV writer that writes the result's text

#### Description:

For `format: "csv"`, convert skips `types.schema_of`, reads the result with every column as a
string, keeps the listed columns (or all of them), and streams a CSV with `sink_csv`, with the kept
columns' names as its header. A NULL is an unquoted empty field, an empty string is `""`, and every
other value is Athena's text exactly, quoted only where the CSV format requires it. It counts rows
as the Excel path does, through one projected column with the real reader, never `select(pl.len())`
and never by counting newlines. The upload, the conflict handling, the notification and the refusals
are the plane's existing ones, with the format label `CSV`.

The `csv` entries in `OUTPUT_EXPANSION` and `RESULTS_MAX_BYTES` are measured by converting generated
Athena-shaped CSVs of the four sizes `MEASURED_ON` already names, in the fleet image, and
`MEASURED_ON` records the run. `test_plane_results_conversion.py`'s format set gains `csv`, and its
throughput table gains a measured `csv` figure.

#### Acceptance Criteria:

- [ ] A result holding a double `1.50`, a timestamp `2026-09-16 10:00:00.000`, a string
  `He said "hi", then left` with a newline inside, a NULL and an empty string round-trips: reading
  the written file back as strings gives exactly those five values, NULL and empty still distinct.
- [ ] A `csv` conversion keeping a column `b` that is a `decimal` with no precision succeeds, and
  the file holds `b`'s text.
- [ ] With `[1]` on a result `a, b`, the file's header is `b` alone.
- [ ] A 100,000-row result, large enough to be split across threads, whose values contain quoted
  newlines, reports 100,000 rows.
- [ ] The streaming guard that covers Parquet and JSON covers `csv`.
- [ ] A `csv` conversion onto an occupied destination with `onConflict: "refuse"` is refused the way
  a Parquet one is today.
- [ ] The success notification names the format `CSV`, asserted as a whole string.
- [ ] `MEASURED_ON` names the run that measured `csv`, and the format set and throughput table in
  `test_plane_results_conversion.py` include it.

### FR-005: The Data Explorer exports what the grid shows

#### Description:

`useSaveResults` takes a new parameter, `columnIndexes: number[] | null`, and one routing predicate,
`convertsFor(format, columnIndexes)`, true for any non-CSV format and for CSV with a list. Both
`save` and `confirmOverwrite` route through it, so an overwrite follows the same path as the save
that raised it. The Query workspace always passes `null`.

In the Data Explorer, `ExplorationResultsRegion` computes `exportColumnIndexes(resultColumns,
visibleInOrder)` when *Save results to my files* is chosen. `resultColumns` is the execution's result
column names, never the Glue fallback. `visibleInOrder` is `useColumnGeometry`'s visible columns in
draw order, pinned first. Columns not in the result, such as the percentage column, are left out. The
helper returns `null` when the list is every result index in order. The region calls
`onExport(columnIndexes)`, and `DataExplorerWorkspace` keeps the list in state and passes it to
`useSaveResults`. When no result column is visible, *Save results to my files* is refused with
"Show at least one of the result's columns to save it.".

With a list:

- a CSV save goes through the conversion path with `format: 'csv'` and the list, instead of copying;
- a Parquet, JSON or Excel save sends the list;
- `SaveResultsDialog` labels the button *Convert and save* for every format and shows
  "The file holds <n> result column(s), in the order shown." above the button. **Reworded twice in
  the build, each time because a reachable state falsified it.** "Only the <n> columns shown are
  saved" reads "Only the 1 columns" at one column, which `hideRefusal` admits directly, and on a
  pure reorder it names an omission that did not happen. Saying "shown" at all then failed its own
  test: a grouped exploration draws its percentage column, so the grid can show two columns while
  the file holds one. The count is of RESULT columns, and the sentence now says so.

With `null`, every path is exactly today's. In the *Copy or save what you found* guide, the step
"CSV is saved straight away — the button reads Save here" is reworded to say that holds when every
column is shown in its original order. The guide gains that a save from the Data Explorer leaves out
hidden columns and keeps the order shown, and that a CSV save then converts, with a notification.

#### Acceptance Criteria:

- [ ] `exportColumnIndexes(['a','b','c'], ['a','c'])` is `[0, 2]`,
  `exportColumnIndexes(['a','b','c'], ['c','a','b'])` is `[2, 0, 1]`,
  `exportColumnIndexes(['a','b','c'], ['a','b','c'])` is `null`, and
  `exportColumnIndexes(['a'], ['a', 'pct_of_count_all'])` is `null`.
- [ ] Result columns `a, b, c`, `b` hidden: a CSV save enqueues one conversion with
  `format: 'csv'` and `columnIndexes: [0, 2]`, and the copy service is not called.
- [ ] The same save onto an occupied name, then *Overwrite*: one conversion is enqueued with
  `onConflict: 'overwrite'` and the list, and the copy service is not called.
- [ ] Result columns `a, b, c`, `c` pinned, none hidden: the conversion carries `[2, 0, 1]`.
- [ ] Result columns `a, b, c`, none hidden, none moved: a CSV save calls the copy service and
  enqueues nothing, and the dialog shows *Save here* and no column sentence.
- [ ] A grouped exploration with every result column hidden and the percentage column visible shows
  *Save results to my files* refused with the sentence above.
- [ ] With `b` hidden the dialog shows "The file holds 2 result columns, in the order shown." and
  *Convert and save* while CSV is selected, and a grid down to one column says "1 result column".
- [ ] The Query workspace's save enqueues no `columnIndexes`, asserted in its existing save test.
- [ ] The guide carries the reworded step and the new sentences. This is static copy, so the diff
  review checks it.

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

The browser's enqueue body type comes from the regenerated `apiContract.generated.ts`.

## API / Interface Contract

```ts
// apps/portal/src/features/catalog/useSaveResults.ts — Params gains
/** Result-column positions to keep, in order; null keeps every column and lets CSV copy. */
columnIndexes: number[] | null;
export function convertsFor(format: ResultsFormat, columnIndexes: number[] | null): boolean;

// apps/portal/src/features/data-explorer/exportColumns.ts
export function exportColumnIndexes(resultColumns: string[], visibleInOrder: string[]): number[] | null;

// ExplorationResultsRegionProps
onExport: (columnIndexes: number[] | null) => void;
```

## File & Folder Structure

```
infra/modules/results-conversion/state-machine.asl.json.tftpl       (FR-002)
lambdas/api/apicommon/contract.py, bounds.py, test_bounds.py         (FR-001)
lambdas/test_request_size_chain.py                                   (FR-001)
apps/portal/src/types/apiContract.generated.ts (regenerated)         (FR-001)
lambdas/results-conversion-common/rccommon/config.py, reasons.py, messages.py
lambdas/results-conversion-common/test_state_machine_results_conversion.py        (FR-002)
lambdas/results-conversion-validate-authorize/rc_validate_authorize.py (+ test)   (FR-001)
lambdas/results-conversion-describe-results/rc_describe_results.py (+ test)       (FR-002)
lambdas/results-conversion-convert/rc_convert.py (+ test)                          (FR-003, FR-004)
lambdas/results-conversion-common/test_plane_results_conversion.py           (FR-004)
lambdas/info/planes/results-conversion.md                            (the envelope and the fourth writer)
apps/portal/src/features/catalog/useSaveResults.ts, SaveResultsDialog.tsx (+ tests)
apps/portal/src/features/data-explorer/exportColumns.ts (+ test), ExplorationResultsRegion.tsx,
  DataExplorerWorkspace.tsx
apps/portal/src/features/help/helpContent.ts
apps/portal/info/component-inventory/catalog-feature.md (useSaveResults, SaveResultsDialog), data-explorer-feature.md (the export row)
```

## Implementation Phases

### Phases 1 and 2: The plane, in two pull requests, in this order

The verbs, the state machine and the browser deploy in separate workflows, and `Deploy
Infrastructure` and `Deploy Lambdas` run in parallel on one push (`lambdas/info/deployment.md`). A
state machine naming `columnIndexes` before the verbs emit it fails every conversion with an
uncatchable `States.Runtime`, and a browser sending `csv` before the converter writes it fails every
such save. The invariant: every pull request leaves `main`'s suites green, and every conversion
works during and after its deploys. So each change lands after the one it needs, and the plan review
decides the test mechanics that keep each step green:

1. **The verbs emit the key, and nothing else.** validate-authorize and describe-results return
   `columnIndexes`, `null` when the request named none. Today's Pass states drop the extra key
   harmlessly, and both verbs read it with a `null` default rather than requiring it, because no
   state carries it yet. **Nothing else lands here, and the reason is that nothing else CAN
   fire.** The field is not admitted (`_ALLOWED_FIELDS` is held equal to the API's declared
   fields by a fleet guard), no state carries it, so a shape check, an index check, a reason code
   and its wording would all be unreachable for a release — a refusal that can deny nobody, which
   this plane's own decisions refuse. They land in step 2, where the contract makes them
   reachable in the same push. Two cross-checks admit `columnIndexes` on the VERBS' side only,
   each named as an exemption step 2 deletes: the plane's own state-machine test, and the
   fleet-wide one, whose per-pair drop table is the mechanism for exactly this. One-sided is
   load-bearing — subtracted from both sides, an exemption survives step 2 in silence — and each
   verb test therefore asserts the key's presence directly, since the equalities have gone quiet
   about it.
2. **The machine carries it, the converter uses it, and the API accepts it.** The two Pass states
   name `columnIndexes` and both exemptions are deleted (FR-002); `rccommon`'s reason and its
   wording, validate-authorize's `_ALLOWED_FIELDS` and its shape checks, and describe-results'
   check of each position against the described columns (FR-001's verb half, FR-002's verb half);
   convert's projection and the CSV writer with its measurement run (FR-003, FR-004); the
   contract, the bound and its equality test, and the regenerated TypeScript (FR-001's API half).
   The plane page's envelope and writer list, and the live-check fixture's format loop.
   **This was authored as two pull requests and is one**, because the key is returned by step 1's
   image: by the time the ASL can name it a deployed image already does, so every order of this
   push is safe — the ASL first (step 1's verbs return it), the fleet first (the old ASL drops it
   and convert reads `null`), or a failed apply (nothing reads it). The condition that makes that
   true is load-bearing: **convert and describe-results read the key with `get`, never
   `events.require`**, which refuses a `null` value as well as an absent one. Splitting it would
   also re-point every function in the fleet for two lines of JSON, since `deploy-lambdas.yml`
   fires on `infra/modules/**` too. The push carries its own race between the API image and the
   convert image, harmless only because nothing sends `csv` or a list until step 3.

### Phase 3: The browser, in a third pull request

- `exportColumnIndexes`, `convertsFor`, `useSaveResults`, `SaveResultsDialog`, the region and the
  workspace, the Query workspace's `null`, and the guide (FR-005).
- The live check, run from a signed-in session after deploy: explore a CSV table with columns
  `a, b, c`, hide `b`, drag `c` first, and save as CSV. The notification arrives, and the file's
  header is `c,a`, with the same row count the pager shows. Pin `c` instead of dragging if the grid
offers no drag at that width. Then show `b` again, put the columns
  back in order, and save as CSV. The file lands at once with all three columns. Fold it into
  `docs/testing/e2e.md` at completion.
