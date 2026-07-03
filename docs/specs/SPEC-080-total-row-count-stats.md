# Spec: Total Row Count in Query Stats

**ID:** SPEC-080
**Status:** Completed
**Last Updated:** 2026-07-01
**Depends On:** SPEC-038 (results pager / `useQueryResults`), SPEC-035 (status bar)

## Overview

The query status bar reports rows as the count **currently loaded** into the pager
with a trailing `+` when more pages exist (e.g. "20+ rows"), because Athena gives no
up-front total and the SPEC-038 pager only knows the definitive total once the user
has paged to the last page. Users want the **exact total row count** of a succeeded
query shown in the stats **regardless of which page they're viewing** — i.e. "1,384
rows", not "20+ rows". This spec computes the true total by **walking every result
page in the background** after a query succeeds (Athena's `GetQueryResults` calls are
free — no extra data scanned), counting rows without rendering them, and surfaces the
count in the status bar as soon as it's known.

## Scope

### In Scope

- After a query reaches `SUCCEEDED`, count its total result rows by paging through
  all `GetQueryResults` pages in the background (large `MaxResults` per page to
  minimize round-trips), independent of the user-facing pager's current page.
- Show the exact total in the status bar ("1,384 rows"); while the count is still
  being computed, show a pending indicator (keep the existing loaded-count "N+"
  form until the exact total resolves).
- Cap the walk at a safety ceiling so a pathologically large result can't page
  forever; beyond the ceiling, display "{ceiling}+ rows" and stop.
- Reset/recompute per query execution (a new run starts a fresh count).
- Correctly report **0 rows** for a succeeded SELECT that returned none, and show
  **no** row count for a DDL/no-result statement (nothing to count).
- Cancel/abandon an in-flight count if the active tab's execution changes (tab
  switch, new run) so background work doesn't leak.

### Out of Scope

- A `COUNT(*)` wrapper query (rejected: extra Athena execution + scan cost/latency).
- Reading/parsing the raw result CSV from S3 to count lines (rejected: downloads the
  whole object).
- Changing the pager itself (page size, Prev/Next) — the visible page is unchanged;
  only the reported total changes.
- Persisting the total across reloads — it recomputes from the (still-valid)
  execution id when the results are shown again.
- Streaming a live count in the table body — this is a status-bar stat only.

---

## Functional Requirements

### FR-001: Background full count on success

#### Description:

When the active query is `SUCCEEDED` and returned a result set, count its total rows
by paging all `GetQueryResults` pages in the background (threading `NextToken`),
using a large page size to reduce round-trips, without mounting those rows.

#### Acceptance Criteria:

- [ ] For a result with more rows than one page, the reported total equals the true
      total once the walk finishes.
- [ ] The count uses `GetQueryResults` only (no new `StartQueryExecution`, no extra
      bytes scanned).
- [ ] The background walk does not disturb the user-facing pager's current page or
      cached pages.

### FR-002: Pending → exact display in the status bar

#### Description:

While the total is being computed, the status bar shows a pending form (the existing
loaded-count with `+`); when the walk completes, it shows the exact total, formatted
with thousands separators.

#### Acceptance Criteria:

- [ ] Before completion, the stat shows the loaded count with a `+` (today's
      behavior) or an explicit "counting…" affordance.
- [ ] After completion, the stat shows the exact total (e.g. "1,384 rows").
- [ ] A single-page result shows the exact total immediately (no lingering `+`).

### FR-003: Safety ceiling

#### Description:

The walk stops after a configured maximum number of rows; beyond it the stat shows
"{ceiling}+ rows" rather than paging indefinitely.

#### Acceptance Criteria:

- [ ] A result exceeding the ceiling stops the walk at the ceiling.
- [ ] The stat shows "{ceiling}+ rows" (formatted) in that case.
- [ ] Results at or below the ceiling always show an exact total.

### FR-004: Empty and no-result statements

#### Description:

A succeeded SELECT with zero rows reports 0; a DDL/no-result statement (no result
set) reports no row count at all.

#### Acceptance Criteria:

- [ ] A succeeded query returning no rows shows "0 rows".
- [ ] A DDL/CTAS/no-result statement shows no row-count stat (unchanged from today).

### FR-005: Reset / cancel per execution

#### Description:

The count is scoped to the active execution id: a new run or a tab switch to a
different execution abandons any in-flight count and (re)starts for the newly shown
execution.

#### Acceptance Criteria:

- [ ] Running a new query resets the total to pending and recomputes.
- [ ] Switching to another tab's succeeded result computes/shows that result's total.
- [ ] An abandoned count does not later overwrite the current execution's stat
      (stale-result guard).

---

## Data Model

```ts
// apps/portal/src/features/query/query.constants.ts
export const ROW_COUNT_PAGE_SIZE = 1000;      // GetQueryResults MaxResults for the count walk (max allowed)
export const ROW_COUNT_CEILING = 100_000;     // stop-walking safety ceiling

// Hook result (extends what QueryStatusBar consumes):
export type UseRowCountResult = {
  total: number | null;   // exact total once known; null while counting
  isCounting: boolean;    // walk in progress
  atCeiling: boolean;     // stopped at ROW_COUNT_CEILING → display "{ceiling}+"
};
```

## API / Interface Contract

```ts
// apps/portal/src/features/query/useResultRowCount.ts
// Given a succeeded execution id (null otherwise), walk all pages counting rows.
// Cancels on id change; never throws (a failed page leaves total = null / pending).
export function useResultRowCount(queryExecutionId: string | null): UseRowCountResult;

// QueryStatusBar gains the exact total + counting/ceiling flags and renders
// "1,384 rows" | "counting…" | "100,000+ rows" in place of today's "N+ rows".
```

The count walk reuses `getQueryResults` (SPEC-034 service) with `maxRows =
ROW_COUNT_PAGE_SIZE`, threading `nextToken`; it can share `useInfiniteQuery`'s cache
by key or run a dedicated lightweight loop — an implementation choice for the plan,
provided it does not perturb the visible pager.

## File & Folder Structure

```
apps/portal/src/features/query/
├── useResultRowCount.ts     # background page-walk counter (+ .test.ts)
├── QueryStatusBar.tsx       # exact total / counting / ceiling display
├── QueryWorkspace.tsx       # feed the active execution id → status bar total
├── query.format.ts          # thousands-separator formatting (reuse/extend)
└── query.constants.ts       # ROW_COUNT_PAGE_SIZE, ROW_COUNT_CEILING
```

## Implementation Phases

### Phase 1: Background counter hook

- `useResultRowCount`: page-walk with `ROW_COUNT_PAGE_SIZE`, ceiling cutoff,
  id-change cancel + stale-result guard, degrade-safe on a failed page. Unit tests
  (multi-page total, single-page immediate, empty=0, ceiling, cancel-on-change).

### Phase 2: Status-bar display

- Wire the hook into `QueryWorkspace` → `QueryStatusBar`; render exact total /
  "counting…" / "{ceiling}+"; keep DDL/no-result showing no count. Component tests.

### Phase 3: Completion ritual

- Delivery doc, INDEX status, component-inventory row (`useResultRowCount`).
