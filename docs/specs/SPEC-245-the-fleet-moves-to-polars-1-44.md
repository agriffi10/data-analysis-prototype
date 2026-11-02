---
type: Spec
id: SPEC-245
title: "The Fleet Moves to polars 1.44, So a Result Holding Line Breaks Converts Instead of Refusing"
description: "Moves the Lambda fleet from polars 1.12 to 1.44 so query results containing line breaks convert to Parquet, JSON or column-subset CSV instead of being refused, re-measuring the probe and Excel caps."
spec_status: Completed
depends_on: []
---

## Overview

Saving query results as Parquet, JSON or a column-subset CSV refuses any result larger than about
2 MB whose values run over more than one line — a pretty-printed JSON document, an address, a
comment field. The cause is polars 1.12.0, the version the whole Lambda fleet pins: its streaming
CSV reader mis-splits such a file. Until #856 a save that kept only some of the columns did worse
than refuse, and wrote the fragments into the file as extra rows. #856 turned that into a refusal
and told the user to replace the line breaks in their query, which is a workaround, not a fix.

polars 1.44.2, the current release, reads the same files correctly, whole or projected. This spec
moves the fleet to it. The move is not a one-line pin change, because three planes read polars
and several of this repo's guards and constants were measured against 1.12: the Parquet schema
probe that table-builder and data-quality depend on silently stops being bounded on 1.44, and the
Excel converter's memory caps were derived on 1.12. So the spec replaces the probe first, on the
version it runs today, then moves the pin with everything measured on 1.12 re-measured or retired.

### What was measured, and how

Every figure below was measured on 2026-09-21 on this Mac, in venvs built from every requirements
file `lambdas/Dockerfile` installs, on Python 3.12.12 (the image's) and polars 1.12.0 against
1.44.2, with `PYTHONDONTWRITEBYTECODE=1`. The probe scripts are in the session that wrote this
spec and are not evidence a reader can re-run; the acceptance criteria below are.

- **The whole Lambda suite on each version.** 1.12.0: `1 failed, 5102 passed` — the one failure is
  `test_local_install_guard.py`, which needs `node_modules` and is not about polars. 1.44.2:
  `3 failed, 5100 passed`. The two new failures are the probe regression and one test that pins
  1.12 on purpose, both below. Those two runs predate #856. At 57498b76, which carries it,
  1.44.2 gives `26 failed, 5093 passed, 6 skipped` with `node_modules` absent: #856's keyword
  refuses every streamed save, as the bullet on `projection_pushdown` below describes.
- **The Parquet probe stops being bounded.** `cpcommon.bounded_read.S3RangeReader` exists so that
  `pl.read_parquet_schema` fetches only an object's footer. On 1.12 a counting file object saw
  `reads=[8192, 16384, 32768, 8192]`; on 1.44.2 `read_parquet_schema` is
  `scan_parquet(source).collect_schema()` and read the whole 2,933,021-byte fixture in one call.
  `test_range_reader_serves_a_real_parquet_footer_to_polars` fails on it. Its callers,
  `infer_schema.py` and `dq_inspect_source.py`, run at 1,024 MB, so a large Parquet source would
  be pulled whole into memory. `pl.read_parquet_metadata` on 1.44.2 also reads the whole object.
- **A footer-only buffer gives polars the same schema, on both versions.** The last 8 bytes of a
  Parquet file are the footer's length and `PAR1`. A buffer of `PAR1`, the footer, its length and
  `PAR1` — the footer alone, framed as a file — handed to `pl.read_parquet_schema` returned a
  schema equal to the full file's on 1.12.0 and on 1.44.2, over Int64, String, Datetime,
  Decimal(10, 2), List(Int64) and Struct columns in 20,000-row row groups.
- **The streaming reader is fixed.** The shape #856 measured (every tenth value a 200-character
  multi-line document) sinks correctly on 1.44.2 at 60,000, 200,000 and 1,000,000 rows, for every
  column and for a one-column projection, where 1.12 raised or wrote 60,001 rows.
- **The keyword #856 relies on is gone.** 1.44.2's three `sink_*` methods take no
  `projection_pushdown`; it moved into `optimizations=pl.QueryOptFlags(...)`. #856's branch on
  1.44.2 refused every streamed save (`23 failed`), because the writers turn the `TypeError` into
  `results_unreadable`; `test_every_streamed_sink_takes_the_options_it_is_given` exists for that.
- **What changes in the converter's output** (the converter's own `_schemas`, `_frame` and
  `_write` over one input, on each version). CSV: byte-identical. Excel: identical apart from the
  `docProps/core.xml` timestamps. JSON: a large float's exponent gains a sign, `1e20` becoming
  `1e+20`. Parquet: different bytes (a `dictionary_page_offset`, boolean encodings, NaN
  statistics, the embedded `ARROW:schema`), and polars reads both back as equal frames. A decimal
  with more digits than its scale rounds instead of truncating, `'1.255'` in a `decimal(10,2)`
  giving `1.26` rather than `1.25`.
- **polars' refusal text changes.** The byte offset in a parse failure is now relative to a chunk:
  an error at byte 3,377,792 reports `35464`. The converter lifts that number into its operator
  detail as "at byte N", which would become wrong.
- **JSON inference changes.** A JSON integer above int64's maximum is inferred as `Int128`, which
  `cpcommon.type_mapping.map_dtype` refuses; on 1.12 it was inferred `Int64`, which cannot hold it.
- **Claims anchored to 1.12, re-tested.** The fast count `select(pl.len())` no longer miscounts
  quoted newlines — 100,000 and 5,000 exact at 2 and 10 threads, where 1.12 gave 3,256 for 5,000.
  `scan_csv` given `schema_overrides` whose keys do not match the header no longer renames columns;
  it ignores the keys, still silently. A doubled quote in a CSV header is still not un-escaped.
  `write_excel` still builds its own workbook with `strings_to_formulas: False`. NDJSON datetimes
  still render with a space, so the converter's explicit cast stays. Parquet's default compression
  is still zstd.
- **Output expansion**, by `scripts/measure_conversion_expansion.py`, worst case, 1.12 → 1.44.2:
  CSV 1.000 → 1.000, JSON 1.403 → 1.403, Parquet 0.045 → 0.040 — all inside `OUTPUT_EXPANSION`.
  Measured on macOS, not in the image.
- **Size.** The Linux x86_64 wheel is 34.1 MB for 1.12.0; 1.44.2 is 0.9 MB of `polars` plus
  49.9 MB of `polars-runtime-32`, which `polars==1.44.2` pins exactly. Installed, 90 MB against
  161 MB on macOS.
- **Not measured:** the Excel memory model. It needs the fleet image (`docker info` exits 0 here),
  and it is FR-004's work rather than an input to this spec.

### The decisions, made while authoring

- **The target is 1.44.2 exactly**, the current release and the one measured. Both pins move
  together, as the requirements files already require.
- **The Parquet probe is rebuilt on this side of polars, and it lands first.** The footer-only
  buffer works on 1.12 and 1.44, so it can ship and deploy while 1.12 is still pinned, and the
  version move then changes nothing about how a probe reads. `S3RangeReader` is deleted with its
  last caller. No polars 1.44 API reads only a footer from a Python file object, so waiting for
  one is not an option. The new reader is `bounded_read.read_parquet_footer`, not
  `parquet_footer`, because `rccommon.parquet_footer` is already a module of that name.
- **The trailer is checked in one place.** `rccommon.parquet_footer._metadata` already checks that
  a file is at least 12 bytes, ends in `PAR1` and declares a footer it holds. A second copy of
  those checks in `bounded_read` would drift from the first, and the first already has the check
  the new reader would otherwise miss (a declared length longer than the object). So the checks
  move to `cpcommon.parquet_trailer.footer_span`, and both readers call it. `_metadata`'s fourth
  check, the LEADING `PAR1`, is dropped rather than moved: a file that ends in `PAR1` and declares
  a footer it holds is decoded next, and a file that is not Parquet fails there. Keeping it would
  cost the S3 reader a third GET for a check the decode already makes.
- **A footer over 32 MiB is a new refusal.** `S3RangeReader` let polars read a footer of any
  length into a 1,024 MB function. `read_parquet_footer` refuses one over
  `DEFAULT_PROBE_MAX_BYTES`, the bound every other probe in `bounded_read` already has, and
  each verb's existing unreadable-source code carries the refusal.
- **`SINK_OPTIONS` is retired, not translated.** Re-expressing it as
  `optimizations=pl.QueryOptFlags(projection_pushdown=False)` would keep parsing dropped columns
  to guard against a mis-split 1.44.2 does not make. The guard that remains is a test that converts
  the mis-splitting shapes and checks every row, and it goes red on 1.12.
- **`results_unreadable`'s sentence loses the line-break clause** and returns to SPEC-239's
  wording, which offers the cast as a conditional. A user refused on 1.44 has a value that does not
  parse as its column's type; telling them to strip line breaks would send them after a cause that
  no longer exists.
- **The refusal's operator detail stops quoting a byte offset.** On 1.44 it is an offset into a
  chunk, and an operator reading "at byte 35464" would look in the wrong place. The column stays.
- **The output changes above are accepted, not worked around.** `1e+20` is the same JSON number.
  A Parquet file polars reads back equal is checked live in Athena, which is the reader that
  matters here (FR-005). A decimal with more fractional digits than its scale cannot come from Athena:
  the converter types a column with the scale Athena declared for it, and a value of that type has
  no more fractional digits than its scale. A JSON integer too large for `bigint` now refuses
  with each plane's existing named code instead of producing a `bigint` column that cannot hold it.
- **The converter's counts are left alone.** It counts through a projected column rather than
  `pl.len()`; on 1.44 both are right, and changing correct code to follow a library fix buys
  nothing. What changes is the tests and the words that say `pl.len()` is wrong, which become a
  statement about 1.12.
- **The 1.44.2 measurements join the evidence; they do not replace it, so no cap can rise.**
  `MEASURED_EXCEL_SHAPES` already keeps each shape's HIGHEST peak over every run and its LOWEST
  rate over the native runs, and `OUTPUT_EXPANSION` the worst figure observed. The new runs join
  those populations by the same rules, so each measured constant can only move to its safer side,
  and each cap derived from them can only stay or fall. FR-004 names the safe side per constant. Letting 1.44's figures REPLACE 1.12's would lower constants on
  the strength of runs nobody has validated in production, and the Parquet cap alone would move
  from 1,472 to 1,728 MiB, past what the scratch disk holds at the measured 0.252 expansion. What
  cannot be re-measured before the push stays as it is and says so. That covers three things:
  the production gap inside `EXCEL_BASELINE_MB`, which is taken as 84 MiB, the top of the 65 to
  84 MiB SPEC-230 recorded at the 490,000 × 4 production shape; `_LOCAL_TO_PRODUCTION`; and the
  Excel expansion figure, which no script measures. The live at-cap conversion is what validates
  the model on 1.44.

## Scope

### In Scope

- A Parquet schema probe that fetches only the footer, replacing `S3RangeReader`, with the
  trailer checks shared with `rccommon.parquet_footer` (FR-001).
- Both polars pins moved to 1.44.2, with the image building and every suite green (FR-002).
- Results holding multi-line values converting correctly in every streamed format, whole or in
  part; `SINK_OPTIONS` and its tests retired; the refusal sentence and detail corrected (FR-003).
- The Excel memory model's corpus and the output expansion re-measured in the images built from
  this spec's branch, joining the existing evidence so that no cap rises (FR-004).
- Every statement that a polars behaviour holds, where it held only on 1.12, re-stated or retired,
  and the live checks that close the move (FR-005).

### Out of Scope

- **The header double-quote defect.** A result column whose name holds a doubled quote still fails
  every conversion on 1.44.2; it is a separate defect with its own trap entry.
- **pyarrow**, and checking how pyarrow or pandas type the new Parquet files. Athena is the reader
  this portal promises; pyarrow is not a dependency and is not added to find out.
- **Narrowing the writers' `except Exception`** to polars' own errors. It would change what every
  non-polars fault tells the user, which is a decision about refusals, not about this version.
- **Raising any Lambda's memory, disk or timeout**, and changing any cap policy. The caps are
  re-derived by the rules they already have.
- **polars' new streaming engine settings** beyond what the default `sink_*` calls use.
- **Mapping `Int128`** to an Athena type. It refuses like any other unmappable type.

---

## Functional Requirements

### FR-001: A Parquet schema probe fetches only the footer, whichever polars is installed

#### Description:

`cpcommon.parquet_trailer.footer_span(object_size, trailer)` takes an object's size and its last 8
bytes and returns the footer's offset and length, raising `ParquetTrailerError` (a `ValueError`)
for an object under 12 bytes, a trailer not ending in `PAR1`, a declared footer of zero bytes, or
a declared footer longer than `object_size - 12`. The size is checked first, so a trailer shorter
than 8 bytes is never indexed. The zero-length refusal is not decoration: the footer's range would
then be `bytes=N-(N-1)`, which is syntactically invalid, and S3 answers an invalid `Range` by
ignoring it and returning the whole object. polars refuses a zero-length footer on both versions,
so the check costs nothing.

`cpcommon.bounded_read.read_parquet_footer(bucket, key)` makes two GETs and no HEAD. The first is
the suffix range `bytes=-8`, whose `ContentRange` (`bytes a-b/SIZE`) carries the object's size;
an object under 8 bytes comes back whole, and an empty one raises S3's `InvalidRange`, which the
reader refuses as a too-short object. It calls `footer_span`, refuses a footer longer than
`DEFAULT_PROBE_MAX_BYTES` with `ParquetTrailerError` before any second request, then fetches
exactly the footer's range. **It never reads more than the span it asked for:** each response's
declared length is checked against the span before the body is read, a mismatch refuses, and
each body read is capped at that span. It returns an `io.BytesIO` of `PAR1`, the footer, its
4-byte little-endian length and `PAR1`. A retryable S3 fault goes through
`errors.raise_if_transient`, as the other reads in that module do.
`rccommon.parquet_footer._metadata` delegates its trailer checks to `footer_span` and re-raises
its error as `ParquetFooterError`, so its callers are unchanged.

`infer_schema._parquet_source` and `dq_inspect_source._parquet_source` return
`read_parquet_footer(bucket, key)` where they return an `S3RangeReader` today, and both are
already called inside the `try` that turns a failure into each verb's named refusal. The
`S3RangeReader` class and its tests are deleted, and every passage describing it is rewritten.

#### Acceptance Criteria:

- [ ] The tests' fake S3 answers ranges as S3 does: a suffix range on an object shorter than it
      returns the whole object, an empty object raises `InvalidRange`, and a syntactically invalid
      range is ignored and returns the whole object. It records the bytes it SERVES, not the
      ranges requested.
- [ ] A test builds a Parquet file of at least 2 MB with at least five dtypes, including a
      decimal, a list and a struct, and many row groups. Served through that fake, it asserts two
      things: that `pl.read_parquet_schema(read_parquet_footer(...))` equals polars' schema of the
      whole file, and that the bytes served total no more than the footer's length plus 8.
- [ ] That test passes under polars 1.12.0 and under 1.44.2, and the PR body quotes both runs'
      exit codes.
- [ ] `footer_span` is tested on an 11-byte object, on a trailer ending in something other than
      `PAR1`, on a declared length of zero, and on a declared length one byte past
      `object_size - 12`. Each raises `ParquetTrailerError`, and each test asserts that the message
      says which of the four failures it was.
- [ ] `read_parquet_footer` over an empty object and over a 5-byte object each raises
      `ParquetTrailerError` naming the object as too short, and neither is served more than the
      object holds.
- [ ] Driven through each verb's handler with the verb's real `_parquet_source` over the fake, an
      object whose trailer is not `PAR1` refuses as `schema_inference_failed` in table-builder's
      infer-schema and as `unreadable_header` in data-quality's inspect-source. These are the codes
      each already raises for an object it cannot read. A footer over `DEFAULT_PROBE_MAX_BYTES`
      refuses the same way, and the fake records no footer GET for it. Each refusal's detail
      carries the new reader's reason — `footer_span`'s for the trailer, `read_parquet_footer`'s
      own for the cap — which is what shows the new reader produced it. Neither case reaches a
      fault.
- [ ] A throttled ranged GET raises `TransientError`.
- [ ] `rccommon.parquet_footer`'s existing tests pass unchanged, and `_metadata` makes none of
      the trailer checks itself, the leading `PAR1` included.
- [ ] `git grep S3RangeReader` returns nothing under `lambdas/`. The passage in
      `lambdas/info/shared-layer.md` describes `read_parquet_footer`, and so do the docstrings
      that describe `S3RangeReader`'s behaviour or its throttle handling: `infer_schema.py`'s
      module docstring, both `_parquet_source` docstrings, both `_columns_from` /
      `_infer_columns` docstrings, and `dq_inspect_source._check_access`'s sentence about what
      polars raises when S3 throttles the read. `shared-layer.md`'s module table gains a
      `parquet_trailer` row.
- [ ] `rccommon.parquet_footer` no longer defines `_MAGIC`, and its Attributes block no longer
      lists it.
- [ ] Live, after this phase deploys and while 1.12 is still pinned: a table-builder run and a
      data-quality check, each over a Parquet folder, succeed. That shows the ranged GETs work
      against real S3 before the version move is added on top.

### FR-002: The fleet runs polars 1.44.2

#### Description:

Both pins read `polars==1.44.2`: `lambdas/table-builder-infer-schema/requirements.txt` and
`lambdas/data-quality-polars/requirements.txt`. The image builds, its requirement-constraint check
passes, and `.github/scripts/lambda-image-matrix.sh <image-ref>` passes against it. The Lambda
suite is green on 1.44.2. Each test that asserted a 1.12 behaviour is changed to assert what is
now true, or is deleted where the behaviour it guarded no longer exists.

#### Acceptance Criteria:

- [ ] Both requirements files pin `polars==1.44.2`.
- [ ] The image built from `lambdas/Dockerfile` for `linux/amd64` prints `1.44.2` for
      `python -c "import polars; print(polars.__version__)"`. Its build log shows the constraint
      check's success line. `.github/scripts/lambda-image-matrix.sh` exits 0 against it.
- [ ] `python3 -m pytest lambdas/` exits 0 with polars 1.44.2 installed, in a checkout where
      `npm ci` has run (`test_local_install_guard.py` needs `node_modules` whatever polars is).
- [ ] The test names the runner collects are diffed against `main`'s. The PR body lists every name
      that disappears, with the 1.12 behaviour it guarded.
- [ ] A JSON source whose integer exceeds int64's maximum refuses as `unmappable_type` in
      table-builder's infer-schema and as `unreadable_header` in data-quality's inspect-source.
      These are the codes each already raises for a dtype `map_dtype` refuses. Each is asserted by
      its reason and by a detail that names the column.

### FR-003: A result holding multi-line values converts, whole or in part

#### Description:

With 1.44.2 installed, `SINK_OPTIONS` is removed from `rc_convert.py` together with
`test_every_streamed_sink_takes_the_options_it_is_given`, and the three sinks are called with no
options. `test_a_column_subset_the_streaming_reader_mis_splits_is_refused_never_written_wrong` is
replaced by a test that the same shapes CONVERT, with every row right. `results_unreadable`'s
sentence returns to SPEC-239's, which #856 replaced: *"part of the results could not be read, so
"{filename}" was not written. If a column's values don't all match the type the query gave it,
casting that column and running the query again will fix it."* `_unreadable` stops putting a byte
offset into the detail.

#### Acceptance Criteria:

- [ ] For Parquet, JSON and CSV, take a result of 200,000 rows whose every tenth value is a
      200-character multi-line document — the live check's size, about 7 MB, well past where 1.12
      fails at 60,000, so the file is split across the reader's chunks on either version. It
      converts both in full and with `columnIndexes=[0]`, and
      the written file's rows equal Python's `csv` module's reading of the input, row for row.
- [ ] The same test fails when run under polars 1.12.0, and the PR body quotes that run.
- [ ] `messages.failure_message(results_unreadable, …)` returns the sentence above, and the plane
      suite's golden asserts it whole.
- [ ] A value that does not parse as its column's type refuses with a detail that names the column
      and carries no "at byte" clause. The test asserts both.
- [ ] `SINK_OPTIONS` has no definition and no reference under `lambdas/`.

### FR-004: The Excel and expansion evidence is re-measured on the new image, and no cap rises

#### Description:

`scripts/measure_excel_peak.py` runs three times natively on arm64 and once on amd64, against
images built from this spec's branch by the script's own instructions. That is the shape of the
evidence `MEASURED_ON` already describes. `scripts/measure_conversion_expansion.py` runs once in
the arm64 image. The results join the existing evidence, and each constant moves only to its
safer side:
- each `MEASURED_EXCEL_SHAPES` row keeps the HIGHEST peak per cell over every run, 1.12's
  included, and the LOWEST rate over the native runs.

The constants are then derived in this order, because each term is net of the one before it, and
each is the larger of `main`'s value and what its step gives (for the covered width, the smaller):
1. `EXCEL_PEAK_BYTES_PER_ROW`: per run, the one-wide one-character shape's peak less the
   fifteen-wide one's, over `1 - 1/15`; the largest over the new runs, rounded up to the next ten.
2. `EXCEL_PEAK_BYTES_PER_CELL`: over the joined corpus's shapes no wider in CSV than `main`'s
   covered width of 23 bytes a cell, the largest peak less its row share
   (`EXCEL_PEAK_BYTES_PER_ROW / columns`), rounded up to the next ten.
3. `EXCEL_COVERED_BYTES_PER_CELL`: the SMALLER of 23 and the CSV width of the shape that set step
   2, because a narrower covered width charges more. Step 2 selected from shapes at or under 23,
   so this can only narrow the set it chose from, and it does not re-open step 2.
4. `EXCEL_PEAK_BYTES_PER_LONG_BYTE`: over the shapes wider than the covered width, the largest
   `(peak - per-cell - row share) / (csv width - covered width)`, rounded up to a whole byte.
5. `EXCEL_BASELINE_MB`: the larger of `main`'s 250 and the largest new local fixed cost (the
   script's `intercept_mib`) plus 84 MiB, rounded up to the next ten.
6. `OUTPUT_EXPANSION`'s CSV, Parquet and JSON figures: each the larger of `main`'s figure and the
   worst the image run measures. Excel's carries over unmeasured.
7. `EXCEL_MAX_CELLS` and `RESULTS_MAX_BYTES` are recomputed by the budget test from the above, so
   they can fall and cannot rise.

**If these rules leave the budget test red, or floor any format's byte cap or the cell cap to
zero, the build stops and escalates** rather than choosing between constants: a cap that falls
that far is a product change, not a re-measurement.

`MEASURED_ON` gains a sentence naming polars 1.44.2, xlsxwriter's version, the runs, and the
`main` commit the measured branch was based on. It says which figures carry over unmeasured and
why.

#### Acceptance Criteria:

- [ ] Each measured constant is on its safe side of `main`'s value, as the list above sets out:
      not lower, or for `EXCEL_COVERED_BYTES_PER_CELL` not higher. The budget test in
      `test_plane_results_conversion.py` passes. No `RESULTS_MAX_BYTES` entry, and not
      `EXCEL_MAX_CELLS`, is higher than on `main`.
- [ ] Every `MEASURED_EXCEL_SHAPES` row's peak is at least `main`'s for that row and at least the
      highest any of the four new runs measured for its shape. Its rate is at most `main`'s and at
      most the lowest the three native runs measured. The PR body carries the four runs' output.
- [ ] `MEASURED_ON` names polars 1.44.2, the xlsxwriter version, the four Excel runs and the
      expansion run, and the `main` commit the branch was based on. It names
      `EXCEL_BASELINE_MB`'s 84 MiB production gap, `_LOCAL_TO_PRODUCTION` and the Excel expansion
      figure as carried over from 1.12, each with its reason. It also says that the Parquet and
      JSON figures are not re-measured on the shapes their own line names, as it already says of
      1.12, so they carry over too, raised only where the script's shapes exceed them.
- [ ] If any Excel constant changed, every §4.3 row in `docs/testing/e2e.md` that quotes a figure
      derived from them is regenerated before the push, by the rule the at-cap row states. That
      is the at-cap row, with its input at the recomputed cap and its model figure from the
      recomputed constants, and the cell-limit row, which quotes the cell cap. If none changed,
      the rows stand and the PR body says so.

### FR-005: Every 1.12-only claim is re-stated or retired, and the move is checked live

#### Description:

Every place that states a polars behaviour as current, where that behaviour held on 1.12 and does
not hold on 1.44.2, is corrected in the same PR as the pin. After the deploy, the move is checked
in production, with a positive control run before the deploy.

#### Acceptance Criteria:

- [ ] `git grep -n -E "polars 1\.12|1\.12\.0"` over `lambdas/`, `scripts/`, `docs/decisions/` and
      `lambdas/info/` is run, and the PR body lists every remaining match with one line on why it
      stays.
- [ ] Each of these states what 1.44.2 does, or marks the 1.12 behaviour as history:
      - the results-conversion Traps entries for the fast count, the streaming mis-split and
        `schema_overrides`;
      - `docs/decisions/control-planes/` at its `schema_overrides` passage and its fast-count
        passage;
      - SPEC-239's two "after close" markers, in its spec and its delivery doc;
      - `lambdas/info/shared-layer.md`'s polars size figure, and the same figure in
        `lambdas/control-plane-common/requirements.txt`;
      - the claims that name no version: `rccommon/reasons.py`'s `RESULTS_UNREADABLE` entry ("the
        reader itself refuses some large results holding newlines inside quoted values"),
        `rc_convert._unreadable`'s paragraph on why the message is not read for a cause, the
        count docstrings in `rc_convert.py` that call the fast count wrong, and the docstring of
        the plane suite's `results_unreadable` golden test.
- [ ] A second grep, for the behaviour rather than the version —
      `git grep -n -i -E "mis-split|newlines? inside quoted|fast count|pl\.len"` over the same
      trees — is run, and the PR body lists each remaining match with one line on why it stays.
- [ ] Positive control, in production **before** the Phase 2 deploy. Save the query below as
      Parquet, in full, from the Query workspace: it is refused as `results_unreadable`. Then run
      `CREATE VIEW` over it, open the view in Data Explorer, hide `doc`, and save as Parquet: that
      is refused as `results_unreadable` too. (Athena caps `sequence` at 50,000 entries, which is
      why the rows come from a cross join.)

      `SELECT CAST(x AS varchar) AS id, IF(x % 10 = 0, '{' || chr(10) || '  "k": 1,' || chr(10) ||
      '  "v": "' || rpad('', 200, 'z') || '"' || chr(10) || '}', '{}') AS doc
      FROM (SELECT i * 500 + j AS x FROM UNNEST(sequence(0, 399)) AS a(i)
      CROSS JOIN UNNEST(sequence(0, 499)) AS b(j))`

      If either save is not refused, the shape does not mis-split in production, and a shape
      that is refused must be found before the checks below count.
- [ ] After the deploy, the same query saves as Parquet in full and as JSON in full, each
      reporting 200,000 rows. The view saves as Parquet from Data Explorer with `doc` hidden,
      also reporting 200,000 rows.
- [ ] After the deploy, a result holding every scalar type the converter maps is saved as Parquet
      into a folder of its own. Table-builder builds a table over that folder. Both
      `SELECT * FROM <table> EXCEPT <the query>` and `<the query> EXCEPT SELECT * FROM <table>`
      return no rows. The query is:

      `SELECT CAST(x % 100 AS tinyint) AS ti, CAST(x AS smallint) AS si, CAST(x AS integer) AS i,
      x AS b, CAST(x AS real) / 3 AS r, CAST(x AS double) / 3 AS d,
      CAST(x AS decimal(12,2)) / 7 AS dec, x % 2 = 0 AS flag,
      date_add('day', x, DATE '2024-01-01') AS dt,
      TIMESTAMP '2024-01-02 03:04:05.123' + x * INTERVAL '1' SECOND AS ts,
      IF(x % 5 = 0, NULL, 'v' || CAST(x AS varchar)) AS s FROM UNNEST(sequence(1, 1000)) AS t(x)`

      A data-quality check over the same folder also succeeds.
- [ ] After the deploy, the §4.3 at-cap Excel row converts. Its `REPORT` line is at or under the
      model's figure, as that row states.
- [ ] Any of these that cannot run from a signed-in session becomes a row in
      `docs/testing/owed.md`.

---

## Data Model

```python
# lambdas/control-plane-common/cpcommon/parquet_trailer.py
class ParquetTrailerError(ValueError): ...

def footer_span(object_size: int, trailer: bytes) -> tuple[int, int]:
    """The footer's (offset, length), from an object's size and its last 8 bytes."""

# lambdas/control-plane-common/cpcommon/bounded_read.py
def read_parquet_footer(bucket: str, key: str) -> io.BytesIO:
    """A buffer holding only the object's Parquet footer, framed as a file polars can read."""
```

No wire type, state-machine field or TypeScript type changes.

## File & Folder Structure

- `lambdas/control-plane-common/cpcommon/parquet_trailer.py` (new), `bounded_read.py`, and their
  tests — FR-001
- `lambdas/results-conversion-common/rccommon/parquet_footer.py` — FR-001 (delegates its checks)
- `lambdas/table-builder-infer-schema/infer_schema.py`,
  `lambdas/data-quality-inspect-source/dq_inspect_source.py`, `lambdas/info/shared-layer.md` —
  FR-001
- `lambdas/table-builder-infer-schema/requirements.txt`,
  `lambdas/data-quality-polars/requirements.txt` — FR-002
- `lambdas/results-conversion-convert/rc_convert.py` and its test,
  `lambdas/results-conversion-common/rccommon/{messages,reasons,config}.py` and the plane suite —
  FR-003, FR-004
- `lambdas/info/planes/results-conversion.md`, `docs/decisions/control-planes/`,
  `docs/testing/e2e.md`, SPEC-239's spec and delivery doc — FR-004, FR-005

## Implementation Phases

### Phase 1: The footer-only probe, on 1.12 (FR-001)

Its own PR. It lands and deploys before the pin moves, because it works on both versions. It
changes how the probe reads, and it adds one refusal, for a footer over 32 MiB. FR-001's live
check runs after its deploy.

### Phase 2: The pin, the converter and the tests (FR-002, FR-003)

FR-005's positive control runs in production first, while 1.12 and #856 are live. Then the pin
moves, and everything that fails on 1.44.2 is resolved on the same branch.

### Phase 3: Re-measure in the image (FR-004)

On the Phase 2 branch, before it is pushed: the images are built, both measurement scripts run,
and the evidence and constants are updated by FR-004's rules.

### Phase 4: The records and the live checks (FR-005)

The claims are corrected on the same branch, which lands as one PR with Phases 2 and 3. The live
checks run after its deploy.
