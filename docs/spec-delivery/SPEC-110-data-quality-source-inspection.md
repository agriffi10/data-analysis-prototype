# Completed Spec — SPEC-110: Data Quality — Source Inspection (`inspect-source`)

The arc's second verb: list an authorized location, classify by extension, enforce one
format, probe every file's header, detect Hive partitions, write the manifest and pass its
KEY onward. Shipped in two PRs (#228 phases 1–2, #230 phase 3) plus a mapper consolidation
(#229). No new infra — SPEC-108 wired the state and the polars layer; SPEC-109 granted the
S3 reads.

## What was completed?

- **`dq_inspect_source.py`** — `_classify` (strip-one-`.gz`; bare `.gz` and `.parquet.gz`
  rejected; `.txt`→csv and `.parquet` are deliberate divergences from table-builder's map),
  `_resolve_listing_prefix` (head_object folder-vs-file; a folder lists WITH a trailing
  slash, and a zero-byte hit IS a folder placeholder), `_enforce_caps`, `_resolve_format`,
  `_probe_columns` (polars, uniform `{name, type}`), `_stream_gzip_head`/`_read_gzip_head`,
  `_detect_partition_keys`, `_write_manifest`.
- **`dqcommon.config`** — `DQ_MAX_GZIP_OBJECT_BYTES`, `DQ_MAX_PARTITION_VALUES`,
  `EXT_FORMAT`, and `_validate_caps()` (FR-004's validate-at-import).
- **`dqcommon.messages`** — this verb's 8 reason codes as exported constants.
- **The manifest** = `{space}/_data-quality-reports/{requestId}/manifest.json`, a pure
  function of `requestId`. Measured at the caps (1000 files × 1024-char keys × 50 cols):
  manifest **2.6 MB**, state payload **312 bytes** (840× under SFN's 256 KB).

Deviations, each a spec correction made in-flight:

- **FR-007 added.** Registration could NOT wait for SPEC-114: `TerminalError` validates its
  reason at construction against a process-global set, and `pytest lambdas/` imports
  tbcommon (which registers `no_data_files`/`unsupported_format`/`mixed_formats`) while the
  deployed function does not — so three codes would have passed CI and raised `ValueError`
  in production. SPEC-114 keeps the arc-wide registry; its FR-002 gained a note that the
  test must assert dqcommon's own table, not `is_known_reason`.
- **`columns` is `{name, type}`, not bare names** — SPEC-111 FR-002 needs a type per column
  (Athena does not auto-detect a Parquet schema). CSV is all-`"string"`, which IS the CSV
  type under its OpenCSVSerde.
- **`partition_layout_mismatch` added** (user decision) — a folder whose objects disagree on
  Hive keys would leave files outside the projected partitions unscanned and **silently
  omitted** from the report.
- **FR-006's "only" clarified to "adds only"** (user decision) — a literal reading drops
  `requestId`/`actor`, and the terminal Pass states hard-fail on an absent JSONPath key with
  an uncatchable `States.Runtime`, skipping `NotifyFailure` entirely.
- **`too_many_partition_values` is unreachable at the shipped defaults** — N values imply
  ≥N objects, so the object cap always fires first. Kept (it goes live if `DQ_MAX_OBJECTS`
  rises), documented in `config.py`, pinned by a test.

## What changed from earlier specs?

- **All nine DQ verb modules renamed `handler.py` → `dq_<verb>.py`** (user decision),
  reversing SPEC-108's uniform-handler choice and updating `locals.tf`'s nine handler
  strings. "The verb directory disambiguates" holds for Lambda, where each function is its
  own zip, but not for pytest, which flattens every verb dir into ONE module namespace —
  SPEC-109's tests were silently importing this verb's handler. The `dq_` prefix is needed
  because table-builder owns the bare names. SPEC-115/116 corrected so the file-converter
  arc doesn't inherit it. SPEC-109's delivery doc records the reversal.
- **`cpcommon/type_mapping.py` is new** (#229) — the polars→Hive mapper consolidated from
  table-builder's verb dir + this arc's copy. `table-builder-infer-schema/type_mapping.py`
  deleted and its import repointed. Safe only because `cpcommon/__init__.py` imports no
  submodules; see that module's docstring before importing it from a polars-free verb.
- **`cpcommon.messages.Resolver.body`** unchanged, but `dqcommon.failure_message` now takes
  `**tokens`.

## Verification

`pytest lambdas/` (485 passed; the verb, `dqcommon.config`/`messages` and `type_mapping` at
100%), `ruff`, `tofu fmt`/`validate`, and a check that all nine `locals.tf` handlers resolve
to a real module — which caught a real break mid-work. Every guard in the verb is
**mutation-tested**: each one, deleted, fails a test. That was not cosmetic — it caught a
vacuous `.gz` bound test (the fixture was smaller than the bound, so the probe always
stopped on line count) and, behind it, a real **compression-bomb OOM** (392 KB compressed →
381 MB held; ~8 GB at the full bound against a 1024 MB function), which an OOM being not a
`TerminalError` would have delivered as no notification at all.

Deferred to deploy: an end-to-end SFN run. The pipeline cannot complete until SPEC-111
replaces the `CreateTempTables` stub, so `inspect-source`'s real-S3 behaviour (polars over
`s3://`, the gzip stream) is unexercised in production until then.

**Docs sweep (completion-ritual step 6): nothing to do, verified.** This spec touches no
`apps/` code and the arc has no user-facing surface — nothing calls `enqueueQualityCheck`
yet; the file-browser entry point and report view are SPEC-113 (Draft). SPEC-074 FR-005
documents only what is shipped AND wired end-to-end, so Help & guides gains its first
data-quality guide when SPEC-113 lands, not here. Component inventory likewise untouched:
it covers `apps/portal/src/` only, and this spec is Lambda-side.
