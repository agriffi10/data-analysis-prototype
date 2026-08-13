# Completed Spec — SPEC-182: The Calc and Grouping Panels

## What was completed?

Two analysis panels that look like siblings and are the opposite of one another.

- **`CalcPanel` + `calc.ts`** — ten aggregates over the current cell selection, computed in the
  browser: Count, Count distinct, Count nulls, Sum, Average, Minimum, Maximum, Median, Mode, with
  Count and Count distinct shown by default, per-function add/remove, Reset, and an
  **Include text values** toggle. It states what it aggregated (`calcScopeText`) and explains
  itself over an empty selection rather than showing zeroes. **Zero executions, asserted by count.**
- **`GroupingPanel`** — grouping columns (added by dragging a grid header onto the panel or through
  a picker, reordered with Move earlier/later) and aggregates (`COUNT(*)` by default; `SUM`, `AVG`,
  `MIN`, `MAX` against a named column), staged and applied as **one** execution. Plus
  **Show duplicates only** (`HAVING COUNT(*) > 1`) and the labelled percentage column.
- **`GeneratedSqlDisclosure`** — the statement the exploration ran, read from `useExploration.sql`,
  available grouped or not, selectable and copyable.
- **`setGrouping` / `groupingApplyRefusal` / `groupingOrderingViolation`** — the grouping edits and
  the one ordering rule, shared with the renderer.

`Grouping` gained `duplicatesOnly` and `showPercentage`; `renderExplorationSql` gained the `HAVING`
clause. No IaC, no IAM, no new AWS call, and **no new `GATED_SURFACES` row** — everything here is
inside `/explore`, which `dataExplorer` already gates.

### Deliberate deviations

- **The percentage is of the rows on the current PAGE, and the column says so** — `% of count_all
  (this page)`. Only one page of a result is in the browser, so a share computed here is a share of
  those rows; a column headed `% of count_all` beside a paged result would be read as a share of the
  table, which is the scale lie grouping exists to avoid. A whole-result figure would need a
  windowed second scan of data the user asked only to *see*.
- **Grouping mode is exactly "at least one grouping column"** (FR-003 AC6 read literally). A
  grouping with aggregates and no columns is legal SQL — a global aggregate — but it is not
  reachable from the panel, because "no columns left" has to mean "not grouped" or the user is left
  in a mode with nothing in it.
- **The percentage rides on `Grouping`, not on `ExplorationPresentation`.** It renders no SQL (a
  test asserts that), but it is meaningless without the grouping it describes, and a grouping
  restored from `sessionStorage` has to restore whole.
- **`CalcPanelState` is region state, not tab state.** It describes a selection, and a selection
  does not survive a page change — persisting the function list with the tab would outlive
  everything it was chosen for.
- **The ordering refusal lands on the Grouping panel's Apply, not on a sort control.** While a
  grouping is in force the grid shows only the grouped columns and the aggregates, so every column
  a user can reach IS orderable; the one reachable way to build the conflict is to sort a column and
  then group it away.

## What changed from earlier specs?

- **`clearAll` now clears the grouping** (FR-006 AC3), superseding SPEC-181's deliberate
  preservation, and **the control's label changes with it** — `Remove all filters` becomes
  `Remove all filters and grouping`. `isEmptyQuery` counts grouping too, so its refusal wording
  changed. A control that said "filters" while removing a grouping would be lying about the click,
  which is what 181 was protecting against; naming it is the other way to keep that promise.
- **`ExplorationResultsRegion` takes `sql`** and appends the percentage column before geometry
  resolves; `ExplorationGrid`/`ExplorationGridHeader` gained an optional `onColumnDrag` so a drop
  target outside the grid can learn what a header drag is carrying. The header's own reorder ref is
  untouched.
- **`canonical()` folds the grouping's two flags explicitly** rather than stringifying the object
  raw, and `readExplorationTabsState` normalises them (absent ⇒ false) on the way out. Both are
  needed together: a document written before this spec carries neither flag, and an absent flag
  comparing unequal to `false` would push a history entry for an apply that changed nothing.

## The two decisions worth carrying

**Calc is client-side because of what it IS, not to save money.** It aggregates the cells a user
selected, and a selection exists only in the browser — so a server-side Calc means a billed
execution per selection change, for a gesture as cheap as dragging across ten cells. Grouping is the
mirror image: aggregating in the browser would aggregate whichever rows happened to be fetched. That
is why the panel says "N selected cells on this page" every time it says anything.

**`groupingOrderingViolation` is exported for the same reason `isBareNumeric` was.** The renderer's
refusal names a column and an operator — operator text SPEC-106 forbids showing a user — so the
panel has to word its own refusal, and a second rule at the panel is a rule that can disagree. The
way it would disagree is a grouping the panel accepts and the renderer throws on, which takes the
whole exploration to an error banner. One rule, two wordings.

Beside it, `setGrouping` drops any sort on an **aggregate's** output column when grouping ends:
`count_all` exists only while the grouping does, so carrying that `ORDER BY` onto the raw table is a
query Athena rejects — and it would also miss the cached ungrouped execution AC6 promises to return
to.

## Verification

`npm run format`, `npm run lint`, `npm run build` and the full Vitest suite (2390 tests, 111 files)
green locally; coverage above every floor. Three new test files —
`calc.test.ts` (the arithmetic), `calcPanel.test.tsx` (the panel, including the zero-execution
assertion) and `groupingPanel.test.tsx` (the SQL that reaches Athena and how many statements do).

## Live checks owed

**None.** This spec adds no infra, no IAM and no AWS call the app did not already make: a `GROUP BY`
is the same `StartQueryExecution` the feature has been making since SPEC-178, and Calc makes none at
all. What no test can see rides SPEC-185's Safari pass: the two side panels beside the grid at 400px
(both are in-flow rather than fixed sheets, so they stack under the grid), the `<details>` disclosure
with a long statement in it, and the header-drag-to-panel gesture, which jsdom can only simulate.

## Help & guides

**No change, deliberately.** SPEC-185 writes the Data Explorer's Help content once the feature is
shipped end to end and gains the `dataExplorer` guide row there (SPEC-074 FR-005 — document only
what is wired end to end). A guide written now would be rewritten at 183 and again at 184.
