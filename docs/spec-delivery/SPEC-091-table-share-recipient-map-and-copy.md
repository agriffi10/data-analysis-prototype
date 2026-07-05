# Completed Spec — SPEC-091: Table Share Recipient Map + Copy

## What was completed?

- **Real `check-target-absent`** (`table_share_check_target_absent.py`): short-circuits recipients SPEC-089 annotated invalid (their `unknown_user`/`unknown_space` reason becomes the per-recipient terminal); resolves the destination by kind (`user` → `{name}/shared_tables/{tableName}/` in the user-space bucket, `space` → the shared-space bucket); fails the recipient `conflict` when the table exists in the recipient DB **or** the destination prefix is non-empty (leftover-partial-run guard, architecture §12 confirmed). Self-share under the same name conflicts naturally.
- **Real `copy-objects`** (`table_share_copy_objects.py`) + **`tscommon.copy`**: bounded-parallel (8 workers) server-side copy of every planned object to `{dest}/{relKey}` (layout preserved); objects > 5 GiB use multipart `UploadPartCopy` (1 GiB ranges, abort on failure); throttle-class errors → `TransientError` (SFN retries the idempotent verb), deterministic failures → `copy_failed`.
- **`tscommon.glue.table_exists`**: recipient conflict probe (`EntityNotFound` → False; `AccessDenied` → `target_not_readable` until SPEC-092's LF admin; else transient).
- **SFN Map hardening**: `MaxConcurrency: 5`; per-item `Catch → RecipientParseError → RecipientFailed` shaping `{recipient, status:'failed', reason}`; success path ends in a `RecipientSucceeded` Pass shaping `{recipient, status:'ok'}` (SPEC-092 finalizes); `TransientError` added to the three inner Retry lists.
- **Execution-role grants**: `s3:GetObject` on both data buckets (copy source), `PutObject`/`AbortMultipartUpload`/`ListMultipartUploadParts` scoped to `*/shared_tables/*` in both buckets, and an explicit `s3:DeleteObject` **Deny** on both buckets + the admin bucket.

## What changed from earlier specs?

- SPEC-088's check-target-absent/copy-objects placeholders replaced; the skeleton `RecipientFailed` Pass gained the structured shape. No new module variables (buckets landed with SPEC-090).

## Verification

14 new unit tests (8 conflict-guard + 6 copy: layout, multipart ranges/abort, transient-vs-terminal mapping, concurrency bound) — all four table-share suites 45 green; `tofu fmt`/`validate` + policy render checks. Live per-recipient path stays blocked on the LF-admin wiring (`target_not_readable`) until SPEC-092, whose end-to-end share is the arc's live check. Nothing user-facing (no Help change); backend-only (no inventory rows).
