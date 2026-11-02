---
type: Spec
id: SPEC-069
title: "Table Builder — Schema Inference & DDL Generation (polars)"
description: "Infers a table's columns from a sample file with polars lazy scanners and generates the Athena CREATE EXTERNAL TABLE DDL, with date parsing, all-string CSV columns and partition keys split out."
spec_status: Completed
depends_on: [SPEC-066, SPEC-068, SPEC-067]
arc: table-builder
arc_order: 4
---

**Dependency notes:** SPEC-066 (polars Lambda layer + the infer-schema function/role), SPEC-068 (inspect-source output: format, partition keys, sample object, location), SPEC-067 (validated request)
> **Reference:** `docs/table-builder-architecture.md` §4/§5. Fourth of the arc. Implements **`infer-schema`** —
> the Lambda that opens a sample data object with a **polars LazyFrame**, derives the **data** column schema,
> maps polars dtypes to Glue/Athena (Hive) types, folds in the **user-declared partition columns** (with their
> declared types), and **generates the `CREATE EXTERNAL TABLE` DDL incl. partition-projection `TBLPROPERTIES`**.
> `execute-ddl` (running it) is **SPEC-070**. Uses the SPEC-066 polars layer; follows
> `lambdas/info/best-practices/lambdas/lambdas.md` (thin handler, pure mapping logic).
>
> **Partitions = projection, keys user-declared (decided 2026-06-30).** Partition columns + their types come from
> the request's `partitionKeys` (SPEC-067), **not** the path; the DDL carries `projection.*` properties so the
> table is queryable with **no `MSCK REPAIR`** (SPEC-070).

## Overview

Turn the inspected source into a concrete table definition. `infer-schema` takes the `inspect-source` payload
(format, partition keys, a representative `sampleObjectKey`, and the table `location`), opens the sample object
with the matching **polars lazy scanner** (`scan_parquet` / `scan_csv` / `scan_ndjson`) — lazy so only the schema
(and a bounded sample for JSON type inference) is materialized, not the whole file — and collects the column
names + types. It maps each polars dtype to the corresponding **Glue/Athena Hive type**, lists the Hive
**partition keys** as `PARTITIONED BY` columns (kept **out** of the main column list, as Athena requires), and
assembles a `CREATE EXTERNAL TABLE IF NOT EXISTS` statement with the right `STORED AS` / `ROW FORMAT` / SerDe for
the format and the `LOCATION`. The generated DDL string + the resolved column list are emitted for `execute-ddl`.
The dtype→Hive mapping and DDL assembly are **pure functions**, unit-tested without AWS or a Lambda runtime.

**Two type-inference rules (decided 2026-06-30):**
1. **Inference tries to parse dates.** For the inferred formats, date/timestamp-looking values are typed as
   `date`/`timestamp`, **not** `string` — Parquet carries real date/timestamp types natively; JSON inference
   enables date parsing (string values matching a date/datetime are detected and typed `date`/`timestamp`).
2. **CSV is NOT type-inferred at all.** A CSV's data columns are **all `string`** (column **names** come from the
   header row); no per-column type guessing. This uses **OpenCSVSerde** (the all-string CSV serde) and **reverses**
   the earlier "LazySimpleSerDe to preserve inferred CSV types" sub-decision. (Parquet/JSON still infer + date-parse.)

## Scope

### In Scope

- **`infer-schema` Lambda** (on the polars layer) — download/scan the `sampleObjectKey` and build a polars
  **LazyFrame** for the format; collect the schema (column order + types):
  - **Parquet:** read the embedded schema (typed natively, incl. real `date`/`timestamp`).
  - **JSON/NDJSON:** infer from a bounded sample **with date parsing on** (date/datetime-looking strings →
    `date`/`timestamp`); nested objects/arrays map to Hive `struct<…>`/`array<…>`.
  - **CSV:** assume a **header row** + comma delimiter (v1 default, `table-builder-architecture.md` §10); take the
    column **names from the header** and type **every data column `string`** — **no type inference** (decided
    2026-06-30). (Read just enough to get the header — e.g. `scan_csv(infer_schema_length=0)` / read 1 row — then
    cast all to `Utf8`.)
- **polars-dtype → Hive-type mapping** (pure) — a single mapping table: e.g. `Int64→bigint`, `Int32→int`,
  `Float64→double`, `Float32→float`, `Boolean→boolean`, `Utf8/String→string`, `Date→date`,
  `Datetime→timestamp`, `Decimal→decimal(p,s)`, `List(T)→array<hive(T)>`, `Struct→struct<field:hive(T),…>`;
  unknown/unsupported dtype ⇒ terminal `unmappable_type` (named column + dtype).
- **Partition columns** — the request's **user-declared** `partitionKeys` (SPEC-067, carried by SPEC-068) become
  `PARTITIONED BY (\`k\` {hiveType}, …)` using each key's **declared type** (`integer→int`, `date→date`,
  `string→string`) and are **excluded** from the table's regular column list (Athena rejects a column appearing
  in both). Keys are **not** re-derived from the path.
- **Partition projection `TBLPROPERTIES`** (pure) — for each partition key emit the Athena projection config from
  its declared type + range: `projection.enabled=true`; integer → `projection.{k}.type=integer` +
  `projection.{k}.range='{min},{max}'` (+ `projection.{k}.digits` when given); date →
  `projection.{k}.type=date` + `range` + `format` (+ `interval`/`interval.unit` when given); string →
  `projection.{k}.type=enum` + `projection.{k}.values='a,b,…'`. Hive `key=value/` layout ⇒ the default projection
  storage location is correct (no `storage.location.template` in v1). No `MSCK REPAIR` (SPEC-070).
- **DDL generation** (pure) — assemble `CREATE EXTERNAL TABLE IF NOT EXISTS \`{database}\`.\`{tableName}\` (cols…)
  [PARTITIONED BY (…)] STORED AS PARQUET | ROW FORMAT … (CSV/JSON SerDe) LOCATION '{location}'
  TBLPROPERTIES(<format props> + <projection props>)`; identifiers safely quoted; the DDL is emitted as a string
  (run by SPEC-070).
- **Format storage clauses** — Parquet → `STORED AS PARQUET`; CSV → `ROW FORMAT SERDE
  'org.apache.hadoop.hive.serde2.OpenCSVSerde'` with `skip.header.line.count=1` (the **all-string** CSV serde —
  matches the "CSV not type-inferred" rule, all columns `string`; reverses the earlier LazySimpleSerDe choice);
  JSON/NDJSON → `ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'`. Recorded as constants/templates so the
  mapping is one source of truth.
- **infer-schema role** — `s3:GetObject` on both data buckets' data prefixes (read the sample) + `logs`; the
  polars layer attached (SPEC-066). No write. `simulate-custom-policy`-verified.
- **SFN wiring** — `inspect-source → infer-schema → (stub) execute-ddl`; `Retry` transient, shared `Catch` →
  recorded-failure for `unmappable_type` / scan errors.

### Out of Scope

- **Running the DDL** / Athena — **SPEC-070** (this spec emits the DDL string + columns). There is **no**
  partition-load step (projection replaces `MSCK REPAIR`).
- **Reconciling schema drift across files** — v1 infers from the **one** sample object (SPEC-068 chose it);
  multi-file reconciliation is a documented future enhancement.
- **Inferring partition key types** — not done; types are **user-declared** in the request (SPEC-067). This spec
  maps the declared type → Hive type + projection config.
- **Non-default CSV options** (alt delimiter, no header) — deferred (`table-builder-architecture.md` §10); v1
  assumes header + comma.
- **`storage.location.template` / non-Hive partition paths** — out of v1 (Hive `key=value/` uses the default).
- **Notifications** — SPEC-072.

---

## Functional Requirements

### FR-001: Lazy scan + schema collection

#### Acceptance Criteria:

- [ ] For `format='parquet'` the Lambda builds a polars `scan_parquet` LazyFrame and reads the **schema** without
  materializing the full dataset (native types, incl. `date`/`timestamp`); for `json` a `scan_ndjson` with bounded
  inference **and date parsing on** (date/datetime strings → `date`/`timestamp`); for `csv` it reads only the
  **header** for column names and types **every column `string`** — **no type inference** — returning an
  **ordered** list of `(columnName, type)`.
- [ ] A scan error (corrupt/empty/not-actually-that-format object) is a terminal failure `schema_inference_failed`
  with a readable reason; a transient S3 error is **raised** for the SFN `Retry` (`lambdas.md` §4).
- [ ] The sample object is read from `/tmp` or streamed; nothing is written outside `/tmp` (`lambdas.md` §12).

### FR-002: polars→Hive type mapping (pure)

#### Acceptance Criteria:

- [ ] A pure `map_dtype(polars_dtype) -> str` covers the documented set (ints/floats/bool/string/date/datetime/
  decimal/list/struct, nested recursively); an unmappable dtype raises a typed error carrying the column name +
  dtype → terminal `unmappable_type`.
- [ ] The mapping is unit-tested directly (no AWS/Lambda runtime) for every supported dtype incl. nested
  `array<…>` and `struct<…>`, and incl. `Date→date` / `Datetime→timestamp` (the date-parsing rule).
- [ ] **CSV bypasses `map_dtype`** entirely — its columns are emitted as `string` directly (no inference), so the
  mapper is only exercised for Parquet/JSON.

### FR-003: Partition columns + projection

#### Acceptance Criteria:

- [ ] The request's **user-declared** `partitionKeys` are rendered as `PARTITIONED BY (\`k\` {hiveType}, …)` in
  declared order using each key's **declared type** (`integer→int`, `date→date`, `string→string`) and are
  **omitted** from the regular column list (no duplication); a flat source (empty keys) produces no
  `PARTITIONED BY` clause and no projection properties.
- [ ] Each partition key contributes the correct **projection `TBLPROPERTIES`** for its type (integer range/digits;
  date range/format/interval; string enum values) plus `projection.enabled=true`; the values come from the
  request, not from listing S3.
- [ ] If an inferred data column name **collides** with a partition key, the partition key wins and the data
  column is dropped from the body (documented), so the DDL is valid.

### FR-004: DDL generation (pure)

#### Acceptance Criteria:

- [ ] A pure `build_create_table_ddl(database, tableName, columns, partitionKeys, format, location) -> str`
  produces a valid `CREATE EXTERNAL TABLE IF NOT EXISTS` with: backtick-quoted DB/table/column identifiers, the
  format's `STORED AS`/`ROW FORMAT`/SerDe + properties (CSV → **OpenCSVSerde**, all columns `string`,
  `skip.header.line.count=1`; JSON → JsonSerDe; Parquet → `STORED AS PARQUET`), the `PARTITIONED BY` clause (with
  declared types) when applicable, `LOCATION '{location}'`, and — when partitioned — the **partition-projection**
  `TBLPROPERTIES` (`projection.enabled` + per-key type/range/values) merged with the format properties
  (`partitionKeys` carry the projection config).
- [ ] `IF NOT EXISTS` is always present (replay-safe alongside SPEC-068's check + SPEC-070's run); the DDL targets
  `{database}.{tableName}` from the validated request.
- [ ] The function is unit-tested for flat Parquet, **partitioned CSV with integer projection** (header skip +
  `projection.*`), partitioned JSON, and a **string `enum`** partition key, asserting the exact generated DDL
  (golden strings).

### FR-005: Output payload + role + SFN wiring

#### Acceptance Criteria:

- [ ] On success the Lambda emits `{ ...request, ddl, columns:[{name,type}], partitionKeys }` (the DDL string +
  resolved schema) for `execute-ddl`; payload stays small (the DDL string, not file data) (`lambdas.md` §10).
- [ ] The `infer-schema` role grants `s3:GetObject` on both data buckets' data prefixes + `logs` (no write), with
  the polars layer attached; `simulate-custom-policy`-verified.
- [ ] The state machine runs `inspect-source → infer-schema → (stub) execute-ddl` with `Retry` + the shared
  `Catch`; deploy-role IAM updated; `tofu validate`/`plan` clean.

### FR-006: Tests + e2e

#### Acceptance Criteria:

- [ ] Python unit tests: `map_dtype` for all supported (and a representative unmappable) dtypes incl. nested **and
  `Date→date`/`Datetime→timestamp`**; `build_create_table_ddl` golden strings for flat-Parquet, **partitioned-CSV
  (all-string columns + OpenCSVSerde)**, JSON, and a **string `enum`** partition key (asserting the `projection.*`
  `TBLPROPERTIES`); the handler asserts (a) a **CSV** fixture yields **all-`string`** columns from the header with
  **no** type inference, (b) a **JSON** fixture with a date/datetime field yields a `date`/`timestamp` column
  (date parsing), (c) a **Parquet** fixture preserves native types; scan error → `schema_inference_failed`;
  transient S3 → raised.
- [ ] `docs/testing/e2e.md`: a flat-Parquet and a partitioned-CSV (projection) request flow through
  `inspect → infer` and the generated DDL is captured (and visibly correct, incl. projection properties) before
  the stub `execute-ddl`.

---

## Data Model

```python
# infer-schema output (passed to execute-ddl)
{
  "actor": "alice",
  "space": {"kind": "personal", "bucket": "dat-prod-user-space", "prefix": "alice/sales/2026/", "database": "alice"},
  "tableName": "sales_2026",
  "location": "s3://dat-prod-user-space/alice/sales/2026/",
  "format": "csv",
  "partitionKeys": [
    {"name": "year",  "type": "integer", "range": [2000, 2100], "digits": 4},
    {"name": "month", "type": "integer", "range": [1, 12],      "digits": 2}
  ],
  # CSV → ALL columns string (no type inference); names from the header row.
  "columns": [{"name": "order_id", "type": "string"}, {"name": "amount", "type": "string"}, {"name": "ts", "type": "string"}],
  "ddl": "CREATE EXTERNAL TABLE IF NOT EXISTS `alice`.`sales_2026` (`order_id` string, `amount` string, `ts` string) PARTITIONED BY (`year` int, `month` int) ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde' WITH SERDEPROPERTIES ('separatorChar'=',', 'quoteChar'='\"', 'escapeChar'='\\\\') STORED AS TEXTFILE LOCATION 's3://dat-prod-user-space/alice/sales/2026/' TBLPROPERTIES ('skip.header.line.count'='1', 'projection.enabled'='true', 'projection.year.type'='integer', 'projection.year.range'='2000,2100', 'projection.year.digits'='4', 'projection.month.type'='integer', 'projection.month.range'='1,12', 'projection.month.digits'='2')",
  "requestId": "f3a1…"
}
# For Parquet/JSON the SAME folder would infer typed columns WITH date parsing, e.g.
#   columns: [{"name":"order_id","type":"bigint"}, {"name":"amount","type":"double"}, {"name":"ts","type":"timestamp"}]
#   Parquet → STORED AS PARQUET; JSON → ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'.

# terminal reasons: schema_inference_failed | unmappable_type
```

## File & Folder Structure

```
lambdas/table-builder-infer-schema/
├── infer_schema.py          # handler: scan sample (polars Lazy) → columns; delegate to pure mappers
├── type_mapping.py          # pure map_dtype(polars_dtype) -> hive type (incl. nested)
├── ddl.py                   # pure build_create_table_ddl(...) + per-format storage clauses/SerDe constants
├── test_type_mapping.py     # NEW
├── test_ddl.py              # NEW (golden DDL strings)
└── test_infer_schema.py     # NEW (handler with stubbed S3 + fixtures)

infra/modules/table-builder/
├── policies/infer-schema.tftpl     # S3 GetObject on data buckets + logs (FR-005)
├── lambda.tf                       # infer-schema attaches the polars layer (SPEC-066)
└── state-machine.asl.json.tftpl    # + infer-schema Task (FR-005)

docs/testing/e2e.md   # infer flow + captured DDL (FR-006)
```

## Implementation Phases

### Phase 1: Pure mapping + DDL generation

- `type_mapping.map_dtype` (incl. nested) + `ddl.build_create_table_ddl` with per-format storage clauses; full
  unit coverage incl. golden DDL strings (FR-002, FR-003, FR-004, FR-006 partial).

### Phase 2: Lazy scan handler + wiring

- `infer_schema` handler: polars lazy scan per format → ordered columns → pure mappers → payload; role policy +
  layer attach; SFN Task + Catch; handler tests + e2e doc (FR-001, FR-005, FR-006).
