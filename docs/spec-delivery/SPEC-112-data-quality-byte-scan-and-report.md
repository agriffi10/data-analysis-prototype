# Completed Spec — SPEC-112: Data Quality — `byte-scan` + Report Assembly

The arc's last two verbs: the one check SQL cannot do, and the report the user actually
reads. Shipped in three PRs — #248 (byte-scan), #249 (assemble-report + `dqcommon.report`),
#250 (SFN terminals). Two follow-up PRs came out of it: #251 (an unrelated Lake Formation
drift that broke `main`'s apply) and #252 (`ParseError` removal across all three control
planes). No new infra resources and no new IAM — the execution role already had every grant.

## What was completed?

- **`dq_byte_scan.py`** — bounded, sampled UTF-8 scan for uncompressed csv/json only;
  Parquet and `.gz` render `skipped` with their reason and read zero bytes. Budget is a
  **per-request total** divided across the manifest's files. One linear decode via a
  registered codec error handler; a character split across a read chunk is carried, not
  counted.
- **`dqcommon.report`** — result-CSV parsing, cross-file column agreement, the
  exact/approximate/skipped/not_computed tagging, verdict, and the top-issues wording.
- **`dq_assemble_report.py`** — reads the three Athena result sets + the manifest, writes
  `{space}/_data-quality-reports/{requestId}/report.json`, threads the summary onward.
- **`dqcommon.config`** — `DQ_SCAN_HEAD_FRACTION`, `DQ_SCAN_SAMPLE_COUNT`,
  `DQ_SCAN_MIN_SAMPLE_BYTES`, `DQ_TOP_ISSUES`, `DQ_OFFSET_SAMPLE`,
  `DQ_SCAN_READ_CHUNK_BYTES`, `is_compressed()`, all validated at import.
- **SFN terminals** — `RecordSuccess` carries the full outcome; `ValidateFailureSeed` seeds
  `location: null`.

## Deviations and corrections, each decided in flight

- **A second bound was missing from FR-001.** The byte budget does not bound REQUESTS. A
  flat `1 + DQ_SCAN_SAMPLE_COUNT` reads per file is 21,000 sequential GetObjects on a
  1000-file manifest — ~630 s against a 300 s function, while reading a legal 2 GiB. Added
  `DQ_SCAN_MIN_SAMPLE_BYTES`, which makes the sample count an "up to" and caps requests at
  ~1000. Both costs are now bounded; the arithmetic is in the constant's comment.
- **Per-file `bytesExamined`/`bytesTotal` are accounted for but returned AGGREGATED**
  (FR-001 says "reports, per file"). A per-file array is ~1 MB at 1000 files × 1024-char
  keys — over SFN's 256 KB limit, and `States.DataLimitExceeded` is thrown outside every
  Catch. The report's encoding block is aggregate anyway.
- **`hasIncompleteFigures` added beside `hasApproximateFigures`** (user decision). FR-003's
  classification makes the latter **true on every report for every format** — ragged and
  encoding are approximate whenever computed and skipped when not — so a flag that never
  varies tells SPEC-114 nothing. The new flag is false for a healthy CSV whose queries all
  succeeded and whose bytes were all scanned. FR-003 + Data Model amended.
- **SPEC-111's profile query changed:** the two sample aggregates are now
  `json_format(CAST(… AS JSON))`. Athena renders a bare array as `[N/A, -, 1,024]` with the
  ELEMENTS unquoted, so an offending value containing a comma split into two wrong examples
  — and these samples are drawn from exactly the malformed values most likely to contain
  one. Query 174,178 → **184,978 bytes (70.6%** of Athena's cap).
- **Results are read from S3, not `athena:GetQueryResults`** (deliberately ungranted), at
  `{resultLocation}{queryExecutionId}.csv`. **This is the one assumption no unit test can
  prove** — nothing in this repo had ever read a result file — so a miss falls back to
  listing the prefix rather than losing a check that already ran three queries.
- **`crossFile.disagreements[].file` is the full object KEY**, not the Data Model's
  illustrative basename (a basename is ambiguous across partitions). The top-issues wording
  uses the basename, which is where readability matters.
- **`rowCountsByFile` is reconciled against the manifest and sorted.** Athena emits no
  `$path` group for a file with no data rows, so a header-only CSV — a common real defect —
  simply vanished; and `GROUPING SETS` has no ORDER BY, so ordering was unstable across
  executions, quietly falsifying the replay guarantee.
- **`RecordFailure` carries the raw `error` object, not a decoded `reason`** (PR #252, FR-005
  amended). See below.

## What changed from earlier specs?

- **`ParseError` is gone from all three control planes** (#252). Every machine decoded the
  error Cause in a `Pass` state with `States.StringToJson`, which raises an uncatchable
  `States.Runtime` whenever `Cause` is absent or is not JSON. Verified live with `TestState`:
  3 of 4 realistic shapes killed the execution **before** the recorded-failure and notify
  states. `cpcommon.errors.failure_reason` now decodes the raw `$.error` in Python. SPEC-108
  (the canonical state list), SPEC-070 and SPEC-092 carry supersede notes; SPEC-114/115/121
  were amended, because they still *required* the deleted state.
- **`cpcommon.errors.failure_reason` is new**, plus
  `test_state_machines_cpcommon.py` — invariants every control-plane machine must satisfy
  (no throwing intrinsic in any state, no dangling transition, no unreachable state).

## Verification

- `pytest lambdas/` — **861 passed**; `ruff`, `tofu fmt`, `tofu validate` clean.
- **Mutation-tested throughout**: 16 (byte-scan), 23 (assemble-report), 6 (terminals), 6
  (ParseError removal) — each caught, including the original ParseError bug reintroduced
  verbatim.
- **Deployed and verified live**: `RecordSuccess` reads all 11 fields in production; zero
  `StringToJson` in any deployed machine's `Parameters`.

**Deferred: the end-to-end run over a real folder** (user decision, 2026-07-21) — it will
run once SPEC-113 lands the UI, so the check is driven the way a user drives it rather than
by invoking verbs directly. A fixture script exists (clean baseline + dirty numerics +
duplicate rows + a drifting column + a verified-invalid-UTF-8 CP1252 file). That run is also
what will confirm the Athena result-key assumption above.

## Docs sweep (completion-ritual step 6)

**Nothing to do in the app, verified.** This spec is Lambda- and infra-side only; the arc
still has no user-facing surface (the file-browser entry point and report view are
SPEC-113), so SPEC-074's Help & guides gains its first data-quality guide when 113 lands,
not here. Component inventory untouched — it covers `apps/portal/src/` only. The three
**operator runbooks** under `docs/testing/` WERE updated: they documented the now-deleted
`ParseError` path and a `reason` field the terminal states no longer emit.
