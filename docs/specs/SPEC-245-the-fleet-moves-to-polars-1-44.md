# Spec: The Fleet Moves to polars 1.44, So a Result Holding Line Breaks Converts Instead of Refusing

**ID:** SPEC-245
**Status:** Draft
**Last Updated:** 2026-09-21
**Depends On:** None

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
  1.12 on purpose, both below.
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
  one is not an option.
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
- **The Excel caps are re-derived, not assumed to carry over.** `MEASURED_ON` says they are only as
  true as the library that produced them. The re-derivation follows the rules already in
  `rccommon.config` and the plane page's Traps, including the live check of the model-peak input.

## Scope

### In Scope

- A Parquet schema probe that fetches only the footer, replacing `S3RangeReader` (FR-001).
- Both polars pins moved to 1.44.2, with the image building and every suite green (FR-002).
- Results holding multi-line values converting correctly in every streamed format, whole or in
  part; `SINK_OPTIONS` and its tests retired; the refusal sentence and detail corrected (FR-003).
- The Excel memory model, its corpus, the caps derived from it and the output expansion
  re-measured in the image built from this spec's branch (FR-004).
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

`cpcommon.bounded_read` gains `parquet_footer(bucket, key)`, which fetches an object's last 8
bytes, checks the `PAR1` trailer, fetches the footer those bytes name, and returns an in-memory
buffer framing that footer as a file (`PAR1`, footer, length, `PAR1`). `infer_schema.py` and
`dq_inspect_source.py` hand that buffer to `pl.read_parquet_schema` where they now hand an
`S3RangeReader`, and `S3RangeReader` is deleted. The footer is bounded by
`DEFAULT_PROBE_MAX_BYTES`; a longer one, an object shorter than 12 bytes, or a trailer that is not
`PAR1` raises an ordinary exception, so each plane's existing handling of an unreadable Parquet
applies unchanged. A retryable S3 fault goes through `errors.raise_if_transient` as the other
reads here do.

#### Acceptance Criteria:

- [ ] A test builds a multi-megabyte Parquet file with at least five dtypes, including a decimal,
      a list and a struct, serves it through a fake S3 that records every `Range` it is asked for,
      and asserts that `pl.read_parquet_schema(parquet_footer(...))` equals polars' schema of the
      whole file **and** that the bytes fetched are no more than the footer's length plus 8.
- [ ] That test passes under polars 1.12.0 and under 1.44.2; the build records both runs' exit
      codes.
- [ ] A footer longer than `DEFAULT_PROBE_MAX_BYTES`, an object of 11 bytes, and an object whose
      last four bytes are not `PAR1` each raise from `parquet_footer`; and driven through each
      verb's handler, one of them refuses as `schema_inference_failed` in table-builder's
      infer-schema and as `unreadable_header` in data-quality's inspect-source — the codes each
      already raises for an object it cannot read — rather than as a fault.
- [ ] `parquet_footer` is called inside the `try` each verb already wraps its probe in, so a fetch
      failure meets the same handling a parse failure does.
- [ ] A throttled ranged GET raises `TransientError`.
- [ ] `S3RangeReader` has no definition and no caller; `git grep S3RangeReader` returns only
      history in `docs/`.

### FR-002: The fleet runs polars 1.44.2

#### Description:

Both pins — `lambdas/table-builder-infer-schema/requirements.txt` and
`lambdas/data-quality-polars/requirements.txt` — read `polars==1.44.2`. The image builds, its
requirement-constraint check passes, and `scripts/lambda-image-matrix.sh` passes. The Lambda suite
is green on 1.44.2, and the tests that asserted a 1.12 behaviour are changed to assert what is
now true or deleted where the behaviour they guarded no longer exists.

#### Acceptance Criteria:

- [ ] Both requirements files pin `polars==1.44.2`, and no file under `lambdas/` or `scripts/`
      names 1.12.0 as the installed version.
- [ ] The image built from `lambdas/Dockerfile` for `linux/amd64` prints `1.44.2` for
      `python -c "import polars; print(polars.__version__)"`, and its build log shows the
      constraint check's success line.
- [ ] `python3 -m pytest lambdas/` exits 0 with polars 1.44.2 installed, and the runner's
      collected test names are diffed against `main`'s: every name that disappears is listed in
      the PR body with the 1.12 behaviour it guarded.
- [ ] A JSON source whose integer exceeds int64's maximum refuses as `unmappable_type` in
      table-builder's infer-schema and as `unreadable_header` in data-quality's inspect-source, the
      codes each already raises for a dtype `map_dtype` refuses; each is asserted by its reason
      and its detail naming the column.

### FR-003: A result holding multi-line values converts, whole or in part

#### Description:

With 1.44.2 installed, `SINK_OPTIONS` is removed from `rc_convert.py` together with
`test_every_streamed_sink_takes_the_options_it_is_given`, and the three sinks are called with no
options. `test_a_column_subset_the_streaming_reader_mis_splits_is_refused_never_written_wrong`
becomes a test that the same shapes CONVERT with every row right. `results_unreadable`'s sentence
returns to SPEC-239's. `_unreadable` stops putting a byte offset into the detail.

#### Acceptance Criteria:

- [ ] For Parquet, JSON and CSV, a result of 60,000 rows whose every tenth value is a 200-character
      multi-line document converts in full and with `columnIndexes=[0]`, and the written file's
      rows equal Python's `csv` module's reading of the input, row for row.
- [ ] The same test, run under polars 1.12.0, fails; the build records that run.
- [ ] `messages.failure_message(results_unreadable, …)` returns SPEC-239's sentence exactly, and the
      plane suite's golden asserts it whole.
- [ ] A value that does not parse as its column's type refuses with a detail naming the column and
      carrying no "at byte" clause.
- [ ] `SINK_OPTIONS` has no definition and no reference in `lambdas/`.

### FR-004: The Excel caps and the output expansion are re-derived on the new image

#### Description:

`scripts/measure_excel_peak.py` is run in the image built from this spec's branch, for amd64,
following its own instructions, and `scripts/measure_conversion_expansion.py` in the same image.
The Excel constants in `rccommon.config`, the `MEASURED_EXCEL_SHAPES` corpus and
`OUTPUT_EXPANSION` are set from those runs by the rules their docstrings already state, and
`MEASURED_ON` names polars 1.44.2 and the commit the image was built from. The caps derived from
them are recomputed by the budget test.

#### Acceptance Criteria:

- [ ] `MEASURED_ON` names polars 1.44.2, the xlsxwriter version and the commit the measured image
      was built from, and no longer names 1.12.0.
- [ ] Each Excel constant is at or above the maximum the new runs measured for the term it bounds,
      and the corpus is the new runs' output; the budget test in
      `test_plane_results_conversion.py` passes against the recomputed caps.
- [ ] Each `OUTPUT_EXPANSION` figure is at or above the worst the image run measured for its
      format.
- [ ] If the recomputed `EXCEL_MAX_CELLS` or any `RESULTS_MAX_BYTES` differs from today's, the
      §4.3 at-cap row in `docs/testing/e2e.md` is regenerated for the new cap, by the rule that row
      states, before the push.

### FR-005: Every 1.12-only claim is re-stated or retired, and the move is checked live

#### Description:

Every place that states a polars behaviour as current, where the behaviour held on 1.12 and not
on 1.44.2, is corrected in the same PR as the pin: the plane pages' Traps, docstrings, test
docstrings, `lambdas/info/shared-layer.md`, and the `docs/decisions/` entries that state them. The
set is the survey's list above plus whatever `git grep -n -i "1\.12"` finds. After deploy, the move
is checked in production.

#### Acceptance Criteria:

- [ ] `git grep -n -i "1\.12"` over `lambdas/`, `scripts/` and `docs/decisions/` returns only
      lines that say what 1.12 did as history, each reviewed by the diff's reviewers.
- [ ] The results-conversion Traps entries for the fast count, the streaming mis-split and
      `schema_overrides` state what 1.44.2 does; the `shared-layer.md` passage on `S3RangeReader`
      describes `parquet_footer`; the polars size figure is corrected.
- [ ] Live, after deploy: a Data Explorer save of a result holding multi-line values, over
      2 MB, with one column hidden, converts to Parquet with the right row count; the same result
      saves as JSON; a table built by table-builder over that Parquet file answers
      `SELECT count(*)` with the same row count; a data-quality check over the same folder
      succeeds, so both callers of `parquet_footer` have run in production; and the regenerated §4.3
      at-cap Excel row converts with its `REPORT` line at or under the model's figure. Any of
      these that cannot run from a signed-in session becomes a row in `docs/testing/owed.md`.

---

## Data Model

```python
# lambdas/control-plane-common/cpcommon/bounded_read.py
def parquet_footer(bucket: str, key: str) -> io.BytesIO:
    """A buffer holding only the object's Parquet footer, framed as a file polars can read."""
```

No wire type, state-machine field or TypeScript type changes.

## File & Folder Structure

- `lambdas/control-plane-common/cpcommon/bounded_read.py` and `test_bounded_read.py` — FR-001
- `lambdas/table-builder-infer-schema/infer_schema.py`,
  `lambdas/data-quality-inspect-source/dq_inspect_source.py` — FR-001 callers
- `lambdas/table-builder-infer-schema/requirements.txt`,
  `lambdas/data-quality-polars/requirements.txt` — FR-002
- `lambdas/results-conversion-convert/rc_convert.py` and its test,
  `lambdas/results-conversion-common/rccommon/{messages,reasons,config}.py` and the plane suite —
  FR-003, FR-004
- `lambdas/info/planes/results-conversion.md`, `lambdas/info/shared-layer.md`,
  `docs/decisions/control-planes.md`, `docs/testing/e2e.md` — FR-004, FR-005

## Implementation Phases

### Phase 1: The footer-only probe, on 1.12 (FR-001)

Lands and deploys on its own before the pin moves, since it works on both versions and changes
how nothing but the probe reads.

### Phase 2: The pin, the converter and the tests (FR-002, FR-003)

The pin moves and everything that fails on 1.44.2 is resolved in the same branch.

### Phase 3: Re-measure in the image (FR-004)

On the Phase 2 branch, before it is pushed: the image is built and both measurement scripts run
in it, and the constants and corpus are set from the output.

### Phase 4: The records and the live checks (FR-005)

The claims are corrected on the same branch, which lands as one PR with Phases 2 and 3; the live
checks run after its deploy.
