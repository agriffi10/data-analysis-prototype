# Spec: Table Builder — Schema Inference & DDL Generation (polars)

**ID:** SPEC-069
**Status:** Draft
**Last Updated:** 2026-06-27
**Depends On:** SPEC-066 (polars Lambda layer + the infer-schema function/role), SPEC-068 (inspect-source output: format, partition keys, sample object, location), SPEC-067 (validated request)

> **Reference:** `docs/table-builder-architecture.md` §4. Fourth of the arc. Implements **`infer-schema`** — the
> Lambda that opens a sample data object with a **polars LazyFrame**, derives the column schema, maps polars
> dtypes to Glue/Athena (Hive) types, folds in the Hive **partition columns**, and **generates the
> `CREATE EXTERNAL TABLE` DDL**. `execute-ddl` (running it) is **SPEC-070**. Uses the SPEC-066 polars layer;
> follows `docs/best-practices/lambdas/lambdas.md` (thin handler, pure mapping logic).

## Overview

Turn the inspected source into a concrete table definition. `infer-schema` takes the `inspect-source` payload
(format, partition keys, a representative `sampleObjectKey`, and the table `location`), opens the sample object
with the matching **polars lazy scanner** (`scan_parquet` / `scan_csv` / `scan_ndjson`) — lazy so only the schema
(and a bounded sample for CSV/JSON type inference) is materialized, not the whole file — and collects the column
names + polars dtypes. It maps each polars dtype to the corresponding **Glue/Athena Hive type**, lists the Hive
**partition keys** as `PARTITIONED BY` columns (kept **out** of the main column list, as Athena requires), and
assembles a `CREATE EXTERNAL TABLE IF NOT EXISTS` statement with the right `STORED AS` / `ROW FORMAT` / SerDe for
the format and the `LOCATION`. The generated DDL string + the resolved column list are emitted for `execute-ddl`.
The dtype→Hive mapping and DDL assembly are **pure functions**, unit-tested without AWS or a Lambda runtime.

## Scope

### In Scope

- **`infer-schema` Lambda** (on the polars layer) — download/scan the `sampleObjectKey` and build a polars
  **LazyFrame** for the format; collect the schema (column order + dtypes). For CSV: assume a **header row** +
  comma delimiter (v1 default, `table-builder-architecture.md` §10), infer dtypes from a bounded sample. For
  JSON/NDJSON: infer from a bounded sample; nested objects/arrays map to Hive `struct<…>`/`array<…>`.
- **polars-dtype → Hive-type mapping** (pure) — a single mapping table: e.g. `Int64→bigint`, `Int32→int`,
  `Float64→double`, `Float32→float`, `Boolean→boolean`, `Utf8/String→string`, `Date→date`,
  `Datetime→timestamp`, `Decimal→decimal(p,s)`, `List(T)→array<hive(T)>`, `Struct→struct<field:hive(T),…>`;
  unknown/unsupported dtype ⇒ terminal `unmappable_type` (named column + dtype).
- **Partition columns** — `partitionKeys` (SPEC-068) become `PARTITIONED BY (k string, …)` (typed `string` in v1)
  and are **excluded** from the table's regular column list (Athena rejects a column appearing in both).
- **DDL generation** (pure) — assemble `CREATE EXTERNAL TABLE IF NOT EXISTS \`{database}\`.\`{tableName}\` (cols…)
  [PARTITIONED BY (…)] STORED AS PARQUET | ROW FORMAT … (CSV/JSON SerDe) LOCATION '{location}'
  TBLPROPERTIES(…)`; identifiers safely quoted; the DDL is emitted as a string (run by SPEC-070).
- **Format storage clauses** — Parquet → `STORED AS PARQUET`; CSV → `ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'`
  with `skip.header.line.count=1` (decided: **`LazySimpleSerDe`** so polars-inferred numeric/date types survive
  into Athena, rather than OpenCSVSerde's all-string columns); JSON/NDJSON → `ROW FORMAT SERDE
  'org.openx.data.jsonserde.JsonSerDe'`. Recorded as constants/templates so the mapping is one source of truth.
- **infer-schema role** — `s3:GetObject` on both data buckets' data prefixes (read the sample) + `logs`; the
  polars layer attached (SPEC-066). No write. `simulate-custom-policy`-verified.
- **SFN wiring** — `inspect-source → infer-schema → (stub) execute-ddl`; `Retry` transient, shared `Catch` →
  recorded-failure for `unmappable_type` / scan errors.

### Out of Scope

- **Running the DDL** / loading partitions / Athena — **SPEC-070** (this spec emits the DDL string + columns).
- **Reconciling schema drift across files** — v1 infers from the **one** sample object (SPEC-068 chose it);
  multi-file reconciliation is a documented future enhancement.
- **Non-default CSV options** (alt delimiter, no header) and **typed partition values** — deferred
  (`table-builder-architecture.md` §10); partitions are `string` in v1.
- **Notifications** — SPEC-072.

---

## Functional Requirements

### FR-001: Lazy scan + schema collection

#### Acceptance Criteria:

- [ ] For `format='parquet'` the Lambda builds a polars `scan_parquet` LazyFrame and reads the **schema** without
  materializing the full dataset; for `csv` a `scan_csv` (header=true, comma) with bounded inference; for `json`
  a `scan_ndjson` with bounded inference — returning an **ordered** list of `(columnName, polarsDtype)`.
- [ ] A scan error (corrupt/empty/not-actually-that-format object) is a terminal failure `schema_inference_failed`
  with a readable reason; a transient S3 error is **raised** for the SFN `Retry` (`lambdas.md` §4).
- [ ] The sample object is read from `/tmp` or streamed; nothing is written outside `/tmp` (`lambdas.md` §12).

### FR-002: polars→Hive type mapping (pure)

#### Acceptance Criteria:

- [ ] A pure `map_dtype(polars_dtype) -> str` covers the documented set (ints/floats/bool/string/date/datetime/
  decimal/list/struct, nested recursively); an unmappable dtype raises a typed error carrying the column name +
  dtype → terminal `unmappable_type`.
- [ ] The mapping is unit-tested directly (no AWS/Lambda runtime) for every supported dtype incl. nested
  `array<…>` and `struct<…>`.

### FR-003: Partition columns

#### Acceptance Criteria:

- [ ] `partitionKeys` are rendered as `PARTITIONED BY (\`k\` string, …)` in declared order and are **omitted**
  from the regular column list (no duplication); a flat source (`partitioned=false`, empty keys) produces no
  `PARTITIONED BY` clause.
- [ ] If an inferred data column name **collides** with a partition key, the partition key wins and the data
  column is dropped from the body (documented), so the DDL is valid.

### FR-004: DDL generation (pure)

#### Acceptance Criteria:

- [ ] A pure `build_create_table_ddl(database, tableName, columns, partitionKeys, format, location) -> str`
  produces a valid `CREATE EXTERNAL TABLE IF NOT EXISTS` with: backtick-quoted DB/table/column identifiers, the
  format's `STORED AS`/`ROW FORMAT`/SerDe + properties (CSV `skip.header.line.count=1`; JSON JsonSerDe), the
  `PARTITIONED BY` clause when applicable, and `LOCATION '{location}'`.
- [ ] `IF NOT EXISTS` is always present (replay-safe alongside SPEC-068's check + SPEC-070's run); the DDL targets
  `{database}.{tableName}` from the validated request.
- [ ] The function is unit-tested for flat Parquet, partitioned CSV (header skip), and JSON, asserting the exact
  generated DDL (golden strings).

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

- [ ] Python unit tests: `map_dtype` for all supported (and a representative unmappable) dtypes incl. nested;
  `build_create_table_ddl` golden strings for flat-Parquet, partitioned-CSV, JSON; the handler with a stubbed S3 +
  a small fixture object yields the expected columns + DDL; scan error → `schema_inference_failed`; transient S3
  → raised.
- [ ] `docs/testing/table-builder-e2e.md`: a flat-Parquet and a partitioned-CSV request flow through
  `inspect → infer` and the generated DDL is captured (and visibly correct) before the stub `execute-ddl`.

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
  "partitionKeys": ["year", "month"],
  "columns": [{"name": "order_id", "type": "bigint"}, {"name": "amount", "type": "double"}, {"name": "ts", "type": "timestamp"}],
  "ddl": "CREATE EXTERNAL TABLE IF NOT EXISTS `alice`.`sales_2026` (`order_id` bigint, `amount` double, `ts` timestamp) PARTITIONED BY (`year` string, `month` string) ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.LazySimpleSerDe' WITH SERDEPROPERTIES ('field.delim'=',') STORED AS TEXTFILE LOCATION 's3://dat-prod-user-space/alice/sales/2026/' TBLPROPERTIES ('skip.header.line.count'='1')",
  "requestId": "f3a1…"
}

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

docs/testing/table-builder-e2e.md   # infer flow + captured DDL (FR-006)
```

## Implementation Phases

### Phase 1: Pure mapping + DDL generation

- `type_mapping.map_dtype` (incl. nested) + `ddl.build_create_table_ddl` with per-format storage clauses; full
  unit coverage incl. golden DDL strings (FR-002, FR-003, FR-004, FR-006 partial).

### Phase 2: Lazy scan handler + wiring

- `infer_schema` handler: polars lazy scan per format → ordered columns → pure mappers → payload; role policy +
  layer attach; SFN Task + Catch; handler tests + e2e doc (FR-001, FR-005, FR-006).
