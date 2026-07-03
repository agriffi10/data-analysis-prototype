# Spec: Collapsible Side Nav (Shared Base Rail + Collapse Control)

**ID:** SPEC-085
**Status:** Completed
**Last Updated:** 2026-07-02
**Depends On:** SPEC-023 (app shell / layouts), SPEC-057 (Files spaces `Sidebar`), SPEC-063 (Query `SchemaBrowser` rail), SPEC-028 (`Button`/`IconButton` primitives)

> **Design:** The two authenticated left rails — the Files spaces `Sidebar` and the Query `SchemaBrowser`
> — today declare the **same** 248px panel chrome independently (`hidden w-[248px] shrink-0 … md:flex`).
> This spec factors that chrome into one **base collapsible-rail** component and adds a collapse control.
> When collapsed the rail is **fully hidden** (removed from the layout so the page content fills the width),
> with a slim **reopen handle** pinned at the content's left edge. Needs a light design pass in
> `design-system.md` (rail header collapse affordance + the reopen handle); no new tokens.

## Overview

The authenticated app shell has a left navigation rail on the two workspace pages: `/files` renders the
spaces `Sidebar` (personal + shared spaces) and `/query` renders the `SchemaBrowser` schema tree. On
narrower or content-dense sessions (a wide file table, a wide result grid) users want to reclaim that
248px. Today there is no way to hide the rail. This spec lets users **collapse the side nav** on any page
that has one and reopen it on demand. Because both rails share identical panel chrome, the collapse
behavior is added **once** to a shared base component both rails render through, so the affordance,
keyboard behavior, and remembered state are consistent across Files and Query. The collapsed/expanded
choice is **remembered per browser** and applies to whichever rail the user is looking at.

## Scope

### In Scope

- A shared **`CollapsibleRail`** base component (in `components/`) that owns the rail's `<aside>` chrome
  (the 248px panel, border, scroll, `hidden … md:flex` responsive behavior) plus a **collapse toggle** in
  its header and, when collapsed, a **reopen handle**.
- Refactoring the Files **`Sidebar`** and the Query **`SchemaBrowser`** to render their existing content
  **inside** `CollapsibleRail` instead of each declaring its own `<aside>` panel — no change to what each
  rail lists or how its items behave.
- **Fully-hidden collapse:** collapsing removes the rail from the flex row so the page's `<main>` fills the
  freed width; a slim, labelled reopen handle appears at the left edge to bring it back.
- **Per-browser persistence:** the collapsed/expanded state is stored in `localStorage` under a single
  shared key, so the choice survives reloads and is shared across both the Files and Query rails (collapse
  on `/files`, navigate to `/query`, the schema rail is collapsed too).
- **Accessibility:** the collapse toggle and reopen handle are keyboard-operable with clear accessible
  names and `aria-expanded`/`aria-controls` wiring; the axe suite (SPEC-045) covers both pages in each
  state.

### Out of Scope

- A **slim icon-rail** collapsed mode (collapse is fully-hidden + reopen handle, not a mini icon strip) —
  explicitly deferred.
- Changing the **mobile / below-`md`** behavior — the rails stay `hidden` below the `md` breakpoint as they
  are today; the collapse control is an `md`+ affordance and this spec does not add a mobile drawer.
- **Resizing** / drag-to-width of the rail (a separate idea; SPEC-079 covers the editor/results splitter,
  not the rail).
- The top-bar **`PrimaryNav`** tabs (Files | Query | Connections) and the **`PageLayout`** pages
  (Connections, Notifications) that have **no** left rail — this spec touches only pages that have a side
  rail.
- Any **data-layer / IAM / infra** change — this is presentation only; no service, hook-data, or
  permission changes.
- Per-rail **independent** collapse state (one rail collapsed while the other is expanded) — the remembered
  state is a **single shared** preference by decision (see Open Questions).

---

## Functional Requirements

### FR-001: Shared collapsible base rail

#### Description:

A single base component supplies the rail chrome and the collapse/expand mechanism to any page that has a
left rail; the Files `Sidebar` and Query `SchemaBrowser` render through it.

#### Acceptance Criteria:

- [ ] A `CollapsibleRail` component renders the panel chrome currently duplicated in `Sidebar` and
  `SchemaBrowser` (the `hidden w-[248px] shrink-0 flex-col overflow-y-auto border-r border-border bg-surface
  … md:flex` `<aside>`), accepting the rail's `aria-label`, an optional header title, and the rail body as
  `children`.
- [ ] `Sidebar` and `SchemaBrowser` are refactored to render their existing content **inside**
  `CollapsibleRail`; the spaces list, schema tree, per-item behavior, and their public props are unchanged
  (drop-in — no call-site prop changes in `FilesPage` / `QueryWorkspace`).
- [ ] The refactor is behavior-preserving when expanded: existing `Sidebar` and `SchemaBrowser` tests
  (spaces selection, active-database radiogroup, node expansion, column insert) still pass.

### FR-002: Collapse hides the rail; reopen handle restores it

#### Description:

Collapsing removes the rail from layout and shows a reopen affordance; reopening restores it.

#### Acceptance Criteria:

- [ ] The rail header shows a **collapse** control (icon button, e.g. `aria-label="Collapse sidebar"`) that,
  when activated, hides the rail so it occupies **no** horizontal space and the adjacent `<main>` fills the
  freed width.
- [ ] While collapsed, a slim **reopen handle** is pinned at the left edge of the content area
  (`aria-label="Show sidebar"`, `aria-expanded="false"`); activating it restores the rail to its 248px
  panel and returns focus to a sensible target (the collapse control or the rail).
- [ ] The collapse control carries `aria-expanded` reflecting rail state and `aria-controls` referencing the
  rail region; the reopen handle mirrors it. Both are reachable by keyboard with the standard focus ring and
  operable via Enter/Space.
- [ ] Collapsing/reopening changes **only** rail visibility — it does not change the active space
  (SPEC-057), the active database (SPEC-047), or any in-rail expansion state.

### FR-003: Per-browser persisted, shared across rails

#### Description:

The collapsed/expanded choice is remembered per browser and applies to both rails.

#### Acceptance Criteria:

- [ ] The state is persisted in `localStorage` under a single shared key (see Data Model) via a small hook,
  so it survives reloads and new sessions.
- [ ] The persisted state is **shared** across the two rails: collapsing on `/files` leaves the `/query`
  schema rail collapsed on navigation, and vice-versa.
- [ ] Storage access is wrapped so a disabled / quota-exceeded / unavailable `localStorage` **degrades to
  not-persisted** (default = expanded) rather than throwing — matching the `useActiveDatabase` storage
  pattern.
- [ ] Default when nothing is stored (and for the dev-unauth path) is **expanded**.

### FR-004: Tests + lint

#### Acceptance Criteria:

- [ ] `npm run test` + `npm run lint` pass; new/updated tests cover: `CollapsibleRail` toggles between
  panel and hidden+handle; the collapse control and reopen handle expose correct `aria-expanded`/labels and
  are keyboard-operable; the collapsed state reads/writes the shared `localStorage` key and a throwing
  `localStorage` degrades gracefully; `Sidebar` and `SchemaBrowser` render through the base with their
  existing behavior intact; the collapsed→expanded round-trip preserves active space / active database.
- [ ] The SPEC-045 axe suite passes for `/files` and `/query` in **both** collapsed and expanded states (no
  new violations).

---

## Data Model

```ts
// apps/portal/src/components/useRailCollapsed.ts  (NEW)

// Single shared key — the preference is one value for both rails (FR-003).
export const RAIL_COLLAPSED_STORAGE_KEY = 'portal.rail.collapsed';

export type UseRailCollapsedResult = {
  collapsed: boolean;
  toggle: () => void;
  setCollapsed: (value: boolean) => void;
};

// localStorage-backed, degrade-to-not-persisted (mirrors useActiveDatabase's guarded access).
export function useRailCollapsed(): UseRailCollapsedResult;
```

No new persisted server shapes, env vars, or `*.types.ts` additions. `Connection` and the schema/space
data the rails render are unchanged.

## API / Interface Contract

```ts
// apps/portal/src/components/CollapsibleRail.tsx  (NEW)

type CollapsibleRailProps = {
  /** Accessible name for the rail region (e.g. "Your spaces navigation", "Schema browser"). */
  ariaLabel: string;
  /** Optional uppercase section label shown in the rail header next to the collapse control. */
  title?: ReactNode;
  /** The rail body — the existing Sidebar list / SchemaBrowser tree. */
  children: ReactNode;
};

// Sidebar / SchemaBrowser become thin: same public props as today, body moved inside the base.
// <CollapsibleRail ariaLabel="Your spaces navigation" title="Spaces"> …spaces list… </CollapsibleRail>
// <CollapsibleRail ariaLabel="Schema browser" title="Database"> …schema tree… </CollapsibleRail>
```

## File & Folder Structure

```
apps/portal/src/
├── components/
│   ├── CollapsibleRail.tsx        ← NEW: base rail chrome + collapse toggle + reopen handle
│   ├── CollapsibleRail.test.tsx   ← NEW
│   ├── useRailCollapsed.ts        ← NEW: localStorage-backed shared collapse state (guarded access)
│   ├── useRailCollapsed.test.ts   ← NEW
│   ├── Sidebar.tsx                ← render existing spaces list inside CollapsibleRail (no prop change)
│   ├── Sidebar.test.tsx
│   └── icons.tsx                  ← add a collapse/panel chevron icon if none fits
└── features/query/
    ├── SchemaBrowser.tsx          ← render the schema tree inside CollapsibleRail (no prop change)
    └── SchemaBrowser.test.tsx
```

## Implementation Phases

### Phase 1: Base component + persisted state

- Build `CollapsibleRail` (extract the shared `<aside>` chrome, add the header collapse control + the
  hidden-state reopen handle, wire `aria-expanded`/`aria-controls`) and `useRailCollapsed`
  (localStorage-backed, guarded, shared key). Cover FR-002 + FR-003 with tests.

### Phase 2: Adopt in both rails

- Refactor `Sidebar` and `SchemaBrowser` to render their existing content through `CollapsibleRail` with no
  call-site prop changes; confirm existing rail tests still pass; extend the SPEC-045 axe suite to assert
  both pages in the collapsed state (FR-001, FR-004).

## Open Questions

- [x] **Resolved (2026-07-02):** collapsed mode is **fully hidden + a reopen handle**, not a slim icon rail.
- [x] **Resolved (2026-07-02):** the collapsed/expanded state is **persisted per browser in `localStorage`**
  and **shared across both rails** (one preference), not per-rail or in-memory only.
- [x] **Resolved (2026-07-02):** the control applies to **both** left rails (Files `Sidebar` + Query
  `SchemaBrowser`) via one shared base component; top-bar tabs and rail-less pages are untouched.
```
