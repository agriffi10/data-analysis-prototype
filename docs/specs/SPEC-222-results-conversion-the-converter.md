# Spec: Results Conversion — The Converter, the Three Writers & the Notification

**ID:** SPEC-222
**Status:** Draft
**Last Updated:** 2026-09-05
**Depends On:** SPEC-221 (the plane, the contract, validate-authorize, describe-results), SPEC-069 (table-builder's polars precedent), SPEC-107 (`cpcommon.type_mapping`, whose inverse this needs)

## Overview

With the plane standing and a request proved legitimate, this spec makes it do the work: read the
result set Athena wrote, give every column the type Athena said it has, and write one file in the
format the user chose — Parquet, JSON or Excel — into the destination they named, then tell them.
The user's experience is one notification with a link to the folder; the property that matters
underneath is that a file this plane writes can be read back by this app's own table builder, so
"save as Parquet" and "make a table from it" compose.

Three decisions are settled here. **Types come from Athena's metadata, never inferred from the
CSV** — a column of numeric-looking strings stays `varchar`, and an unknown Athena type refuses
rather than degrading to text, because a closed vocabulary that falls back is not closed.
**JSON is newline-delimited**, one object per line, because that is what the table builder and
Athena read and what the cancelled file-converter arc had already settled; a pretty-printed array is
what the Explorer's *Copy* offers for a page, and the two are different tools. And **the destination
write is conditional**: without `overwrite`, S3's `If-None-Match` is what refuses a name taken
between the browser's pre-flight and the write, so no lock is needed and no race is silent.

## Scope

### In Scope

- `rccommon.types`: the Athena-type-to-polars-dtype table, and the CSV read that applies it.
- The **convert** verb: read the result object, build the typed frame, write the file to the
  verb's local storage, upload it under the conditional write.
- The three writers — Parquet, NDJSON, Excel — with their format-specific fences.
- The **notify** verb: the success notification with its link, and the outcome vocabulary.
- The execution role's write grant, the `xlsxwriter` dependency, the converter's memory, storage
  and timeout budget, and the re-derived `RESULTS_MAX_BYTES` and `TimeoutSeconds`.

### Out of Scope

- Any browser surface — SPEC-223. Nothing a user can reach ships here either.
- CSV output, or re-serialising the CSV Athena wrote. Unchanged, and never this plane's.
- Parsing nested values. An Athena `array`, `map`, `row` or `struct` column arrives as the text
  Athena rendered and is written as text in every format. Reconstructing the structure from that
  text is a parser this arc does not build.
- Excel formatting beyond a header row: no column widths, number formats, frozen panes or styles.
- Multiple sheets, multiple files, partitioned output, or compression the user chooses.
- Preserving the order of rows across a conversion beyond what the CSV holds — Athena's result
  order is the row order, and an `ORDER BY` is the user's to write.

---

## Functional Requirements

### FR-001: A typed frame from the result set

#### Description:

The CSV Athena wrote is all strings. The frame the writers see is typed as Athena declared.

#### Acceptance Criteria:

- [ ] `rccommon.types.polars_dtype(athena_type)` maps every type Athena can report in
      `ColumnInfo.Type`: `boolean`, `tinyint`, `smallint`, `integer`/`int`, `bigint`, `real`/`float`,
      `double`, `decimal(p,s)` (to `Decimal(p, s)`), `date`, `timestamp` (to `Datetime("us")`, naive —
      Athena timestamps carry no zone), `varchar`/`char`/`string` (to `String`), and `json`,
      `binary`, `varbinary`, `array`, `map`, `row`, `struct`, `ipaddress`, `time`,
      `interval` and `unknown` **as text**, kept as the characters Athena rendered. A test walks
      every name Athena documents and asserts a mapping or a listed text-kept entry for each; a name
      in neither refuses with `unsupported_column_type` naming the column, never falls back.
- [ ] The table is asserted against `cpcommon.type_mapping` over the **image of `polars_dtype`**:
      for every dtype this table produces, `map_dtype` of that dtype mapped back through this table
      is the same dtype (decimal parameters included). Dtypes only `map_dtype` knows — the unsigned
      integers it widens, `List` and `Struct`, a zoned `Datetime` — are outside the assertion by
      construction, and the test says so. The two tables cannot drift apart on the types both hold.
- [ ] The CSV is read by polars with the schema **given**, never inferred: `schema_overrides` from
      the mapped dtypes, `infer_schema_length=0`. A value that does not parse as its declared type
      refuses the whole conversion with `results_unreadable` naming the column and the byte offset
      polars reports — polars names no row number, and the spec does not pretend one; no partial
      file is written.
- [ ] NULL and the empty string are distinguished for text columns exactly as Athena's CSV encodes
      them — an unquoted empty field is NULL, `""` is an empty string — and the fixture proving it is
      a **captured** Athena result object from the workgroup, committed under `lambdas/…/fixtures/`
      with its `ColumnInfo` beside it, never a hand-written CSV. For non-text columns an empty field
      is NULL.
- [ ] The read is bounded by `RESULTS_MAX_BYTES`, checked again against the object's actual
      `ContentLength` at read time (a result that grew between describe and convert is a fault, not
      a user error); the object goes to the verb's local storage, never into memory whole, and a
      test asserts the read path is `download_fileobj` to a file, not `get()["Body"].read()`.
- [ ] **Parquet and JSON are streamed, never materialised.** The frame is `scan_csv` over the local
      file and the writer is `sink_parquet` / `sink_ndjson`, so memory holds a batch at a time and
      the cap is set by the disk, not by RAM. A test asserts the verb calls no `collect()` and no
      `read_csv` on those two paths. Excel cannot stream and is materialised, which is why its
      ceiling is Excel's own row limit (FR-004) rather than the disk.

### FR-002: Parquet

#### Description:

One Parquet file, typed, readable by the table builder.

#### Acceptance Criteria:

- [ ] One `.parquet` object is written with every column's polars dtype from FR-001; text-kept types
      are `String` columns. Row count equals the CSV's data-row count.
- [ ] Compression is polars' default, and the test asserts the file's compression codec by reading
      the footer, so a library default changing on an upgrade is a red test rather than a silent
      change in what users receive.
- [ ] The written file is read back by table-builder's own inference,
      `infer_schema._infer_columns(source, "parquet")` on the local file (it reads a local path,
      which is what makes this a unit test), and the column names and Hive types it infers equal
      what `describe-results` reported (through `cpcommon.type_mapping`), for a fixture carrying
      every mapped type. This is the round-trip that makes "save as Parquet, then build a table"
      compose.
- [ ] An empty result set writes a Parquet file with the schema and zero rows, and the notification
      says `0 rows`.

### FR-003: JSON

#### Description:

Newline-delimited JSON, one object per line.

#### Acceptance Criteria:

- [ ] One `.json` object is written with one JSON object per line, keys in column order, and no
      enclosing array — the shape the table builder's JSON path and Athena's SerDe read.
- [ ] NULL is `null`; the empty string is `""`; booleans are JSON booleans; integers and floats are
      JSON numbers; `decimal` is a JSON **string** of its exact digits, because a JSON number would
      round it; `date` is `YYYY-MM-DD`; `timestamp` is ISO-8601 to microseconds with no zone
      designator; text-kept types are strings.
- [ ] The written file is read back by `infer_schema._infer_columns(source, "json")` on the local
      file and yields the column names `describe-results` reported, for the same every-type fixture
      as FR-002. Types are asserted too, with one stated exception: infer-schema recovers a `date`
      column from NDJSON by a regex over sample values, so `date` round-trips through that heuristic
      and the test names it rather than pretending the format carries the type.
- [ ] An empty result set writes a zero-byte `.json` object, and the notification says `0 rows`.

### FR-004: Excel

#### Description:

One workbook, one sheet, and the fences Excel needs that the other two do not.

#### Acceptance Criteria:

- [ ] `xlsxwriter` is pinned in `lambdas/results-conversion-convert/requirements.txt` with a comment
      saying which verb needs it and that the image installs it fleet-wide; CLAUDE.md's Tech Stack
      names it. Nothing else new is installed — `polars.write_excel` needs no `openpyxl`.
- [ ] One `.xlsx` object with a single sheet named `results`, a header row of column names, and
      rows beneath. `date` and `timestamp` are written as Excel date serials, not text; `decimal`
      and floats as numbers; booleans as booleans; NULL as an empty cell; text-kept types as text.
- [ ] **A cell is never a formula.** A string beginning with `=`, `+`, `-`, `@`, a tab or a carriage
      return is written as a string, asserted by reading the workbook back and finding no formula
      cell — the injection every spreadsheet export has to refuse. polars already passes
      `strings_to_formulas: False` to the workbook it creates, so the guard is the library's default
      and the plant is a caller-built `xlsxwriter.Workbook(path, {"strings_to_formulas": True})`
      handed in through `write_excel(workbook=…)`; the assertion reddens under it, and the verb is
      asserted never to pass a workbook of its own.
- [ ] A result with more than 1,048,575 data rows or more than 16,384 columns refuses with
      `excel_row_limit` or `excel_column_limit`, carrying the count, and writes nothing. The row
      count is known only after the read, so the refusal is a return value from the convert verb
      and the notification names the count and suggests Parquet.
- [ ] Precision is stated, not hidden: a `bigint` above 2^53 or a `decimal` with more than 15
      significant digits loses precision in Excel, and the notification for an `.xlsx` whose frame
      contains such a column says so in one sentence. The condition is computed from the frame.

### FR-005: The destination write, and the converter's budget

#### Description:

The write is where the race and the size both live.

#### Acceptance Criteria:

- [ ] The upload is conditional when `onConflict` is `refuse`: `If-None-Match: "*"` on the `PutObject`,
      and on `CompleteMultipartUpload` when the file exceeds the single-put size. A
      `PreconditionFailed` refuses with `destination_occupied` and the multipart is aborted; nothing
      is overwritten. With `overwrite` the condition is omitted. A test asserts the header is present
      in exactly the `refuse` case.
- [ ] `Content-Type` is `application/vnd.apache.parquet`, `application/x-ndjson` or
      `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`; no user metadata is
      written (the SQL, the execution id and the actor are not stamped onto the object).
- [ ] The execution role gains `s3:PutObject` and `s3:AbortMultipartUpload` on `{user_space_bucket}/*`
      and `{shared_space_bucket}/*`, still under SPEC-221 FR-003's Deny on the app-managed prefixes;
      the rendered policy is asserted to carry both.
- [ ] The convert function's `memory`, ephemeral storage (up to Lambda's 10 GB) and `timeout` (up
      to 15 minutes) are set in the module's `locals.tf`, and **one test** computes
      `RESULTS_MAX_BYTES` from them — for the streamed formats the largest CSV that fits on the disk
      beside its output, at the measured expansion ratio per format; for Excel the smaller of that
      and the frame the memory holds — and computes the machine's `TimeoutSeconds` from the same
      numbers as `validate + describe + convert timeout + notify + headroom`, with the derivation
      in the test's docstring. The throughput that sizes the timeout is **measured** on the image,
      not assumed. The constants in
      `rccommon` and `locals.tf` equal what the test computes, so a hand edit to one is a red test.
- [ ] Local storage is cleaned on every path, including refusal and fault, so a warm container does
      not carry a previous request's file into the next; a test runs two conversions on one
      container and asserts the second sees an empty scratch directory.

### FR-006: The notification and the outcome vocabulary

#### Description:

One producer, at the end of the machine, says what happened.

#### Acceptance Criteria:

- [ ] The `notify` verb sends exactly one success notification to the actor, through the shared
      sender in `cpcommon.notify`, saying the file name, the format and the row count, and carrying a
      `link` to the destination folder that `isSafeInAppPath` accepts, in the shape file-ops'
      notifier already builds: `/files?prefix=…` for a personal space and
      `/files?space={name}&prefix=…` for a shared one, every component URL-encoded — the prefix is
      the user's own text and encoding is what keeps it a path parameter rather than a route. The
      builder lives in `rccommon.links` and a test asserts a prefix carrying `&`, `?`, `#` and a
      space round-trips through the browser's parser to the same folder.
- [ ] The success message names the precision sentence of FR-004 when it applies, and nothing else
      about the data — no column name, no cell value.
- [ ] Every code the convert verb can return — `results_unreadable`, `unsupported_column_type`,
      `excel_row_limit`, `excel_column_limit`, `destination_occupied` — is registered in `rccommon`
      with wording that names the file and the format, and reaches the user through `NotifyFailure`
      as a return value routed by the machine's `Choice`, never as a raised error. The code
      enumeration test from SPEC-221 FR-006 is extended and stays a set equality.
- [ ] The plane starts zero Athena executions and reads the result object exactly once per
      request, asserted by counting calls in the convert verb's tests and by the absence of
      `athena:StartQueryExecution` in the rendered policy.

---

## Data Model

```py
# lambdas/results-conversion-common/rccommon/types.py
TEXT_KEPT: frozenset[str]                       # Athena types written as their rendered text
def polars_dtype(athena_type: str) -> pl.DataType   # raises UnsupportedColumnType

# lambdas/results-conversion-convert/convert.py — the verb's one return shape
{
  "outcome": "converted" | "refused",
  "reason": str | None,                    # a registered rccommon code when refused
  "rows": int, "bytes": int,
  "precisionNote": bool,                   # FR-004's sentence applies
  "destination": {...as emitted by validate-authorize}
}
```

## File & Folder Structure

```
lambdas/
├── results-conversion-common/rccommon/types.py, links.py
├── results-conversion-convert/  (convert.py, requirements.txt, fixtures/…)
└── results-conversion-notify/
infra/modules/results-conversion/locals.tf   (convert: memory, ephemeral_storage, timeout)
```

## Implementation Phases

### Phase 1: The type table and the typed read

- `rccommon.types`, the captured fixture, the NULL/empty distinction, the bounded file read.

### Phase 2: The three writers

- Parquet, NDJSON and Excel with their fences, the round-trip tests through table-builder's probes.

### Phase 3: The write, the budget and the machine

- The conditional upload, the write grant, the budget test that sizes `RESULTS_MAX_BYTES` and
  `TimeoutSeconds`, the `Convert` and `Notify` states replacing the placeholder, the `Choice` that
  routes a refused outcome.

### Phase 4: The notification

- `notify`, the link builder, the wording registry, the code enumeration.

### Phase 5: Verification

- A live conversion of a real execution in each format, read back: the Parquet through the table
  builder, the JSON through the table builder, the Excel opened and checked for formula cells; one
  `destination_occupied` produced by a race the test stages.

### Phase 6: Completion ritual

- Delivery doc, INDEX row, the plane page's *fences* section, CLAUDE.md's Tech Stack row.
