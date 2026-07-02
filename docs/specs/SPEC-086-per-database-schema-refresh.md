# Spec: Per-Database Schema Refresh (Look for New Tables/Views)

**ID:** SPEC-086
**Status:** Draft
**Last Updated:** 2026-07-02
**Depends On:** SPEC-063 (schema rail `DatabaseNode` + per-node `useSchema`), SPEC-034 (`useSchema` + Glue services + `invalidateSchema`), SPEC-047 (`useConnections`), SPEC-028 (`IconButton`)

> **Design:** A minor addition to each schema-rail database node (SPEC-063). Reuses the SPEC-028
> `IconButton` (ghost icon) placed in the `DatabaseNode` header row beside the active-target radio — no new
> design surface. See `design-system.md` §6.

## Overview

The schema rail lists every database the user can access as a collapsible node; expanding a node loads that
database's Tables and Views via `useSchema(database)` (SPEC-063). That schema is cached by TanStack Query
and today only re-reads when schema-changing SQL runs in the app (`invalidateSchema` after a `CREATE`/`DROP`
— SPEC-044/048) or when the whole app reloads. Tables and views created **outside** the current session —
by the Table Builder pipeline (SPEC-066→072), another browser tab, another device, or a teammate in a
shared space — don't appear until something forces a re-read. This spec adds a **per-database Refresh
control** to each node so a user can deliberately re-read **that** database's tables and views on demand,
without reloading the app or touching the other databases' cached schemas.

## Scope

### In Scope

- A **Refresh** control (icon button) on each **usable** database node in the schema rail (`DatabaseNode`)
  that re-reads **that** database's schema (`getDatabase` + `listTables`) from Glue on demand.
- A brief in-flight affordance (spinner / disabled) while the node's refetch runs, with no overlapping
  refetches for the same node.
- **Scoped invalidation:** refreshing one database re-reads only that database's schema query
  (`queryKeys.schema(database)`); other nodes' cached schemas and their expansion state are untouched.
- **Error handling:** a failed refresh reuses the node's existing error/"setting up" treatment and leaves
  the **previously-loaded** tables/views visible (non-destructive), never crashing the rail.

### Out of Scope

- **Automatic / polled** schema refresh (manual only — no background polling; keeps Glue reads deliberate).
- A **rail-wide "refresh all databases"** button — the control is **per node** (each database refreshes
  independently). May be revisited later.
- Any change to the **schema storage/service layer** (`useSchema` / `glue.service` own the read) or to the
  existing post-DDL `invalidateSchema` flow (SPEC-044/048) — this spec adds a **user-initiated** re-read,
  not a new data path.
- Refreshing a node that has **never been expanded** (schema only loads on expand, SPEC-063 FR-004) — the
  control appears with the node body, on expanded/usable nodes.
- Refreshing **query history** (SPEC-046 owns that), **saved queries** (SPEC-043), or the **connections
  list** itself (SPEC-052 refresh) — this control is scoped to a single database's tables/views.
- Any **IAM / infra** change — the re-read reuses the Glue access already scoped by the
  `username`/membership principal tag (SPEC-033/056).

---

## Functional Requirements

### FR-001: Per-node Refresh control

#### Description:

Each usable, expandable database node exposes a Refresh control that re-reads that database's tables/views.

#### Acceptance Criteria:

- [ ] Each **usable** `DatabaseNode` renders a **Refresh** `IconButton` (accessible label e.g.
  `aria-label="Refresh tables in {database}"`) in the node's header row, alongside the disclosure toggle and
  the active-target radio (SPEC-063).
- [ ] Activating it invalidates and refetches **only** `queryKeys.schema(connection.database)` for that node
  (reusing `invalidateSchema` / the `useSchema` query), so the next read comes from Glue, not cache.
- [ ] Unusable nodes (provisioning/failed/leaving shared connections — `isConnectionUsable === false`, the
  `UnusableNode`) show **no** Refresh control.
- [ ] The control is keyboard-focusable with the standard focus ring and does not toggle the node's
  expansion or change the active database when activated.

### FR-002: In-flight + post-refresh behavior

#### Acceptance Criteria:

- [ ] While that node's refetch is in flight, its Refresh button shows a disabled/spinner state and cannot
  be re-triggered (no overlapping refetches **for that node**).
- [ ] On success the node's Tables and Views groups reflect the freshly-read schema: newly-created tables/
  views appear and deleted ones disappear; the node's and groups' expansion state and any open column rows
  are preserved where the object still exists.
- [ ] Refreshing one node does **not** show a spinner on, refetch, or collapse any **other** node, and does
  not change the workspace active database.
- [ ] If the schema is unchanged since the last read, the node re-renders identically (no flicker beyond the
  brief loading state); a database with zero tables continues to show the existing empty-state guidance.

### FR-003: Error path

#### Acceptance Criteria:

- [ ] A failed refresh (read/permission error) reuses the node's existing error treatment (the `role="alert"`
  "Couldn't load this schema…" message) and leaves the **previously-loaded** tables/views visible — the
  refresh is non-destructive.
- [ ] A `getDatabase` NotFound continues to render the node's friendly "Setting up your database…" state
  (SPEC-063), not a hard error.

### FR-004: Tests + lint

#### Acceptance Criteria:

- [ ] `npm run test` + `npm run lint` pass; tests cover: clicking Refresh invalidates/refetches only that
  node's `queryKeys.schema(database)`; the button is disabled while in flight and re-enables after; a
  successful refresh surfaces a newly-added table and drops a removed one; a refresh error keeps the prior
  list visible with the error treatment; refreshing one node leaves another node's schema and expansion
  untouched; the Refresh control is absent on an unusable node.

---

## Data Model

No new types. Consumes SPEC-034 `SchemaData` / `GlueTableSummary`, the existing `useSchema(database)` query,
and `invalidateSchema(client, database)` (already in `useSchema.ts`). `Connection` (SPEC-047/052) already
carries `database`, `label`, `kind`, `status`, `isConnectionUsable`.

## API / Interface Contract

```ts
// Reuse the existing per-database schema query + its invalidator (no new service).
// In DatabaseNode, expose a scoped refresh for this node's database:

const queryClient = useQueryClient();
const {data, isPending, isError, error, isFetching} = useSchema(expanded ? connection.database : null);

async function refresh(): Promise<void> {
  // invalidate + refetch ONLY this database's schema key (queryKeys.schema(database))
  await invalidateSchema(queryClient, connection.database);
}
// Button disabled/spinner is driven by `isFetching` for this node's query (FR-002).
```

## File & Folder Structure

```
apps/portal/src/features/query/
├── DatabaseNode.tsx          ← + per-node Refresh IconButton in the header row; scoped invalidate/refetch
├── DatabaseNode.test.tsx     ← + refresh tests (scoped refetch, in-flight, error non-destructive, isolation)
├── useSchema.ts              ← reuse existing useSchema + invalidateSchema (no change expected)
└── SchemaBrowser.tsx         ← unchanged (renders DatabaseNode per connection)
```

## Implementation Phases

### Phase 1: Per-node refresh control

- Add a Refresh `IconButton` to `DatabaseNode`'s header row (usable nodes only); wire it to
  `invalidateSchema(queryClient, connection.database)` and drive its disabled/spinner state from the node's
  `useSchema` `isFetching`; preserve expansion + active-database on refresh (FR-001, FR-002, FR-003).

## Open Questions

- [x] **Resolved (2026-07-02):** refresh is **per database node**, not a single rail-wide "refresh all"
  button — each database re-reads independently so one refresh never churns the others.
- [x] **Resolved (2026-07-02):** refresh is **manual only** (no polling), matching SPEC-046's history-refresh
  decision.
- [x] **Resolved (2026-07-02):** the control is an **icon button in the node header** beside the disclosure +
  active-target radio (SPEC-063), reusing `IconButton`.
```
