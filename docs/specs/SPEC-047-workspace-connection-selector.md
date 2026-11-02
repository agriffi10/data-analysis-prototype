---
type: Spec
id: SPEC-047
title: "Workspace Database Switcher (Schema-Rail Connection List)"
description: "Turns the schema browser's database area into a list of accessible databases whose selection sets a workspace-global active database, retargeting every query tab and the schema, with a read-only chip in the toolbar."
spec_status: Completed
depends_on: [SPEC-035, SPEC-041, SPEC-034, SPEC-033]
arc: query-editor-round-3
arc_order: 2
---

**Dependency notes:** SPEC-035 (query workspace + schema browser), SPEC-041 (query tabs), SPEC-034 (Glue services + `useSchema`), SPEC-033 (per-user Glue DB = username)
> **Design:** Needs a design pass. The schema browser's **Database** section becomes a **switchable list** of the
> databases the user can query (personal + — later — shared); selecting one is how you change the workspace's
> target database. The editor toolbar's `db-chip` (`design-system.md` §6) becomes a **read-only indicator** of the
> active database (no dropdown). See also the navigation model in SPEC-052 (the **Connections** top-level tab) and
> the Files-side equivalent in SPEC-057.

## Overview

Today the query workspace hard-codes the target database to the signed-in user's own Glue database
(`const database = username` in `QueryWorkspace`). To let users query databases **other than their own** — starting
conceptually now and concretely once **shared connections** exist (the shared-spaces arc) — this spec turns the
schema browser's **Database** area into a **list of the databases the user can access** and makes selecting one the
single way to switch the workspace's **active database**. The chosen database is **workspace-global** (user decision):
switching it re-keys the schema browser's tables/views **and** retargets every query tab's Run at the new database.
The toolbar shows the active database as a small **read-only chip** (it no longer offers its own dropdown — the rail
is the switcher). Until shared connections are built, the list contains exactly one database (the user's own), so
behavior is unchanged for existing users while the switching seam is in place and forward-compatible.

## Scope

### In Scope

- A **connections source** — a hook (`useConnections`) returning the databases the signed-in user can target, each a
  `{ id, label, database, kind }` record. In this spec it returns exactly **one** entry: the user's **personal**
  database (`kind:'personal'`, `database = username`, label e.g. "My workspace"). This hook is the **single extension
  point** the shared-spaces arc (SPEC-052) feeds shared connections into — consumers don't change
- A **workspace-global active database**: a single piece of workspace state (the currently-targeted `database`),
  **persisted per-user** (`sessionStorage`, alongside the SPEC-041 tabs state), defaulting to the **personal**
  database. It **replaces** the hard-coded `database = username` everywhere the workspace uses it (Run, schema,
  schema-changing-SQL invalidation) — and applies to **all** query tabs (not per-tab)
- A **schema-rail database switcher**: the schema browser's **Database** section lists the databases from
  `useConnections` (the active one highlighted, `accent-soft`); clicking a different one sets the workspace active
  database, which **updates the tables/views shown** (`useSchema(activeDatabase)`) and the Run target for every tab.
  Accessible (a labelled list/`radiogroup`-style selection; keyboard-navigable; selection conveyed as text, not
  color-only)
- A **read-only `db-chip`** in the editor toolbar reflecting the active database (the former static chip stays a
  chip — **no dropdown**; switching is the rail's job)
- A clean **single-database** rendering: when only the personal database exists, the Database section shows one
  (active) item and no switching affordance is implied
- The **Run path** targets the active database; **results route to the user's own `{username}/athenaresults/`**
  regardless of which database is queried (shared-DB result routing is decided in SPEC-055, not here)

### Out of Scope

- **Per-tab** database context — the active database is **workspace-global** (user decision; see Resolved). Tabs no
  longer carry their own `database`
- A **toolbar dropdown** selector — switching is the schema-rail list; the toolbar chip is read-only (user decision)
- **Populating shared connections** — the entire shared-spaces arc (SPEC-050→056) and the Files-side space list
  (SPEC-057). This spec only defines the `useConnections` seam + the global active-database switching the rail drives
- Changing **where results are written** (always personal `{username}/athenaresults/` here; SPEC-055 handles shared)
- Any IAM/infra change (the only reachable database today is the user's own)

---

## Functional Requirements

### FR-001: Connections source (`useConnections`)

#### Acceptance Criteria:

- [ ] `useConnections(username)` returns `{ connections: Connection[], isLoading, error }` where, in this spec,
  `connections` is exactly one entry: `{ id:'personal', label:'My workspace', database:username, kind:'personal' }`
- [ ] The hook is the documented **single source** of selectable databases; the shared-spaces arc (SPEC-052) extends
  it with `kind:'shared'` entries without changing consumers (the schema rail, the toolbar chip)
- [ ] When `username` is null/empty the hook returns an empty list and the workspace falls back to its existing
  not-signed-in handling (no crash)

### FR-002: Workspace-global active database

#### Description:

The workspace targets one active database for all tabs; it is no longer hard-coded to `username`.

#### Acceptance Criteria:

- [ ] The workspace holds a single **active database** value, **persisted per-user** in `sessionStorage` (a small
  store mirroring the SPEC-041 tabs persistence), defaulting to the **personal** database (`username`)
- [ ] The active database **replaces** the hard-coded `username` everywhere the workspace uses it: the schema browser
  (`useSchema(activeDatabase)`), the Run path (`runQuery({ database: activeDatabase, … })`), and schema-changing-SQL
  invalidation (`invalidateSchema(activeDatabase)`)
- [ ] The active database applies to **all** query tabs — switching it changes the target for every tab's next Run
  (there is no per-tab database); a persisted value that is no longer available (e.g. a removed shared DB) falls back
  to the personal database with a non-blocking notice
- [ ] A previously-persisted workspace with no stored active database defaults cleanly to the personal database (no
  crash)

### FR-003: Schema-rail database switcher

#### Acceptance Criteria:

- [ ] The schema browser's **Database** section renders the `useConnections` list (personal first, then — later —
  shared A–Z); the **active** database is visibly selected (`accent-soft` item, as the current single-DB treatment)
- [ ] Selecting a **different** database sets the workspace active database (FR-002), which **re-keys the schema**
  (the tables/views below update to the newly-selected database) and retargets Run for all tabs
- [ ] The switcher is accessible: a labelled selectable list (keyboard-navigable; Enter/Space selects; the active
  item is conveyed by text/state, never color-only) and does not interfere with the existing expand/collapse of
  tables/columns
- [ ] With only the personal database available, the section shows a single active item and implies no switching

### FR-004: Read-only toolbar DB indicator

#### Acceptance Criteria:

- [ ] The editor toolbar's `db-chip` reflects the **active database** as a **read-only** chip (`accent` dot +
  monospace label) — it has **no** dropdown/menu (switching is the schema rail, FR-003)
- [ ] The chip updates immediately when the active database changes

### FR-005: Run + results routing

#### Acceptance Criteria:

- [ ] `runQuery` targets the **active database**; the recorded history entry's `database` is the active database
  (already a field, SPEC-034)
- [ ] Regardless of the active database, results route to the user's own `{username}/athenaresults/` (SPEC-034) in
  this spec — querying a (future) shared database does not change where the result object lands here (SPEC-055 owns
  shared-results routing)

### FR-006: Tests + lint

#### Acceptance Criteria:

- [ ] `npm run test` + `npm run lint` pass; tests cover: `useConnections` returns the single personal connection; the
  active database defaults to personal and persists across reloads; the schema rail lists databases and selecting one
  sets the active database + re-keys `useSchema` + retargets Run for all tabs; an unavailable persisted database falls
  back to personal; the toolbar chip is read-only and reflects the active database; results still route to
  `{username}/athenaresults/`

---

## Data Model

```ts
// apps/portal/src/features/query/query.types.ts (additions)

export type ConnectionKind = 'personal' | 'shared';

export type Connection = {
  id: string;            // 'personal' for the user's own DB; shared-space id later
  label: string;         // display name ('My workspace', or the shared name)
  database: string;      // Glue database name targeted by queries
  kind: ConnectionKind;
};

// Workspace-global active database (persisted per-user, mirroring queryTabs.ts):
//   key: s3portal.query.activeDatabase.{username}  → string (a database name)
//   default + fallback = username (the personal DB). NOT a per-tab field.
```

> Note: this **supersedes** the earlier per-tab `QueryTab.database` design — the database is workspace-global.

## API / Interface Contract

```ts
// useConnections.ts
useConnections(username: string | null): { connections: Connection[]; isLoading: boolean; error: string | null };

// QueryWorkspace: replace `const database = username` with the workspace-global active database
const [activeDatabase, setActiveDatabase] = useActiveDatabase(username); // persisted; default = username
// schema rail:   useSchema(activeDatabase)              + the database list (switcher) from useConnections
// run (any tab): runQuery({ sql, database: activeDatabase, username })   // results -> {username}/athenaresults/
```

## File & Folder Structure

```
apps/portal/src/features/query/
├── useConnections.ts          ← NEW: connections source (personal-only here; SPEC-052 extends it)
├── useConnections.test.ts     ← NEW
├── useActiveDatabase.ts       ← NEW: workspace-global active DB + per-user sessionStorage persistence
├── useActiveDatabase.test.ts  ← NEW
├── query.types.ts             ← + Connection / ConnectionKind
├── SchemaBrowser.tsx          ← Database section becomes the switchable list (active highlight + select)
├── SchemaBrowser.test.tsx
└── QueryWorkspace.tsx         ← use activeDatabase (Run + schema + invalidation, all tabs); read-only db-chip
```

## Implementation Phases

### Phase 1: Connections source + global active database

- `useConnections` (personal-only); `useActiveDatabase` (persisted, default personal); switch `QueryWorkspace` off
  the hard-coded `username` to `activeDatabase` (Run, schema, invalidation) (FR-001, FR-002, FR-005)

#### Checkpoint

Existing users see no behavioral change: one database ("My workspace"), schema + Run target their own DB, results
land in `{username}/athenaresults/`. The active database persists across a reload. `npm run test` + `npm run lint`
pass.

### Phase 2: Schema-rail switcher + read-only chip

- Render the database list in the schema browser's Database section (active highlight + select → set active DB →
  re-key schema + retarget Run); make the toolbar `db-chip` a read-only indicator (FR-003, FR-004)

#### Checkpoint

With only the personal database, the rail shows one active item and the toolbar chip reads it. (Simulating a second
database in a test) selecting it in the rail updates the tables/views and the chip, and the next Run targets it.
`npm run test` + `npm run lint` pass.

## Open Questions

- [x] **Resolved (2026-06-21, user decision):** the active database is **workspace-global** (one for all tabs), not
  per-tab — this **supersedes** the earlier per-tab `QueryTab.database` design.
- [x] **Resolved (2026-06-21, user decision):** switching is done in the **schema-rail database list**; the toolbar
  `db-chip` is a **read-only** indicator (no dropdown).
- [x] **Resolved (2026-06-21):** add the switcher **now** (returns only the personal database; SPEC-052 feeds shared
  connections in without consumer changes).
- [x] **Resolved (2026-06-21):** results route to the user's own `{username}/athenaresults/` here; shared-DB result
  routing lands with SPEC-055 (`docs/shared-spaces-architecture.md` §5).
