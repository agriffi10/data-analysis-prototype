# Completed Spec — SPEC-105: View Data — Full Table, Paginated

## What was completed?

The schema-rail **View data** action now browses the whole table instead of a 10-row preview.

- `QueryWorkspace`'s `onViewData` opens the `{table}` tab pre-filled with an **unbounded** `SELECT * FROM {database}.{table}` (fully-qualified per SPEC-077, **no `LIMIT`**) and auto-runs it — same open-tab + auto-run flow. Behaves identically for views.
- The full result set pages through the existing results pager at the user's configured "Rows per page" (SPEC-087); the status-bar total-row count (SPEC-080) reflects the full table. No pager/pipeline/history change.
- Retired the now-unused `TABLE_PREVIEW_ROW_LIMIT` constant + its barrel export.

**No `LIMIT` / client-side cap** (user decision 2026-07-08): the Athena workgroup bytes-scanned cutoff is the cost guard, as for any user query.

## What changed from earlier specs?

- SPEC-044's "View data" SQL changed (`… LIMIT 10` → unbounded). `TABLE_PREVIEW_ROW_LIMIT` (SPEC-044) removed from `query.constants.ts` + `features/query/index.ts`.

## Verification

`format` + `lint` + `tsc -b` + `build` clean; full suite green (1118). The `QueryWorkspace` "View data" test now asserts the tab SQL is exactly `SELECT * FROM alice.sales_2026` with no `LIMIT` token; no source/test references the retired constant.
