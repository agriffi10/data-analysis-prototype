# Completed Spec — SPEC-230: Bound Excel by Cells, Because the Converter's Memory Binds per Cell and Not per Byte

Landed as [#718](https://github.com/agriffi10/data-analysis-prototype/pull/718), one PR. Its live
checks ran after deploy and were recorded when the spec closed.

## What was completed?

- **Excel is bounded by cells as well as rows.** `rccommon.config.excel_refusal(rows, columns)`
  decides both Excel refusals: Excel's row ceiling first, then `EXCEL_MAX_CELLS`, which is
  4,100,000. `rc_convert._write_excel` asks it of a row count taken before the workbook is built,
  and asks again of the built frame's height. The production shape that used to run the converter
  for its full ten minutes is now refused in seconds. `EXCEL_MAX_ROWS` moved into `rccommon.config`,
  so it is declared once.
- **The count goes through one projected column with the real CSV reader**, not polars' fast
  count. The fast count miscounts a quoted newline once the reader splits the file across
  threads, which at the function's two threads gave 65,104 rows for 100,000. The first diff review
  found this, and the check of the built frame's height is what guards against it recurring.
- **Both Excel caps are derived from a measured model** of baseline, per-cell, per-row and
  long-text costs (`EXCEL_BASELINE_MB`, `EXCEL_PEAK_BYTES_PER_CELL`, `EXCEL_PEAK_BYTES_PER_ROW`,
  `EXCEL_PEAK_BYTES_PER_LONG_BYTE` and `EXCEL_COVERED_BYTES_PER_CELL`), which replaces
  `EXCEL_MEMORY_EXPANSION`. The budget test recomputes both caps from the model. The byte cap is
  still 64 MiB, but it is now derived rather than kept.
- **The offline guard is a measured corpus.** `MEASURED_EXCEL_SHAPES` in
  `test_plane_results_conversion.py` holds 23 shapes, measured in the fleet image over five runs on
  two architectures. The guard scales each shape to the largest input production's own two checks
  admit. With the cell check removed, it fails on memory and names the production shape.
  `scripts/measure_excel_peak.py` re-measures the corpus when polars or xlsxwriter moves, and it
  joined the mypy list.
- **Two new reasons, each with its own sentence.** `excel_cell_limit` names the rows, columns,
  cells and limit. `excel_exhausted` is the sentence notify-failure uses when an Excel request's
  Lambda error is `Sandbox.Timedout` or `Runtime.OutOfMemory`, in place of "something went wrong".
  The log keeps the raw name.
- **Every integer token in a plane sentence is rendered with thousands separators**, which fixed
  the row-limit refusal's `1049000`.
- **Docs:** Help's two Excel sentences, three `e2e.md` §4.3 rows, `owed.md`, the control-planes
  Fence and a new register entry, the plane page's traps, the `locals.tf` comment and two ASL
  `Comment` fields.

### Deliberate deviations

- **The cap is 4,100,000, not the 4,000,000 in the wording Andrew approved.** The preview's
  derivation mixed decimal MB with MiB. The corrected derivation, taken over five runs, gives
  4,100,000. The decision itself was unchanged, so the number moved without being re-asked, and
  the spec says so.
- **The spec's predicted production reading was wrong.** FR-005 expected 2,150 to 2,250 MB at the
  cap, from the local peak plus the offset a small shape had measured. Production read 2,410,
  which is inside the model's 2,518. The gap between local and production grows with the input, so
  the `e2e.md` row now states that principle instead of a band.
- **No streaming writer.** xlsxwriter refuses `add_table()` in `constant_memory` mode, so that
  route means writing a writer by hand, and it would still need a cell cap, because time is spent
  per cell too. It is the follow-up if 4,100,000 cells proves too few.

## What changed from earlier specs?

- **SPEC-222's Excel size cap** was derived per CSV byte from one wide shape, using
  `EXCEL_MEMORY_EXPANSION` and the "23–32×" figure. It is now one of two caps derived from the
  per-cell model. SPEC-222's register entry and delivery doc both carry superseded markers.
- **SPEC-222's row-limit refusal** moved ahead of the frame being built and now uses the same
  count. Its token is rendered with separators, and its golden test is driven with the integer the
  converter actually sends.
- **SPEC-222's offline timeout guard** passed on the shape that failed in production. It now covers
  the two streamed formats, and Excel is held by the corpus guard.
- **notify-failure** maps two Lambda error names for Excel requests only. Every other failure keeps
  its sentence.

## Verification

Local gates were green on the merged branch: pytest (3,695 passed, 90.5% coverage), vitest, lint,
format, build, mypy and `validate_docs.py`. A mutation battery of 17 plants, run between green
baselines, turned every guard red.

The live checks ran after deploy and are in `sessions.md`, under the second 2026-09-10 sitting:

- The production shape was refused in 3.1 s at 251 MB, with the approved sentence, and the same
  query saved as Parquet.
- The at-cap input converted in 61.4 s at 2,410 MB, which is 108 MiB under the model's figure.
- The row-limit refusal reads "1,100,000".

Still owed is the `Runtime.OutOfMemory` name, which only a deliberately starved converter can
produce.
