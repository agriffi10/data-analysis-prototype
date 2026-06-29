# Completed Spec — SPEC-063: Schema Rail — Collapsible Databases with Tables/Views Groups

## What was completed?

The query schema rail is now a **tree**. Every accessible database (each `useConnections`
entry — personal first, active shared A–Z) renders as a collapsible **`DatabaseNode`**; expanding
one loads *its own* schema (per-node `useSchema(database)`, fetched only when expanded) and splits
the objects into two collapsible sub-groups — **Tables** and **Views** — each with a chevron + count
and an empty state (the `CREATE EXTERNAL TABLE …` hint for empty Tables; "No views." for empty
Views). Default reveal opens Tables; Views opens only when ≥1 view exists.

- **Browsing is decoupled from the active query target.** The disclosure (chevron + icon + label)
  only expands/collapses; a separate per-node **radio dot** (the nodes form one keyboard-navigable
  `radiogroup`, arrow-key roving + Enter/Space) sets the workspace-global active database
  (`setActiveDatabase`, SPEC-047) without toggling expansion. Active is conveyed by
  `aria-checked` + `aria-current` + sr-only label + `accent-soft` — never color alone.
- Files/symbols added: `DatabaseNode.tsx` (node + internal `ObjectGroup`/`TableRow`),
  `schema.partition.ts` (`partitionSchema(tables) → {tables, views}`, split on `VIRTUAL_VIEW`),
  plus tests for each and a rewritten `SchemaBrowser.test.tsx` (incl. a vitest-axe check).
- In-group row behavior is unchanged: column click-to-insert and the view-aware actions menu
  (SPEC-044/048) still fire. The old inline **"View" badge was dropped** — Views-group membership
  conveys the type (FR-005).

No deliberate deviations. Node/group expansion is in-memory only (not persisted), per scope.

## What changed from earlier specs?

- **`SchemaBrowser.tsx`** (SPEC-035/047/048) was restructured: `useSchema`/`TableRow`/`DatabaseIcon`
  moved into `DatabaseNode.tsx`; `SchemaBrowser` now owns the rail + radiogroup only. **Public props
  are unchanged** (`database` / `connections` / `onSelectDatabase` / `onInsert` / `actions`), so the
  `QueryWorkspace` call site is untouched. The SPEC-047 active-database highlight moved from an
  `aria-current` button to the per-node `radio` + `aria-current`.
- No data-layer / IAM / infra change — per-node reads reuse the existing `username`/membership-tag-
  scoped `useSchema`/Glue services.

## Verification

`npm run lint`, `npm run test` (752 passed, incl. the new partition/node/rail tests + axe), and
`npm run build` (typecheck) all green locally. Browser preview was **not** run: the schema rail
lives on the Cognito-gated `/query` route backed by live AWS, which the local dev-unauth preview
(`/files` read-only) can't exercise — covered instead by the unit + a11y suite.
