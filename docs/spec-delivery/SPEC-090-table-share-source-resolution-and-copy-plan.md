# Completed Spec — SPEC-090: Table Share Source Resolution & Copy Plan (inspect-source)

## What was completed?

- **Real `inspect-source`** (`table_share_inspect_source.py`): Glue `GetTable` on the source → shape validation → **definition clone** → object listing → caps → emits `{…request, tableDefinition, location:{bucket,prefix}, objects:[{relKey,size}], partitioned}` for the recipient Map.
- **Shape rejections** (whole-request terminals): `source_is_view`, `source_not_external`, `source_catalog_partitioned` (partition keys without `projection.enabled=true`), `source_location_unsupported`, `source_not_found`, `source_not_readable` (LF `AccessDenied` — resolves once SPEC-092 makes the role an LF admin), `source_empty`, `source_too_large`.
- **`tscommon.glue`**: `get_table` (error-code mapping; other failures → `TransientError` for SFN Retry) + `clone_definition` (columns/partitionKeys/SerDe/formats/`TBLPROPERTIES` carried verbatim; `LOCATION`, catalog identity, `transient_lastDdlTime`, `EXTERNAL` stripped).
- **`tscommon.s3_listing`**: paginated listing emitting **prefix-relative** keys + sizes with the shared ignore rules.
- **Caps** (named constants): `SHARE_MAX_OBJECTS = 1000`, `SHARE_MAX_TOTAL_BYTES = 20 GiB` (sized for copy-objects' 900s timeout; "too large for v1 — S3 Batch Ops deferred" reason).
- **Infra**: `USER_SPACE_BUCKET`/`SHARED_SPACE_BUCKET` module vars + execution-role `s3:ListBucket`/`GetBucketLocation` on both buckets; **the full tscommon-required env is now COMMON to all five verbs** (the PR #196 env-union rule); `tscommon.clients.glue()` added.

In-session decisions (reversible, documented):

- **LOCATION rule (architecture §12 nailed):** must parse as `s3://bucket/prefix` with the bucket ∈ {user-space, shared-space}; prefix normalized to a trailing slash (an object-level LOCATION lists empty → `source_empty`).
- **Ignore rules extended segment-wise:** any `_`/`.`-prefixed path **segment** (e.g. Spark `_temporary/`) excludes the object — Athena ignores those directories, so the copy plan must too (extends the table-builder's basename-only rule).
- **Caps chosen:** 1000 objects / 20 GiB.

## What changed from earlier specs?

- SPEC-088's inspect-source placeholder replaced. SPEC-089's tscommon `config` gained the bucket names + caps (all `_require`d vars now common env). No SFN shape change (089 already routes InspectSource's Catch → recorded failure and retries `TransientError`).

## Verification

16 new inspect-source unit tests (+ the validate suite re-run, 15) — shape matrix, clone fidelity, projection carry, LOCATION rules, ignore rules/relative keys, both caps, transient-vs-terminal Glue mapping; `tofu fmt`/`validate` + template render checks green. Live happy-path `GetTable` on an LF-gated DB stays blocked until SPEC-092's LF-admin wiring (expected; `source_not_readable` is the interim terminal) — end-to-end share is SPEC-092's live check. Nothing user-facing (no Help change); component inventory untouched (backend-only).
