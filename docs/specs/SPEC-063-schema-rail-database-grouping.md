# Spec: Schema Rail — Collapsible Databases with Tables/Views Groups

**ID:** SPEC-063
**Status:** Completed
**Last Updated:** 2026-06-29
**Depends On:** SPEC-047 (workspace database switcher + `useConnections`), SPEC-035 (schema browser), SPEC-048 (views in the schema browser), SPEC-034 (`useSchema` + Glue services), SPEC-044 (per-table actions menu)

> **Design:** Needs a design pass. The schema rail's flat *Database → Tables* layout becomes a **tree**: each
> database is a **collapsible node**, and under an expanded database sit two **collapsible groups — Tables and
> Views** — keeping a database's tables and views grouped together next to the database they belong to. The
> editor toolbar `db-chip` (SPEC-047) is unchanged. See `design-system.md` §6.

## Overview

Today the schema rail (`SchemaBrowser`) lists the selectable databases at the top and, below them, a single flat
**Tables** list for the **active** database only — with views (SPEC-048) interleaved into that same list and marked
by a "View" badge. As users gain access to more than one database (the shared-spaces arc) and accumulate both
tables and views, this flat layout makes it hard to see what belongs to which database and to tell tables from
views at a glance. This spec restructures the rail into a **tree**: every database the user can access is a
**collapsible node**; expanding a database reveals two **collapsible sub-groups — Tables and Views** — so a
database's tables and views are always grouped together, beneath the database they pertain to. Expanding a database
is **decoupled from choosing the active query target** (user decision): a user can browse any accessible database's
tables and views without changing which database their queries run against. Setting the active database remains a
separate, explicit choice (the SPEC-047 model is preserved).

## Scope

### In Scope

- **Per-database collapsible nodes** — the rail's Database section renders each `useConnections` entry as an
  expand/collapse **disclosure** node (chevron + database icon + label). Collapsing a database hides its Tables and
  Views groups; expanding reveals them.
- **Two collapsible sub-groups per database — Tables and Views** — under an expanded database, tables and views are
  split into two independently collapsible groups (each with its own chevron and a count), so they sit grouped
  next to each other under their database. A view is a Glue `VIRTUAL_VIEW` (SPEC-048); everything else is a table.
- **Per-node schema loading** — an expanded database loads its own schema via `useSchema(database)` (only when
  expanded), so the user can browse the tables/views of databases **other than the active one**. Loading / empty /
  "setting up" / error states render per node (reusing the existing friendly states).
- **Decoupled active-target selection** — expanding/collapsing a database does **not** change the workspace's
  active database. Setting the active database is a **separate, explicit control** on each database node (a
  radio-style "use this database" affordance); the active database stays **workspace-global** (SPEC-047) and keeps
  driving Run + results routing. The active node is conveyed by text/state (`aria-current` + sr-only label), never
  color-only.
- **Preserve existing row behavior inside the groups** — within Tables and Views, each entry keeps its current
  behavior: expand to show columns, click a column to insert it into the editor, the per-row actions menu
  (SPEC-044/048, view-aware), and the "View" affordance. Column click-to-insert is unchanged.
- **Single-database rendering** — when the user has exactly one database (the common case today), it renders as one
  node (expanded by default) with its Tables and Views groups and no active-selection ambiguity.

### Out of Scope

- Changing the **active-database model** — it stays **workspace-global** (SPEC-047); this spec only decouples
  *expanding to browse* from *selecting the active target*. Run still targets the active database; results still
  route to the user's own `{username}/athenaresults/` (SPEC-047 FR-005 / SPEC-055 for shared).
- **Persisting** node/group expansion across reloads — expansion is in-memory UI state (matching today's
  per-table column toggle, which is not persisted). May be revisited later.
- **Populating** shared connections — `useConnections` already returns personal + shared (SPEC-052); this spec only
  changes how that list is rendered.
- Any **IAM / infra / data-layer** change — per-node schema reads reuse `useSchema`/Glue services already scoped by
  the `username`/membership principal tag; no new permissions.
- Search / filter within the schema tree, drag-resize of the rail, or virtualized rendering of very large schemas.

---

## Functional Requirements

### FR-001: Database nodes are collapsible

#### Description:

Each accessible database in the rail is a disclosure node that expands/collapses its contents.

#### Acceptance Criteria:

- [ ] The rail's **Database** section renders one node per `useConnections` entry (personal first, then active
  shared A–Z, matching SPEC-052 ordering); each node has a disclosure toggle (chevron + database icon + label) with
  `aria-expanded` reflecting its state.
- [ ] Toggling a node shows/hides that database's Tables and Views groups; **collapsing the database collapses both
  groups** (they are not rendered while the database is collapsed).
- [ ] A node that is **not usable** (provisioning/failed/leaving shared connection — `isConnectionUsable === false`)
  is shown but **not expandable** and not selectable, with its status label (reusing the SPEC-052 treatment).
- [ ] The disclosure toggle is keyboard-operable (Enter/Space) and does not also change the active database (FR-003).

### FR-002: Tables and Views are separate collapsible groups under each database

#### Description:

Under an expanded database, its objects are split into a Tables group and a Views group, each independently
collapsible, so tables and views are grouped together beneath the database they belong to.

#### Acceptance Criteria:

- [ ] An expanded database shows exactly two sub-group headers — **Tables** and **Views** — each with its own
  disclosure toggle (`aria-expanded`) and an object count (e.g. "Tables (3)").
- [ ] Objects are partitioned by Glue type: `tableType === 'VIRTUAL_VIEW'` → **Views**; all other tables → **Tables**
  (single source of truth, see Data Model `partitionSchema`).
- [ ] Collapsing **Tables** hides only the tables; collapsing **Views** hides only the views; collapsing the parent
  database hides both (FR-001).
- [ ] An empty group renders a muted empty state ("No tables." / "No views.") rather than disappearing, so the
  grouping is always legible. The existing "No tables yet — create one with `CREATE EXTERNAL TABLE …`" guidance is
  shown for the **Tables** group when the database has zero tables.
- [ ] Default expansion on first reveal: the database node's groups open with **Tables** expanded; **Views**
  expanded when the database has at least one view, otherwise collapsed. (Ephemeral; not persisted.)

### FR-003: Expanding is decoupled from selecting the active database

#### Description:

Browsing a database (expanding it) is independent of choosing which database queries run against.

#### Acceptance Criteria:

- [ ] Each **usable** database node carries a separate, explicit **active-target control** (a radio-style "use this
  database" affordance across the node list = a `radiogroup`); selecting it sets the workspace active database
  (`setActiveDatabase`, SPEC-047) without toggling the node's expansion.
- [ ] Expanding/collapsing a database node **does not** change the active database; selecting the active target
  **does not** force the node open or closed.
- [ ] The active database is conveyed by text/state — `aria-current` + an sr-only "(current database)" label and the
  existing `accent-soft` highlight — never color alone; exactly one database is active at a time.
- [ ] The active database continues to drive Run, `useSchema` for the run target, and schema-changing-SQL
  invalidation (unchanged from SPEC-047); the toolbar `db-chip` still reflects it.

### FR-004: Per-node schema loading

#### Description:

An expanded database loads and displays its own tables/views, including databases that are not the active target.

#### Acceptance Criteria:

- [ ] Expanding a database triggers `useSchema(database)` for **that** database (the query is enabled by expansion);
  a collapsed/never-expanded database does not fetch its schema.
- [ ] Each node renders its own loading / empty / "Setting up your database…" (Glue `getDatabase` NotFound) / error
  states, reusing the existing friendly messaging — a failure in one node never breaks the rail or other nodes.
- [ ] The active database's schema and a separately-expanded database's schema can be displayed simultaneously
  without one overwriting the other (per-node `useSchema`, keyed by database name).

### FR-005: Preserve in-group row behavior

#### Acceptance Criteria:

- [ ] Inside the Tables and Views groups, each object row keeps its current behavior: expand to reveal columns,
  click a column to insert its name into the editor at the cursor (`onInsert`), and the per-row actions menu
  (SPEC-044) — **view-aware** for views (SPEC-048: SHOW CREATE VIEW / DROP VIEW; source-files disabled).
- [ ] The "View" badge is **no longer needed inside the Views group** (membership in the Views group conveys the
  type) but the view-aware actions remain; tables in the Tables group keep table actions.

### FR-006: Single-database and accessibility

#### Acceptance Criteria:

- [ ] With exactly one accessible database, the rail shows a single node (expanded by default) with its Tables and
  Views groups; the active control is present but implies no ambiguity (one database, already active).
- [ ] The tree is accessible: nested disclosures expose `aria-expanded`; the active-target control is a labelled
  `radiogroup` (keyboard-navigable; Enter/Space selects; selection conveyed by state/text); no axe violations
  (SPEC-045 suite covers the rail).

### FR-007: Tests + lint

#### Acceptance Criteria:

- [ ] `npm run test` + `npm run lint` pass; tests cover: a database node toggles its groups (collapsing the database
  hides Tables + Views); tables vs views partition by `tableType`; empty groups show their empty states; expanding a
  **non-active** database fetches and shows its schema without changing the active database; selecting the active
  control sets the active database without toggling expansion; column click-to-insert and the view-aware actions
  menu still fire; single-database default expansion; an unusable shared node is shown but not expandable.

---

## Data Model

```ts
// apps/portal/src/features/query/schema.partition.ts  (NEW — pure helper)

import type {GlueTableSummary} from './query.types';

export type PartitionedSchema = {
  tables: GlueTableSummary[]; // tableType !== 'VIRTUAL_VIEW'
  views: GlueTableSummary[];  // tableType === 'VIRTUAL_VIEW'
};

export function partitionSchema(tables: GlueTableSummary[]): PartitionedSchema;
```

No new persisted shapes, env vars, or `query.types.ts` additions — `Connection` (SPEC-047/052) already carries
everything the node needs (`database`, `label`, `kind`, `status`, `isConnectionUsable`).

## API / Interface Contract

```ts
// SchemaBrowser keeps the same public props (drop-in for QueryWorkspace, unchanged call site):
//   database: string            // the active database (drives the active highlight + run target)
//   connections?: Connection[]  // all accessible databases -> one node each
//   onSelectDatabase?: (database: string) => void   // active-target control (FR-003)
//   onInsert: (name: string) => void                // column click-to-insert (unchanged)
//   actions: TableActions                           // per-row menu (unchanged)

// New internal component (per database node): owns its expansion + useSchema(database) + the two groups.
function DatabaseNode(props: {
  connection: Connection;
  isActive: boolean;
  onSetActive: (database: string) => void;
  onInsert: (name: string) => void;
  actions: TableActions;
}): JSX.Element;
```

## File & Folder Structure

```
apps/portal/src/features/query/
├── SchemaBrowser.tsx          ← rail + database-node list; same public props (FR-001, FR-003, FR-006)
├── SchemaBrowser.test.tsx
├── DatabaseNode.tsx           ← NEW: one database node — disclosure + per-node useSchema + Tables/Views groups
├── DatabaseNode.test.tsx      ← NEW
├── schema.partition.ts        ← NEW: partitionSchema(tables) -> {tables, views}
├── schema.partition.test.ts   ← NEW
└── index.ts                   ← export DatabaseNode if needed by tests/barrel
```

## Implementation Phases

### Phase 1: Partition helper + Tables/Views groups for the active database

- Add `partitionSchema`; refactor the current flat list into the two collapsible **Tables** and **Views** groups
  (with counts + empty states) for the active database, preserving column-insert + the view-aware actions menu
  (FR-002, FR-005).

### Phase 2: Per-database collapsible nodes + decoupled active control

- Extract `DatabaseNode` (disclosure + per-node `useSchema`), render one per `useConnections` entry, add the
  separate radio-style active-target control, and wire single-database default expansion + accessibility
  (FR-001, FR-003, FR-004, FR-006).
