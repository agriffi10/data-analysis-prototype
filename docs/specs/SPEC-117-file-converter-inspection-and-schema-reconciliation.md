# Spec: File Converter — Source Inspection + Schema Reconciliation

**ID:** SPEC-117
**Status:** Draft
**Last Updated:** 2026-07-13
**Depends On:** SPEC-107 (`cpcommon`), SPEC-115 (foundation), SPEC-116 (request contract + authorization)

> **Read `docs/file-converter-architecture.md` §4 first.** This spec produces the target schema everything downstream converts against.

## Overview

Two verbs. **`inspect-source`** lists the source, classifies it, probes **every** file's header and schema, detects partition layout, and writes a manifest. **`reconcile-schema`** reduces those per-file schemas into **one target schema** — the `CAST` list the Athena `UNLOAD` will use.

This is where the arc earns its existence. Table Builder infers schema from a **single sample file** and does not union columns across files: a folder of `{id,name}` and `{id,extra}` yields `{id,name}`, and `extra` is **silently dropped** (`table-builder-architecture.md` §10). Probing every file is what removes that.

**But one capability is deliberately given up, and it must be given up loudly.** An Athena external table has **one schema for the whole folder**, and for CSV it reads columns **by position**. Files that disagree on column names or order would be **silently misaligned** — the worst possible outcome, a conversion that "succeeds" and produces garbage. So a CSV folder whose files do not share a consistent header is **rejected**, naming the offending file. Type widening still works fully; only column *union* is lost, and only for CSV. JSON is unaffected — Athena's JSON serde matches by key name and yields nulls for missing keys.

## Scope

### In Scope

- Listing via `cpcommon.s3_listing` (segment-level hidden-path rule, per SPEC-107 FR-003).
- Format classification by extension: `.csv`/`.txt` → csv, `.json`/`.jsonl`/`.ndjson` → json — with **one trailing `.gz` stripped before mapping** (`.csv.gz` → csv).
- **Single-format enforcement** — a mixed-format folder is terminal.
- An **object-count cap**, a **partition-value cap**, and a **size cap on compressed (`.gz`) objects** — the one place a byte count still matters on the Athena path.
- A **per-file header + schema probe** for every object (polars — which is why **`inspect-source` carries the polars layer**, SPEC-115 FR-003).
- **Rejection of heterogeneous CSV headers**, with a message naming the offending file.
- **Partition detection** (Hive-style `key=value/`).
- **`reconcile-schema`**: union by name (JSON), the **full type-widening rule table**, string fallback, and the resulting CAST list / target schema.
- The manifest and the target schema, both written to `_fc-work/`, with bounded state output.

### Out of Scope

- **Excel (`.xlsx`) — deferred entirely, user decision 2026-07-13.** `.xlsx` is a terminal `unsupported_format` like any other unsupported extension (FR-001); there is no Excel probe, no Excel size cap, and no Excel exemption anywhere in this spec.
- Creating any Glue table, running any query, or converting anything — SPEC-118 (the `UNLOAD` path) and SPEC-119 (finalize + terminals).
- Total-size and per-object size caps on **uncompressed** sources — those were Lambda-era ceilings and no longer exist; Athena reads the data and splits it across workers. (The `.gz` cap in FR-002 is the one place a byte count still matters.)
- Content sniffing to detect an extension/content mismatch — an accepted arc-wide limitation.
- Unioning mismatched CSV headers — rejected by design (see Overview, and FR-004).

---

## Functional Requirements

### FR-001: Listing and classification

#### Acceptance Criteria:

- [ ] The source is listed with a paginated `list_objects_v2` via `cpcommon.s3_listing`; zero-byte objects, the marker, `athenaresults/`, `user_settings/`, and any `_`/`.`-prefixed **path segment** are excluded.
- [ ] Extension map: `.csv`/`.txt` → csv; `.json`/`.jsonl`/`.ndjson` → json. A comment records that `.txt` is **deliberately not** in Table Builder's map (`inspect_source.py:22-28`) — a new decision for this arc, not inherited. `.xlsx` maps **nowhere**: Excel is deferred entirely (user decision 2026-07-13) and `.xlsx` is a terminal `unsupported_format` like any other unsupported extension.
- [ ] **Exactly one trailing `.gz` is stripped before mapping:** `.csv.gz`/`.txt.gz` → csv; `.json.gz`/`.ndjson.gz`/`.jsonl.gz` → json. A bare `.gz` (no inner extension) is a terminal `unsupported_format`.
- [ ] A test asserts `data.csv.gz` classifies as **csv** — and is therefore subject to `FC_MAX_GZIP_OBJECT_BYTES` (FR-002), not silently rejected as an unknown extension.
- [ ] Any other extension is a terminal `unsupported_format` naming the object.
- [ ] More than one resolved format is a terminal `mixed_formats`.
- [ ] An empty source is a terminal `no_data_files`; a single-file source yields a one-object manifest and proceeds.

### FR-002: The object-count, partition, and compressed-source caps

#### Acceptance Criteria:

- [ ] `FC_MAX_OBJECTS` defaults to **1000** (mirroring `tscommon` `SHARE_MAX_OBJECTS`). Exceeding it is a terminal `too_many_files`.
- [ ] `FC_MAX_PARTITIONS` defaults to **100**, matching Athena's documented CTAS/UNLOAD partition limit. A source with more distinct partition values is a terminal `too_many_partitions` with a friendly message. A comment records that this cap mirrors an engine limit, so it is conservative by construction — if the real limit is higher, we simply fail earlier than we must.
- [ ] There is **no total-size cap and no per-object size cap on uncompressed sources on the Athena path.** A comment records why: those were Lambda-era ceilings, and Athena — not a Lambda — reads the data now, and it splits it across workers.
- [ ] **A compressed (`.gz`) object above `FC_MAX_GZIP_OBJECT_BYTES` (default 1 GiB) is a terminal `compressed_source_too_large`.** A comment records the disaster this prevents: **gzip is not splittable**, so a single large `.csv.gz` is processed by **exactly one Athena worker** no matter how the engine parallelizes — the `UNLOAD` simply runs until the **30-minute DML query timeout** (an account quota, SPEC-115 FR-003) kills it, half an hour after the user pressed the button, leaving partial output the pipeline cannot delete. Failing at inspection, in seconds, with *"decompress this file, or split it into several smaller objects"*, is strictly better.
- [ ] The friendly message names the offending object and says what to do; a test pins it.
- [ ] All caps are `fccommon.config` values validated at import (per `lambdas.md` §6 / SPEC-083).

### FR-003: The per-file schema probe

#### Acceptance Criteria:

- [ ] **Every** object is probed for `{ columns: [{ name, dtype }] }` — not one sample file.
- [ ] The probe is a **bounded** read: polars `scan_csv` / `scan_ndjson` → `collect_schema()`, reading a bounded head direct from `s3://` with no `/tmp` download (mirroring `lambdas/table-builder-infer-schema/infer_schema.py:38-41`).
- [ ] **`inspect-source` therefore carries the polars layer** — SPEC-115 FR-003 attaches it to `inspect-source` **only**, and the SPEC-107 combined size guard must pass for it. A comment records why the layer is unavoidable: the probe is the source of the target schema, and it needs a reader.
- [ ] **For CSV, type inference is ON** during the probe — the deliberate reversal of Table Builder's all-string CSV choice (`table-builder-architecture.md` §4), and the reason this arc exists. A comment says so. (Note: at *read* time on the Athena path the data is still read as all-string by the OpenCSVSerde, and the probe's inferred types become the `CAST` list — see SPEC-118.)
- [ ] CSV assumes a **header row and comma delimiter** (the same v1 assumption as Table Builder). JSON is **NDJSON only**; a pretty-printed JSON array is a terminal `unsupported_json_shape`.
- [ ] A `head_object` access probe runs before each scan so a transient S3 error surfaces as a retryable boto error rather than a terminal failure (mirroring `infer_schema.py:44-52`).
- [ ] A file that cannot be probed is a terminal **`unreadable_file`** for the **whole request** — converting a folder while ignoring a file we cannot understand would produce a silently incomplete result. The friendly message names the object. The reason code is **registered** in SPEC-121 FR-002; an unregistered code is a **hard error at import** (SPEC-107 FR-005), so "a terminal with no code" is a Lambda that fails to load, not a vague message.

### FR-004: Heterogeneous CSV headers are rejected

#### Description

The one capability this arc deliberately gives up, and the one most likely to be "fixed" back in by someone who doesn't know why it's there.

#### Acceptance Criteria:

- [ ] For a **CSV** source, if the probed files do not share an **identical, identically-ordered** header, the request is a terminal **`inconsistent_headers`**.
- [ ] The friendly message names **which file differs and how** (missing columns, extra columns, or a different order), and points the user at the **data-quality check** to see the full picture.
- [ ] A comment records the disaster this prevents: an Athena external table has one schema for the whole folder and reads CSV **positionally**, so a mismatched file would be **silently misaligned** — a conversion that reports success and produces garbage.
- [ ] **JSON is exempt.** Athena's JSON serde matches by **key name** and yields nulls for missing keys, so a JSON folder with drifting keys reconciles naturally. A test asserts a JSON folder with `{id,name}` + `{id,extra}` is accepted and produces a target schema containing `id`, `name` and `extra`.

### FR-005: `reconcile-schema` — the type-widening rule table

#### Description

The architecture doc states the policy. This FR requires the **exhaustive rule table**, because an under-specified widening rule is how a column silently becomes a string in production.

#### Acceptance Criteria:

- [ ] It reads the manifest from S3 (never inline from state) and produces **one** target schema.
- [ ] An explicit, exhaustive widening table is implemented and covered by a **table-driven test over every type pair**, including at minimum: integer widths (Int8…Int64 → the widest); signed/unsigned mixes; integer + float → float; Float32 + Float64 → Float64; date + datetime → datetime; any temporal + non-temporal → **string**; boolean + numeric → **string**; anything + string → **string**; and an all-null column in one file unifying with any type in another (an all-null column must **not** force a string fallback).
- [ ] **The widening vocabulary is pinned:** widening operates over the **probe's polars dtypes**, and the reconciled dtype maps to its Athena type via the **SPEC-069 dtype→Hive mapping, reused through the layer** — never re-invented here. The mapping step is part of the table-driven test (every reconciled dtype in the table has an asserted Athena type).
- [ ] Where no common numeric/temporal type exists, the column falls back to **string** for that column **only** — the conversion does **not** fail, and other columns keep their types.
- [ ] Every string fallback is **recorded in the target schema** with the conflicting types, so SPEC-119's `finalize` can surface it and SPEC-121 can tell the user *"the column `note` was saved as text because some files had dates and others had numbers."*
- [ ] For **JSON**, columns are **unioned by name** across files; a column absent from some files is included and will be null there.
- [ ] Column order in the target schema is deterministic (first-seen order across the manifest's file order), so two runs over the same folder produce identical output.
- [ ] The rule table is a **data structure**, not a chain of `if`s.
- [ ] It performs **no bulk I/O** — it reads the manifest and writes the target schema, nothing else. (This is why it fits a 60 s / 512 MB budget.)

### FR-006: The manifest, the target schema, and the bounded state output

#### Acceptance Criteria:

- [ ] `inspect-source` writes `{space}/_fc-work/{requestId}/manifest.json`; `reconcile-schema` writes `{space}/_fc-work/{requestId}/target-schema.json`. Both keys are **pure functions of `requestId`** — a retry overwrites them byte-identically.
- [ ] Both live under **`_fc-work/`, which is NOT the destination**. A comment records why: SPEC-116 requires the destination to be **empty**, and SPEC-119's `finalize` verifies the `UNLOAD`'s output inside it — writing scratch files there would break both. `_fc-work/` is on SPEC-116's reserved-prefix blocklist for the same reason.
- [ ] The state output contains **only** pointers and scalars: the manifest key, the target-schema key, the format, the file count, and the partition keys — **never** the file list or the schemas inline.
- [ ] A test builds a manifest for `FC_MAX_OBJECTS` (1000) files with 1024-character keys and asserts the **state payload is under 8 KB** (the 256 KB Step Functions limit with three orders of magnitude of headroom).
- [ ] A comment records the disaster this prevents: `States.DataLimitExceeded` is thrown **outside** every `Catch`, so the execution dies with **no notification at all**.

---

## Data Model

```python
# lambdas/file-converter-common/fccommon/config.py
FC_MAX_OBJECTS: int = 1000
FC_MAX_PARTITIONS: int = 100                      # Athena's CTAS/UNLOAD partition limit
FC_MAX_GZIP_OBJECT_BYTES: int = 1 * 1024**3       # gzip is NOT splittable → one worker → query_timeout
# NO size cap on UNCOMPRESSED objects — Athena reads them, and splits them.

_EXT_FORMAT = {
    ".csv": "csv", ".txt": "csv",
    ".json": "json", ".ndjson": "json", ".jsonl": "json",
}
# Exactly ONE trailing ".gz" is stripped before mapping (data.csv.gz → csv, then subject
# to FC_MAX_GZIP_OBJECT_BYTES); a bare ".gz" is unsupported_format.
# .xlsx maps NOWHERE — Excel is deferred entirely (user decision 2026-07-13) and is a
# terminal unsupported_format like any other unsupported extension.
```

```jsonc
// {space}/_fc-work/{requestId}/target-schema.json
{
  "requestId": "…",
  "format": "csv",
  "partitionKeys": ["region"],
  "columns": [
    { "name": "id",     "dtype": "BIGINT" },
    { "name": "amount", "dtype": "DOUBLE", "widenedFrom": ["BIGINT", "DOUBLE"] },
    { "name": "note",   "dtype": "VARCHAR", "stringFallback": true,
      "conflictingTypes": ["DATE", "BIGINT"] },   // surfaced to the user by SPEC-121
    { "name": "extra",  "dtype": "VARCHAR", "absentIn": ["part-2.json"] }   // JSON union only
  ]
}
```

## File & Folder Structure

```
lambdas/file-converter-inspect-source/inspect_source.py       (+ tests)
lambdas/file-converter-reconcile-schema/reconcile_schema.py   (+ table-driven widening tests)
lambdas/file-converter-common/fccommon/
├── config.py     # caps + extension map (+ the .gz strip rule)
├── probe.py      # the per-file header/schema probe
└── widening.py   # the exhaustive rule table (FR-005) + the reused SPEC-069 dtype→Hive mapping
infra/modules/file-converter/state-machine.asl.json.tftpl     # InspectSource, ReconcileSchema
```

## Implementation Phases

### Phase 1: Listing, classification, caps

- The extension map with the **one-trailing-`.gz` strip rule**, single-format rule, object-count, partition and **`.gz`** caps with validate-at-import.
- Tests: single file; folder; mixed formats; unsupported extension (incl. `.xlsx` and a bare `.gz`); **`data.csv.gz` classifying as csv and subject to `FC_MAX_GZIP_OBJECT_BYTES`**; each cap breach — **including an oversized `.gz` producing `compressed_source_too_large` with the decompress-or-split guidance**; empty source; `_`-segment and `user_settings/` exclusion.

### Phase 2: The probe + the header-consistency gate

- Bounded per-file polars `s3://` probes (**`inspect-source` carries the polars layer**); CSV inference on; NDJSON-only; partition detection.
- **Tests: a CSV folder with mismatched headers is rejected with a message naming the file; a JSON folder with drifting keys is accepted and unions correctly; an unprobeable file produces `unreadable_file` naming the object.**

### Phase 3: `reconcile-schema` + the manifest

- The exhaustive widening rule table with a table-driven test over every type pair — including the **reused SPEC-069 dtype→Hive mapping** for each reconciled dtype; string-fallback recording; JSON union by name; deterministic column order.
- Write the manifest and target schema **to `_fc-work/`**; emit the bounded state output; test the payload bound at 1000 files with maximal keys. Completion ritual.
