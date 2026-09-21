# Completed Spec — SPEC-242: A Query Result Opens in Data Explorer, and a Selection of Statements Gets a Tab Each

## What was completed?

- **A multi-statement selection gets a result tab per statement.** `handleRunStatement` in
  `QueryWorkspace.tsx` submits with the tab-per-statement scope when `resolveRunStatements` returns
  more than one statement, and `'statement'` otherwise.
- **Explore in Data Explorer** on the Query status bar, beside *Save results to my files* and on
  Save's terms: the displayed result, whatever the batch's verdict, once its columns have arrived.
  Offered only for a statement `isExplorableSql` (`query.sql.ts`) accepts — SELECT, WITH, VALUES —
  with both the `query` and `dataExplorer` flags on and the editor owning the run. A result with a
  `_colN` column, or two names equal once lowercased, gets the control disabled with
  `unnamedColumnsRefusal` (`features/query/exploreResult.ts`).
- **`lib/routeHandoff.ts`** — `ExploreSqlHandoff`, `buildExploreSqlHandoff`, `readExploreSqlHandoff`.
  The statement rides router state, never the URL. SPEC-243 adds its own hand-off beside it.
- **The Explorer consumes a hand-off once.** `DataExplorerWorkspace` reads it per history entry
  (`location.key`, since `StrictMode` runs the effect twice), opens a `sql` tab through a shared
  `openExplorationTab` (the picker and the deep link use it too), evicts only that body's cached
  executions with `evictSqlSource` (`useExplorationEviction.ts`), and replaces the entry with no
  state — at the tab limit too. While a hand-off is pending, the restored tab runs nothing.
- **A `sql`-source tab works end to end.** `ExplorationTab.sqlSourceColumns` is recorded from each
  ungrouped succeeded execution (`ExplorationResultsRegion`'s `onSourceColumns`,
  `useExplorationTabs.setTabSourceColumns`), persisted and validated in `explorationTabs.ts`, and
  returned by `useSourceColumns` so the Grouping panel lists the source's columns while a grouping
  is applied. *Create view…* refuses with `SQL_SOURCE_VIEW_REFUSAL`.
- **`rendersFromSqlBody`** (`renderExplorationSql.ts`) and **`readsFromSqlBody`** (`explorerKeys.ts`)
  say which body a cached execution read, judged at the outer `FROM`.
- **Registry and guides:** *Explore in Data Explorer* under `dataExplorer` and *Explore in Data
  Explorer on a query result* under `query`, each with a recipe; a step each in the `run-script`
  and `start-exploring` guides.

### Deliberate deviations

- **`sqlSourceColumns` is recorded from every ungrouped execution, not only the first.** Every run
  of one body reports the same list, so a repeat is a no-op, and the list stays right if the tables
  under the statement change shape. The spec was updated.
- **A deep link on the same entry opens first**, and its `clear()` now keeps the history state so
  the hand-off survives it (found by the diff review; unreachable from today's only sender).
- **The restored tab runs nothing while a hand-off is pending.** Not in the draft; found by the plan
  review, since after a reload the restored tab's statement would otherwise be billed on the way
  past. The spec was updated.
- **`renderWithProviders` gained `strictMode` as well as route state.** A `<StrictMode>` handed in
  as the element under test runs every effect once, so the StrictMode criterion could not fail; the
  option renders StrictMode as the placed root. Found by a mutation that deleted the `location.key`
  guard and stayed green.
- **One `eslint-disable-next-line react-hooks/set-state-in-effect`** on the hand-off effect. The
  deep link beside it sets the same state from an effect and passes only because the compiler's
  analysis does not trace it; which of two identical shapes the rule flags turned on incidental
  features of the event body.

## What changed from earlier specs?

- `ExplorationSource`'s `sql` arm, unreachable since SPEC-178, is now opened by the Query hand-off.
  Loading a saved `.sql` file as a source is still deferred (SPEC-183's register entry is marked).
- The *Create view…* refusal is reworded to cover SQL opened from a query or a saved file.
- `useSourceColumns` takes the tab's remembered columns as a second argument.
- `QueryStatusBar` takes an `explore` prop; `QueryResultsRegion` passes it through.
- `useExploreDeepLink`'s `clear()` keeps the history entry's state across its replace.

## Verification

Formatter, lint, `tsc -b`, the portal suite and `npm run build` green by exit code, plus the branch
validators `ci.yml` runs and the Python gates. Mutation batteries over the hand-off, the Query-side
gate, the column memory and both flags against the registry walk — each plant reddens its test. The live check (select two
SELECTs, Run Statement, explore the second, hide and filter a column, reload) is folded into
`docs/testing/e2e.md` as §4.5 rows G to K. It ran on 2026-09-21 and every row passed, including
re-exploring a statement explored earlier (`docs/testing/sessions.md`, 2026-09-21 evening).
