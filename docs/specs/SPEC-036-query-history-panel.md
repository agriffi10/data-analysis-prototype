# Spec: Query History Panel UI

**ID:** SPEC-036
**Status:** Completed
**Last Updated:** 2026-06-18
**Depends On:** SPEC-034 (per-user history store + `useQueryHistory`), SPEC-035 (query workspace + editor)

> **Design:** Design-led. Build to the history panel in `docs/design/query-workspace.html` and `docs/design/design-system.md` §6 (the "drawer pattern (query history / saved queries)" reuse noted there). Visuals follow the design; behavior/data wiring follows this spec.

## Overview

Give each user a private, persistent view of the queries they have run, so they can revisit, re-open, and re-run past work. History is read exclusively from the per-user `{username}/athenaresults/query-history.json` store (SPEC-034) — never from Athena's workgroup history, which is shared across all users and would leak everyone's SQL. This spec is the presentation layer over the SPEC-034 history store, integrated into the SPEC-035 query workspace as a panel/drawer.

## Scope

### In Scope

- A **Query History panel** in the query workspace, listing the user's past queries newest-first (from `useQueryHistory`)
- Per-entry display: a truncated SQL preview, the target database, submitted time (relative + absolute on hover), terminal status badge (succeeded/failed/cancelled/running), and data-scanned/duration when present
- **Re-open**: clicking an entry loads its SQL back into the Monaco editor (does not auto-run)
- **Re-run**: an explicit action that loads + runs the entry's SQL via the SPEC-035 run path (which appends a new history entry)
- Open/close behavior consistent with the design (drawer/slide-over or side panel, reusing the SPEC-026 dialog/drawer patterns where applicable)
- Empty state (no history yet) and loading/error states

### Out of Scope

- Any change to the history storage schema or service functions (SPEC-034 owns them)
- Cross-device/real-time sync beyond what the JSON file provides (last-writer-wins per SPEC-034)
- Saved/named queries as first-class server objects (history is the JSON store only)
- **Deleting or clearing history** — history is **read-only** to the user in v1 (user decision); entries are only ever added/updated by the run flow (SPEC-034). No delete/clear controls
- Surfacing other users' or workgroup-wide history (explicitly never)
- Result re-fetch for old executions — the panel never re-fetches a past query's result objects (it only displays results for a query run in the current session); Re-open loads the stored SQL and Re-run re-executes. (Results are kept indefinitely per SPEC-032, but the panel still doesn't fetch them for history entries — it stores SQL + metadata, not result rows.)

---

## Functional Requirements

### FR-001: History Panel + List

#### Acceptance Criteria:

- [ ] A History panel/drawer is reachable from the query workspace (toggle control per the design); it lists entries from `useQueryHistory(username)` newest-first
- [ ] Each row shows: SQL preview (single line, ellipsis-truncated), database, submitted time (relative, with absolute ISO on hover/title), and a status badge using design status colors (`success`/`danger`/neutral; never color-only — include text/icon per §7)
- [ ] Data-scanned (human-readable bytes) and duration render when present on the entry
- [ ] Long histories scroll within the panel; the SPEC-034 cap (`QUERY_HISTORY_MAX`) bounds the list
- [ ] Loading and error states render per the design; a read error shows a `Banner`, not a crash

### FR-002: Empty State

#### Acceptance Criteria:

- [ ] When history is empty (new user, or missing `query-history.json` → empty per SPEC-034), a friendly empty state renders (icon + headline + guidance to run a query), not an error — consistent with the architecture's "missing config = empty state" rule

### FR-003: Re-open

#### Acceptance Criteria:

- [ ] Clicking an entry (or an explicit "Open in editor" action) loads its `sql` into the Monaco editor, replacing current content, and focuses the editor; it does **not** auto-run
- [ ] If the editor has unsaved/modified content, the design's chosen behavior applies (replace directly in v1 unless the design specifies a confirm — see Open Questions)
- [ ] The entry's `database` is reflected (the workspace targets the user's own DB; if a historical entry's DB differs from the current derived DB, document the handling — normally identical for a single-DB-per-user model)

### FR-004: Re-run

#### Acceptance Criteria:

- [ ] An explicit **Re-run** action loads the entry's SQL and immediately invokes the SPEC-035 Run path
- [ ] Re-running creates a **new** history entry (via the normal run → `appendQueryHistory` flow); it does not mutate the original entry
- [ ] Re-run is disabled while another query is in flight (consistent with FR-004 of SPEC-035)

### FR-005: Status Sync

#### Acceptance Criteria:

- [ ] An entry submitted in the current session reflects its terminal status once polling completes (SPEC-034 `updateQueryHistoryEntry`), without requiring a reload — the panel reflects the updated store via TanStack Query invalidation
- [ ] An entry that was left non-terminal in a prior session (tab closed mid-run) displays as its last-known state; re-opening it does not falsely show "running" (document the handling — treat unknown/stale `RUNNING` as a neutral "unknown" after load)

---

## Data Model

No new types — consumes SPEC-034 `QueryHistory` / `QueryHistoryEntry`.

## File & Folder Structure

```
apps/portal/src/features/query/
├── QueryHistoryPanel.tsx        ← NEW: panel/drawer listing history
├── QueryHistoryPanel.test.tsx
├── QueryHistoryRow.tsx          ← NEW: one entry row (preview, status, stats, actions)
└── QueryWorkspace.tsx           ← + history toggle + re-open/re-run wiring into the editor/run path
```

## Implementation Phases

### Phase 1: Panel + list + empty/loading/error (read-only)

- FR-001, FR-002, FR-005 (display side)

#### Checkpoint

`npm run dev`, signed in with prior history: the panel opens and lists past queries newest-first with correct previews, timestamps, and status badges; a brand-new user sees the empty state (no error) even with no `query-history.json`. Tests/lint pass. Matches the design.

### Phase 2: Re-open + re-run + status sync

- FR-003, FR-004, FR-005 (interaction side)

#### Checkpoint

Clicking an entry loads its SQL into the editor (no auto-run); Re-run executes it and a new entry appears at the top once submitted; the in-session entry's status updates to its terminal state without reload; re-run is blocked while a query is in flight. Tests/lint pass.

## Open Questions

- [x] **Resolved (2026-06-17, user decision):** history is **read-only** — **no** per-entry delete or "Clear all" in v1. The panel is view / re-open / re-run only. (Future admin/deprovisioning may purge history; not a user control.)
- [x] **Resolved (2026-06-17):** **direct replace** on re-open in v1 (history is non-destructive and Monaco undo recovers prior text); no confirm dialog. (The user chose read-only history; they did not request a re-open confirm, so direct replace stands.)
- [x] **Resolved (2026-06-17):** the panel **never fetches result objects for old entries** — Re-open loads only the stored SQL, and Re-run re-executes. Results are only ever fetched for a query executed in the current session. (Results are retained indefinitely per SPEC-032, so this isn't about expiry — the panel simply stores SQL + metadata, not result rows.)
