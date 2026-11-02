---
type: Spec
id: SPEC-046
title: "Refresh History Button"
description: "Adds a Refresh control to the query history drawer that re-reads the per-user history store from S3 on demand, so users can pick up history written from another tab, device, or session."
spec_status: Completed
depends_on: [SPEC-036, SPEC-042, SPEC-034]
arc: query-editor-round-3
arc_order: 1
---

**Dependency notes:** SPEC-036 (query history panel/drawer), SPEC-042 (history pagination), SPEC-034 (per-user history store + `useQueryHistory`)
> **Design:** Minor addition to the existing history drawer (`docs/design/query-workspace.html` + `design-system.md` §6). Reuses the SPEC-028 `IconButton` (ghost icon) in the drawer header accessory slot — no new design surface.

## Overview

Query history is read from the per-user `query-history.json` store (SPEC-034). Today the panel only reflects changes the current session itself wrote (the run flow seeds the cache on append/update); there is no way to pull in history written by another browser tab, another device, or a re-login without reloading the whole app. This spec adds a **manual Refresh control** to the Query History drawer that re-reads the store from S3 on demand, so a user can deliberately reconcile the list against the source of truth.

## Scope

### In Scope

- A **Refresh** control in the Query History drawer header (icon button) that re-fetches the history store (`{username}` history JSON) from S3
- A brief in-flight affordance (spinner / disabled state) while the refetch is running, and a return to the **newest** page on completion (consistent with SPEC-042's reset-to-newest behavior)
- Error handling: a failed refresh surfaces the existing read-error treatment (Banner), never a crash, and leaves the previously-loaded list intact

### Out of Scope

- **Automatic / polled** refresh of history (manual only; no background polling)
- Any change to the history **storage schema** or service functions (SPEC-034 owns them)
- Refreshing saved queries (SPEC-043) or schema (SPEC-035) — this control is scoped to the history drawer only
- Real-time / cross-device sync beyond an explicit user-initiated re-read (last-writer-wins per SPEC-034 is unchanged)
- Deleting/clearing history (history stays read-only to the user, SPEC-036)

---

## Functional Requirements

### FR-001: Refresh control in the history drawer

#### Description:

A Refresh button in the history drawer header re-reads the user's history from S3 on demand.

#### Acceptance Criteria:

- [ ] The Query History drawer header shows a **Refresh** icon button (accessible label e.g. `aria-label="Refresh history"`), placed in the drawer's `headerAccessory` slot (SPEC-036 `Drawer`)
- [ ] Activating it invalidates and refetches `queryKeys.history(username)` (the `useQueryHistory` query) so the next read comes from S3, not cache
- [ ] The control is keyboard-focusable with the standard focus ring and reachable whenever the drawer is open

### FR-002: In-flight + post-refresh behavior

#### Acceptance Criteria:

- [ ] While the refetch is in flight the button shows a disabled/spinner state and cannot be re-triggered (no overlapping refetches)
- [ ] On success the list reflects the freshly-read store and the pager resets to the **newest** page (page 1, newest-first — SPEC-042)
- [ ] If the store is unchanged since the last read, the list simply re-renders identically (no flicker beyond the brief loading state); an empty store renders the SPEC-036 empty state, not an error

### FR-003: Error path

#### Acceptance Criteria:

- [ ] A failed refresh (read/permission/parse error) surfaces the SPEC-036 read-error `Banner` treatment and leaves the **previously-loaded** entries visible (the refresh is non-destructive)
- [ ] A corrupt/missing `query-history.json` continues to read as an **empty** store (SPEC-034), never an error

### FR-004: Tests + lint

#### Acceptance Criteria:

- [ ] `npm run test` + `npm run lint` pass; tests cover: clicking Refresh triggers a refetch of the history query key; the button is disabled while in flight and re-enables after; a refresh error shows the Banner without dropping the existing list; the pager returns to the newest page after a successful refresh

---

## Data Model

No new types. Consumes SPEC-034 `QueryHistory` / `QueryHistoryEntry` and the existing `useQueryHistory` hook.

## API / Interface Contract

```ts
// useQueryHistory already wraps the history query. This spec adds an explicit
// refetch path. Either expose a `refresh` from the hook or invalidate the key
// directly in the panel — keep the single source of truth on queryKeys.history.

// Option (preferred): extend the hook's returned surface
type UseQueryHistoryResult = {
  // …existing…
  refresh: () => Promise<unknown>;   // invalidate + refetch queryKeys.history(username)
  isRefreshing: boolean;             // in-flight state for the button (FR-002)
};
```

## File & Folder Structure

```
apps/portal/src/features/query/
├── useQueryHistory.ts        ← + refresh() + isRefreshing (invalidate/refetch the history key)
├── useQueryHistory.test.ts   ← + refresh tests
├── QueryHistoryPanel.tsx     ← Refresh icon button in the drawer headerAccessory; reset-to-newest on success
└── QueryHistoryPanel.test.tsx
```

## Implementation Phases

### Phase 1: Hook refresh + button

- Add `refresh`/`isRefreshing` to `useQueryHistory`; wire a Refresh `IconButton` into the history drawer header; reset to newest page on success (FR-001, FR-002, FR-003)

#### Checkpoint

`npm run dev`, open the history drawer, click Refresh: the button shows an in-flight state and the list re-reads from S3 (verify with a second tab that wrote a new entry — Refresh surfaces it). The pager returns to the newest page; an induced read error shows the Banner without clearing the list. `npm run test` + `npm run lint` pass.

## Open Questions

- [x] **Resolved (2026-06-21):** refresh is **manual only** — no automatic polling (keeps S3 reads deliberate and avoids cost/churn).
- [x] **Resolved (2026-06-21):** a successful refresh **resets to the newest page** (matches SPEC-042's open/append behavior), so the user lands on the most recent entries.
- [x] **Resolved (2026-06-21):** the control is an **icon button in the drawer header** (`headerAccessory`), not a row in the list or a global-bar button.
