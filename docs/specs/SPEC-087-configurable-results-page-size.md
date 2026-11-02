---
type: Spec
id: SPEC-087
title: "Configurable Query-Results Page Size (default 100)"
description: "Raises the query-results page size default to 100 and adds a rows-per-page control above the results table, applying to every result tab at once and persisting for the browser session."
spec_status: Completed
depends_on: [SPEC-038, SPEC-078, SPEC-080, SPEC-079]
---

**Dependency notes:** SPEC-038 (results pager / `useQueryResults`), SPEC-078 (result tabs), SPEC-080 (row-count stats), SPEC-079 (session-persisted per-user preference pattern)
## Overview

The query-results table shows a **fixed 20 rows per page** (SPEC-038 `QUERY_RESULTS_PAGE_SIZE`). Users want to see more rows at a glance and to control that number themselves. This spec (a) raises the **default page size to 100** and (b) adds a **user-adjustable "rows per page" control** above the results table. The chosen value is **workspace-global**: it applies to every result tab (SPEC-078) at once, and every currently-open result tab re-pages to the new size immediately — there is no per-tab page size. The preference persists per user for the browser session (matching the SPEC-079 layout-preset pattern), so it survives tab switches and reloads within a session and resets to the default when the session ends.

## Scope

### In Scope

- Change the default query-results page size from **20 to 100** (a named default constant).
- A **"Rows per page" control** rendered **above the results table, adjacent to the total-row-count stat**, letting the user set any integer page size.
- The setting is **workspace-global** — one value shared by all result tabs; there is no per-tab override.
- **Live application to every open result tab:** changing the value re-pages every mounted result set (each SPEC-078 result tab) to the new size, resetting each to page 1 and re-fetching page 1 at the new size.
- **Clamp to Athena's single-fetch maximum:** the accepted range is **1–1000** (`GetQueryResults` returns at most 1000 rows per call, and this spec keeps one display page = one fetch). Out-of-range / non-numeric input is corrected to the nearest valid value (or reverts to the last valid value).
- **Per-user session persistence** of the chosen value (sessionStorage, per-user key), so it carries across query-tab switches and reloads within the session.

### Out of Scope

- **Page sizes above 1000** (would require stitching multiple `GetQueryResults` fetches into one display page — explicitly rejected this round; the cap is 1000, user decision 2026-07-04).
- Changing the **file-browser** page size (SPEC-037, 25/append), **query-history** page size (SPEC-042, 7), or **notifications** page size (SPEC-060, 10) — this spec is query-results only.
- The **background total-row-count walk** (SPEC-080) — it keeps its own `ROW_COUNT_PAGE_SIZE = 1000` and is unaffected by the display page size.
- A **per-result-tab** page size (the requirement is one global value that all tabs reflect).
- Persisting the value **across sessions** (localStorage) or to the user's server-side settings — session-scoped only.
- Virtualized rendering — a large page (up to 1000 rows) mounts that many rows by design; no virtualization is added here.

---

## Functional Requirements

### FR-001: Default page size of 100

#### Description:

The default query-results page size becomes 100, replacing the fixed 20. It remains a single named constant that is the source of truth when the user has not chosen a value.

#### Acceptance Criteria:

- [ ] A named constant `DEFAULT_RESULTS_PAGE_SIZE = 100` (in `query.constants.ts`) replaces `QUERY_RESULTS_PAGE_SIZE = 20` as the default; all prior references resolve to the new default when no user value is set.
- [ ] With no stored preference, a succeeded `SELECT` returning >100 rows shows exactly 100 data rows on page 1 (header row stripped, not 99 — the SPEC-038 first-page `+1` net-full-page behavior is preserved at the new size).
- [ ] `MIN_RESULTS_PAGE_SIZE = 1` and `MAX_RESULTS_PAGE_SIZE = 1000` constants define the accepted range and are the single source of truth for clamping (FR-003).

### FR-002: "Rows per page" control above the results table

#### Description:

A control above the results table, next to the total-row-count stat, displays the current page size and lets the user change it.

#### Acceptance Criteria:

- [ ] The control is rendered **above the results grid**, adjacent to the total-row-count / stats readout (not in the Prev/Next pager below the grid).
- [ ] It shows the current effective page size and accepts a new integer value (free-form entry; a stepper/select affordance is acceptable so long as any integer in range can be set).
- [ ] Committing a new value (blur / Enter / selection) updates the page size; transient keystrokes do not trigger a refetch per character (commit-on-blur/Enter, not per-keystroke).
- [ ] The control is keyboard-accessible and labeled (accessible name "Rows per page"); state is never conveyed by color alone (a11y, SPEC-045 suite must pass).
- [ ] When no result set is present (empty state / DDL-only run), the control is **disabled** (rendered but non-interactive, showing the current value) — never hidden, and it never errors.

### FR-003: Validation and clamping

#### Description:

Only integers in the range 1–1000 are accepted; anything else is corrected rather than allowed to break paging.

#### Acceptance Criteria:

- [ ] A value below 1 is corrected to 1; a value above 1000 is corrected to 1000.
- [ ] Non-numeric, empty, or fractional input reverts to the last valid value (or the default if none) — it never sets an invalid page size and never throws.
- [ ] The committed value is always an integer within `[MIN_RESULTS_PAGE_SIZE, MAX_RESULTS_PAGE_SIZE]`.

### FR-004: Workspace-global — every result tab reflects the change

#### Description:

The page size is one shared workspace value. Changing it applies to all result tabs (across the active query tab's result tabs, SPEC-078) simultaneously; there is no per-tab page size.

#### Acceptance Criteria:

- [ ] Changing the value re-pages **every currently-open result tab** to the new size — not just the active one.
- [ ] Each affected result set **resets to page 1** and its first page is (re-)fetched at the new size; the pager range indicator ("Rows 1–N") reflects the new size.
- [ ] Cached pages fetched at a previous size are not shown at the new size (the results query is re-keyed/invalidated by page size so stale-sized pages are not mixed in).
- [ ] The SPEC-080 total-row-count stat is unchanged by a page-size change (it walks at `ROW_COUNT_PAGE_SIZE` independently); only the displayed page and pager range change.
- [ ] Switching between query tabs (SPEC-041) shows the same global page size (it is not per query tab either).

### FR-005: Per-user session persistence

#### Description:

The chosen value persists per user for the browser session, mirroring the SPEC-079 layout-preset persistence.

#### Acceptance Criteria:

- [ ] The value is stored in `sessionStorage` under a per-user key (prefix + username) and restored on load, so it survives reloads and query-tab switches within the session.
- [ ] With no stored value, the effective size is `DEFAULT_RESULTS_PAGE_SIZE` (100).
- [ ] A malformed / out-of-range stored value falls back to the default (defensive read; never throws).
- [ ] The value does **not** persist to a new browser session (sessionStorage, not localStorage) — a fresh session starts at 100.

---

## Data Model

```ts
// apps/portal/src/features/query/query.constants.ts
export const DEFAULT_RESULTS_PAGE_SIZE = 100;   // was QUERY_RESULTS_PAGE_SIZE = 20
export const MIN_RESULTS_PAGE_SIZE = 1;
export const MAX_RESULTS_PAGE_SIZE = 1000;      // Athena GetQueryResults MaxResults ceiling (one page = one fetch)

/** sessionStorage key prefix for the per-user results page size (full key: prefix + username). */
export const QUERY_RESULTS_PAGE_SIZE_STORAGE_PREFIX = 's3portal.query.resultsPageSize.';

// Workspace-global page-size state exposed to every result tab:
export type UseResultsPageSizeResult = {
  pageSize: number;                 // effective, clamped, in [MIN, MAX]
  setPageSize: (value: number) => void; // clamps + persists; no-op if unchanged
};
```

## API / Interface Contract

```ts
// apps/portal/src/features/query/useResultsPageSize.ts
// Workspace-global, per-user session-persisted results page size. Provided once
// at the workspace level (context) so all result tabs read the same value and
// re-render together when it changes (FR-004). clamp() enforces FR-003.
export function useResultsPageSize(username: string): UseResultsPageSizeResult;

// SPEC-038 useQueryResults gains the shared page size and re-keys on it so a size
// change refetches page 1 at the new size and drops stale-sized cached pages:
useQueryResults(queryExecutionId: string | null, pageSize: number): UseQueryResultsResult;
//   - queryKey includes pageSize (e.g. queryKeys.results(executionId, pageSize))
//   - pageIndex resets to 0 for an execution when the active pageSize changes
//   - getQueryResults maxRows = pageSize (first page still requests pageSize + 1
//     to absorb the Athena SELECT header row, SPEC-038 FR-001)
```

## File & Folder Structure

```
apps/portal/src/features/query/
├── query.constants.ts        # DEFAULT/MIN/MAX_RESULTS_PAGE_SIZE + storage prefix (replaces QUERY_RESULTS_PAGE_SIZE)
├── useResultsPageSize.ts      # workspace-global, session-persisted page size (+ .test.ts)
├── useQueryResults.ts         # take pageSize; re-key + reset page on size change
├── ResultsPageSizeControl.tsx # "Rows per page" input above the grid (+ .test.tsx)
├── QueryResultsTable.tsx      # render the control above the table, near the stats
├── ResultTabs.tsx             # all result tabs consume the shared page size
├── QueryWorkspace.tsx         # provide useResultsPageSize to the results region
└── *.test.tsx                 # default=100, clamp 1..1000, global re-page, persistence
```

## Implementation Phases

### Phase 1: Default + constants + page-size state

- Replace `QUERY_RESULTS_PAGE_SIZE` with `DEFAULT_RESULTS_PAGE_SIZE = 100` and add `MIN`/`MAX` + storage prefix. Add `useResultsPageSize` (clamp + per-user sessionStorage read/write, defensive parse). Unit tests: default, clamp low/high, invalid→revert, persist/restore.

### Phase 2: Wire the shared size through the pager

- Thread the workspace-global page size into `useQueryResults` (re-key by pageSize, reset pageIndex on change, `maxRows = pageSize`, keep the first-page `+1` header handling). Ensure every result tab (SPEC-078) reads the same value and re-pages to page 1. Tests: size change refetches page 1 at new size, drops stale-sized pages, all tabs update, SPEC-080 count unaffected.

### Phase 3: The "Rows per page" control

- `ResultsPageSizeControl` above the results grid next to the stats; commit-on-blur/Enter; clamp + revert per FR-003; accessible name + keyboard support; hidden/disabled with no result set. Component tests + a11y (SPEC-045).

### Phase 4: Completion ritual

- Delivery doc, INDEX status, component-inventory rows (`useResultsPageSize`, `ResultsPageSizeControl`), and the SPEC-074 Help content sweep (a user-facing results control — add/adjust its guide).
