# Completed Spec — SPEC-245: The Fleet Moves to polars 1.44, So a Result Holding Line Breaks Converts Instead of Refusing

## What was completed?

- **A query result holding multi-line values now saves as Parquet, JSON or a column-subset CSV.**
  polars 1.12's streaming CSV reader mis-split such results above about 2 MB: a whole save was
  refused, and a column-subset save wrote fragments as extra rows until #856 turned that into a
  refusal too. The fleet now runs `polars==1.44.2`, whose reader splits them correctly. The
  `results_unreadable` sentence is back to SPEC-239's, without the line-break repair.
- **The Parquet schema probe reads the footer itself** (#863, landed and deployed first, on 1.12).
  `cpcommon.bounded_read.read_parquet_footer` fetches the trailer with a suffix GET, then exactly
  the footer, and hands polars an in-memory file of the footer alone. `cpcommon.parquet_trailer`
  holds the trailer checks once, shared with `rccommon.parquet_footer`. New refusals: a footer over
  the 32 MiB probe bound, a zero-length footer, a response that is not the range asked for, and an
  empty object. `S3RangeReader` is deleted.
- **The pin move (#865).** `SINK_OPTIONS` is retired. The refusal's detail stops quoting a
  chunk-relative byte offset. Both schema probes catch polars' `PanicException` beside
  `Exception`. A JSON integer too large for `bigint`, which 1.44 infers as `Int128`, refuses by name.
- **The Excel model re-measured in the 1.44.2 image**: three clean native arm64 runs, a fourth
  kept for its memory only, one amd64 run, and the expansion run, joined with 1.12's evidence so no cap could rise. `EXCEL_BASELINE_MB` 250 → 350,
  `EXCEL_PEAK_BYTES_PER_ROW` 400 → 410, **`EXCEL_MAX_CELLS` 4,100,000 → 3,900,000**; every byte cap
  and every expansion figure held.

### Deliberate deviations

- **The spec was revised twice before the build**, both times from its reviews:
  - the zero-length refusal, the pinned request sequence and the S3-faithful test fake;
  - FR-004's derivation order, with an escalation clause for a cap floored to zero;
  - the claims FR-005's grep could not find because they name no version;
  - FR-003's fixture at 200,000 rows rather than 60,000.
- **One measurement run was kept for memory and dropped for rates.** It shared the machine with a
  fuzzing job. CPU contention lowers a rate and cannot inflate a cgroup peak. Its per-row figure is
  what raised that term to 410. Both diff reviews caught the first draft discarding the run whole.
- **The PanicException catch was not in the spec.** A review fuzzed 1,610 damaged footers, and some
  escaped both verbs on 1.44 as a fault. It landed with the pin, where its fixture discriminates.

## What changed from earlier specs?

- SPEC-230's Excel cell cap is 3,900,000 and its baseline 350 MiB. The at-cap live-check row in
  `e2e.md` §4.3 is regenerated at 975,000 rows. `ARCS.md` carries the marker.
- SPEC-239's two after-close markers now say the streaming mis-split is history. #856's stopgap is
  retired, and so is its line-break sentence.
- The table-builder infer-schema and data-quality inspect-source Parquet probes read through
  `read_parquet_footer`, not a file object over S3.

## Verification

- Every local gate exited 0: under 1.12 for #863, and under 1.44.2 for #865. The footer test passes
  on both versions. The multi-line conversion test fails all six cases on 1.12.
- Mutation checks turned each new guard red, apart from one plant that survives by design: turning
  pushdown off on 1.44.2 changes no output, so no test can see it. Each diff had two fresh-context
  reviews in different frames before it was pushed.
- Live, 2026-09-21, recorded in `docs/testing/sessions.md`:
  - FR-001's table build and data-quality check over a Parquet folder, on #863;
  - the positive control, refused on 1.12;
  - after #865's deploy: 200,000-row Parquet and JSON saves and the column-hidden view save;
  - the typed Parquet round-trip, with both `EXCEPT`s empty, and a data-quality check;
  - the at-cap Excel conversion at 58.7 s and 2,115 MB against the model's 2,517.

  Nothing is owed.
