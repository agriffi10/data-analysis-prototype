---
type: Spec
id: SPEC-052
title: "Connections Tab, Connection Lists & Refresh"
description: "Adds a Connections tab listing the user's shared spaces with role and status, merges shared connections into the database and space lists, and adds a Refresh connections control that applies new memberships."
spec_status: Completed
depends_on: [SPEC-047, SPEC-051, SPEC-056, SPEC-035, SPEC-046, SPEC-044]
arc: shared-connections
arc_order: 4
---

**Dependency notes:** SPEC-047 (`useConnections` seam + schema-rail database list), SPEC-051 (per-user cache shape + create flow), SPEC-056 (membership tags; token-refresh requirement), SPEC-035 (`PrimaryNav` Files | Query tabs), SPEC-046 (refresh-button pattern), SPEC-044 (`Toast`), SPEC-053 (member-management drawer — opened from here), SPEC-054 (leave/delete — invoked from here)
> **Reference:** `docs/shared-spaces-architecture.md` §6 (async UX: pending state + manual refresh that forces a
> token refresh so newly-granted membership tags take effect). This spec is the **read/display + navigation** layer:
> it adds the **Connections** top-level tab (where spaces are managed), extends `useConnections` so shared
> connections appear in **one list** alongside the personal one, and adds the **Refresh connections** control. It does
> not mutate state (create = SPEC-051; manage members = SPEC-053; leave/delete = SPEC-054).

## Overview

Surface the user's shared connections everywhere they're used, and give them a home to manage. This spec (1) extends
`useConnections` (SPEC-047) to merge the **personal** database with the user's **shared** connections (read from the
per-user cache `{username}/user_settings/shared-connections.json`), including **provisioning**/**failed** entries; (2)
adds a new **Connections** top-level tab (Files | Query | **Connections**) — the management surface listing the user's
spaces with their role + status and entry points to Create, Manage members, Leave, and Delete; and (3) adds a
**Refresh connections** control that forces a credential/token refresh (so a newly-granted membership applies) and
re-reads the cache. The same `useConnections` list feeds the **Query** schema-rail database switcher (SPEC-047) and
the **Files** space list (SPEC-057), so shared connections appear inline in those surfaces too — active ones usable,
pending/failed shown but not.

## Scope

### In Scope

- **Extend `useConnections`** (SPEC-047) to return personal **+ shared** connections: each shared entry maps to a
  `Connection` (`kind:'shared'`, `database:name`, `label:name`) plus its `status`/`role`; a missing/corrupt cache
  yields **personal-only** (empty state, not error). This single list is consumed by the Query schema rail (SPEC-047),
  the Files space list (SPEC-057), and the Connections tab (here)
- A new **Connections top-level tab**: add **Connections** to `PrimaryNav` (Files | Query | Connections, SPEC-035) and
  a `/connections` route. The page lists the user's shared connections — name, **role** (Owner/Member), **status**
  badge — with a **New shared connection** action (SPEC-051) and per-row **Manage** (owner → opens the member drawer,
  SPEC-053), **Leave** (member → SPEC-054), **Delete** (owner → SPEC-054). Friendly empty state
- **Refresh connections**: a control (mirroring SPEC-046) that (1) **forces a credential/token refresh**
  (`fetchAuthSession({ forceRefresh: true })`) so new `shared_space_k` tags are stamped, then (2) re-reads the
  per-user cache; in-flight affordance + error handling per SPEC-046
- **Status semantics**: `provisioning` (spinner/badge, not usable), `active` (usable), `failed` (reason + Dismiss /
  Retry), `leaving`/`deleting` (transient, not usable) — the shared-surface primitive (design-system §7) used in the
  Connections tab, the schema rail, and the Files list
- **Feeding the other surfaces:** the schema-rail database list (SPEC-047) and the Files space list (SPEC-057) show
  **active** shared connections as selectable/browsable and **provisioning/failed** ones disabled with their status

### Out of Scope

- **Any mutation** — create (SPEC-051), member add/remove (SPEC-053), leave/delete (SPEC-054); the Connections tab only
  **links** to those (Manage opens the SPEC-053 drawer; Leave/Delete open the SPEC-054 dialogs)
- The **schema-rail switching behavior** itself (SPEC-047) and the **Files browsing** of a shared space (SPEC-057) —
  this spec only feeds those lists from `useConnections`
- **Results routing** for shared queries (SPEC-055)
- The **registry**/pipeline internals (SPEC-050/056); this spec reads only the per-user cache
- Real-time membership sync — refresh is **manual** (the architecture's accepted constraint)

---

## Functional Requirements

### FR-001: `useConnections` returns personal + shared

#### Acceptance Criteria:

- [ ] `useConnections(username)` reads the per-user cache (SPEC-051 `SharedConnectionsCache`) and returns the personal
  connection **plus** one `Connection` per shared entry, each carrying `status` and `role`; a missing/corrupt cache
  yields **personal-only** (not an error)
- [ ] Ordering: personal first, then shared A–Z; `provisioning`/`failed`/`leaving` entries are included but flagged
  **not usable** (the schema rail / Files list disable them)
- [ ] `isLoading`/`error` are consistent with SPEC-047; the schema rail, Files list, and Connections tab all consume
  this one hook (no parallel sources)

### FR-002: Connections top-level tab

#### Acceptance Criteria:

- [ ] `PrimaryNav` gains a third tab **Connections** (Files | Query | Connections, same underline-tab treatment as
  SPEC-035), routed at `/connections`; keyboard-focusable with the standard focus ring
- [ ] The Connections page lists the user's shared connections as cards/rows: **name** (monospace, it's the prefix/DB),
  a **role** pill (Owner/Member), a **status** badge (provisioning/active/failed — text + icon, never color-only)
- [ ] Per row, role-appropriate actions: **New shared connection** (page-level, SPEC-051), **Manage** (owner →
  opens the SPEC-053 member drawer), **Leave** (member → SPEC-054), **Delete** (owner → SPEC-054); actions not allowed
  for the user's role are absent
- [ ] Empty state: a friendly "No shared connections yet — create one or ask an owner to add you" + the New CTA;
  loading/error reuse the established treatments (Banner on read error, never a crash)

### FR-003: Refresh connections (force token refresh)

#### Acceptance Criteria:

- [ ] A **Refresh connections** control (icon/button, SPEC-046 pattern) on the Connections tab first calls
  `fetchAuthSession({ forceRefresh: true })` (so newly-granted `shared_space_k` principal tags are stamped on the next
  credentials) and then re-reads the per-user cache (invalidate/refetch the connections query)
- [ ] An in-flight affordance disables the control during refresh; on completion the lists (Connections tab, schema
  rail, Files list) reflect the current cache + refreshed session; a failure shows the SPEC-046 error treatment and
  leaves the prior list intact
- [ ] After a refresh that picks up a newly-`active` connection, the user can use it (query/browse) without a full app
  reload (verifies the §3/§6 propagation story)

### FR-004: Feeding the Query + Files lists

#### Acceptance Criteria:

- [ ] The **Query** schema-rail database list (SPEC-047) shows **active** shared connections (personal first, shared
  A–Z) as selectable; **provisioning/failed** shared connections appear **disabled** with their status
- [ ] The **Files** space list (SPEC-057) shows **active** shared connections as browsable roots; pending/failed ones
  appear disabled with their status
- [ ] If a selected/active shared connection later disappears (left/deleted/revoked), the consuming surface falls back
  gracefully (Query → personal database with a non-blocking notice, per SPEC-047; Files → the personal space)

### FR-005: Status resolution for pending/failed

#### Acceptance Criteria:

- [ ] A `provisioning` entry the pipeline has since flipped to `active` (in the cache) becomes usable after a Refresh;
  a `failed` entry shows its `reason` and offers **Dismiss** (removes it from view) and, where applicable, **Retry**
  (re-enqueues via the originating feature, e.g. SPEC-051 create)
- [ ] No `provisioning` entry is usable; no `active` entry shows a spinner

### FR-006: Tests + lint

#### Acceptance Criteria:

- [ ] `npm run test` + `npm run lint` pass; tests cover: `useConnections` merges personal + shared (personal-only on
  missing cache); the Connections tab renders in `PrimaryNav`, lists roles/status + role-gated actions, and routes;
  Refresh calls `forceRefresh` then re-reads and re-enables; the schema rail + Files list receive active vs disabled
  entries; a vanished connection falls back gracefully; a failed entry shows reason + Dismiss/Retry

---

## Data Model

No new persisted types — consumes SPEC-051 `SharedConnectionsCache`/`SharedConnectionEntry` and enriches the SPEC-047
`Connection` with the already-defined `kind:'shared'` plus surfaced `status`/`role`:

```ts
type Connection = {
  id: string; label: string; database: string; kind: 'personal' | 'shared';
  status?: SharedConnectionStatus;   // shared only
  role?: SharedConnectionRole;       // shared only
};
```

## File & Folder Structure

```
apps/portal/src/features/query/
├── useConnections.ts            ← merge personal + shared (read cache); + refresh (forceRefresh + refetch)
└── useConnections.test.ts
apps/portal/src/components/
└── PrimaryNav.tsx               ← + Connections tab (Files | Query | Connections)
apps/portal/src/features/shared-spaces/
├── ConnectionsPage.tsx          ← NEW: /connections route — management list (role + status + actions)
├── ConnectionsPage.test.tsx
├── RefreshConnectionsButton.tsx ← NEW (SPEC-046 pattern; forceRefresh + cache refetch)
└── sharedSpaces.service.ts      ← + readSharedConnectionsCache (used by useConnections)
```

## Implementation Phases

### Phase 1: useConnections (personal + shared) + feeding the lists

- Extend `useConnections` to read + merge shared entries with status/role; the Query schema rail (SPEC-047) and the
  Files list (SPEC-057) consume it — active selectable, pending/failed disabled; graceful fallback (FR-001, FR-004)

#### Checkpoint

With a seeded cache (one active + one provisioning shared connection), the schema rail lists the personal + active
shared DB (provisioning disabled) and selecting the active one re-keys the schema (SPEC-047); a missing cache shows
personal-only. Tests/lint pass.

### Phase 2: Connections tab + refresh + status

- Add the **Connections** `PrimaryNav` tab + `/connections` page (cards, role/status, action entry points, empty
  state); `RefreshConnectionsButton` (forceRefresh → refetch); failed dismiss/retry (FR-002, FR-003, FR-005)

#### Checkpoint

The Connections tab appears in the topbar and lists connections with correct role-gated actions (Manage opens the
SPEC-053 drawer; Leave/Delete open the SPEC-054 dialogs); Refresh forces a session refresh then re-reads the cache (a
newly-active connection becomes usable without a reload); a failed entry shows reason + Dismiss/Retry. Tests/lint pass.

## Open Questions

- [x] **Resolved (2026-06-21, user decision):** managing connections lives in a **new top-level Connections tab**
  (Files | Query | Connections), not a sidebar group; shared connections also appear **inline** in the Query schema-rail
  database list (SPEC-047) and the Files space list (SPEC-057).
- [x] **Resolved (2026-06-21, user decision):** **member management is a slide-out drawer** (SPEC-053), opened from the
  Connections tab's **Manage** action — not a separate full screen.
- [x] **Resolved (2026-06-21):** refresh **forces a credential/token refresh** then re-reads the cache, so a new
  membership applies on demand (`shared-spaces-architecture.md` §3/§6).
- [x] **Resolved (2026-06-21):** `provisioning`/`failed` connections are **shown but not usable** (clear status) across
  all three surfaces, not hidden.
