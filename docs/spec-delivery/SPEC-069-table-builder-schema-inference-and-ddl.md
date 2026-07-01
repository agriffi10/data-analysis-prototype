# Completed Spec — SPEC-069: Table Builder Schema Inference & DDL Generation (polars)

## What was completed?

`infer-schema` — real logic replacing the SPEC-066 stub: open the `inspect-source`
sample object with a polars LazyFrame, derive the data columns, fold in the user-declared
partition columns, and generate the `CREATE EXTERNAL TABLE IF NOT EXISTS` DDL (with
partition-projection `TBLPROPERTIES`). `execute-ddl` (running it) stays a stub (SPEC-070).
SPEC-066 already shipped the infer-schema role (S3 read) + polars layer, so the only infra
touch is CI.

- **`type_mapping.py`** (pure) — `map_dtype(polars_dtype) -> hive`; ints/floats/bool/
  string/`Date→date`/`Datetime→timestamp`/decimal, nested `array<…>`/`struct<…>`;
  unmappable ⇒ `UnmappableTypeError` (handler → terminal `unmappable_type`).
- **`ddl.py`** (pure) — `build_create_table_ddl(...)` + per-format storage clauses
  (Parquet `STORED AS PARQUET`; **CSV** OpenCSVSerde all-string + `skip.header.line.count`;
  **JSON** JsonSerDe) + `projection.*` `TBLPROPERTIES` (integer range/digits, date
  range/format/interval, string `enum` values). Backtick-quoted identifiers; a data column
  colliding with a partition key is dropped from the body (partition key wins).
- **`infer_schema.py`** (handler, on the polars + tbcommon layers) — scans the sample
  **directly from S3** (`scan_*('s3://…')`, object_store, **no `/tmp`**, nothing
  full-materialized — [[lambda-no-tmp-read-s3-directly]]): **Parquet** = footer-only via
  `scan_parquet().collect_schema()`; **CSV** = header-only (`infer_schema_length=0`),
  every column `string` (no inference); **JSON** = `scan_ndjson(n_rows=1000)` inference +
  date/datetime-looking **strings** typed `date`/`timestamp` (regex, since `scan_ndjson`
  has no date-parse option). A cheap `head_object` runs first so transient S3 ⇒ raised
  (SFN Retry); a polars scan error on an existing object ⇒ terminal
  `schema_inference_failed`.
- **CI** — `deploy-lambdas.yml` now attaches **both** layers to infer-schema (the attach
  step builds a layer array in one `update-function-configuration` call; the old
  per-flag calls overwrote each other). `ci.yml` installs polars so the type-mapping +
  handler tests run for real.

## What changed from earlier specs?

- The SPEC-066 `infer-schema` **stub** became real; role + polars layer unchanged.
- `deploy-lambdas.yml`: infer-schema gains `tbcommon: true` (needs the `tbcommon` package
  too) and the layer-attach step supports **multiple** layers.
- `ci.yml` lambdas job installs `lambdas/table-builder-infer-schema/requirements.txt`
  (polars) so SPEC-069 tests execute in CI.

## Post-merge amendment (direct-S3 read)

The initial merge downloaded the sample object to `/tmp` before scanning. Per the
standing rule [[lambda-no-tmp-read-s3-directly]] (Lambdas must stream from S3, never use
`/tmp`), `infer-schema` now scans directly from `s3://…` — polars' object_store fetches
only the byte ranges each reader needs (parquet footer / CSV header / bounded JSON rows)
using the Lambda role's env credentials. Verified against **real S3**: `scan_parquet`,
`scan_csv(infer_schema_length=0)`, and `scan_ndjson(n_rows=…)` all read correctly with no
`storage_options`, no `/tmp`, no `fsspec`.

## Verification

**17** unit tests — `map_dtype` (6: all supported + nested + `Date`/`Datetime` + a
representative unmappable), `build_create_table_ddl` golden strings (5: flat-Parquet,
partitioned-CSV all-string + integer projection, partitioned-JSON date projection, string
`enum`, collision-drop), handler (6: Parquet native / CSV all-string / JSON date-parse /
DDL carried, scan-error terminal, transient-S3 raised). Full `pytest lambdas/` = **153
passed**; `ruff check lambdas/` clean. Local polars 1.42.1 (CI pins 1.12.0); dtype API
usage is version-stable.
