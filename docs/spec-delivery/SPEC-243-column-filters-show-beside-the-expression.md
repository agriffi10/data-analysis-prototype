# Completed Spec — SPEC-243: A Column Filter Shows Beside the Expression, and the Generated SQL Opens in Query

## What was completed?

- **Column filters show as chips.** `ExplorationResultsRegion` renders a `ChipList` named
  *Column filters* under the expression bar, one `Chip` per entry of `query.filters` in array order,
  and nothing when there are none. `filterChipLabel` (`explorationQueryOps.ts`) words each one with
  the menu's operator label. It quotes a value exactly when the renderer does, by the same
  `operatorUsesValueKind` test, shows `(empty)` for an empty string, and names a list in the
  renderer's de-duplicated sorted order, three values and then "and n more".
- **A chip's remove is one filter, one apply.** It calls the region's existing `clearFilter` action,
  so it is at most one execution and one history entry, and *Back* restores it. Focus passes to the
  next chip's remove control, else the previous one's, else the *Filter expression* input.
  `ExpressionBar` gained `inputRef` for that last case.
- **Open in Query.** `GeneratedSqlDisclosure` renders it beside the copy button, under the same
  open-only rule, when given `onOpenInQuery`. The region passes that only with the `query` flag on.
  `DataExplorerWorkspace` navigates to `/query` with `buildOpenSqlHandoff({sql, label})`, which
  holds the disclosure's own statement and the tab's label. The exploration is not touched.
- **`lib/routeHandoff.ts`** gained `OpenSqlHandoff`, `buildOpenSqlHandoff` and `readOpenSqlHandoff`
  beside SPEC-242's shape, by the same own-property rules.
- **Query receives it once.** `QueryWorkspace` reads the state per `location.key`. It opens a new
  tab, active and unrun, or raises the tab-limit dialog at the cap. It then replaces the entry with
  no state, and state it did not build is ignored and left alone.
- **Registry and guides:** *Open in Query* under `query` with a recipe and a contract entry, plus a
  step each in the *Filter and sort* and *Save an exploration as a query* guides.

### Deliberate deviations

- **On a phone the statement always shows, and no tab-limit dialog is raised.** The draft opened a
  tab and showed the read-only view, and at the cap raised the dialog and showed nothing. A phone has
  no tab strip, so it could not close a tab as the dialog asks, and the statement never appeared.
  Found by the spec review. Andrew chose to show the view always, open a tab only when there is room,
  and never raise the dialog below `tablet`. The spec was updated.
- **The chip and hand-off tests are new files** (`filterChips.test.tsx`, `openInQuery.test.tsx`,
  `GeneratedSqlDisclosure.test.tsx`, `features/query/openSqlHandoff.test.tsx`), not additions to
  suites already far past the per-unit scenario budget. The spec lists them.
- **Two decisions in the spec were reworded, and no behaviour changed.** Applying *Order and filter*
  re-sets every list filter through `setFilter`, so it can move their chips to the end. A long list's
  remove label carries the shortened label, not every value.

## What changed from earlier specs?

- `ExpressionBar` takes an optional `inputRef`. `GeneratedSqlDisclosure` and
  `ExplorationResultsRegion` take an optional `onOpenInQuery`.
- `QueryWorkspace` now reads `location.state`, and declares `useNavigate` earlier to do so.
- `renderWorkspace` (`test/queryWorkspaceSupport.tsx`) takes a route object with history state, and
  passes `strictMode` and `browserRouter` through.
- `Chip` also serves the column filters, not only the three recipient lists.

## Verification

Formatter, lint, `tsc -b`, `npm run build`, the bundle check and the portal suite with coverage were
green by exit code. So were the branch validators `ci.yml` runs, mypy and the Lambda suite. Planted
mutations reddened their tests: the `location.key` guard, the phone's no-dialog branch, the
previous-chip focus, and the `query` gate against the registry walk. The live check, `e2e.md` §4.5
rows L to P, ran on 2026-09-21 after the deploy. Rows L to N passed, and row O apart from its edit
of the statement. Row P, that edit and the row-count comparison it enables are owed: a hidden Chrome window took no editor input and never
reported a phone width.
`docs/testing/owed.md` has what ran and what discharges the rest.
