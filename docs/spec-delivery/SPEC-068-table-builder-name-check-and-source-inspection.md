# Completed Spec — SPEC-068: Table Builder Name Uniqueness + Source Inspection

## What was completed?

The two gathering/validation verbs between `validate-authorize` and `infer-schema` —
real logic replacing the SPEC-066 echo stubs. **Lambda code + tests only**: SPEC-066
already shipped the final-shape per-verb IAM (check-table-absent = Glue read;
inspect-source = S3 list+get) and the linear SFN wiring, so no infra change.

- **`check-table-absent`** (`lambdas/table-builder-check-table-absent/`) — Glue
  `GetTable(database, tableName)`; `EntityNotFoundException` ⇒ pass the request through;
  a table that exists ⇒ terminal `table_exists`. Transient Glue errors **raise** (SFN
  `Retry`), never terminalized. New `tbcommon.clients.glue()` factory.
- **`inspect-source`** (`lambdas/table-builder-inspect-source/`) — paginated list of
  `space.prefix`, then: **layout** validated against the request's **user-declared**
  `partitionKeys` (empty ⇒ flat / no `key=value/`; non-empty ⇒ each declared key as an
  ordered Hive segment) and **format** (single supported Parquet/CSV/JSON by extension).
  Emits `{…request, format, partitioned, sampleObjectKey, location, fileCount}`. Terminal
  reasons: `unexpected_partitioning` / `partition_layout_mismatch` / `mixed_formats` /
  `no_data_files` / `unsupported_format`.
- **`tbcommon.s3_listing`** (NEW, in the layer) — the shared paginated lister + ignore
  rules (marker `DO_NOT_DELETE.txt`, `athenaresults/`, zero-byte, `_`/`.`-prefixed), so a
  normal space folder isn't misread. One source of the "what counts as data" rule.
- **CI** — `deploy-lambdas.yml` flips `tbcommon: true` for check-table-absent +
  inspect-source (they now import the `tbcommon` package from the layer).

## What changed from earlier specs?

- The SPEC-066 `check-table-absent` / `inspect-source` **stubs** became real; SFN ASL +
  IAM unchanged (SPEC-066 shipped them final-shape).
- `tbcommon` gained `clients.glue()` + the `s3_listing` module (both ride the existing
  `table-builder-common` layer build — it copies the whole package).

## Verification

**15** unit tests (check-table-absent: pass / `table_exists` / transient-raise /
targets-declared-DB; inspect-source: flat-Parquet, partitioned-CSV match, JSON variants,
every terminal reason, ignore-rules via a fake paginator). Full `pytest lambdas/` =
**153 passed** (no `tbcommon`/`shared-space-common` collision); `ruff check lambdas/`
clean.
