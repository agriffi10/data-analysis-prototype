# Completed Spec — SPEC-100: Query Workspace Responsive

## What was completed?

The Query workspace now reflows across the three SPEC-095 breakpoints. Presentation only — no
service, data-layer, routing, IAM or infra change; the run path is the shipped one at every width.

- **Tablet (FR-002/003).** `CollapsibleRail` gained an optional `widthClass`; the schema rail passes
  `w-[220px] desktop:w-[248px]`, so it narrows in the tablet band and the Files sidebar is untouched.
  Editor-toolbar labels (Clear / Save / Create view / Stop / Run Statement) are wrapped in a
  `hidden desktop:inline` span — icon-only at tablet, `aria-label`s and handlers unchanged.
- **Mobile home (FR-004).** New **`QueryMobileView`**: a Saved/History segmented toggle over the
  workspace's existing `useSavedQueries` / `useQueryHistory` data (no new fetch), history paged with
  the shared `Pager`. **Run** on a card submits through the same `submitBatch` the editor uses.
- **Mobile rail (FR-005).** **`SchemaTree`** extracted from `SchemaBrowser` (the rail is now chrome +
  tree); below `tablet` the inline rail is not mounted and the same tree is registered into the
  `AppNavDrawer` contextual slot via `useProvideNavRail`.
- **Mobile results (FR-006).** New **`QueryResultsMobile`**: back + name + re-run, read-only SQL
  preview, the shared `QueryStatusBar`, one labelled card per row (column → value), and a fixed
  Prev/Next pager that renders disabled when a single page holds every row.
- **`MobileQueryView`** UI type in `query.types.ts` (local state, never persisted). Help gained a
  “Use Query on a phone” guide (SPEC-074 FR-005).

### Deliberate deviations

- **The tablet rail keeps the shipped tree rather than becoming a flat table list.** Every FR-002
  acceptance criterion (visible, ~220px, tap-to-expand columns through the existing node expand,
  same data source) is met by the shipped `DatabaseNode` tree; forking a second rail structure would
  have duplicated logic the spec explicitly says to reuse. The tablet change is width only.
- **Mount-gating, not a CSS swap.** `useIsMobile()` selects the branch (react.md §20's mount-cost
  exception, and the SPEC-099 precedent): `hidden` would still instantiate Monaco, and in jsdom both
  trees would live in the DOM.
- **The SQL preview is monospace, not syntax-highlighted.** Highlighting needs a highlighter on a
  route that deliberately does not load Monaco; adding a dependency is out of scope for a
  presentation spec.
- **No Save-results on mobile.** The spec enumerates the mobile results view's contents and does not
  include it, so `canSaveResults` is false there; nothing was removed from tablet/desktop.

## What changed from earlier specs?

- `CollapsibleRail` (SPEC-085) takes an optional `widthClass` (defaults to the shipped 248px).
- `QueryHistoryRow` (SPEC-036) takes optional action labels — mobile has no editor to open into, so
  the same row reads View + Run there. Defaults are the shipped Open + Re-run.
- `QueryStatusBar` (SPEC-035) wraps onto a second line below `tablet`; `tablet:` restores the shipped
  single-row bar.
- `SchemaBrowser` (SPEC-035/077) now composes the extracted `SchemaTree` (same DOM inline).

## Verification

`format:check` + `lint` (incl. the security plugins and React Compiler) + `tsc -b` + `build` clean;
full suite green — **1207 tests, +23**. New: `QueryMobileView.test.tsx` (8), `QueryResultsMobile.test.tsx`
(8), a `QueryWorkspace` responsive block (mobile pares to browse-first, rail off-canvas via a
`NavRailProvider` probe, saved-card Run → row cards + pager → back, tablet toolbar labels) and a
mobile route-level axe case. **Not browser-verified:** `/query` is auth-gated and the preview can't
hold a Cognito session (same limitation recorded in SPEC-099); the breakpoint tokens themselves are
browser-verified via SPEC-095.
