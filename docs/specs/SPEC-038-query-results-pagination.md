---
type: Spec
id: SPEC-038
title: "Query Results Pagination — 20 Rows per Page"
description: "Limits the query results table to 20 rows per page with a Prev/Next pager that replaces the visible rows, fetching later Athena pages lazily and caching them so paging back is instant."
spec_status: Completed
depends_on: [SPEC-034, SPEC-035]
---

**Dependency notes:** SPEC-034 (`getQueryResults` + `NextToken`), SPEC-035 (query workspace + results table)
> **Design:** Built to the results region of `docs/design/query-workspace.html` + `design-system.md` §6 (results table). This spec replaces SPEC-035 FR-006's results "Load more" with a fixed-size **pager**.

## Overview

A query can return far more rows than a browser should render at once. This spec makes the query-results table show a **maximum of 20 rows at a time** and page through the rest, so the UI only ever holds one page of rows in the DOM. Unlike the file browser's append-style "Load more" (SPEC-037), query results use a **Prev/Next pager** that *replaces* the visible rows — keeping exactly one 20-row page on screen. Forward pages are fetched lazily from Athena via `GetQueryResults` `NextToken` and cached, so paging back is instant.

This refines the SPEC-034 data layer and supersedes SPEC-035 FR-006's "Load more" for results; no new dependency, no IAM change.

## Scope

### In Scope

- A query-results page size of **20 rows** (named constant), driving `GetQueryResults` `MaxResults`
- A **Prev/Next pager** under the results table that shows one 20-row page at a time (replace, not append), with a page/range indicator
- Lazy forward fetching of pages via `NextToken`, cached with `useInfiniteQuery` so **Prev** reads from cache (no refetch) and **Next** fetches the next page only when not already loaded
- Correct Athena header-row handling so page 1 shows a full 20 data rows (not 19)
- Disabled/enabled states: Prev disabled on page 1; Next disabled when the current page is the last (no `NextToken`) — with a loading state while a forward page is in flight
- Replacing SPEC-035 FR-006's results "Load more" with this pager (the file-browser "Load more" is unaffected)

### Out of Scope

- File-browser listing pagination (SPEC-037 — 25 items, append)
- Changing the page size of the schema browser or history panel
- Client-side sorting/filtering of result rows (future)
- Typed per-column coercion of cell values (SPEC-034 keeps `string[][]`)
- Virtualized rendering (unnecessary — only 20 rows are mounted at a time)
- CSV download (unchanged — it downloads the full raw result object, SPEC-034 `getResultCsvUrl`)

---

## Functional Requirements

### FR-001: 20-Row Page Size

#### Description:

Results are fetched and displayed 20 rows at a time.

#### Acceptance Criteria:

- [ ] A named constant `QUERY_RESULTS_PAGE_SIZE = 20` (in `query.constants.ts`) is the single source of truth; `getQueryResults` (SPEC-034 FR-004) passes it to `GetQueryResults` `MaxResults`
- [ ] **Header-row handling:** for a `SELECT`, Athena returns the column names as the first data row of the *first* page. To net a full 20 data rows on page 1, the first request uses `MaxResults = QUERY_RESULTS_PAGE_SIZE + 1` (21) and drops the header row; subsequent pages use `MaxResults = 20`. Column names always come from `ResultSetMetadata`, not the header row. A comment documents this Athena foot-gun (already flagged in SPEC-034 FR-004)
- [ ] DDL / zero-row results yield an empty page (no rows, columns from metadata if any), rendering the empty state — never an error

### FR-002: Prev/Next Pager (Replace, Not Append)

#### Description:

A pager shows exactly one 20-row page; navigating replaces the visible rows.

#### Acceptance Criteria:

- [ ] Below the results table, a pager shows **Prev** and **Next** controls plus a range/page indicator (e.g. "Rows 1–20" or "Page 1"); styling per `design-system.md` §6 (reuse ghost buttons; never color-only state)
- [ ] The table renders **only the current page's ≤20 rows** — earlier/later pages are not in the DOM (the "only pull a certain number into the UI" requirement)
- [ ] **Next** advances to the next page: if that page is already cached it renders immediately; otherwise it fetches forward via `NextToken` (loading state shown), then renders. **Next is disabled** when the current page has no `NextToken` (last page)
- [ ] **Prev** returns to the previous page, always served **from cache** (no refetch). **Prev is disabled** on page 1
- [ ] The page indicator reflects the current page; total row count is shown when known (i.e. once the last page is reached — Athena doesn't return a total up front, so the indicator shows "Rows X–Y" and only shows a definitive total after the final page is loaded — documented)

### FR-003: Caching & Hook

#### Acceptance Criteria:

- [ ] `useQueryResults` (SPEC-034 FR-004) is implemented on `useInfiniteQuery` keyed by `queryExecutionId`, with each page = 20 rows and `getNextPageParam` reading the Athena `NextToken`; fetched pages stay cached for instant Prev
- [ ] A small UI-state value tracks the current page index; it resets to page 1 when a new query is run (new `queryExecutionId`)
- [ ] Switching away from and back to the results (e.g. via the history panel re-opening, SPEC-036) does not lose cached pages for the same execution id within the cache window

### FR-004: Supersede SPEC-035 Results "Load more"

#### Acceptance Criteria:

- [ ] SPEC-035 FR-006's results "Load more" control is replaced by this pager; a note is added to SPEC-035 FR-006 pointing here. The file-browser "Load more" (SPEC-015/037) is untouched
- [ ] `npm run test` + `npm run lint` pass; tests cover the header-row net-20 behavior, Next-fetch-forward, Prev-from-cache, and the disabled states

---

## Data Model

No new domain types. Consumes SPEC-034 `QueryResultPage` (`columns`, `rows: string[][]`, `nextToken?`). Adds `QUERY_RESULTS_PAGE_SIZE = 20` to `query.constants.ts`.

## API / Interface Contract

```ts
// SPEC-034 getQueryResults, called with the 20-row page size
getQueryResults({
  queryExecutionId,
  nextToken,                       // undefined → first page (requests 21, drops header)
  maxRows: QUERY_RESULTS_PAGE_SIZE // 20
}): Promise<ServiceResult<QueryResultPage>>;

// useQueryResults (useInfiniteQuery) exposes:
//   pages: QueryResultPage[]      (cached, 20 data rows each)
//   currentPageIndex, setPage     (UI pager state)
//   hasNext (current page has nextToken), hasPrev (index > 0)
//   fetchNextPage, isFetchingNextPage
```

## File & Folder Structure

```
apps/portal/src/features/query/
├── query.constants.ts        ← + QUERY_RESULTS_PAGE_SIZE = 20
├── query.service.ts          ← getQueryResults: header-row net-20 on page 1
├── useQueryResults.ts        ← useInfiniteQuery (20/page) + pager state
├── QueryResultsTable.tsx     ← renders current page only + Prev/Next pager
└── QueryResultsTable.test.tsx
```

## Implementation Phases

### Phase 1: 20-row pages + pager (single phase — small spec)

- FR-001, FR-002, FR-003, FR-004

#### Checkpoint

Run a `SELECT` returning >20 rows: the table shows exactly 20 rows and a Prev/Next pager; page 1 shows 20 *data* rows (header stripped, not 19); **Next** loads page 2 (fetching forward the first time, instant on return), **Prev** is instant from cache; Next is disabled on the last page, Prev on the first; only 20 rows are in the DOM at any time. A ≤20-row result shows no enabled Next. A DDL/zero-row result shows the empty state. `npm run test` + `npm run lint` pass.

## Open Questions

- [x] **Resolved (2026-06-17):** query results use a **Prev/Next pager (replace, 20 rows/page)**, not append-style "Load more" — so only one page is ever in the UI ("only pulling a certain number into the UI"). This differs deliberately from the file browser's append "Load more" (SPEC-037), matching the user's distinction.
- [ ] **Total-count display.** Athena doesn't return a total row count up front; the indicator shows "Rows X–Y" and a definitive total only once the final page is reached. Confirm this is acceptable vs. issuing a separate `SELECT COUNT(*)` (rejected for v1 — extra cost/scan). Default: no count query.
