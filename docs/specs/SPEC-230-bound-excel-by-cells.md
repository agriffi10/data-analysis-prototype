# Spec: Bound Excel by Cells, Because the Converter's Memory Binds per Cell and Not per Byte

**ID:** SPEC-230
**Status:** Completed
**Last Updated:** 2026-09-10
**Depends On:** SPEC-222

## Overview

Saving a query's results as Excel can promise a file the converter cannot make. On 2026-09-10 a
production query of 1,048,575 rows × 15 one-character text columns — 62,914,590 bytes of CSV —
passed every up-front check: under the 64 MB Excel size cap, and exactly at Excel's row limit. The
converter then ran for its full ten minutes at its full 3,008 MB (`REPORT … Max Memory Used: 3008 MB
Status: timeout`), and the user was told, ten minutes after they submitted, only *"Couldn't save the
query results as Excel: something went wrong."*

**The cap was set in the wrong unit.** The Excel path cannot stream: polars hands xlsxwriter a
Python copy of every cell and xlsxwriter stores every cell again before it writes a byte. So peak
memory is set by the number of **cells**, at no less than about 240 bytes each whatever the cell holds,
while a cell of Athena's CSV can be a single byte (a NULL). The 64 MB cap was derived from a
measured 32.45 bytes of memory per CSV byte on a wider shape, but on narrow data the figure is about
73 (one-character text) or 250 (NULLs). No byte cap can be both safe and useful: one that is safe for
the worst shape sits near 8 MB.

This spec bounds Excel by a **cell count** (rows × columns). The count is derived from memory
measured across 23 data shapes, and the converter refuses above it **before** it builds the
workbook, so the refusal arrives in seconds with a sentence naming the rows, the cells and the
limit. The existing row-limit refusal moves to the same point. A converter that still runs out of
time or memory gets a sentence that says so. The offline guard, which could not see this shape,
is replaced by one derived from the measured shapes that fails on it.

### What was measured, and how

The fleet image was built from `lambdas/Dockerfile` (polars 1.12.0, xlsxwriter 3.2.9), with one
container per run. The real `rc_convert._write_excel` ran over a generated Athena-shaped CSV
(every field quoted, NULL as an unquoted blank) sitting in `/tmp` the way the download lands it.
Peak memory is the container's cgroup v2 `memory.peak`, which is higher than the process's RSS
because it also counts the page cache of the CSV and of xlsxwriter's temporary XML. It is the
conservative one of the two, it is what matches production (below), and it is what the constants
use. Each per-cell figure is the **slope between two sizes** of the same shape, so the fixed cost
of importing the Excel path cancels out. **Every memory figure in this spec is in MiB**, which is
the unit Lambda's "MB" means.

**Five runs**: two exploratory ones (arm64 native, and amd64 under emulation), then the committed
harness `scripts/measure_excel_peak.py` (FR-003) three times — arm64, amd64, and arm64 again once
nothing else was running. The architectures agree within 5% at matched sizes; time under
emulation is not used for anything. **The cgroup slope moves from run to run** — under 10% for most
shapes and 19% for 200-character text, whose large CSV the exploratory runs charged twice by
reading it through a bind mount before copying it into `/tmp` — so the table is the HIGHEST slope
any run measured and the LOWEST native rate, and every constant sits above it.

| Shape | Columns | CSV bytes per cell | Peak bytes per cell | Local cells/s |
|---|---:|---:|---:|---:|
| NULL text | 15 | 1 | 252 | 480k |
| empty text | 15 | 3 | 259 | 475k |
| one-character text (the production shape) | 15 | 4 | 293 | 425k |
| small integer | 15 | 4 | 255 | 484k |
| unique integer | 15 | 9.75 | 319 | 483k |
| double | 15 | 6 | 311 | 479k |
| boolean | 15 | 7 | 263 | 364k |
| date | 15 | 13 | 312 | 412k |
| timestamp | 15 | 26 | 363 | 379k |
| decimal(10,2) | 15 | 9 | 413 | 431k |
| decimal(38,10), unique | 15 | 41 | 488 | 383k |
| unique 20-character text | 15 | 23 | 498 | 302k |
| unique 37-character text | 15 | 40 | 610 | 276k |
| NULL integer / NULL double | 15 | 1 | 239 / 245 | 491k / 525k |
| one-character text | 60 | 4 | 273 | 505k |
| three bigints and a unique label (the 490k production run's own query) | 4 | 8.22 | 411 | 396k |
| unique 13-character text (the live at-cap fixture) | 4 | 16 | 520 | 257k |
| unique 16-character text | 4 | 19 | 539 | 184k |
| timestamp | 4 | 26 | 433 | 346k |
| decimal(10,2) | 4 | 9 | 491 | 353k |
| unique 200-character text | 4 | 203 | 1,553 | 152k |
| one-character text | 1 | 4 | 643 | 296k |

Three production figures anchor the table, all read from the converter's own `REPORT` lines on
2026-09-10:

- **A warm baseline of 137 to 147 MiB**, from the smallest conversions.
- **A 490,000 × 4 result of 16,119,678 bytes: 933 MiB peak in 19,566 ms.** Its query is in
  Athena's history (`SELECT a, b, a*b AS p, 'row-' || cast(a*1000+b AS varchar) AS label FROM
  UNNEST(sequence(1,700)) … CROSS JOIN UNNEST(sequence(1,700)) …`), and the generator reproduces it
  to the byte. Measured locally at 387 to 411 bytes per cell across the runs, its 1,960,000 cells
  account for 724 to 768 MiB, which puts **production's fixed cost at 165 to 209 MiB**, 65 to 84 MiB
  above the same shape's local peak in the same run — about what the Lambda runtime's larger
  baseline accounts for, where RSS would land some 190 MiB short. The largest local fixed cost of any shape,
  plus its own run's offset, is 249.2 MiB. The same write takes 4.91 s locally, so production (whose
  Duration also includes the download and the upload) is **4.0 times** slower.

  > **Corrected when the spec closed:** "production's fixed cost" here assumes production spends
  > per cell what a local run does, and the offset is not only the runtime's baseline. The live
  > conversion at the cap sat 247 to 332 MiB over its local peak (FR-005's note), so two
  > production readings cannot separate a fixed cost from a per-cell one. What that means for a
  > re-derivation is under Traps in `lambdas/info/planes/results-conversion.md`.
- **The failing 1,048,575 × 15 result**, rebuilt byte-for-byte (the generator reproduces
  62,914,590 bytes exactly): **3,851 MiB peak RSS and 4,496 MiB cgroup** on amd64, against a
  3,008 MiB function. Memory binds, not time: the same write completes in 61 s under emulation when
  memory is unbounded.

### The decisions, made while authoring

- **Cells, not bytes, and not a streaming writer** — Andrew's call, 2026-09-10, put to him with the
  table above. Two alternatives were rejected:
  - **A lower byte cap** would be about 8 MB for every shape. The NULL row is why: 1 byte of CSV,
    252 bytes of memory.
  - **xlsxwriter's `constant_memory` mode** is not a flag on today's writer. xlsxwriter refuses
    `add_table()` in that mode, which its 3.2.9 source (`"add_table() isn't supported in
    'constant_memory' mode"`) and its documentation both say. polars' `write_excel` always builds a
    table, from `df.rows()`. So the mode means a hand-written writer: the file loses its Excel table
    and polars' per-type formats have to be re-implemented. It would *still* need a cell cap,
    because time is per cell as well: xlsxwriter's documentation puts that mode's speed at
    "approximately the same as normal mode". It is the remedy if 4,100,000 cells proves too few,
    and it is a spec of its own.
- **The rows are counted in the converter, not in describe-results.** describe-results could only
  learn the row count from Athena's `GetQueryRuntimeStatistics`. The API reference says that
  statistic "may not be available immediately after a query completes or, in some cases, may not
  be returned", and that it is not included at all when a query has Lake Formation row-level
  filters. A cap needs an answer every time, and the only fallback for a missing count is the byte
  cap this spec exists to replace. So the converter counts the downloaded file instead, and the
  cost is that the refusal arrives after the download, a few seconds later, rather than before it.
  **It counts through ONE column with the real CSV reader, not with `pl.len()`.** That is polars'
  fast count, which projects nothing and tracks quotes chunk by chunk: once the reader splits the
  file across threads it miscounts a quoted newline — 65,104 rows for 100,000 at the two threads the
  function has, measured in the fleet image — and the first diff review showed where that leads: a
  1.1-million-row result admitted as 717,008, its rows dropped by xlsxwriter past Excel's ceiling,
  and an empty workbook reported as saved. The projected count was exact on every file that fooled
  the fast one, and costs 52 to 63 ms on the full-size inputs, with no rise in peak RSS. **The
  frame's height is then checked again once it is built**, by the same helper, so a count that
  ever disagrees with the frame refuses instead of writing a workbook short.
- **The wording** is Andrew's call (2026-09-10): the refusal names the rows, the columns, the cells
  and the limit, mirroring the row-limit sentence. The out-of-time-or-memory case gets its own
  sentence rather than "something went wrong".
- **The cap is 4,100,000, not the 4,000,000 in the preview Andrew approved.** The preview's number
  came from an anchor that mixed decimal MB with MiB and a per-row figure below its own
  measurement; the spec review caught both, and the corrected derivation gave 4,200,000. The
  committed harness then re-measured the whole corpus three more times, the corpus became the
  maximum over all five runs, and two bounds rose with it — the baseline to 249.2 MiB and the
  per-row figure to 392 — which derives 4,100,000. Taking a maximum over more runs can only lower
  the number, which is the safe direction. The decision is unchanged, so the number moved rather
  than being re-asked, and every measured shape still fits with the 15% reserve intact.
- **The byte cap stays 64 MiB, but is re-derived rather than kept.** At the corner, where every
  admitted cell is present, it admits no byte the per-cell figure does not already cover (FR-002).
  A result of fewer, longer cells does pay the long-byte term, but less in total: per-cell (480)
  exceeds per-long-byte × covered bytes (7 × 23 = 161), so trading cells for bytes only lowers the
  peak.

## Scope

### In Scope

- A cell cap on Excel conversions, derived from the measured model, refused before the workbook is
  built; and Excel's row limit refused at the same point, from the same count.
- The model's constants in `rccommon.config`, replacing `EXCEL_MEMORY_EXPANSION`, with both Excel
  caps recomputed from them by a test. The Excel byte cap is re-derived rather than retained.
- The offline guard, replaced by a fixture corpus of the measured shapes. It fails on the
  production shape under today's caps, and it checks time per cell as well as memory.
- A specific sentence when an Excel conversion's verb runs out of time or memory, instead of the
  fallback.
- Integer wording tokens rendered with thousands separators, in every plane sentence that carries
  one.
- The committed measurement harness, the live checks in `e2e.md`, and the help, fence and
  plane-page text that states the Excel limit.

### Out of Scope

- **A streaming Excel writer.** It is rejected above, and it is the follow-up if the cap proves too
  small.
- **Raising the converter's memory.** 3,008 MB is this account's `CreateFunction` ceiling, not
  Lambda's (`CONVERTER_MEMORY_MB`'s docstring), and lifting it is a quota request outside this
  repo. A raised quota would move every number here, which is why they are derived rather than
  typed.
- **Any change to Parquet or JSON.** They stream, their memory is flat, and their caps and wording
  are untouched. Their time check moves onto the measured production ratio (FR-003) and still
  passes with wide margin.
- **A browser pre-check.** The browser does not know the row count, and the sentence reaches the
  user through the notification as every other refusal does.
- **A per-type model.** A cap that knew each column's type could admit more of the cheap shapes,
  where one-character text fits about 8M cells. It would also be a model with twenty coefficients
  instead of four, and every one of them could be wrong. One conservative envelope is the trade.
- **The owed row "The converter's real throughput on amd64".** A peer session is discharging it
  and recording the measurements in `owed.md` and `sessions.md`. This spec consumes those numbers
  and touches the row only with a one-clause supersede marker on the check it retires. Its recipe block in `results-conversion-plane.sh` is edited only
  where it states the model this spec retires (FR-005), and a conflict with the peer's edit is
  resolved at rebase.

---

## Functional Requirements

### FR-001: Excel refuses too many cells, and too many rows, before the workbook is built

#### Description:

The converter counts the downloaded result's data rows with one streamed pass before anything is
materialised. An Excel conversion is refused when that count is over Excel's row limit, or when
rows × columns is over the cell cap, and nothing is written. Both refusals are return values, as
the row limit's is today, and one predicate in `rccommon.config` decides both, so the guard in FR-003
exercises exactly what production runs.

#### Acceptance Criteria:

- [ ] `rccommon.config.excel_refusal(rows, columns)` returns `excel_row_limit` when rows exceed
  `EXCEL_MAX_ROWS`, `excel_cell_limit` when rows × columns exceed `EXCEL_MAX_CELLS`, and `None`
  otherwise. The row check comes first, because it is the more specific sentence. Exactly
  `EXCEL_MAX_CELLS` cells, and exactly `EXCEL_MAX_ROWS` rows, are admitted.
- [ ] `EXCEL_MAX_ROWS` is declared once, in `rccommon.config`. `rc_convert` imports it rather than
  declaring a second copy.
- [ ] An `.xlsx` request whose result is over either limit returns `{"outcome": "refused", "reason":
  …}`, writes nothing, and never materialises the typed frame. A test that records the width of
  every frame `LazyFrame.collect` returns sees only the count's single column.
- [ ] A cell refusal carries the tokens `rows`, `columns` and `count` as integers. A row refusal
  carries `count`, as today.
- [ ] Each refusal is constructed with its reason written out, as
  `_Refusal(reasons.EXCEL_ROW_LIMIT, …)` and `_Refusal(reasons.EXCEL_CELL_LIMIT, …)`, one branch
  each, in one helper (`_refuse_what_excel_cannot_hold`) that `_write_excel` asks of the count and
  again of the built frame's height. That keeps both codes visible to the plane's refusal-vocabulary sweep
  (`test_every_code_any_verb_on_this_plane_can_raise_is_registered_and_worded`), which reads only a
  literal first argument. The sweep's expected set, and `NAMES_THE_FILE`, gain `excel_cell_limit`.
- [ ] A plane test asserts that every `reasons.X` returned by `excel_refusal` (read from its AST) is
  one the convert verb refuses with, so a code the predicate learns without a converter branch
  cannot fall through to a write.
- [ ] The count runs for Excel only. The existing test that makes `collect` raise still passes for
  Parquet and JSON, so the streamed formats gained no materialisation.
- [ ] The count is the CSV's own data-row count: equal to the frame's height on a file with a
  quoted embedded newline — including one large enough that the reader splits it across threads,
  where polars' fast count is wrong — and zero on a header-only file. The multi-chunk case is
  refused from the COUNT, which the width recorder shows (only the one-column count collected).
- [ ] A count that admitted a result the built frame then shows to be over a limit is refused
  before the write, asked of the frame's height, and nothing is written.
- [ ] The notification for a cell refusal reads, for the failing query and a file called
  `big.xlsx`: *Couldn't save the query results as Excel: the results have 1,048,575 rows and 15
  columns (15,728,625 cells), which is more than the 4,100,000 cells an Excel file can be made from
  here, so "big.xlsx" was not written. Please save them as Parquet instead, or narrow the query.*
  `{maxCells}` is filled from `EXCEL_MAX_CELLS` by `failure_message`, never by the raise site.
- [ ] Every integer token is rendered with thousands separators, so the row-limit sentence
  production sends now reads "1,400,000 rows". Its cross-language golden test is driven with the
  integer the converter really sends, not the pre-formatted string it passes today.

### FR-002: The cell cap and the Excel byte cap are derived from one measured model

#### Description:

Four measured constants model the Excel path's peak memory, and both Excel caps are derived from
them and the function's memory budget. The model is an **upper envelope**: every term is set at or
above the worst measurement, the terms are added together, and the budget keeps its 15% reserve.

```text
peak_MiB(rows, columns, csv_bytes) =                 (bytes ÷ 1024² wherever a term is in bytes)
    EXCEL_BASELINE_MB
  + rows × columns × EXCEL_PEAK_BYTES_PER_CELL                             (per cell)
  + rows × EXCEL_PEAK_BYTES_PER_ROW                                        (per row)
  + max(0, csv_bytes − cells × EXCEL_COVERED_BYTES_PER_CELL) × EXCEL_PEAK_BYTES_PER_LONG_BYTE
```

The per-cell figure covers a cell of up to `EXCEL_COVERED_BYTES_PER_CELL` CSV bytes, the width at
which the shape that binds it was measured. Only bytes beyond that pay the long-string term. The
baseline, per-cell and per-row constants are each their measured bound **rounded up to the next
10** (MiB, or bytes); the long-byte constant is rounded up to the next whole byte, and the covered
width is the measured width itself. `_MB` in a name means MiB, as it does in
`CONVERTER_MEMORY_MB`.

#### Acceptance Criteria:

- [ ] `rccommon.config` declares these constants, each docstring entry naming the shape that sets
  it:
  - `EXCEL_BASELINE_MB = 250`. The production fixed cost is 165 to 209 MiB across the runs, and
    the largest local fixed cost of any shape, plus its own run's local-to-production offset, is
    249.2 (unique 20-character text, in the second arm64 harness run).

    > **Corrected when the spec closed:** "the production fixed cost" is an inference, not a
    > measurement. See the note under the 490,000 × 4 run above.
  - `EXCEL_PEAK_BYTES_PER_CELL = 480`. The envelope needs at least 471: unique 20-character text at
    15 columns measures 498, less its 27-byte row share.
  - `EXCEL_PEAK_BYTES_PER_ROW = 400`. One against fifteen columns of one-character text, in the
    same run, gives 362 to 392 across the runs.
  - `EXCEL_COVERED_BYTES_PER_CELL = 23`, the CSV width of the shape that binds the per-cell figure.
  - `EXCEL_PEAK_BYTES_PER_LONG_BYTE = 7`. The corpus needs at most 6.1.

  `EXCEL_MEMORY_EXPANSION` is removed, along with every sentence that quotes "23–32x".
- [ ] `EXCEL_MAX_CELLS` = (budget − baseline − per-row × `EXCEL_MAX_ROWS`) ÷ per-cell, all in MiB,
  floored to 100,000. That is (2,556.8 − 250 − 400.0) MiB ÷ 480 B = 4,165,468, which floors to
  **4,100,000** on today's constants. A test recomputes it independently, so a hand edit to either
  side is red.
- [ ] `RESULTS_MAX_BYTES["xlsx"]` = the smaller of the disk bound and `EXCEL_COVERED_BYTES_PER_CELL`
  × `EXCEL_MAX_CELLS`, floored to 64 MiB — **64 MiB**, unchanged in value. The budget test
  recomputes it the same way. Its old memory term is gone.
- [ ] The budget test asserts that per-cell exceeds per-long-byte × covered-bytes, and says why:
  that inequality is what makes the model's maximum over everything the caps admit sit at the
  corner (every admitted cell, every admitted row). Swapping the two figures makes it red.
- [ ] `MEASURED_ON` names the image commit, the two library versions, the two architectures, the
  harness path and the production anchors.

### FR-003: The offline guard is a corpus of measured shapes, and it fails on the production shape

#### Description:

The guard stops asking whether a throughput figure in bytes per second clears the timeout, a
question the failing shape passed. It asks two things about every measured shape: whether the
model bounds it, and whether it fits the memory budget and the time budget at the largest size the
caps admit. The failing query is one of the corpus's named rows. The harness that produced the
corpus is committed.

#### Acceptance Criteria:

- [ ] The plane suite carries the table above as a fixture corpus: each shape's columns, CSV bytes
  per cell, peak bytes per cell and local cells per second. One test asserts that the FR-002 model
  is at or above every measured peak, at the shape's own width and bytes.
- [ ] One test scales every shape to the largest row count the caps admit, using
  `excel_refusal` and `max_result_bytes("xlsx")` themselves. It asserts that the row count is
  admitted and that one more row is not. It then asserts that `EXCEL_BASELINE_MB` plus the shape's
  MEASURED per-cell cost times its cells fits `CONVERTER_MEMORY_MB × (1 − MEMORY_RESERVE)`. It
  also asserts that the shape's time fits the timeout less its reserve, at its local rate divided by
  the measured local-to-production ratio (4.0 on the 490k run's exact shape, rounded up to 5). It
  collects every failing shape before it asserts, so its message names all of them.
- [ ] A test named for the production query asserts that `excel_refusal(1_048_575, 15)` refuses it
  as `excel_cell_limit`.
- [ ] **Mutation-proven before the push**, recorded on the PR, one plant per check:
  - dropping the cell clause from `excel_refusal` reddens both the production-query test and the
    scaled-corpus test, and the corpus failure lists the 15-column one-character shape among
    those that fail;
  - raising `EXCEL_MAX_CELLS` by one granule reddens the derivation test;
  - lowering `EXCEL_PEAK_BYTES_PER_CELL` to 470, below the 471 the envelope needs, reddens the
    envelope test;
  - removing the long-byte term reddens the envelope test on the 200-character shape;
  - adding a third return code to `excel_refusal` with no converter branch reddens the subset test
    in FR-001;
  - counting with `pl.len()` reddens the multi-chunk count test, and removing the check after the
    frame is built reddens the test that a disagreeing count is refused before the write.
- [ ] The byte-per-second check for Excel is gone. The Parquet and JSON time check keeps its
  measured MB/s and uses the same local-to-production ratio instead of the unmeasured derate of 4.
- [ ] `scripts/measure_excel_peak.py` reproduces a table row: given a built fleet image, it
  generates a shape at two sizes, runs `_write_excel` in one container per run, and prints the
  per-cell slope — at or below the corpus figure, since most maxima come from the exploratory runs,
  which read high. Its docstring says how to build the image for either architecture, and that
  memory transfers across them while time under emulation does not.

### FR-004: A converter that runs out of time or memory says so

#### Description:

When an Excel request's Lambda verb ends in `Sandbox.Timedout` or `Runtime.OutOfMemory`,
notify-failure words it as the plane's `excel_exhausted` rather than falling through to "something
went wrong". The name of the error that reached it is still what it logs.

#### Acceptance Criteria:

- [ ] On an `.xlsx` request, an error named `Sandbox.Timedout` (or `Runtime.OutOfMemory`) produces:
  *Couldn't save the query results as Excel: the conversion ran out of time or memory before it
  finished, so nothing was saved. Please save them as Parquet instead, or narrow the query.* The
  structured log's `reason` is still the Lambda error name.
- [ ] Any other error name on an `.xlsx` request keeps the fallback, so the mapping widens nothing
  but these two names.
- [ ] On a Parquet or JSON request the same error keeps today's fallback sentence. Those formats
  stream, so running out is a genuine fault rather than a size the user can change, and advice to
  switch to Parquet would be wrong on a Parquet request.
- [ ] `excel_exhausted` is a registered reason with a worded sentence, and the plane's
  registered-and-worded test covers it.
- [ ] **The limits of the evidence are stated, not hidden.** `Sandbox.Timedout` is the name
  production delivered on 2026-09-10. `Runtime.OutOfMemory` is the name Lambda reports for an
  out-of-memory kill on managed runtimes, but it has not been observed in this account and cannot
  be staged once the cap holds; if it is wrong, that case keeps today's sentence. Any verb of an
  Excel request that times out reads this sentence, not only the converter — describe-results
  takes one `HeadObject` and one `GetQueryResults`, so a timeout there is an outage and the
  misdirection is accepted. The spec's `owed.md` row carries both.

### FR-005: The limit is stated where users and operators read it, and checked live

#### Description:

Everywhere that says what Excel holds says it in the unit that binds. The failing query becomes a
live check, and so does the largest input the caps admit, whose `REPORT` line is the model's only
production validation.

#### Acceptance Criteria:

- [ ] Help's two Excel sentences (`helpContent.ts`, the Query and Data Explorer entries) keep
  "about a million rows" and add that a wide result reaches its limit sooner. No number is written
  in the portal, because the number lives in the plane and the notification names it.
- [ ] `e2e.md` §4.3 gains two rows, each with its fixture query and its expected text. Both scan
  0 bytes.
  - **The failing query**, saved as Excel, is refused within a minute with the FR-001 sentence,
    and the same query saved as Parquet succeeds.
  - **Exactly at the cell cap**, saved as Excel, converts: 1,025,000 rows × 4 unique 13-character
    columns, from `lpad(cast(x * 1025 + y AS varchar), 12, '0') || 'a'` (then `'b'`, `'c'`, `'d'`)
    over `sequence(1, 1000)` crossed with `sequence(1, 1025)`. It is 4,100,000 cells and 65,600,020
    bytes. Its `REPORT` line's Max Memory Used must be at most the model's 2,518 MiB for that
    input; locally it peaks at 2,078 to 2,163 MiB across runs, so about 2,150 to 2,250 is expected in
    production. Its Duration must be under 120 s. Both figures go into `sessions.md`. Anything
    over the model is a finding against the constants, not a pass.

    > **Run after deploy: 2,410 MiB in 61.4 s.** It is inside the model and the time bound, and
    > **above the expected band**, which was wrong. Production's gap over the local peak was 247 to
    > 332 MiB here against 65 to 84 at the 490,000 × 4 shape, so the gap is not a fixed offset, and
    > an offset measured on one input does not predict another. The model's own figure is the only
    > memory prediction that held, 108 MiB above the reading, because this shape sets none of the
    > model's terms. The run is in `sessions.md`; the model's figure replaced the band in `e2e.md`,
    > and what this means for a re-derivation is under Traps in
    > `lambdas/info/planes/results-conversion.md`.
- [ ] The existing §4.3 row-limit row's note that "a wide million-row result comes back
  `results_too_large`" is corrected: under 64 MiB it now comes back as `excel_row_limit` (over
  1,048,575 rows) or `excel_cell_limit` (under that). Over 64 MiB it is still `results_too_large`.
- [ ] `control-planes.md`'s Fence clause on Excel is rewritten in place so that the memory is
  stated per CELL, and the SPEC-222 register entry's "23–32x the input CSV" is marked superseded.
  A new register entry carries this spec's reasoning. `results-conversion.md`'s trap, the
  module's `locals.tf` comment, the throughput block of
  `docs/testing/fixtures/results-conversion-plane.sh` ("23-32x", "derate by 4") and the state
  machine's comments on `ConvertRefusedSeed` and `ConversionOutcome` stop describing the retired
  model or the one-refusal token set. The ASL edits are comment-only.
- [ ] `owed.md` gains a row for the `Runtime.OutOfMemory` name (FR-004). Its row for staging the
  `excel_row_limit` refusal loses the claim that a wide result comes back `results_too_large`,
  because the row check now runs first, and it names a zero-scan fixture in place of the table it
  says must be built: `SELECT 'a' AS c FROM UNNEST(sequence(1, 1100)) CROSS JOIN UNNEST(sequence(1,
  1000))`, which is 1,100,000 rows and about 4.4 MB. The "real throughput" row is the peer
  session's, as Out of Scope says, and is left alone.

---

## Data Model

```python
# lambdas/results-conversion-common/rccommon/config.py
EXCEL_MAX_ROWS = 1_048_575                 # moved here from rc_convert; one declaration
EXCEL_BASELINE_MB = 250                    # MiB, as every _MB in this module
EXCEL_PEAK_BYTES_PER_CELL = 480
EXCEL_PEAK_BYTES_PER_ROW = 400
EXCEL_COVERED_BYTES_PER_CELL = 23
EXCEL_PEAK_BYTES_PER_LONG_BYTE = 7
EXCEL_MAX_CELLS = 4_100_000                # derived; the budget test recomputes it
RESULTS_MAX_BYTES = {..., "xlsx": 64 * 1024**2}   # value unchanged, derivation replaced

def excel_refusal(rows: int, columns: int) -> str | None: ...
#   -> reasons.EXCEL_ROW_LIMIT | reasons.EXCEL_CELL_LIMIT | None

# lambdas/results-conversion-common/rccommon/reasons.py
EXCEL_CELL_LIMIT = "excel_cell_limit"
EXCEL_EXHAUSTED = "excel_exhausted"

# lambdas/results-conversion-convert/rc_convert.py — the refusal's tokens on the state
{"rows": int, "columns": int, "count": int}          # excel_cell_limit
{"count": int}                                        # excel_row_limit, unchanged

# lambdas/results-conversion-notify-failure/rc_notify_failure.py
_EXHAUSTION = frozenset({"Sandbox.Timedout", "Runtime.OutOfMemory"})
```

No state-machine behaviour changes: the refusal travels the existing `ConvertRefusedSeed` →
`RecordFailure` path, whose `tokens.$` already carries an object of integers, and the only ASL edit
is to two `Comment` fields. They live inside the state machine's definition, so the apply shows an
in-place update with no behaviour change. No IAM change, and no new resource.

## File & Folder Structure

```
lambdas/results-conversion-common/rccommon/{config,reasons,messages}.py
lambdas/results-conversion-common/test_plane_results_conversion.py
lambdas/results-conversion-convert/{rc_convert,test_rc_convert}.py
lambdas/results-conversion-notify-failure/{rc_notify_failure,test_rc_notify_failure}.py
infra/modules/results-conversion/{locals.tf,state-machine.asl.json.tftpl}   (comments only)
apps/portal/src/features/help/helpContent.ts
scripts/measure_excel_peak.py, pyproject.toml (mypy files)
docs/testing/{e2e,owed}.md, docs/testing/fixtures/results-conversion-plane.sh
docs/decisions/control-planes.md, lambdas/info/planes/results-conversion.md
```

## Implementation Phases

### Phase 1: The model and the derivation

- Constants, `EXCEL_MAX_ROWS` moved, `excel_refusal`, the two reasons and their sentences, and
  integer token rendering. Budget test rewritten around the model.

### Phase 2: The converter refuses first

- The projected count and both refusals ahead of `collect` in `_write_excel`, and the same
  refusals asked again of the built frame's height. Convert tests, and the row-limit golden driven
  with an integer.

### Phase 3: The guard, its corpus and its harness

- The corpus, the envelope test, the scaled-corpus memory and time test, the production-query test,
  and `scripts/measure_excel_peak.py`. Every mutation in FR-003 planted and reverted.

### Phase 4: The exhaustion sentence

- The mapping in notify-failure and its tests.

### Phase 5: Words, and the live check

- Help, `e2e.md`, `owed.md`, the fence and register, the plane page and the `locals.tf` comment.
  The two live rows are run after deploy and recorded before the spec closes.
