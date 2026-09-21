# Completed Spec — SPEC-239: An Export Leaves Out the Columns the Grid Hides

## What was completed?

- **A Data Explorer export holds the result columns the grid is showing, in the order it shows
  them**, with no second query and nothing extra billed. The plane still reads the finished result
  object; it now writes a subset of it.
- **The request carries `columnIndexes`** — positions in the execution's own column list, in the
  order the file is to carry them, absent when every column is kept. `ResultsConversionEnqueueRequest`
  declares it, `bounds.MAX_COLUMN_INDEXES_PER_REQUEST` caps its length at the plane's own result
  width, and `Validated` and `Described` carry it.
- **A fourth writer.** `rc_convert._write_csv` reads every column as text and streams it back out,
  so a CSV conversion carries the characters Athena wrote and only the quoting differs. `csv` joins
  `FORMATS`, `FORMAT_LABELS`, `OUTPUT_EXPANSION`, `RESULTS_MAX_BYTES` and `CONTENT_TYPES`.
- **`rc_convert._schemas`** splits the read schema (every described column, so `_frame`'s header
  check still sees the whole header) from the write schema (the kept columns, in request order), so
  typing and every type refusal it raises see the kept columns alone.
- **`exportColumnIndexes`** (`features/data-explorer/exportColumns.ts`) and **`convertsFor`**
  (`features/catalog/useSaveResults.ts`) — the resolver and the one routing predicate.
- **`scripts/measure_conversion_expansion.py`**, which drives the plane's own read and write in the
  fleet image. `OUTPUT_EXPANSION` had no runnable derivation before it.

### Deliberate deviations

- **The plane shipped in two pull requests, not three.** The spec split the ASL from the converter;
  the key is returned by the first release's image, so by the time the ASL can name it a deployed
  image already does and every order of that push is safe. Measured: `Validated` reads nine keys and
  release 1's validate-authorize returns nine, with nothing unresolvable in the window.
- **The dialog's count sentence was reworded twice**, each time because a reachable state falsified
  it. "Only the <n> columns shown are saved" reads "Only the 1 columns" at one column and names an
  omission that did not happen on a pure reorder; saying "shown" at all then failed too, because a
  grouped exploration draws a percentage column the file never holds. It reads "The file holds <n>
  result column(s), in the order shown."
- **The reason code, its wording and every shape check landed in the second release**, not the
  first. In the first none of them could fire — the field was not admitted and no state carried it —
  and a refusal that can deny nobody is a fence this plane has already decided against.
- **The feature flag is not consulted.** `resultsConversion` gates the dialog's format options;
  reading it as a second answer to what a save should write would hand a user who hid a column a
  file that still has it.

## What changed from earlier specs?

- **`results_unreadable` stopped asserting its own cause** (SPEC-222's wording). It blamed a
  column's type, which a CSV conversion can never be guilty of, since it types nothing.
- **`useSaveResults` gained a required `columnIndexes` parameter** and `OverwritePrompt` a field;
  both call sites pass one. `SaveResultsDialog` gained the prop and no longer decides *Save here*
  from the format alone (SPEC-223).
- **The generated contract's format union is four**, so the narrowing `catalog.types.ts` documented
  no longer exists.
- **`_CHECKED` in `test_state_reads_match_verb_returns.py`** carried a one-release drop for the two
  results-conversion pairs and is back to `frozenset()`.

## Verification

Formatter, both linters, both suites, mypy, `npm run build`, `check:bundle`, the doc/flag/path
validators, `tofu fmt -check -recursive` and `tofu validate` — green by exit code on each release
before its push. Three fresh-context review frames per release rather than two, because in both
cases the second frame's worst finding would have changed the built result: a negative position
writing the LAST column and reporting success, and the pager button's `onExport` call site sending
no list while 136 tests stayed green.

Deferred to a signed-in session: the end-to-end save itself. `docs/testing/e2e.md` carries the
steps and `docs/testing/owed.md` the row, and the plane's own fixture script gained a section. The
browser steps ran on 2026-09-21 and passed (`docs/testing/sessions.md`, 2026-09-21 evening). The
fixture script's section has not run, and is its own row in `owed.md`.

Two pre-existing defects were measured while building this and are recorded under **Traps** in
`lambdas/info/planes/results-conversion.md`: polars' streaming sink refuses a large CSV holding
quoted newlines, so Parquet and JSON saves of such results have been failing since they shipped;
and a result column whose name holds a double quote fails every conversion, because polars
un-escapes a doubled quote in the data but not in the header. Neither is fixed here.

> **Corrected after close:** the first was worse than recorded here. A save that kept a SUBSET of
> the columns did not refuse such a result: projection pushdown left the multi-line column
> unparsed, and its fragments were written into the kept columns as extra rows with no error.
> A stopgap made the streamed writers parse every column, so that save refused too. SPEC-245
> then moved the fleet to polars 1.44.2, whose streaming reader splits such a result correctly,
> so it converts, whole or in part; the plane page's Traps carry the measurement.
