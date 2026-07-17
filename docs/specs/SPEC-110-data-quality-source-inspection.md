# Spec: Data Quality — Source Inspection (`inspect-source`)

**ID:** SPEC-110
**Status:** Draft
**Last Updated:** 2026-07-16
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

- [ ] **Every** object is probed for its columns as ordered `{ name, type }` pairs — not one sample file. The probe is a **bounded** read: a Parquet footer, or the header line of a CSV, or the first line of an NDJSON file.
- [ ] The `{ name, type }` shape is **uniform across all three formats**; CSV emits `"string"` for every column. A comment records why this is not a fudge: SPEC-111 FR-002 builds the CSV temp table with **OpenCSVSerde and all-string columns**, so `"string"` IS the CSV type, and reading everything as string is what makes SPEC-111's `TRY_CAST` checks possible. A names-only-for-CSV variant would make the manifest polymorphic by format and force every consumer to branch.
- [ ] The probe uses **polars** (`scan_parquet` / `scan_ndjson` / `scan_csv` → `collect_schema()`), which is why `inspect-source` — and only `inspect-source` — carries the polars layer (SPEC-108 FR-003). A comment records why the layer is not optional: **Athena requires an explicit column list for a Parquet or JSON external table and does not auto-detect a Parquet schema**, so SPEC-111's DDL is built from *this* probe. Without a Parquet reader here, this arc's Parquet support (FR-002) cannot exist.
- [ ] The union of the per-file probes is what SPEC-111 turns into the `CREATE EXTERNAL TABLE` column list; the manifest is therefore a contract with SPEC-111, not just an input to SPEC-112's cross-file check. SPEC-111 FR-002 needs a **name AND a type** per column (Athena does not auto-detect a Parquet schema) — which is why `columns` carries pairs and not bare names.
- [ ] The probe never downloads the whole object; it reads from `s3://` with a bounded range, following the pattern at `lambdas/table-builder-infer-schema/infer_schema.py:38-41`.
- [ ] **`.gz` sources cannot be range-read** — gzip is not seekable, so "bounded range" is false for compressed objects. For a `.gz` source the probe **streams and decompresses only until the header/schema is available**, then abandons the stream. A test asserts the bytes read from a large `.gz` object stay **under a stated bound** (the first compressed chunk(s), not the object).
- [ ] A `head_object` access probe runs before each read, so a transient S3 error surfaces as a retryable boto error rather than a terminal failure (mirroring `infer_schema.py:44-52`).
- [ ] **Partition detection:** if object keys under the location contain Hive-style `key=value/` segments, the ordered partition keys and their observed values are recorded in the manifest, so SPEC-111 can declare them with partition projection.
- [ ] **Every data object must yield the SAME ordered partition keys.** A folder whose objects disagree — a stray file at the root next to `region=us/`, or one object under `region=us/` and another under `region=us/dt=2024-01/` — is a terminal **`partition_layout_mismatch`** naming a disagreeing object. A flat folder (every object yields zero keys) is the common case and stays free.
  A comment records the disaster this prevents: SPEC-111 builds the temp table with `LOCATION` at the folder root and **projection** over the detected keys, so Athena only ever resolves `LOCATION/{key}={value}/` paths. An object outside those paths belongs to **no partition**, is never scanned, and is **silently omitted from the report** — the user gets a clean verdict over a folder we did not fully read. That is the same harm `unreadable_header` (below) already refuses to accept, so it is refused here for the same reason.
  The code name is **reused from table-builder** (`table-builder-inspect-source/inspect_source.py:60-69`) for the same condition — but the mechanism differs and a comment says so: table-builder validates each object against **user-declared** keys, while this arc **auto-detects** them, so consistency must be derived from the data itself.
- [ ] **Observed partition values are capped per key at `DQ_MAX_PARTITION_VALUES` (default 1000)**; exceeding it is a terminal **`too_many_partition_values`** naming the key, the count and the limit — the cap is what keeps the manifest and SPEC-111's projection-enum DDL bounded.
- [ ] A file whose header/schema cannot be read is a terminal **`unreadable_header`** for the whole request (not a silent skip) — checking a folder while ignoring a file we cannot parse would produce a report that quietly omits the worst file in it. Registered per FR-007, so a bare "terminal with no code" cannot ship silently.

### FR-006: The manifest and the bounded state output

#### Acceptance Criteria:

- [ ] `inspect-source` writes `{space}/_data-quality-reports/{requestId}/manifest.json` containing `{ requestId, format, fileCount, files: [{ key, size, columns }], partitionKeys }`, where each entry of `columns` is `{ name, type }` (see the Data Model).
- [ ] The manifest key is a **pure function of `requestId`** — a retry overwrites it byte-identically, which is how this pipeline is replay-safe (no verb in this codebase does request-id idempotency checking).
- [ ] The state output **adds only** the manifest key, the format, the file count, and the partition-key NAMES to the threaded request object — and **never** the file list or the column lists inline. That is what "only" means here, and the distinction is load-bearing: the verb must still thread `requestId` and `actor` through (SPEC-109's identity contract), because `RecordSuccess`/`RecordFailure` read `$.requestId`/`$.actor` and a Pass state's JSONPath **hard-fails on an ABSENT key** with an uncatchable `States.Runtime` — which would skip `NotifyFailure` and leave the user with nothing, the very outcome the next criterion exists to prevent. It also threads `space`/`location`/`reportPrefix`, which SPEC-111 needs. A literal "only these four keys" would break the pipeline; the point is that the payload must not grow with the number of files.
- [ ] The state output carries partition-key **names only**; the observed VALUES live in the manifest, which SPEC-111 reads via `manifestKey` when it builds the projection enum. Values are unbounded-ish (up to `DQ_MAX_PARTITION_VALUES` per key) and so must not ride in the payload.
- [ ] A test builds a manifest for `DQ_MAX_OBJECTS` (1000) files with 1024-character keys and asserts the **state payload is under 8 KB** (the 256 KB Step Functions limit with three orders of magnitude of headroom).
- [ ] A comment records the disaster this prevents: `States.DataLimitExceeded` is thrown **outside** every `Catch`, so the execution dies without a notification and the user is never told anything at all.

### FR-007: Terminal reason codes are registered HERE, not in SPEC-114

#### Description

Earlier drafts of FR-004/FR-005 deferred registration of this verb's reason codes to SPEC-114 FR-002. **That cannot work, and it fails in the worst possible way** — green CI, broken production.

`TerminalError.__init__` (`cpcommon/errors.py:28`) validates its reason **at construction time** against `cpcommon.messages._known_reasons`. An unregistered code does not degrade to a generic message: it raises `ValueError` **instead of** the terminal. `_known_reasons` is a single **global set**, seeded with the base codes and extended by each domain layer **at import**. In production `inspect-source` attaches cpcommon + dqcommon + polars and **never imports tbcommon**; under `pytest lambdas/` all four domain layers import into one process. So tbcommon's registration of `no_data_files` / `unsupported_format` / `mixed_formats` (`tbcommon/messages.py:25-27`) makes those three codes valid **in tests only** — the three most common failure paths in this verb would pass CI and raise `ValueError` in production.

The user-visible damage: `RecordFailure` sets `reason.$: "$.parsed.cause.errorMessage"`, so the recorded reason becomes the raw `ValueError` text — exactly the raw-Python leak SPEC-106 FR-008 forbids.

This is the PR #196 failure shape (a shared layer's import-time requirement satisfied by the test process but not by a deployed function). SPEC-114 FR-002 keeps the arc-wide exhaustive registry; its job is to **verify exhaustiveness and own the verdict wording**, not to be the first registration.

#### Acceptance Criteria:

- [ ] Every reason code this verb raises is registered in **`dqcommon.messages`** with its wording, as an **exported constant** (no bare literals at raise sites), matching SPEC-109's pattern: `no_data_files`, `unsupported_format`, `mixed_formats`, `too_many_files`, `compressed_source_too_large`, `unreadable_header`, `too_many_partition_values`, `partition_layout_mismatch`.
- [ ] A test asserts each of those codes is present in **dqcommon's own domain table**, NOT merely `is_known_reason(code)` — the global set is polluted by tbcommon/tscommon under pytest, so an `is_known_reason` assertion would pass for a code this arc never registered. This test is the guard against the whole failure mode above, and a comment says so.
- [ ] A comment at the registration site records why the codes live here and not in SPEC-114.

---

## Data Model

```python
# lambdas/data-quality-common/dqcommon/config.py
DQ_MAX_OBJECTS: int = 1000                        # mirrors tscommon SHARE_MAX_OBJECTS (already shipped by SPEC-108)
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
    {
      "key": "alice/sales/region=us/part-0.csv",
      "size": 4096,
      // {name, type} pairs for EVERY format — SPEC-111's DDL needs a type per column and
      // Athena does not auto-detect a Parquet schema. CSV is all-"string": that IS the CSV
      // type (SPEC-111 FR-002's OpenCSVSerde), not a placeholder.
      "columns": [
        { "name": "id", "type": "string" },
        { "name": "amount", "type": "string" },
        { "name": "note", "type": "string" }
      ]
    },
    {
      "key": "alice/sales/region=eu/part-0.csv",
      "size": 8192,
      "columns": [
        { "name": "id", "type": "string" },
        { "name": "amount", "type": "string" }
      ]
      // NOTE: `note` is absent from the second file → SPEC-112's cross-file agreement check
      // reports it. That check compares `name` and ignores `type`.
    }
  ]
}
```

```jsonc
// The SFN state output — bounded by construction (FR-006). The four keys below are what
// this verb ADDS; the threaded request object (requestId, actor, space, location,
// reportPrefix) passes through underneath and MUST NOT be dropped — RecordSuccess /
// RecordFailure read $.requestId/$.actor, and a Pass state's JSONPath hard-fails on an
// absent key with an uncatchable States.Runtime.
{
  "requestId": "…",          // threaded (SPEC-109 identity contract)
  "actor": "alice",          // threaded
  "space": { … },            // threaded — SPEC-111 needs the bucket
  "location": "alice/sales", // threaded
  "reportPrefix": "alice/_data-quality-reports/…/",  // threaded
  "manifestKey": "alice/_data-quality-reports/…/manifest.json",
  "format": "csv",
  "fileCount": 3,
  "partitionKeys": ["region"]  // NAMES only; the values live in the manifest
}
```

## File & Folder Structure

```
lambdas/data-quality-inspect-source/dq_inspect_source.py   (+ test_dq_inspect_source.py)
lambdas/data-quality-common/dqcommon/config.py             # caps + extension map
lambdas/data-quality-common/dqcommon/messages.py           # this verb's reason codes (FR-007)
infra/modules/data-quality/locals.tf                       # the nine handler entries (see below)
infra/modules/data-quality/state-machine.asl.json.tftpl    # InspectSource → real Lambda
```

**Module naming (user decision, 2026-07-16).** All nine DQ verbs were renamed from a uniform
`handler.py` to `dq_<verb>.py` as in-scope work here. SPEC-108 chose the uniform name because
"the verb directory already disambiguates" — true for Lambda, where each function is its own
zip, and **false for pytest**, which flattens every verb dir into ONE module namespace: the
first `import handler` wins for the whole session, so SPEC-109's tests silently imported this
verb's handler. It surfaced the moment this arc had a second tested verb. The `dq_` prefix is
required on top of that because table-builder already owns the bare `inspect_source` /
`validate_authorize` module names — table-share prefixes for exactly the same reason. The
`handler` string in `locals.tf` also drives the placeholder filename, so that map and the
module files move together.

## Implementation Phases

Shipped as **two PRs**: phases 1+2 (the verb's logic), then phase 3 (the manifest + state-output contract).

### Phase 1: Reason codes, listing, classification, caps

- **FR-007 first**: register this verb's eight reason codes in `dqcommon.messages` with wording + exported constants, and the domain-table test. Everything below raises them, so nothing else can be tested until they exist.
- The extension map (incl. `.parquet` and the **strip-one-`.gz`** rule), single-format enforcement, the object-count cap and the **`.gz` size cap** in `dqcommon.config` with validate-at-import (`DQ_MAX_OBJECTS` already shipped in SPEC-108).
- Tests: single file; folder; mixed formats; unsupported extension; **`.xlsx` producing the plain `unsupported_format` message (no convert-first guidance)**; **`.csv.gz` classifying as csv, a bare `.gz` rejected, `.parquet.gz` rejected**; the object-count cap breach; **an oversized `.gz` producing `compressed_source_too_large` with the decompress-or-split guidance**; an empty location; a `_`-segment object being excluded; a `user_settings/` object being excluded.

### Phase 2: Header probe + partition detection

- Bounded per-file polars probes with the `head_object` access probe, yielding uniform `{name, type}` columns; the **streaming `.gz` probe with its byte bound**; Hive-style partition-key detection with the per-key value cap and the **layout-consistency check**.
- Tests: a folder whose files disagree on columns (the input SPEC-112 must report); **a Parquet folder whose footer probe yields the dtypes SPEC-111's DDL needs**; **a CSV folder whose columns are all-`"string"`**; **a large `.gz` whose probe stays under the stated byte bound**; a partitioned folder; **a stray root file beside `key=value/` producing `partition_layout_mismatch`**; **objects nested to differing depths producing `partition_layout_mismatch`**; a key exceeding `DQ_MAX_PARTITION_VALUES` producing **`too_many_partition_values`**; an unreadable header failing the request with **`unreadable_header`**.

### Phase 3: Manifest + SFN wiring

- Write the manifest; emit the bounded state output; confirm `InspectSource` is wired (SPEC-108 already points the state at this function's ARN with its `Retry`/`Catch` — verify rather than assume, and change nothing if it is correct). Test the payload bound at 1000 files with maximal keys. Completion ritual.
