# Spec: View Data — Full Table, Paginated (drop the 10-row preview limit)

**ID:** SPEC-105
**Status:** Completed
**Last Updated:** 2026-07-08
**Depends On:** None

## Overview

The schema-rail table-options menu's **View data** action (SPEC-044) currently opens a query tab
pre-filled with `SELECT * FROM {db}.{table} LIMIT 10` and auto-runs it — so the user only ever sees the
first 10 rows. This spec changes View data to run an **unbounded `SELECT * FROM {db}.{table}`**, letting
the user browse the **entire** table through the existing results pager, with each page showing exactly
the number of rows the user has configured (SPEC-087, "Rows per page"). Nothing else about how queries
execute, paginate, or cost changes — the only functional change is the generated SQL (the `LIMIT` is
removed); the whole run → results → Prev/Next → total-row-count path is the shared machinery every query
already uses.

## Scope

### In Scope

- Change `QueryWorkspace`'s `onViewData` handler so the tab it opens is pre-filled with
  `SELECT * FROM {database}.{table}` (fully-qualified per SPEC-077) with **no `LIMIT`**, and auto-runs
  exactly as today.
- Rely on the **existing** results pagination to page the full result set at the user's configured
  results page size (SPEC-087) via Prev/Next (SPEC-038); one display page = one `GetQueryResults` fetch.
- Retire the now-unused `TABLE_PREVIEW_ROW_LIMIT` constant and its barrel export.
- Update the affected unit tests (they currently assert `LIMIT 10`).

### Out of Scope

- **No `LIMIT` or client-side safety cap.** View data runs a truly unbounded `SELECT *` (user decision,
  2026-07-08); the Athena **workgroup bytes-scanned cutoff remains the cost guard**, as it already is
  for any user-authored query.
- No change to the results pager, the "Rows per page" control (SPEC-087), the results table
  (SPEC-038/064), the run/execute/poll pipeline, query history, or the total-row-count walk (SPEC-080) —
  all are reused unchanged.
- No `ORDER BY` is added. Pagination walks a single query execution's **materialized** result set, which
  is stable within that execution; ordering across the table is not guaranteed (same as any `SELECT *`).
- No change to the other table-options items (View DDL, View source files, Drop table, Share table) or
  to the menu's labels/copy.
- No change to the opened tab's label (`{table.name}`), its auto-run behavior, or the tab-limit dialog.
- No data-layer, service, IAM, or infra changes.

---

## Functional Requirements

### FR-001: View data runs an unbounded, fully-qualified `SELECT *`

#### Description:

Selecting **View data** on a schema-rail table (or view) opens a tab labelled `{table.name}` pre-filled
with `SELECT * FROM {database}.{table.name}` — fully-qualified, **no `LIMIT`** — and auto-runs it, using
the same open-tab + auto-run flow as today.

#### Acceptance Criteria:

- [ ] Triggering View data for table `t` in database `d` opens a tab whose SQL is exactly
      `SELECT * FROM d.t` (fully-qualified, no `LIMIT` clause, no trailing `;` requirement change).
- [ ] The tab is labelled `{table.name}` and the query auto-runs into that tab (unchanged from today).
- [ ] The generated SQL contains no `LIMIT` token.
- [ ] View data behaves identically for a **view** (SPEC-048) — `SELECT * FROM {db}.{view}`, no `LIMIT`.
- [ ] If opening the tab is refused at the tab cap, the existing tab-limit dialog shows and no query
      runs (unchanged from today).

### FR-002: The full result set paginates at the user's page size

#### Description:

The View-data results render in the existing results table and pager. Each page shows the user's
configured "Rows per page" value (SPEC-087, default 100), and Prev/Next walk the entire result set —
no preview truncation.

#### Acceptance Criteria:

- [ ] The results table shows up to the configured page-size rows per page (not a fixed 10).
- [ ] Prev/Next page through the whole result set (one page = one `GetQueryResults` fetch), exactly as
      for any other query.
- [ ] The status bar's total-row count (SPEC-080) reflects the full table up to its ceiling (e.g.
      `12,480 rows`, or `100,000+ rows` past the ceiling) — not `10`.
- [ ] Changing "Rows per page" re-pages the View-data results the same way it does for any query.
- [ ] A table with zero rows renders the existing friendly empty state (not an error).

### FR-003: Retire the preview row-limit constant

#### Description:

`TABLE_PREVIEW_ROW_LIMIT` is no longer used and is removed, along with its barrel export, so no dead
constant remains.

#### Acceptance Criteria:

- [ ] `TABLE_PREVIEW_ROW_LIMIT` is deleted from `features/query/query.constants.ts`.
- [ ] Its re-export is removed from `features/query/index.ts`.
- [ ] No source or test file references `TABLE_PREVIEW_ROW_LIMIT`; the build, lint, and type-check pass.

---

## API / Interface Contract

The `onViewData` table-action signature is unchanged — only the SQL string it produces changes:

```ts
// features/query/QueryWorkspace.tsx — table actions
onViewData: (database: string, table: GlueTableSummary) => void;

// before: `SELECT * FROM ${database}.${table.name} LIMIT ${TABLE_PREVIEW_ROW_LIMIT}`
// after:  `SELECT * FROM ${database}.${table.name}`
```

## File & Folder Structure

```
src/features/query/
├── QueryWorkspace.tsx        # onViewData: drop `LIMIT ${TABLE_PREVIEW_ROW_LIMIT}`; remove its import
├── query.constants.ts        # remove TABLE_PREVIEW_ROW_LIMIT
├── index.ts                  # remove the TABLE_PREVIEW_ROW_LIMIT barrel export
└── QueryWorkspace.test.tsx   # update the View-data test: assert `SELECT * FROM d.t` (no LIMIT) +
                              #   full-table pagination at the configured page size
```

## Implementation Phases

### Phase 1: SQL change + constant retire + tests

- In `onViewData`, build `SELECT * FROM ${database}.${table.name}` (no `LIMIT`); remove the
  `TABLE_PREVIEW_ROW_LIMIT` import.
- Delete `TABLE_PREVIEW_ROW_LIMIT` from `query.constants.ts` and its export in `index.ts`.
- Update `QueryWorkspace.test.tsx` (the "View data opens a `{table}` tab and auto-runs" test) to expect
  the unbounded SQL, and add/adjust a test asserting the results paginate at the configured page size
  rather than a fixed 10.
- Run format / lint / unit tests green.
