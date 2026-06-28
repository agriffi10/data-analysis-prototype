# Spec: Table Builder — Name Uniqueness + Source Inspection & Format Validation

**ID:** SPEC-068
**Status:** Draft
**Last Updated:** 2026-06-27
**Depends On:** SPEC-066 (control plane + Lambda stubs/roles), SPEC-067 (validated request payload + the validate→check handoff shape), SPEC-034 (Glue services / catalog model)

> **Reference:** `docs/table-builder-architecture.md` §4. Third of the arc. Implements the two **gathering /
> validation** Lambdas that run after `validate-authorize`: **`check-table-absent`** (the requested table must not
> already exist in the target DB) and **`inspect-source`** (is the folder flat data files or Hive-partitioned;
> is it a single supported, consistent format). They emit the facts `infer-schema` (SPEC-069) needs. `infer-schema`
> + `execute-ddl` stay stubs. Lambdas follow `docs/best-practices/lambdas/lambdas.md`.

## Overview

Before inferring schema or running DDL, the pipeline must confirm two things from the validated request. First,
**`check-table-absent`** asks Glue whether `tableName` already exists in the target database — if it does, the
request fails terminally with a clear reason (no accidental clobber; collisions are surfaced, since table
versioning isn't a thing here). Second, **`inspect-source`** lists the request's prefix and determines the
**physical layout** — a set of **flat** data files directly under the prefix, or **Hive-style partitions**
(subdirectories named `key=value/`) — and validates that the data is a **single, consistent, supported format**
(Parquet, CSV, or JSON/NDJSON). It returns the format, the partition keys (if any), a representative **sample
object key**, and the table **location**, which together drive schema inference and DDL generation downstream.
Anything ambiguous or unsupported (mixed formats, no data files, an unrecognized extension) is a terminal failure
with a specific, user-readable reason.

## Scope

### In Scope

- **`check-table-absent` Lambda** — Glue `GetTable(database=space.database, name=tableName)`; **not found** ⇒
  proceed; **found** ⇒ terminal failure `table_exists`. Idempotency-friendly (this is the duplicate-name guard
  alongside `CREATE … IF NOT EXISTS` in SPEC-070). Its role gets Glue `GetTable`/`GetDatabase` on the catalog +
  `logs` only.
- **`inspect-source` Lambda** — list `space.prefix` (paginated) in `space.bucket`; classify layout + format:
  - **Layout:** **flat** (data objects directly under the prefix) vs **Hive-partitioned** (immediate children are
    `key=value/` directories; capture the ordered **partition keys** from the first data object's path). A prefix
    that mixes top-level data files **and** `key=value/` dirs, or has inconsistent partition depth, is terminal
    `ambiguous_layout`.
  - **Format:** infer from object extensions (`.parquet`, `.csv`, `.json`/`.ndjson`/`.jsonl`); the folder must be
    a **single** supported format across its data objects (ignoring the prefix marker `DO_NOT_DELETE.txt` and
    `athenaresults/` and zero-byte/`_`-prefixed/`.`-prefixed files). Mixed formats ⇒ terminal `mixed_formats`;
    none recognized ⇒ terminal `no_data_files`; unsupported only (e.g. `.orc`) ⇒ terminal `unsupported_format`.
  - Emit `{ format, partitioned, partitionKeys[], sampleObjectKey, location, fileCount }` for `infer-schema`.
  Its role gets `s3:ListBucket` + `s3:GetObject` (head/list; a small range get is fine) on **both** data buckets,
  scoped to the data prefixes, + `logs`.
- **Wire both as SFN states** — `validate → check-table-absent → inspect-source → (stub infer-schema)`, each a
  Task with `Retry` (transient) and the shared `Catch` → recorded-failure (terminal reasons) from SPEC-066/067.
- **Deploy-role IAM** finalized for these two roles (Glue read; S3 list/get on the data buckets).

### Out of Scope

- **Reading file contents to infer column types** — `inspect-source` only classifies layout/format and picks a
  **sample object key**; opening it with polars is **SPEC-069**.
- **DDL generation / execution** — SPEC-069/070.
- **Notifications** for these failure reasons — SPEC-072 (recorded in the SFN execution here).
- **Non-Hive partition schemes** (directory-position partitions without `key=value`) — terminal `ambiguous_layout`
  in v1 (documented), not silently guessed.
- **Per-request CSV options** (delimiter/header) — assumed defaults, validated/applied in SPEC-069.

---

## Functional Requirements

### FR-001: check-table-absent

#### Acceptance Criteria:

- [ ] The Lambda calls Glue `GetTable(database=space.database, name=tableName)`; a `EntityNotFoundException`
  (not found) ⇒ pass (emit the request payload unchanged); a found table ⇒ terminal failure with reason
  `table_exists` (message names the table + DB).
- [ ] Transient Glue errors (throttling/5xx) are **raised** for the SFN `Retry` (not converted to terminal);
  the terminal reason is reserved for a genuine existing table (`lambdas.md` §4).
- [ ] The role grants Glue `GetTable`/`GetDatabase` on the catalog ARNs + `logs` only; `simulate-custom-policy`
  confirms no create/delete/table-mutation rights.

### FR-002: inspect-source — layout classification

#### Acceptance Criteria:

- [ ] Listing `space.prefix`, the Lambda classifies the folder as **flat** (data objects directly under the
  prefix, no `key=value/` children) or **Hive-partitioned** (immediate children are `key=value/` directories);
  for partitioned data it captures the **ordered partition keys** (e.g. `["year","month"]`) from the first data
  object's path.
- [ ] A folder mixing top-level data files with `key=value/` dirs, inconsistent partition key sets/depths across
  objects, or no data under it ⇒ terminal failure with the specific reason (`ambiguous_layout` / `no_data_files`).
- [ ] The marker (`DO_NOT_DELETE.txt`), `athenaresults/`, zero-byte objects, and `_`/`.`-prefixed files are
  **ignored** when classifying (so a normal space folder isn't misread).

### FR-003: inspect-source — format validation

#### Acceptance Criteria:

- [ ] The data objects must be a **single supported format** — Parquet (`.parquet`), CSV (`.csv`), or JSON/NDJSON
  (`.json`/`.ndjson`/`.jsonl`); a consistent format across all (non-ignored) data objects ⇒ pass.
- [ ] **Mixed** supported formats ⇒ terminal `mixed_formats`; **no** recognized data files ⇒ terminal
  `no_data_files`; only **unsupported** formats present (e.g. `.orc`/`.avro`) ⇒ terminal `unsupported_format`.
  Each reason is specific and user-readable.

### FR-004: inspect-source — output payload

#### Acceptance Criteria:

- [ ] On success the Lambda emits `{ ...request, format, partitioned, partitionKeys[], sampleObjectKey, location,
  fileCount }` where `sampleObjectKey` is a representative data object (for partitioned data, one leaf data
  object) that `infer-schema` will open; `location` is the table `LOCATION` (the request prefix for flat data;
  the **partition root** prefix for partitioned data) — small payload, ids/keys only (`lambdas.md` §10).
- [ ] The role grants `s3:ListBucket` (prefix-scoped) + `s3:GetObject` on **both** the user-space and shared
  buckets' data prefixes + `logs`; no write/delete; `simulate-custom-policy`-verified.

### FR-005: SFN wiring + deploy IAM

#### Acceptance Criteria:

- [ ] The state machine runs `validate → check-table-absent → inspect-source → (stub) infer-schema`, each Task
  with `Retry` for transient errors and the shared `Catch` → recorded-failure for terminal reasons.
- [ ] The deploy-role table-builder fragment is extended for the two roles' grants; `tofu validate`/`plan` clean.

### FR-006: Tests + e2e

#### Acceptance Criteria:

- [ ] Python unit tests (AWS stubbed) cover: `check-table-absent` passes on not-found, fails `table_exists` on
  found, **raises** (not terminal) on a transient Glue error; `inspect-source` correctly classifies a **flat**
  Parquet folder, a **Hive-partitioned** CSV folder (keys captured in order), and returns the right terminal
  reason for `mixed_formats`, `no_data_files`, `unsupported_format`, and `ambiguous_layout`; the marker/results/
  hidden files are ignored; the output payload matches FR-004.
- [ ] `docs/testing/table-builder-e2e.md`: a valid flat-Parquet request flows `validate → check → inspect` and
  reaches the stub `infer-schema` with the expected payload; an existing-name and a mixed-format request are each
  recorded-failed at the right step.

---

## Data Model

```python
# inspect-source output (passed to infer-schema)
{
  "actor": "alice",
  "space": {"kind": "personal", "bucket": "dat-prod-user-space", "prefix": "alice/sales/2026/", "database": "alice"},
  "tableName": "sales_2026",
  "location": "s3://dat-prod-user-space/alice/sales/2026/",   # partition root if partitioned
  "format": "parquet",            # 'parquet' | 'csv' | 'json'
  "partitioned": true,
  "partitionKeys": ["year", "month"],   # [] when flat
  "sampleObjectKey": "alice/sales/2026/year=2026/month=01/part-0.parquet",
  "fileCount": 24,
  "requestId": "f3a1…"
}

# terminal failure reasons (carried to the recorded-failure state):
#   table_exists | ambiguous_layout | no_data_files | mixed_formats | unsupported_format
```

## File & Folder Structure

```
lambdas/table-builder-check-table-absent/
├── check_table_absent.py        # Glue GetTable → pass | table_exists
└── test_check_table_absent.py   # NEW

lambdas/table-builder-inspect-source/
├── inspect_source.py            # list + classify layout/format → payload | terminal reason
└── test_inspect_source.py       # NEW

lambdas/table-builder-common/
└── s3_listing.py                # shared paginated list + ignore-rules helper (marker/results/hidden)

infra/modules/table-builder/
├── policies/check-table-absent.tftpl   # Glue GetTable/GetDatabase + logs (FR-001)
├── policies/inspect-source.tftpl       # S3 list/get on both data buckets + logs (FR-004)
└── state-machine.asl.json.tftpl        # + check-table-absent, inspect-source Tasks (FR-005)

infra/modules/base/policies/            # deploy-policy-table-builder additions (FR-005)
docs/testing/table-builder-e2e.md       # check + inspect flow (FR-006)
```

## Implementation Phases

### Phase 1: check-table-absent

- Glue GetTable pass/fail + transient-vs-terminal handling; role policy; SFN Task + Catch; unit tests
  (FR-001, FR-005 partial, FR-006 partial).

### Phase 2: inspect-source

- Paginated listing + ignore-rules; flat/Hive classification + partition-key capture; single-consistent-format
  validation; output payload + sample selection; role policy; SFN Task; unit tests + e2e doc
  (FR-002, FR-003, FR-004, FR-005, FR-006).
