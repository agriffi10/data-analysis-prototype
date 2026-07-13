# Spec: Data Quality — `byte-scan` + Report Assembly

**ID:** SPEC-112
**Status:** Draft
**Last Updated:** 2026-07-13
**Depends On:** SPEC-107 (`cpcommon`), SPEC-108 (foundation), SPEC-109 (S3 grants), SPEC-110 (the manifest + per-file columns), SPEC-111 (the Athena results)

> **Read `docs/data-quality-architecture.md` §5.2, §5.3 and §6 first.**

## Overview

Two verbs that finish the job. **`byte-scan`** performs the one check a SQL engine fundamentally cannot do, and **`assemble-report`** joins everything into the report the user actually reads.

**Why `byte-scan` exists.** By the time Athena hands you a row, the raw bytes are gone — the serde has already decoded and parsed them. So **invalid UTF-8**, one of the most common real-world corruptions (a file exported from Excel in a Windows codepage), is invisible to SQL. A small Lambda reads a **bounded sample of bytes** and reports what it finds. It cannot read 250 GB, so this figure is **sampled, and the report says so** — with the coverage percentage. A number that silently means "of the first 0.8%" is worse than no number.

**The budget is bounded PER REQUEST, not per file — and that correction is the whole point of this FR.** An earlier draft gave *each* file a 256 MiB window; across the 1000 files `DQ_MAX_OBJECTS` permits, that is **~276 GB pulled through a single 1024 MB Lambda in 300 seconds** — about **920 MB/s sustained**, against a real-world S3-to-Lambda rate of roughly 60–100 MB/s. It would have passed every test on a three-file fixture and timed out on every real folder in production. That is precisely the class of error the whole Athena re-architecture exists to eliminate, and it had been reproduced in the one Lambda that survived it. The budget is now a **total** (`DQ_SCAN_TOTAL_BYTES`, default 2 GiB) **divided across the manifest's files**.

**Why cross-file agreement is computed here and not in SQL.** An Athena external table has **one schema for the whole folder**. It would happily read a folder whose files disagree on columns and give you a clean-looking answer — *hiding the exact disagreement the user needs to know about*. So this check is a reduce over SPEC-110's per-file probe, not a query. It is the check most likely to explain why a Table Builder table came out wrong.

## Scope

### In Scope

- **`byte-scan`**: an encoding check for **uncompressed csv/json text sources only** (Parquet and `.gz` render `skipped`, FR-001), bounded by a **total, per-request byte budget** divided across the manifest's files (head window + ranged samples), with explicit coverage reporting.
- **`assemble-report`**: read the Athena results (SPEC-111) and the manifest (SPEC-110); compute cross-file column agreement; write the report; emit a small summary payload for SPEC-114.
- Clear separation, in the report and in its schema, between **exact** and **approximate/sampled** figures.
- A deterministic report key.

### Out of Scope

- Any exact figure that Athena already computes — SPEC-111 owns those; this spec **consumes** them and must not recompute anything.
- The notification itself — SPEC-114 (this spec emits the summary payload it is built from).
- The report **view** — SPEC-113. This spec produces the JSON; SPEC-113 renders it.
- Reading bulk file content. `byte-scan` spends a **fixed total budget** (`DQ_SCAN_TOTAL_BYTES`, default 2 GiB) across the whole manifest — never the whole file, at any size, and never a budget that scales with the file count.
- Excel — unsupported in this arc.

---

## Functional Requirements

### FR-001: `byte-scan` — the encoding check, bounded per REQUEST and honest

#### Acceptance Criteria:

- [ ] **The encoding byte-scan runs ONLY for uncompressed csv/json text sources.** For a **Parquet** source the encoding figure renders as **`skipped`** with the reason "binary format — encoding is defined by the file format"; for a **`.gz`** source it is likewise **`skipped`** ("compressed source — raw bytes are DEFLATE output" — scanning them would measure the compressor, not the text). When every file is skipped, `byte-scan` reads nothing. (The ragged-row check via the raw-line table is similarly text-only — SPEC-111 FR-002 already creates it for CSV alone.) SPEC-113 FR-005 renders the `skipped` variant; SPEC-114 FR-001's approximate-figures qualifier applies **only when the figures exist**.
- [ ] **The total byte budget for the whole invocation is `DQ_SCAN_TOTAL_BYTES` (default 2 GiB)**, and it is **divided across the files in the manifest** — a 1000-file manifest gives each file ~2 MiB, a 2-file manifest gives each ~1 GiB. The bytes read by the invocation **never exceed the total**, regardless of file count or file size. A test asserts the bound holds for a 1-file manifest, a 1000-file manifest, and a manifest of 250 GB files.
- [ ] Each file's share is spent as a **head window** (`DQ_SCAN_HEAD_FRACTION`, default 0.5 of the share — corruption clusters at the start of a badly-exported file) plus up to `DQ_SCAN_SAMPLE_COUNT` (default **20**) ranged reads spread evenly across the remainder, each sized from what is left of that file's share.
- [ ] A comment records the disaster this prevents, with the arithmetic: a **per-file** window of 256 MiB × 1000 files ≈ **276 GB** through one 1024 MB Lambda in 300 s ≈ **920 MB/s sustained**, against a real ~60–100 MB/s. It passes on a three-file fixture and times out on every real folder. **The budget must never be re-expressed per file.**
- [ ] It counts byte sequences that fail clean UTF-8 decoding, and records a capped sample (10) of the byte offsets at which they occur.
- [ ] It reports, per file, `bytesExamined` and `bytesTotal`, from which the report derives an explicit **coverage percentage**.
- [ ] A file read **in full** within its share is marked `coverage: "complete"`; any file larger than its share is marked `coverage: "sampled"`. A test asserts both.
- [ ] The invocation stays within its **300 s / 1024 MB** budget (SPEC-108 FR-002) for a manifest of `DQ_MAX_OBJECTS` (1000) files: 2 GiB at a conservative 60 MB/s is **~35 seconds**, an order of magnitude inside the timeout, and the bytes are decoded in a streaming fashion so peak memory is bounded by the read-chunk size, not the budget. A test asserts the total bytes read do **not** grow with either file size or file count.
- [ ] All constants live in `dqcommon.config`, validated at import.
- [ ] A comment records why this cannot be exact: 250 GB cannot be read in a Lambda, and Athena cannot see raw bytes. The honest response is a **labelled** sample, not a bigger budget.

### FR-002: `assemble-report` — cross-file column agreement

#### Acceptance Criteria:

- [ ] Using the per-file `columns` from SPEC-110's manifest, the report states whether **every file presents the same columns**, and where they disagree names the file, the missing columns, and the extra columns.
- [ ] A comment records why this is **not** a SQL check: an Athena external table has one schema for the whole folder and would silently mask exactly this disagreement.
- [ ] A single-file source reports `columnsAgree: true` trivially, with no disagreements.

### FR-003: `assemble-report` — the report

#### Acceptance Criteria:

- [ ] It reads the Athena query results (**all three** — profile, ragged-rows, duplicates, SPEC-111 FR-003) from the result locations in the state, and the manifest from SPEC-110. It **recomputes nothing** that Athena already computed.
- [ ] The report is written to `{space}/_data-quality-reports/{requestId}/report.json`, a key that is a **pure function of `requestId`** — a retry or SQS redelivery **overwrites it (same key, no duplicate object)**. A test re-runs the machine with the same `requestId` and asserts the object is overwritten, no duplicate object appears, and **every field except `completedAt` is identical**. A comment records why this is the replay-safety mechanism: no verb in this codebase does request-id idempotency checking.
- [ ] The report carries **`"completedAt": "<ISO-8601>"`** — the report records **when the check completed**. SPEC-113's metadata footer and SPEC-123's index entry both need it.
- [ ] Every figure in the report is tagged `"exact"`, `"approximate"`, `"skipped"` or `"not_computed"`. **Exact:** type consistency, null/blank ratios, duplicate rows, row counts, cross-file agreement. **Approximate:** ragged rows and encoding, **when computed**. **Skipped:** encoding on Parquet/`.gz` (FR-001) and type consistency on Parquet. **Not_computed:** a degraded ragged or duplicates query (SPEC-111 FR-003). The encoding and ragged fields are therefore a **union** — a figure variant or a `skipped`/`not_computed` variant carrying its reason (Data Model below).
- [ ] **Type consistency on a Parquet source renders as `skipped`, with the reason** — "Parquet enforces types in the file format, so this check cannot find anything" (SPEC-111 FR-003). It is **not** rendered as a clean pass. A test asserts a Parquet report never shows a green type-consistency result it did not earn.
- [ ] **A ragged or duplicates figure that SPEC-111's separate queries could not produce renders as `not_computed`, with its reason** — and the report is still written, with a verdict, from everything else. A test asserts a report with `duplicates: not_computed` still has exact null ratios, row counts and cross-file agreement, and still reaches a verdict.
- [ ] **The ragged-row figure carries BOTH of its caveats**, not one: `split` over-reports when a field contains a **quoted comma** *and* when a field contains an **embedded newline inside quotes** (one logical row appearing as two physical lines). A test asserts the rendered note mentions both.
- [ ] If a file exceeded **Athena's 200 MB single-line limit** and the raw-line table failed, the ragged figure renders as `not_computed` with that reason — it does **not** fail the request (SPEC-111 FR-002).
- [ ] A report where **any** figure is approximate, sampled, skipped or not-computed sets a top-level `hasApproximateFigures: true` — the flag SPEC-114's notification reads so it never says an unqualified "clean" over a sampled scan or an uncomputed check.
- [ ] The overall verdict is `clean` or `issues_found`.
- [ ] A **top-issues list** of at most **5** human-readable strings is produced for the notification body, ordered by severity (structural before statistical), each naming the file and column involved. A test pins the ordering and the cap.
- [ ] The verb emits a **small** summary payload (`requestId`, `location`, `format`, `fileCount`, verdict, top issues, `hasApproximateFigures`, `completedAt`, report key) for SPEC-114 — and, by design, everything a SPEC-123 index entry needs (FR-004). The notification never carries the full report.

### FR-004: The runs index (delivered by SPEC-123)

#### Description

The report alone is not findable. SPEC-123 later amends `assemble-report` to append a small entry to a per-space index — the append, `dqcommon.index_store`, and all CAS tests are **SPEC-123 FR-001 deliverables**, not this spec's.

#### Acceptance Criteria:

- [ ] `assemble-report` leaves a **documented seam** for SPEC-123: the report write completes **before** any index write would run, and the summary payload (FR-003) carries everything an index entry needs (`requestId`, `location`, `format`, `verdict`, `fileCount`, `hasApproximateFigures`, `completedAt`). A comment marks the seam.

### FR-005: Terminal states

#### Acceptance Criteria:

- [ ] `RecordSuccess` shapes `{ requestId, actor, location, verdict, hasApproximateFigures, reportKey }`; `RecordFailure` shapes `{ requestId, actor, location, status: "failed", reason }`.
- [ ] Both are `Pass` states, matching the existing machines (`table-builder/state-machine.asl.json.tftpl:190-202`). **Nothing durable is written to S3 by a terminal state** — the report object is the artefact. A comment says so, so no future UI is built expecting a failure object in S3.
- [ ] The state order matches SPEC-108's canonical list exactly: success `… → DropTempTables → RecordSuccess → Succeed`; failure `Catch → ParseError → DropTempTables → RecordFailure → NotifyFailure → Fail` (`NotifyFailure` is wired in SPEC-114). Both paths route through `DropTempTables` (SPEC-111 FR-005).

---

## Data Model

```python
# lambdas/data-quality-common/dqcommon/config.py
# PER REQUEST, not per file. A per-file window of 256 MiB × 1000 files ≈ 276 GB through one
# Lambda in 300 s ≈ 920 MB/s required, vs ~60–100 MB/s real. Never re-express this per file.
DQ_SCAN_TOTAL_BYTES: int = 2 * 1024**3      # total budget, divided across the manifest's files
DQ_SCAN_HEAD_FRACTION: float = 0.5          # of each file's share, read as a head window
DQ_SCAN_SAMPLE_COUNT: int = 20              # ranged reads spending the rest of the share
DQ_TOP_ISSUES: int = 5
```

```jsonc
// {space}/_data-quality-reports/{requestId}/report.json
{
  "requestId": "…",
  "location": "alice/sales/",
  "format": "csv",
  "fileCount": 3,
  "verdict": "issues_found",              // | "clean"
  "hasApproximateFigures": true,          // ⇒ SPEC-114 qualifies the notification
  "completedAt": "2026-07-12T14:32:11Z",  // when the check completed — the ONLY field a replay changes

  "exact": {
    "rowCount": 412_884_301,
    "rowCountsByFile": [{ "key": "…/part-0.csv", "rows": 140_000_000 }],
    "duplicateRows": 812,                   // or: { "status": "not_computed", "reason": "…" }
    "columns": [
      { "name": "amount", "dominantType": "DOUBLE", "nonParsingValues": 412,
        "nullBlankRatio": 0.01, "sampleOffending": ["N/A", "-", "1,024"] }
      // On a PARQUET source: { "name": …, "typeConsistency": "skipped",
      //   "reason": "Parquet enforces types in the file format." }   ← never a green pass
    ],
    "crossFile": {
      "columnsAgree": false,
      "disagreements": [{ "file": "part-2.csv", "missing": ["note"], "extra": [] }]
    }
  },

  "approximate": {
    // Both fields are UNIONS: a computed-figure variant, or a skipped/not_computed
    // variant carrying its reason (FR-001 / FR-003).
    "raggedRows": {
      "count": 37,
      "note": "Approximate — over-counts rows with commas inside quotes, and rows with newlines inside quoted fields."
      // | { "status": "not_computed", "reason": "a line exceeded Athena's 200 MB limit" }
      // | { "status": "skipped", "reason": "not a line-delimited text format" }   ← json/parquet
    },
    "encoding": {
      "invalidUtf8Sequences": 4,
      "coverage": "sampled",
      "coveragePercent": 0.4,
      "note": "Sampled — 0.4% of bytes examined."
      // | { "status": "skipped", "reason": "binary format — encoding is defined by the file format" }  ← parquet
      // | { "status": "skipped", "reason": "compressed source — raw bytes are DEFLATE output" }        ← .gz
    }
  },

  "topIssues": [
    "part-2.csv is missing the column `note` that the other 2 files have",
    "`amount` has 412 values that aren't numbers in an otherwise numeric column",
    "812 duplicate rows"
  ]
}
```

## File & Folder Structure

```
lambdas/data-quality-byte-scan/byte_scan.py             (+ tests)
lambdas/data-quality-assemble-report/assemble_report.py (+ tests)
lambdas/data-quality-common/dqcommon/
├── report.py    # report shape, exact/approximate tagging, top-issues rendering
└── config.py    # window/sample constants
infra/modules/data-quality/state-machine.asl.json.tftpl # ByteScan, AssembleReport, terminals
```

## Implementation Phases

### Phase 1: `byte-scan`

- **The per-request byte budget**, divided across the manifest's files; the head window + ranged samples; coverage accounting; the **text-only gate** (FR-001).
- Tests: a small file (complete coverage); a large file (sampled, correct coverage percentage); a file with known invalid UTF-8; **a Parquet manifest and a `.gz` manifest each yielding `skipped` with zero bytes read**; **the total bytes read staying under `DQ_SCAN_TOTAL_BYTES` for 1 file, 1000 files, and 250 GB files** — the bound that the per-file design silently violated by ~200×.

### Phase 2: `assemble-report`

- Read **all three** Athena result sets + the manifest; cross-file column agreement; the exact / approximate / **skipped** / **not_computed** tagging; `completedAt`; `hasApproximateFigures`; the top-issues list with its ordering and cap; the report write with a deterministic key.
- Tests: **a Parquet source rendering type consistency as `skipped`, never as a pass**; **a failed ragged or duplicates query rendering `not_computed` while the rest of the report lands**; the ragged note carrying **both** caveats.
- **The replay test:** re-run with the same `requestId`, assert the object is overwritten (same key, no duplicate object) and **every field except `completedAt` is identical**.

### Phase 3: Terminals + end-to-end

- The SFN terminal states (still routing through cleanup).
- End-to-end over a real multi-file folder with a drifting column, dirty numeric values, duplicate rows and a Windows-codepage file: assert the exact figures are exact, the approximate ones are labelled, and the top-issues list names the right things. Completion ritual.
