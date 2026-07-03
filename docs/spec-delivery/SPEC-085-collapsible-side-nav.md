# Completed Spec — SPEC-085: Collapsible Side Nav (Shared Base Rail + Collapse Control)

## What was completed?

The two authenticated left rails (Files spaces `Sidebar` + Query `SchemaBrowser`) now share one collapsible
base and can be **hidden on demand**, freeing the 248px for content. Presentation-only; no data/IAM/infra.

- **`CollapsibleRail` (new, `components/`):** owns the shared `<aside>` chrome (248px, `hidden … md:flex`) plus a
  header **collapse** control and, when collapsed, a slim **reopen** handle at the content's left edge. Collapsing
  sets the panel to `display:none` (removed from the flex row → `<main>` fills the width) **without unmounting**, so
  in-rail expansion/selection state is preserved and both controls' `aria-controls` stay valid. `aria-expanded` +
  labels on both controls; keyboard-operable.
- **`useRailCollapsed` (new, `components/`):** `localStorage`-backed (`RAIL_COLLAPSED_STORAGE_KEY =
  'portal.rail.collapsed'`), a single **shared** key so the choice carries across both rails; guarded access
  degrades to not-persisted (default expanded) when storage is unavailable.
- **`Sidebar` + `SchemaBrowser` refactored** to render their existing content **inside** `CollapsibleRail` — no
  call-site prop changes in `FilesPage` / `QueryWorkspace`; per-item behavior unchanged.
- New `ChevronLeftIcon` / `ChevronRightIcon` in `icons.tsx`.

## What changed from earlier specs?

`Sidebar`/`SchemaBrowser` internals only (public props unchanged, drop-in). Added a baseline in-memory
`localStorage` polyfill to the test harness (`test-setup.ts` + `test/storage.ts`) — Node's experimental
`localStorage` is non-functional in the runner and this is the first `localStorage`-backed feature; no existing
test used `localStorage`.

## Verification

`format:check`, `tsc`/`build`, ESLint, Vitest **920 passed**. New `useRailCollapsed` tests (default/persist/toggle/
shared-across-instances/degrade-on-throw) + `CollapsibleRail` tests (panel↔handle toggle, `aria-expanded`/labels/
`aria-controls`, persistence, state-preserved) + **axe in both expanded and collapsed states** (component-level and
the `/query` route). `Sidebar`/`SchemaBrowser` existing tests still pass (one incidental button-count assertion
retargeted to the Spaces list). Live browser deferred — the rail renders in dev-unauth `/files`, but that path needs
an env toggle + a reachable bucket; the collapse behavior/states are fully covered by the component + a11y tests.
