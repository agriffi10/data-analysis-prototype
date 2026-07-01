# Spec: Per-Tab Query Database (+ Saved Query Targets Its Database)

**ID:** SPEC-076
**Status:** Superseded (by SPEC-077)
**Last Updated:** 2026-07-01
**Depends On:** SPEC-047 (workspace database selector — superseded here), SPEC-041 (multi-tab editor), SPEC-043 (saved queries)

> **Superseded by SPEC-077 (2026-07-01).** Per user feedback, the workspace is
> dropping the active-database *session* concept altogether (browse-only rail +
> fully-qualified cross-database queries) rather than making the active database
> per-tab. Do not build this spec; see SPEC-077.

## Overview

The query workspace currently targets **one workspace-global active database** for
all tabs (SPEC-047): choosing a database in the schema rail changes it for every
open tab. Per user feedback (2026-06-30) each query tab should target its **own**
database, so a user can work against their personal database in one tab and a
shared connection in another without switching back and forth. This spec moves the
active-database selection from workspace-global to **per-tab**, and — because it
now can — makes **opening a saved query select the database that saved query
targets** (item deferred here from the feedback batch: a saved query already
records its `database`, but opening it ignored that and used the global active DB).

## Scope

### In Scope

- A `database` field on each query tab, persisted with the tab (survives reloads).
- The schema rail, the "querying `<db>`" toolbar chip, query execution, and editor
  autocomplete all reflect the **active tab's** database.
- Selecting a database in the schema rail changes **only the active tab**.
- Opening a saved query opens a tab whose database is the saved query's
  `database`; if that database is unavailable, fall back to personal with the
  existing non-blocking banner.
- New tabs inherit the currently active tab's database (falling back to personal).
- Per-tab reconciliation: a tab whose stored database is no longer available
  (e.g. a revoked shared space) falls back to personal, surfaced non-blockingly.
- Migration for persisted tabs written before this spec (no `database` → personal).

### Out of Scope

- Cross-database queries within a single statement (no cross-DB joins) — a tab
  still targets exactly one database.
- Changes to the results/history data model, saved-query storage shape (already
  has `database`), or the Save Results destination logic.
- Any control-plane / IAM / infra change (this is entirely frontend).
- The shared-space roster work (SPEC-075) — independent.

---

## Functional Requirements

### FR-001: Each tab carries its own database (persisted)

#### Description:

Add `database: string` to the query-tab model and persist it in the existing tab
store. Tabs written before this spec (no `database`) migrate to the personal
database on load.

#### Acceptance Criteria:

- [ ] A tab's `database` persists across reloads (same store as tab SQL/label).
- [ ] A persisted tab lacking `database` loads with the personal database, no error.
- [ ] `useQueryTabs` exposes a way to set the **active** tab's database.

### FR-002: The workspace reflects the active tab's database

#### Description:

The active database used across the workspace is the active tab's `database`
(replacing the workspace-global `useActiveDatabase`). The schema rail's active
selection, the "querying `<db>`" chip, query execution target, and editor
autocomplete schema all derive from the active tab.

#### Acceptance Criteria:

- [ ] The schema rail shows the active tab's database as selected.
- [ ] The "querying `<db>`" chip shows the active tab's database.
- [ ] Running a query targets the active tab's database.
- [ ] Editor autocomplete uses the active tab's database schema.
- [ ] Switching tabs updates all of the above to the newly active tab.

### FR-003: Selecting a database changes only the active tab

#### Description:

Choosing a database in the schema rail sets the active tab's `database` and leaves
every other tab's database untouched.

#### Acceptance Criteria:

- [ ] Selecting a database in the rail changes the active tab only.
- [ ] Other open tabs keep their databases (verified by switching to them).

### FR-004: Opening a saved query selects its database

#### Description:

Opening a saved query opens a tab whose `database` is the saved query's stored
`database`. If that database is not currently available to the user (missing /
revoked), the tab falls back to the personal database and the existing
non-blocking "switched to your workspace" banner is shown.

#### Acceptance Criteria:

- [ ] Opening a saved query targeting an available database opens a tab set to
      that database.
- [ ] Opening a saved query targeting an unavailable database opens a tab on the
      personal database with the fallback banner.
- [ ] Saving a query records the active tab's database (unchanged storage shape).

### FR-005: New tabs inherit the active tab's database

#### Description:

A newly created (blank) tab inherits the database of the tab that was active when
it was created, falling back to personal if none.

#### Acceptance Criteria:

- [ ] Creating a new tab while a shared database is active opens the new tab on
      that same database.
- [ ] With no prior tab / no active database, a new tab defaults to personal.

### FR-006: Per-tab database reconciliation

#### Description:

If a tab's stored database becomes unavailable (e.g. a shared space is revoked),
that tab falls back to the personal database when it becomes active, surfaced
non-blockingly (reuse the SPEC-047 fallback banner, now scoped per active tab).

#### Acceptance Criteria:

- [ ] Activating a tab whose database is no longer available shows the personal
      database and the fallback banner.
- [ ] Reconciliation is harmless/idempotent (resolves on read; no crash).
- [ ] Tabs whose databases are still available are unaffected.

---

## Data Model

```ts
// apps/portal/src/features/query/query.types.ts
export type QueryTab = {
  id: string;
  label: string;
  sql: string;
  savedQueryId?: string;
  database: string; // SPEC-076: per-tab target database (was workspace-global)
};

// SavedQuery.database already exists (SPEC-043) — now honoured on open.
```

Persistence: the per-tab store (`queryTabs.ts`, sessionStorage) gains `database`
per tab; a load-time migration defaults missing values to the personal database.

## API / Interface Contract

```ts
// useQueryTabs — set the active tab's database
setActiveTabDatabase(database: string): void;

// openTab already carries label/sql/savedQueryId — extend with database
openTab(input: {label: string; sql: string; savedQueryId?: string; database?: string}): void;
```

The existing `useActiveDatabase` (workspace-global) is retired or refactored into a
per-tab reconciliation helper reusing `isConnectionUsable` for availability.

## File & Folder Structure

```
apps/portal/src/features/query/
├── query.types.ts        # QueryTab.database
├── queryTabs.ts          # persist database per tab + migration
├── useQueryTabs.ts       # setActiveTabDatabase; openTab({database})
├── QueryWorkspace.tsx    # derive active DB from active tab; rail/chip/run/autocomplete
├── SchemaBrowser.tsx     # onSelectDatabase → active tab
└── *.test.tsx            # updated + new coverage
```

## Implementation Phases

### Phase 1: Tab data model + persistence

- Add `database` to `QueryTab`; persist in `queryTabs.ts`; load-time migration to
  personal for legacy tabs. Add `setActiveTabDatabase` + `openTab({database})`.
- Unit tests for the store (persist/restore/migrate).

### Phase 2: Wire the workspace to the active tab's database

- Replace workspace-global `useActiveDatabase` usage with the active tab's
  database across the schema rail, the chip, run, and autocomplete.
- Rail selection sets the active tab only; switching tabs re-derives everything.
- Per-tab reconciliation + fallback banner (reuse SPEC-047 pattern).

### Phase 3: Saved-query database + new-tab inheritance

- Opening a saved query sets the tab's database to `SavedQuery.database`
  (fallback to personal + banner when unavailable).
- New tabs inherit the active tab's database.
- Confirm Save records the active tab's database.
- Component + a11y tests (rail selection scoped to a tab; open-saved DB honoured;
  inheritance; reconciliation).

### Phase 4: Completion ritual

- Delivery doc, INDEX status, and the Key Decisions update noting SPEC-047's
  "workspace-global active database" is superseded by per-tab databases.
