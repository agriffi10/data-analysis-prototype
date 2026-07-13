# Spec: Data Quality — Source Inspection (`inspect-source`)

**ID:** SPEC-110
**Status:** Draft
**Last Updated:** 2026-07-13
**Depends On:** SPEC-107 (`cpcommon`), SPEC-108 (foundation), SPEC-109 (request contract + authorization)

> **Read `docs/data-quality-architecture.md` §4 first.**

## Overview

The second verb. Given an authorized location, `inspect-source` lists the objects under it, classifies each by **file extension**, enforces that the folder is a **single, consistent format**, probes **every** file's header, detects Hive-style partition directories, and writes a **manifest** to S3.

Two things here are new relative to the earlier Lambda-based design, and both matter:

**Parquet is a supported input.** The natural workflow is *convert, then verify* — a user who runs the file converter on a messy CSV must be able to check the resulting Parquet. The previous design rejected it with `unsupported_format`, which made the two arcs unable to talk to each other.

**There is no total-size cap.** The 20 GiB ceiling in the earlier design was a Lambda artefact. Athena does the reading now, so the only cap that remains is on **object count** — because the manifest and the cross-file comparison scale with the number of files, not their size.

## Scope

### In Scope

- Listing the location via `cpcommon.s3_listing` — which, per SPEC-107 FR-003, uses the **segment-level** hidden-path rule, so this pipeline's own `_data-quality-reports/` folder is never treated as source data, and excludes `user_settings/`.
- Format classification **by extension**: `.csv`/`.txt` → csv, `.json`/`.jsonl`/`.ndjson` → json, **`.parquet` → parquet**.
- **Single-format enforcement** — a mixed-format folder is a terminal failure.
- Probing **every** file's header/schema (column names, and for Parquet the dtypes) — the input to SPEC-112's cross-file column-agreement check **and** to SPEC-111's `CREATE EXTERNAL TABLE` column list, which Athena requires explicitly for Parquet and JSON.
- **Partition detection** — Hive-style `key=value/` directories, so SPEC-111 can declare partition columns with projection.
- An **object-count cap**, and a **size cap on compressed (`.gz`) objects** — the one place a byte count still matters on the Athena path.
- Writing the **manifest** to S3 and emitting a small, bounded state output.

### Out of Scope

- Reading file *contents* in bulk. `inspect-source` reads listings, object metadata, and bounded headers only. The data is read by **Athena** (SPEC-111) and, for the encoding check alone, by `byte-scan` (SPEC-112).
- Any total-size cap — removed deliberately (see Overview).
- Creating any Glue table — SPEC-111.
- Excel. Athena cannot read `.xlsx`, and the file-converter arc does not handle it either (user decision, 2026-07-13) — `.xlsx` is simply unsupported everywhere.
- Content sniffing to detect an extension/content mismatch — an accepted arc-wide limitation.

---

## Functional Requirements

### FR-001: Listing

#### Acceptance Criteria:

- [ ] The location is listed with a paginated `list_objects_v2` via `cpcommon.s3_listing`.
- [ ] Zero-byte objects, the `DO_NOT_DELETE.txt` marker, `athenaresults/`, `user_settings/`, and any object with a `_`- or `.`-prefixed **path segment** are excluded. The `athenaresults/` exclusion covers **both** buckets — including the shared bucket's `{spaceName}/athenaresults/` prefix that SPEC-111 FR-003 introduces for shared-space query results.
- [ ] A single-file location (the user selected one file, not a folder) yields a one-object manifest and proceeds normally.
- [ ] An empty location is a terminal `no_data_files` with a friendly reason.

### FR-002: Extension-based format classification

#### Acceptance Criteria:

- [ ] The map is `.csv`/`.txt` → `csv`; `.json`/`.jsonl`/`.ndjson` → `json`; `.parquet` → `parquet`.
- [ ] **One trailing `.gz` is stripped before classification**: `data.csv.gz` → `csv`, `.json.gz`/`.ndjson.gz`/`.jsonl.gz` → `json`. A **bare `.gz`** with no inner extension is a terminal `unsupported_format`. **`.parquet.gz` is REJECTED as `unsupported_format`** — gzipped Parquet is not readable by Athena, and polars cannot range-read the footer through gzip. Tests cover all three cases (`.csv.gz` classifies as csv; bare `.gz` rejected; `.parquet.gz` rejected). This is what makes FR-004's sub-1-GiB compressed-object acceptance reachable at all.
- [ ] A comment records that this is **deliberately different** from Table Builder's `_EXT_FORMAT` (`lambdas/table-builder-inspect-source/inspect_source.py:22-28`), which has no `.txt` — a new decision for this arc, not inherited behaviour.
- [ ] A comment records that **`.parquet` support is what makes the convert-then-verify workflow possible**, so it must not be dropped as "out of scope for a quality checker."
- [ ] `.xlsx` is a terminal `unsupported_format`, plain — **no convert-first guidance** (Excel is unsupported everywhere; the file-converter arc does not handle it). A test pins the message.
- [ ] Any other extension is a terminal `unsupported_format` naming the offending object.
- [ ] Classification is on the extension only; content is not sniffed.

### FR-003: Single-format enforcement

#### Acceptance Criteria:

- [ ] If the surviving objects resolve to more than one format, the request is a terminal `mixed_formats` naming the formats found.
- [ ] The rule matches Table Builder's (`inspect_source.py:106-113`), so a folder Table Builder would reject for mixed formats is rejected here for the same reason.

### FR-004: The object-count cap, and the compressed-source guard

#### Acceptance Criteria:

- [ ] `DQ_MAX_OBJECTS` defaults to **1000**, mirroring `SHARE_MAX_OBJECTS` (`lambdas/table-share-common/tscommon/config.py:44`). Exceeding it is a terminal `too_many_files` naming the count and the limit.
- [ ] There is **no total-size cap and no per-object size cap on uncompressed sources**. A comment records why: those were Lambda-era ceilings, and Athena — not a Lambda — reads the data now.
- [ ] **A compressed (`.gz`) object above `DQ_MAX_GZIP_OBJECT_BYTES` (default 1 GiB) is a terminal `compressed_source_too_large`.** A comment records the disaster this prevents: **gzip is not splittable**, so a single large `.csv.gz` is processed by **exactly one Athena worker** no matter how much the engine parallelizes — it will simply run until the **30-minute DML query timeout** (an account quota, §7.2 of the architecture doc) kills it, half an hour after the user pressed the button. Failing at inspection, in seconds, with the guidance *"decompress this file, or split it into many smaller objects"*, is strictly better than failing at minute 30 with `query_timeout`.
- [ ] The friendly message names the offending object and says what to do; a test pins it.
- [ ] All caps are `dqcommon.config` values validated at import (per `lambdas.md` §6 / SPEC-083), not magic numbers in the handler.

### FR-005: The per-file header probe and partition detection

#### Acceptance Criteria:

- [ ] **Every** object is probed for its column names (and, for Parquet, dtypes) — not one sample file. The probe is a **bounded** read: a Parquet footer, or the header line of a CSV, or the first line of an NDJSON file.
- [ ] The probe uses **polars** (`scan_parquet` / `scan_ndjson` / `scan_csv` → `collect_schema()`), which is why `inspect-source` — and only `inspect-source` — carries the polars layer (SPEC-108 FR-003). A comment records why the layer is not optional: **Athena requires an explicit column list for a Parquet or JSON external table and does not auto-detect a Parquet schema**, so SPEC-111's DDL is built from *this* probe. Without a Parquet reader here, this arc's Parquet support (FR-002) cannot exist.
- [ ] The union of the per-file probes is what SPEC-111 turns into the `CREATE EXTERNAL TABLE` column list; the manifest is therefore a contract with SPEC-111, not just an input to SPEC-112's cross-file check.
- [ ] The probe never downloads the whole object; it reads from `s3://` with a bounded range, following the pattern at `lambdas/table-builder-infer-schema/infer_schema.py:38-41`.
- [ ] **`.gz` sources cannot be range-read** — gzip is not seekable, so "bounded range" is false for compressed objects. For a `.gz` source the probe **streams and decompresses only until the header/schema is available**, then abandons the stream. A test asserts the bytes read from a large `.gz` object stay **under a stated bound** (the first compressed chunk(s), not the object).
- [ ] A `head_object` access probe runs before each read, so a transient S3 error surfaces as a retryable boto error rather than a terminal failure (mirroring `infer_schema.py:44-52`).
- [ ] **Partition detection:** if object keys under the location contain Hive-style `key=value/` segments, the ordered partition keys and their observed values are recorded in the manifest, so SPEC-111 can declare them with partition projection.
- [ ] **Observed partition values are capped per key at `DQ_MAX_PARTITION_VALUES` (default 1000)**; exceeding it is a terminal **`too_many_partition_values`** (registered in SPEC-114 FR-002) naming the key, the count and the limit — the cap is what keeps the manifest and SPEC-111's projection-enum DDL bounded.
- [ ] A file whose header/schema cannot be read is a terminal **`unreadable_header`** for the whole request (not a silent skip) — checking a folder while ignoring a file we cannot parse would produce a report that quietly omits the worst file in it. The reason code is **registered** in SPEC-114 FR-002 — registered codes are exported constants, and an unregistered code raises at raise-time (SPEC-107 FR-005) — so a bare "terminal with no code" cannot ship silently.

### FR-006: The manifest and the bounded state output

#### Acceptance Criteria:

- [ ] `inspect-source` writes `{space}/_data-quality-reports/{requestId}/manifest.json` containing `{ requestId, format, fileCount, files: [{ key, size, columns }], partitionKeys }`.
- [ ] The manifest key is a **pure function of `requestId`** — a retry overwrites it byte-identically, which is how this pipeline is replay-safe (no verb in this codebase does request-id idempotency checking).
- [ ] The state output contains **only** the manifest key, the format, the file count, and the partition keys — **never** the file list or the column lists inline.
- [ ] A test builds a manifest for `DQ_MAX_OBJECTS` (1000) files with 1024-character keys and asserts the **state payload is under 8 KB** (the 256 KB Step Functions limit with three orders of magnitude of headroom).
- [ ] A comment records the disaster this prevents: `States.DataLimitExceeded` is thrown **outside** every `Catch`, so the execution dies without a notification and the user is never told anything at all.

---

## Data Model

```python
# lambdas/data-quality-common/dqcommon/config.py
DQ_MAX_OBJECTS: int = 1000                        # mirrors tscommon SHARE_MAX_OBJECTS
DQ_MAX_GZIP_OBJECT_BYTES: int = 1 * 1024**3       # gzip is NOT splittable → one worker → query_timeout
DQ_MAX_PARTITION_VALUES: int = 1000               # per key; keeps manifest + projection enums bounded
# No size cap on UNCOMPRESSED objects — Athena reads the data, and it splits them.

_EXT_FORMAT = {
    ".csv": "csv", ".txt": "csv",           # .txt is NOT in table-builder's map — new decision
    ".json": "json", ".ndjson": "json", ".jsonl": "json",
    ".parquet": "parquet",                  # NEW in v3: enables convert-then-verify
}
# ONE trailing ".gz" is stripped before lookup: data.csv.gz → csv. Bare ".gz" is
# unsupported_format; ".parquet.gz" is unsupported_format (Athena can't read it,
# polars can't range-read the footer through gzip).
```

```jsonc
// {space}/_data-quality-reports/{requestId}/manifest.json
{
  "requestId": "…",
  "format": "csv",
  "fileCount": 3,
  "partitionKeys": [{ "name": "region", "values": ["us", "eu"] }],
  "files": [
    { "key": "alice/sales/region=us/part-0.csv", "size": 4096, "columns": ["id", "amount", "note"] },
    { "key": "alice/sales/region=eu/part-0.csv", "size": 8192, "columns": ["id", "amount"] }
    // NOTE: `note` is absent from the second file → SPEC-112's cross-file agreement check reports it
  ]
}
```

```jsonc
// The SFN state output — bounded by construction (FR-006)
{ "manifestKey": "…/manifest.json", "format": "csv", "fileCount": 3, "partitionKeys": ["region"] }
```

## File & Folder Structure

```
lambdas/data-quality-inspect-source/inspect_source.py      (+ tests)
lambdas/data-quality-common/dqcommon/config.py             # cap + extension map
infra/modules/data-quality/state-machine.asl.json.tftpl    # InspectSource → real Lambda
```

## Implementation Phases

### Phase 1: Listing, classification, caps

- The extension map (incl. `.parquet` and the **strip-one-`.gz`** rule), single-format enforcement, the object-count cap and the **`.gz` size cap** in `dqcommon.config` with validate-at-import.
- Tests: single file; folder; mixed formats; unsupported extension; **`.xlsx` producing the plain `unsupported_format` message (no convert-first guidance)**; **`.csv.gz` classifying as csv, a bare `.gz` rejected, `.parquet.gz` rejected**; the object-count cap breach; **an oversized `.gz` producing `compressed_source_too_large` with the decompress-or-split guidance**; an empty location; a `_`-segment object being excluded; a `user_settings/` object being excluded.

### Phase 2: Header probe + partition detection

- Bounded per-file polars probes with the `head_object` access probe; the **streaming `.gz` probe with its byte bound**; Hive-style partition-key detection with the per-key value cap.
- Tests: a folder whose files disagree on columns (the input SPEC-112 must report); **a Parquet folder whose footer probe yields the dtypes SPEC-111's DDL needs**; **a large `.gz` whose probe stays under the stated byte bound**; a partitioned folder; a key exceeding `DQ_MAX_PARTITION_VALUES` producing **`too_many_partition_values`**; an unreadable header failing the request with **`unreadable_header`**.

### Phase 3: Manifest + SFN wiring

- Write the manifest; emit the bounded state output; wire `InspectSource`. Test the payload bound at 1000 files with maximal keys. Completion ritual.
