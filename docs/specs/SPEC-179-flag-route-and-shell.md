---
type: Spec
id: SPEC-179
title: "Data Explorer — the Feature Flag, the `/explore` Route and the Shell"
description: "Makes the Data Explorer reachable with a fifth feature flag, a /explore route and nav tab, a source picker, exploration tabs and an Explore data item on a table's menu, showing rows in a plain table."
spec_status: Completed
depends_on: [SPEC-176, SPEC-178]
arc: data-explorer
arc_order: 4
---

## Overview

The Data Explorer becomes reachable: a fifth feature flag, a `/explore` route, a primary-nav
tab, a source picker, an exploration tab strip, and an **Explore data** item on a table's `⋮`
menu in the Query schema rail. At the end of this spec a user can pick a database and table and
see rows — through SPEC-178's engine, in a plain table that SPEC-180 then replaces with the real
grid.

The flag is the substantial part. `FeatureFlagKey` has been a closed union of four since
SPEC-162, and the publish pipeline's validator reads the deploy workflow's matrix, so a fifth
key touches the types, the defaults, the config document, the workflow and the gated-surface
registry as one change. Getting a key half-added is the failure mode this spec is shaped to
prevent.

## Scope

### In Scope

- A fifth `FeatureFlagKey`, `dataExplorer`, wired end to end: types, `FEATURE_FLAG_KEYS`,
  `FEATURE_FLAG_DEFAULTS`, `config/feature-flags.json`, the `deploy-config.yml` matrix, and a
  non-empty `GATED_SURFACES.dataExplorer`.
- The `/explore` route, lazily loaded and gated by `FeatureRoute`.
- The **Data Explorer** tab in `PrimaryNav`.
- The source picker: space → database → table.
- The exploration tab strip and its cap dialog, rendering SPEC-178's tab state.
- **Explore data** on `DatabaseNode`'s `TableActionsMenu`, deep-linking into `/explore`.
- A minimal results table, explicitly a placeholder for SPEC-180's grid.

### Out of Scope

- **The grid.** Column resize, reorder, pin, hide, cell selection, Value panel, Record and Text
  presentations are SPEC-180. This spec renders rows in a plain table so the route has something
  to show; nothing about it is a contract.
- **Filtering, ordering, grouping, Calc, formatting, copy and export** — SPEC-181 onward.
- **Saved queries.** The `sql` source arm exists in the model but has no UI here; the picker
  offers tables only. SPEC-183.
- **Help guides.** SPEC-185 writes them, once there is a shipped, wired-end-to-end feature to
  document (SPEC-074 FR-005).
- Any IaC or IAM change. There is none in this arc.

---

## Functional Requirements

### FR-001: The `dataExplorer` flag exists everywhere a flag must

#### Description:

Adding a key is a five-place change, and the publish validator fails on either side of a
mismatch between the config document and the workflow matrix.

#### Acceptance Criteria:

- [ ] `FeatureFlagKey` includes `'dataExplorer'`; `FEATURE_FLAG_KEYS` and
      `FEATURE_FLAG_DEFAULTS` each gain it, defaulting to `true`.
- [ ] `config/feature-flags.json`'s `defaults` block gains it, and the existing test asserting
      the file matches `FEATURE_FLAG_DEFAULTS` passes without being edited to accommodate a
      drift.
- [ ] `scripts/validate_feature_flags.py` passes against the updated document and the unchanged
      workflow matrix.
- [ ] The resolver still returns all **five** keys for a document naming none of them — the
      resolver walks `FEATURE_FLAG_KEYS`, not the document.
- [ ] One bad **value** falls back for that key only; a wrong **version or shape** is refused
      whole. Both behaviours are re-asserted with five keys present.

### FR-002: `GATED_SURFACES.dataExplorer` is non-empty and enforced

#### Description:

`GATED_SURFACES` is keyed by `FeatureFlagKey`, so a fifth key adds a fifth entry. An empty row
list would pass the walking test vacuously — the test walks rows, and no rows is no work.

#### Acceptance Criteria:

- [ ] A guard fails if any flag's row list is empty.
- [ ] The registry holds a row for the nav tab, a row for the route, and a row for the
      **Explore data** menu item.
- [ ] Every row has a reach-recipe that renders the **real page** — SPEC-163 measured that a
      recipe re-implementing the gate leaves the suite green with the real gates deleted.
- [ ] The off-half of each gating assertion runs **after settling**, never inside `waitFor`,
      whose first attempt lands while every surface is legitimately absent.

### FR-003: The `/explore` route

#### Description:

A lazily-loaded route, because it pulls the Athena and Glue clients, wrapped in `ErrorBoundary`
and `Suspense` **inside** `FeatureRoute` — the gate decides whether the page mounts at all, and
a chunk that loads before the answer arrives is a page that has already started fetching.

#### Acceptance Criteria:

- [ ] With the flag off, `/explore` renders the feature-unavailable page — the route still
      matches, so a correct URL is never answered with a 404.
- [ ] While flags resolve, the route renders `LoadingState` and the page does **not** mount.
- [ ] A chunk-load rejection is caught by the `ErrorBoundary` rather than unmounting the tree.
- [ ] The route is `/explore`.

### FR-004: The primary-nav tab

#### Description:

A fifth tab, gated through the existing predicate.

#### Acceptance Criteria:

- [ ] `PrimaryNav` gains a `Data Explorer` tab pointing at `/explore`.
- [ ] Gating arrives as `isPathEnabled`, supplied by `Header` — `PrimaryNav` makes no
      `useFeatureFlags` call, because `components/` may not import `features/` (SPEC-155).
- [ ] With the flag off the tab is **removed**, not hidden and not disabled — a `hidden` tab is
      still in the accessibility tree.
- [ ] The tab appears in the 400px hamburger drawer under the same gate.

### FR-005: The source picker

#### Description:

The page opens on a picker: space, then database, then table, sourced from SPEC-176's
`useQuerySpaces` and `useSchema`. Choosing a table opens an exploration tab bound to it.

#### Acceptance Criteria:

- [ ] The space list is `useQuerySpaces()`'s, personal first.
- [ ] With `sharedWorkspaces` off, the picker offers **My files** alone, filtered at the view —
      never in `useQuerySpaces` and never in a service, following SPEC-174's precedent. This is
      its own registry row under `sharedWorkspaces`.
- [ ] Databases and tables come from the Glue reader; a database the user cannot see is absent
      rather than present-and-failing.
- [ ] Views are selectable — a view is a perfectly good thing to explore, and the renderer does
      not care.
- [ ] Choosing a table opens a tab and runs its first execution.
- [ ] With no usable space, the picker explains itself rather than rendering empty (SPEC-167's
      precedent).

### FR-006: Deep links carry the source, and resolve without an oracle

#### Description:

`/explore?space={id}&db={database}&table={table}` opens directly on that table. An unreachable
space renders denied and issues **no Glue or S3 request**, following SPEC-113 — otherwise the
route reports whether a database the user cannot see exists.

#### Acceptance Criteria:

- [ ] All three params present and reachable → a tab opens bound to that table.
- [ ] A space the user is not an active member of → the denied state, with **zero** Glue and S3
      calls asserted by mocking the boundary and counting.
- [ ] A missing or malformed param → the picker, not an error.
- [ ] Own username always wins over a same-named shared space, mirroring SPEC-113's precedence.
- [ ] A `space` param is not read at all when `sharedWorkspaces` is off, and never routed
      through a "fell back" banner that would be a lie.

### FR-007: **Explore data** on the schema rail's table menu

#### Description:

A new item on `DatabaseNode`'s `TableActionsMenu`, beside **View data**, navigating to the deep
link. It is a Data Explorer capability living on a Query-workspace surface, so it needs a row
under **both** flags — the mirror image of "Create table", which SPEC-163 calls the one everyone
forgets.

#### Acceptance Criteria:

- [ ] The item appears for base tables and views alike.
- [ ] It navigates to `/explore` with the node's own database — SPEC-077 FR-007: the database
      comes from the rail node the table was invoked from, never an active-database selection.
- [ ] With `dataExplorer` off the item is absent while the rest of the menu is unchanged.
- [ ] With `query` off the whole Query page is gone, so the item is unreachable — asserted, not
      assumed, and carried as a registry row under `query`.
- [ ] The mobile nav-drawer copy of the tree offers the same item, through the existing
      `TableActions` ref indirection.

### FR-008: The exploration tab strip

#### Description:

SPEC-178's tab state gets its surface: a strip of tabs, a `+`, close buttons, and the cap
dialog when `openTab` refuses.

#### Acceptance Criteria:

- [ ] Tabs render in creation order with the active one marked, and switching restores that
      tab's exploration.
- [ ] At the cap the `+` stays enabled and the refusal raises the "close a tab first" dialog,
      matching the Query workspace's model.
- [ ] Closing a tab does not run a query.
- [ ] Tab state survives a reload via `sessionStorage`.

### FR-009: A placeholder results table

#### Description:

Rows have to render somewhere for the route to be verifiable. A plain table over
`useQueryResults` suffices, with the existing Prev/Next pager.

#### Acceptance Criteria:

- [ ] Columns and rows render for a succeeded execution; the Athena header row is absent.
- [ ] A zero-row result renders the friendly empty state, not an error.
- [ ] A failed execution renders through `toUserMessage` — no Athena text reaches the user
      (SPEC-106).
- [ ] The delivery doc records that this table is a placeholder SPEC-180 replaces, so its
      absence of features is not read as a regression.

---

## Data Model

```ts
// features/feature-flags/featureFlags.types.ts — the union gains one member
export type FeatureFlagKey = 'files' | 'query' | 'sharedWorkspaces' | 'dataQuality' | 'dataExplorer';
```

```jsonc
// config/feature-flags.json
{
  "version": 1,
  "defaults": {
    "files": true,
    "query": true,
    "sharedWorkspaces": true,
    "dataQuality": true,
    "dataExplorer": true
  },
  "environments": { "prod": {} }
}
```

```ts
// The deep-link contract
type ExploreSearchParams = {
  /** QuerySpace id: 'personal' or a shared space name. Ignored when sharedWorkspaces is off. */
  space?: string;
  db?: string;
  table?: string;
};
```

---

## File & Folder Structure

```
apps/portal/src/
├── routes/
│   └── ExplorePage.tsx              # NEW — default export, lazy
├── features/data-explorer/
│   ├── DataExplorerWorkspace.tsx    # NEW
│   ├── SourcePicker.tsx             # NEW
│   ├── ExplorationTabStrip.tsx      # NEW
│   ├── ExplorationResultsTable.tsx  # NEW — placeholder, replaced by SPEC-180
│   ├── useExploreDeepLink.ts        # NEW
│   └── dataExplorerUi.test.tsx      # NEW
├── components/PrimaryNav.tsx        # +1 tab
├── features/query/DatabaseNode.tsx  # +1 menu item
└── features/feature-flags/          # +1 key, +1 registry entry
```

---

## Implementation Phases

### Phase 1: The flag

- The fifth key across types, defaults, config document and the workflow matrix.
- The non-empty-rows guard and the first registry rows.

### Phase 2: Route, nav and shell

- `/explore` with `FeatureRoute` + `ErrorBoundary` + `Suspense`; the nav tab and drawer entry.
- The workspace shell and the tab strip over SPEC-178's state.

### Phase 3: Picker and deep links

- The space/database/table picker, with the `sharedWorkspaces` view filter.
- The deep-link resolver, including the no-request denied path.

### Phase 4: Entry point and results

- **Explore data** on the rail menu, registered under both flags.
- The placeholder results table and the gating walk over every new row.
