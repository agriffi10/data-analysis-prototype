---
type: Spec
id: SPEC-042
title: "Query History Pagination — 7 per Page"
description: "Paginates the query history drawer client-side at 7 entries per page, newest first, with a Prev/Next pager over the in-memory list and no new fetch."
spec_status: Completed
depends_on: [SPEC-036, SPEC-034]
arc: query-editor-follow-ups
arc_order: 3
---

**Dependency notes:** SPEC-036 (query history panel UI), SPEC-034 (`getQueryHistory` / `useQueryHistory` — unchanged)
> **Design:** Built to the history drawer in `docs/design/query-workspace.html` + `design-system.md` §6 (history drawer). Adds a Prev/Next pager at the foot of the drawer, mirroring the results pager pattern from SPEC-038.

## Overview

The query history drawer (SPEC-036) lists a user's past queries newest-first and can hold up to `QUERY_HISTORY_MAX = 100` entries — a long, unbounded scroll. This spec paginates the drawer so it **always shows the 7 most recent queries first**, with a **Prev/Next pager** to step back through older entries 7 at a time. The full history is already loaded in memory by `useQueryHistory` (it's a single JSON object from S3), so this is purely a **client-side** pager over the in-memory list — no new fetch, no data-layer or IAM change. It follows the same replace-style pager the query-results table uses (SPEC-038), not the file-browser's append model (SPEC-037).

## Scope

### In Scope

- A **page size of 7** history entries (named constant), newest-first
- Page 1 always shows the **7 most recent** entries; **Next** steps to the next-older 7 (replace, not append); **Prev** steps back toward newest
- A pager at the foot of the history drawer with Prev/Next controls and a range/page indicator (e.g. "1–7 of 23")
- Disabled states: **Prev** disabled on page 1; **Next** disabled on the last page (fewer than a full page / no older entries)
- Resetting to page 1 when the drawer is reopened and when a new entry is appended (so the newest query is always visible on open)
- Purely client-side pagination over the already-loaded `useQueryHistory` list

### Out of Scope

- Any change to `getQueryHistory` / `appendQueryHistory` / `updateQueryHistoryEntry` or the `query-history.json` store (SPEC-034) — unchanged
- Server-side / token-based paging of history (the whole capped-100 list is already in memory; not worth a fetch boundary)
- Delete / clear / search / filter of history (history remains read-only per SPEC-036; search is a possible future spec)
- Changing `QUERY_HISTORY_MAX` (still 100) or the results/file-browser page sizes
- Infinite scroll / "Load more" for history (deliberately a Prev/Next pager, per user decision)

---

## Functional Requirements

### FR-001: 7-entry page size, newest-first

#### Description:

History is shown 7 entries at a time, most-recent first.

#### Acceptance Criteria:

- [ ] A named constant `QUERY_HISTORY_PAGE_SIZE = 7` (in `query.constants.ts`) is the single source of truth for the history page size
- [ ] Entries are ordered newest-first (as today, SPEC-036); page 1 contains the 7 most recent entries
- [ ] If the user has ≤7 entries, the single page shows them all and **both** pager controls are disabled
- [ ] If the user has 0 entries, the existing SPEC-036 empty state renders (no pager shown)

### FR-002: Prev/Next pager (replace, not append)

#### Description:

A pager replaces the visible 7 entries when navigating, like the results pager (SPEC-038).

#### Acceptance Criteria:

- [ ] A pager at the foot of the history drawer shows **Prev** and **Next** controls plus a **range** indicator in the form `"1–7 of N"` (matching the SPEC-038 results pager); styled per `design-system.md` §6, reusing the ghost-button pager pattern (never color-only state)
- [ ] The drawer renders **only the current page's ≤7 entries** — not earlier/later pages
- [ ] **Next** advances toward older entries (the next 7); **Prev** returns toward newer entries; navigation replaces the visible list
- [ ] **Prev** is disabled on page 1 (newest); **Next** is disabled on the last page (the oldest partial/full 7 — no older entries remain)
- [ ] The total entry count is known (the full list is in memory), so the indicator can show a definitive total (e.g. "8–14 of 23") — unlike the Athena results pager, no "unknown total" caveat applies

### FR-003: Reset-to-newest on open and on new entry

#### Description:

The pager returns to page 1 so the newest query is always visible when it matters.

#### Acceptance Criteria:

- [ ] Reopening the history drawer resets the pager to page 1 (newest 7)
- [ ] When a new history entry is appended in-session (a fresh Run, SPEC-034 FR-007), the pager resets to page 1 so the just-run query is visible at the top
- [ ] In-session status updates (an entry transitioning to SUCCEEDED/FAILED/CANCELLED, SPEC-036) update in place without forcing a page change
- [ ] If the current page becomes out of range because the list shrank (e.g. capped at `QUERY_HISTORY_MAX`), the pager clamps to the last valid page (never a blank page)

### FR-004: Tests + lint

#### Acceptance Criteria:

- [ ] `npm run test` + `npm run lint` pass; tests cover: page 1 shows the newest 7; Next/Prev move by 7 and replace the list; disabled states at first/last page and with ≤7 entries; reset-to-page-1 on reopen and on append; clamp when the list shrinks

---

## Data Model

No new domain types. Consumes the existing `QueryHistoryEntry[]` from `useQueryHistory` (SPEC-034). Adds one constant:

```ts
// apps/portal/src/features/query/query.constants.ts

// SPEC-042: the history drawer shows this many entries per page (newest-first),
// with a Prev/Next pager. Client-side only — the full capped-100 list is already
// in memory (useQueryHistory), so paging is a slice, not a fetch.
export const QUERY_HISTORY_PAGE_SIZE = 7;
```

## API / Interface Contract

Pagination is a thin slice over the in-memory list — no service change. The pager state can live in `QueryHistoryPanel` (or a small `useState` page index), e.g.:

```ts
// Within QueryHistoryPanel (newest-first `entries` from useQueryHistory):
const pageCount = Math.max(1, Math.ceil(entries.length / QUERY_HISTORY_PAGE_SIZE));
const start = pageIndex * QUERY_HISTORY_PAGE_SIZE;
const pageEntries = entries.slice(start, start + QUERY_HISTORY_PAGE_SIZE);
const hasPrev = pageIndex > 0;            // newer entries exist
const hasNext = pageIndex < pageCount - 1; // older entries exist
// reset pageIndex to 0 on open and when entries length grows from an append
```

## File & Folder Structure

```
apps/portal/src/features/query/
├── query.constants.ts          ← + QUERY_HISTORY_PAGE_SIZE = 7
├── QueryHistoryPanel.tsx       ← slice to current page + Prev/Next pager + reset logic
└── QueryHistoryPanel.test.tsx  ← + pagination tests
```

## Implementation Phases

### Phase 1: History pager (single phase — small spec)

- Add `QUERY_HISTORY_PAGE_SIZE = 7`
- Slice the newest-first list to the current page in `QueryHistoryPanel`; add the Prev/Next pager + range indicator and disabled states (FR-001, FR-002)
- Reset to page 1 on drawer open and on append; clamp when the list shrinks (FR-003)
- Tests for all of the above (FR-004)

#### Checkpoint

With >7 history entries, open the drawer → it shows the 7 newest and a pager reading "1–7 of N"; **Next** shows entries 8–14 (replacing the list), **Prev** returns to 1–7; **Prev** is disabled on page 1 and **Next** on the last page; with ≤7 entries both controls are disabled. Run a new query → drawer resets to page 1 with the new entry on top. Reopen the drawer → it's back on page 1. `npm run test` + `npm run lint` pass.

## Open Questions

- [x] **Resolved (2026-06-19):** history paging is a **Prev/Next pager showing 7 per page** (newest-first), matching the SPEC-038 results-pager pattern rather than the SPEC-037 append model.
- [x] **Resolved (2026-06-19):** the pager uses the **range form `"1–7 of N"`** (not "Page 1 of 4"), matching the SPEC-038 results indicator.
