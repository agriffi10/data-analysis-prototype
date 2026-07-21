# Spec: Table Share — Source Resolution & Copy Plan (inspect-source)

**ID:** SPEC-090
**Status:** Completed
**Last Updated:** 2026-07-04
**Depends On:** SPEC-089 (validated request + actor), SPEC-068 (`tbcommon.s3_listing` precedent), SPEC-032 (LF-registered buckets)

> **Read `docs/table-share-architecture.md` §4 first.**

> **Corrected 2026-07-21 (PR #256):** the object list no longer rides on the Step Functions
> state. `inspect-source` writes it to `{admin_bucket}/table-share/{hash}/copy-plan.json`
> and emits `copyPlanKey` + `objectCount`; `copy-objects` loads it. Inline, the Map's
> output state reached **101%** of the 256 KB payload limit at the caps (the Map's
> `ItemSelector` copies the whole state into every item) — `States.DataLimitExceeded`
> on the Map, destroying every per-recipient outcome. By pointer it is ~34%.
> `tableDefinition` still rides inline and is now capped by `SHARE_MAX_DEFINITION_BYTES`.

## Overview

Implement **inspect-source**: given the validated request, `GetTable` the source, confirm it is a **shape we can share** (a base external table, flat or partition-projection-based), **clone its table definition**, list the source data objects, enforce copy caps, and emit a **copy plan** the recipient `Map` will execute. This is where the source's real Glue definition (columns, SerDe, format, partition keys, projection `TBLPROPERTIES`) is captured verbatim so the recipient table is an exact clone with only the `LOCATION` repointed.

## Scope

### In Scope

- Glue `GetTable(source.database, source.table)` and **rejection** (whole-request terminal failure, clear reason) when the source is:
  - a **view** (no `LOCATION` / `TableType` VIRTUAL_VIEW),
  - a **non-external / managed** table,
  - **catalog-partitioned** (partition keys present but **no** `projection.enabled=true`/`projection.*` props),
  - a table whose `LOCATION` can't be resolved to a single, listable prefix inside a known bucket.
- **Clone** the source definition into a portable structure: `columns`, `partitionKeys`, `serde/inputFormat/outputFormat`, `tableType`, and the `TBLPROPERTIES` to carry (incl. `projection.*`, `storage.location.template`, serde params) — everything except `LOCATION`, catalog/DB identity, and stat/owner metadata.
- **List** the source objects under the resolved `LOCATION` (`tscommon.s3_listing`), computing the object count + total bytes and preserving each object's **key relative to the source prefix** (for layout-preserving copy).
- **Enforce caps**: `SHARE_MAX_OBJECTS` and `SHARE_MAX_TOTAL_BYTES` (named constants); exceeding either is a whole-request terminal failure with a "too large for v1 — S3 Batch Ops deferred" reason.
- Emit `{ tableDefinition, location:{bucket,prefix}, objects:[{relKey,size}], partitioned:boolean }` for the `Map`.
- Wire as the SFN state after `validate` (before the recipient `Map`).

### Out of Scope

- Copying data / creating tables / per-recipient work — SPEC-091/092.
- Copying **catalog partition metadata** (`GetPartitions`) — deferred (v1 rejects catalog-partitioned sources).
- Re-inferring schema (polars) — explicitly **not** done; we clone (§4 decision).
- Notifications — SPEC-094.

---

## Functional Requirements

### FR-001: Source fetch + shape validation

#### Acceptance Criteria:

- [ ] A flat base external table passes; a projection-partitioned base external table passes.
- [ ] A **view** is rejected with "views can't be shared (no data files)".
- [ ] A **catalog-partitioned** source (partition keys, no projection props) is rejected with a reason pointing at partition projection as the supported shape.
- [ ] A non-external/managed table, or an unresolvable `LOCATION`, is rejected with a clear reason.
- [ ] All rejections are **whole-request** terminal failures (no recipient runs).

### FR-002: Definition clone

#### Acceptance Criteria:

- [ ] The emitted `tableDefinition` reproduces the source's columns (name+type+comment), partition keys, SerDe/InputFormat/OutputFormat, `TableType`, and carried `TBLPROPERTIES` (including all `projection.*` and `storage.location.template` when present).
- [ ] `LOCATION`, database/catalog identity, and source-only metadata (owner, stats, `CreateTime`) are **excluded** from the clone (the recipient step sets its own LOCATION/DB).
- [ ] A projection-partitioned source carries its projection props so the recipient table needs no `MSCK`.

### FR-003: Object listing + caps

#### Acceptance Criteria:

- [ ] Listing yields every data object under the source prefix with its **relative** key and size; the marker/DDL-noise objects (e.g. `_$folder$`, zero-byte prefix markers) are excluded from the copy set as appropriate.
- [ ] Object count > `SHARE_MAX_OBJECTS` or total bytes > `SHARE_MAX_TOTAL_BYTES` is a whole-request terminal failure with the documented "too large" reason.
- [ ] An empty source prefix (no data objects) is a whole-request terminal failure ("source has no data to share").

---

## Data Model

```python
# emitted by inspect-source (input to the recipient Map)
{
  "tableDefinition": { "columns":[...], "partitionKeys":[...],
                       "serde": {...}, "inputFormat": "...", "outputFormat": "...",
                       "tableType": "EXTERNAL_TABLE", "tableProperties": {...} },  # projection.* etc.
  "location": { "bucket": "...", "prefix": "..." },
  "objects": [ { "relKey": "year=2025/part-0.parquet", "size": 12345 }, ... ],
  "partitioned": true
}
```

```python
# lambdas/table-share/common/tscommon
#   glue.py     get_table + clone_definition(table) -> tableDefinition (LOCATION stripped)
#   s3_listing.py  list_objects(bucket, prefix) -> [{relKey,size}]  (reuse tbcommon pattern)
#   config.py   SHARE_MAX_OBJECTS, SHARE_MAX_TOTAL_BYTES
```

## Implementation Phases

### Phase 1: Fetch + shape validation + clone

- `GetTable`; reject view/managed/catalog-partitioned/unresolvable; `clone_definition`.

### Phase 2: Listing + caps + emit

- List objects (relative keys + sizes), enforce caps, emit the copy plan; wire the SFN state.

### Phase 3: Completion ritual

- Delivery doc, INDEX status, component-inventory rows (`tscommon.glue.clone_definition`, cap constants).
