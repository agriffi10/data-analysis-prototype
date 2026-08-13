# Completed Spec — SPEC-181: Filtering and Ordering

## What was completed?

The Data Explorer can now be *used*: every filter and every sort renders new SQL through
SPEC-178's builder, mints an Athena execution, and reports what it scanned. Nothing is filtered or
sorted in the browser.

- **`ColumnFilterMenu` + `FilterValueDialog`** — the per-column header menu: sort ascending /
  descending / clear, the six comparisons (each opening a value input), `IS NULL`, `IS NOT NULL`
  and clear filter. Its accessible name identifies the column *and says what that column is doing*.
- **Filter by this value** — a toolbar action over the focused cell, using its **raw** value.
- **`ExpressionBar`** — a verbatim `WHERE` fragment, applied on Enter or Apply and **never** on a
  keystroke.
- **`OrderFilterDialog`** — every column's visibility, pinning, sort and criteria, staged and
  applied as **one** execution.
- **`FilterHistoryControls`** — Back and forward through this tab's descriptions.
- **`CostIndicator`** — what the last apply scanned and what the tab has scanned.
- **`useExplorationQuery`** — the one door every description change goes through: apply, clear all,
  the history cursor, and the failed-statement hold.
- **`explorationQueryOps`** — the pure edits (set/clear filter, set/clear sort, priority moves,
  `filterValueKind`, `sameQuery`, `isEmptyQuery`) shared by all three surfaces.

`ExplorationTab` gained `history: QueryHistoryCursor`, persisted with the tab;
`EXPLORER_FILTER_HISTORY_MAX` is 25. No IaC, no IAM, no new AWS call, and **no new
`GATED_SURFACES` row** — everything here is inside `/explore`, which `dataExplorer` already gates,
and the expression bar is deliberately ungated (below).

## The four decisions worth carrying

**One `apply` per gesture, and the surfaces cannot do it any other way.** Every filter and sort
edit is a `Partial<ExplorationQuery>` handed to `useExplorationQuery.apply`, which writes the tab's
description once; `useExploration` then renders one statement and the execution cache decides
whether it costs anything. "One gesture is one execution" is therefore a property of the feature
rather than a rule each of the four surfaces has to keep.

**A numeric filter is refused at the INPUT, using the renderer's own predicate.** SPEC-178 emits a
numeric value bare (Trino does not coerce) and throws `ExplorationRenderError` for a value that is
not a number — and that message names a column and an operator, which SPEC-106 forbids rendering.
So `isBareNumeric` is now exported and both the value dialog and the settings dialog refuse with it.
A second numeric rule at the input is a rule that can disagree with the renderer; there is one.
The same predicate also drives a `disabledReason` on **Filter by this value**, so a numeric column
whose cell holds something unfilterable refuses at the gesture rather than seconds later.

**A failure keeps the previous rows, and the toolbar never goes away.** `ExplorationResultsRegion`
was restructured: the query toolbar and the expression bar render whatever the results are doing,
and `useQueryResults` is pointed at the last execution whose rows actually arrived while the current
one is failed. A failed apply has to leave the user somewhere they can correct it, and a toolbar
that disappears with the rows takes the correction with it (FR-003 AC4/AC5).

**Athena's own refusal had to be turned into an error before it could be worded.** A query Athena
rejects is not an error anywhere in the plumbing — `getQueryStatus` resolves and the reason arrives
as `stateChangeReason` on a successful poll — so `useExploration` now surfaces a
`FAILED`/`CANCELLED` execution as `{code, message}`, the shape `toUserMessage` maps engine text
from. Without it, a syntax error in the expression bar surfaced one layer later as "couldn't read
the results", which is a true sentence about the wrong thing.

## Deviations from the spec, and the reasons

- **`useExplorationQuery(tabs, tabId)`, not `useExplorationQuery(tabId)`.** The history lives with
  the tab in `sessionStorage` (FR-006 AC3) and `useExplorationTabs` owns that document. A hook that
  read its own instance would be a second copy of the same state — two writers to one key,
  diverging on the first edit. The tab id still names *which* tab, because a description and the
  history entry it pushes must be written in one update; `useExplorationTabs` gained `updateTab`
  for exactly that.
- **No `stage`.** The spec's staging channel is query-only, and the settings dialog stages
  presentation too (FR-005 AC3 — "Cancelling discards every staged change, **including the
  presentation ones**"). Split across two places, half a draft could survive a Cancel. The dialog
  holds **one** draft object and `apply` takes the whole staged description, which makes AC3
  structural rather than a rule two pieces of state have to keep.
- **No field in the settings dialog submits on Enter.** `FormDialog`'s implicit-submission
  suppression is on (inputs *and* `<select>`s), and no `submitOnEnterRef` is designated: every
  field in this dialog is a criteria row, and a criteria row filing the whole dialog is precisely
  what SPEC-155's rule exists to prevent. AC5's "exactly one field" presupposes a dialog with a
  primary field this one does not have. Enter on Apply still submits, natively.
- **Remove all preserves `grouping`.** FR-007 says "every filter, the expression and every sort";
  grouping is SPEC-182's, and un-grouping a view from a control labelled "Remove all filters" would
  be a change nobody asked for.
- **`ExpressionBar` sits below the toolbar, not "above the grid".** Same region, one row lower, so
  the toolbar's controls stay on one line at tablet widths.
- **A fourth test file.** `queryHistory.test.tsx` carries FR-006, FR-007, FR-008 and the pure ops;
  the three the spec named cover FR-001/002, FR-004/005 and FR-003.

## FR-006 AC4, which needed a mechanism the spec did not name

"Navigating history never re-runs a query that failed" cannot be satisfied by the cache: SPEC-178
deliberately **evicts** a failed execution on the way out, so restoring its description would start
a fresh one. The tab therefore keeps an in-memory set of statements seen to fail this session, and a
history step onto one *suspends* — `useExploration` is handed nothing to run, the region says the
set of filters failed last time, and a **Run it anyway** control is the retry. An `apply` always
clears the suspension, because an apply *is* the user asking for it again. The set is not persisted:
a failure from a previous session should not stop this one from trying.

## What cost reporting can and cannot be

**A pre-flight "this looks expensive" confirm is not buildable.** Athena will not report what a
query will scan before running it — there is no dry-run, no `EXPLAIN` byte estimate, and the
per-query statistics exist only once the execution has finished. So the only honest guards are the
workgroup's per-query cutoff and reporting after the fact, which is what FR-008 asks for and all it
could have asked for.

A cache hit **says so** rather than showing the figure the execution originally scanned: that number
is true about the execution and false about the gesture. It is decided by reading the tab's ledger
*during render, before `recordScan` writes to it* — after that write every execution looks known and
every apply would report itself free.

## What review changed

A fresh-context review found five real defects and three weak proofs. Every fix has a test that was
**mutation-checked** — the fix is reverted, the test must redden.

- **The per-apply cost was frozen at the first poll, so the surface read "This query scanned 0 B"
  for every real query.** A `QUEUED`/`RUNNING` poll carries no `Statistics`, so `cost` reported a
  confident zero; the per-apply figure is captured **once** per execution (deliberately — a cache hit
  has to be read before the ledger is written), so that zero stuck while the running total beside it
  said 2 GB. `useExploration` now reports `cost` only for a **terminal** state. Every test fixture in
  the feature returned `SUCCEEDED` on the first call, which is what hid it; the new test polls
  `RUNNING` then `SUCCEEDED`.
- **`suspended` was one boolean for every tab.** A held-back history step in one tab handed
  `useExploration` nothing for *all* of them: the next tab ran nothing and said a set of filters had
  failed that never had. Reset during render when the tab id changes.
- **The last-good-execution fallback was not per tab.** A tab whose *first* execution failed drew
  the other tab's rows and columns under its own error banner. It is now keyed by tab id — and the
  test that catches it needed the failing tab to have **never succeeded**, because a tab with a good
  execution of its own falls back correctly either way.
- **The header menu's operator list was a hand-written array cast to `FilterOperator[]`**, so three
  of the six comparisons could be deleted and still compile — and nothing exercised more than two of
  them. It is derived from `FILTER_OPERATORS` now, with a test asserting the whole menu.
- **`FilterValueDialog` was rendered inside a `<th>`.** `Modal` does not portal, so a dialog opened
  from a non-pinned header would be confined to that cell's `z-20` stacking context and paint under
  the `z-30` sticky headers, scrim and all — invisible to jsdom. The region raises it now; the menu
  asks.
- Two smaller ones: **"Running…" was announced while nothing was running** (the status line sat above
  the panel saying nothing had been run), and **"Run it anyway" did not forget the failure**, so a
  transient failure that then succeeded went on suspending that description all session.
- **`apply` built its description outside its own state updater**, so two applies batched into one
  commit would lose the first change and push a history entry equal to the description it replaced.
  Not reachable from a single gesture today; reachable the moment any surface calls `apply` twice.

Two weak proofs were tightened: the cache-hit assertion waited for cells that were already on screen
(it waits for the sort to leave the menu's name now), and a comment claimed to seed one entry short
of the history cap while seeding exactly the cap.

## Accepted tension, and one limitation

**FR-005 AC5 is literally unmet, knowingly.** It asks for "exactly one field submitting on Enter";
the settings dialog designates **none**, because every field in it is a criteria row and a criteria
row filing the whole dialog is what SPEC-155's suppression exists to prevent. The AC's other half —
implicit submission suppressed, `<select>`s included — is met and tested by `defaultPrevented`
(jsdom implements no implicit submission, so "the dialog stayed open" would prove nothing).

**A column that is neither text nor a number has no working filter.** `FilterValueKind` has two
arms, so a `timestamp`, `date` or `boolean` column filters as a quoted string and Trino — which does
not coerce — rejects the comparison; the user gets SPEC-106's wording for a query error rather than
anything actionable. Refusing the gesture up front would be worse (a `varchar` column holding dates
filters fine), and a third kind means either a `CAST` in the renderer or a temporal input, both of
which are model changes SPEC-178 owns. It is the first thing SPEC-184 should pick up if formatting
brings types with it.

## Notes for the next spec, and for the Safari pass

- `valueKind` now has its producer (`filterValueKind`, from the column's declared type, covering
  both Athena's and Glue's spellings) — see the limitation above for the types it cannot serve.
- The header menu is **grid-only**, so below `tablet` (where Record is the default) filtering and
  sorting are reached through **Order and filter**. Worth confirming that path in SPEC-185's Safari
  pass, along with the two things no test can see: the menu popover inside the grid's scroll
  container, and the settings dialog's row layout at 400px.

## What is NOT here

Grouping and the Calc panel (SPEC-182), saved queries as a source (SPEC-183), formatting and
transformers (SPEC-184), copy/export and the Help guides (SPEC-185). Named, saved or persisted
filters are **out of the arc** — history is per tab and per session, and a named filter implies a
store.

## Help & guides

**No change, deliberately.** The Data Explorer has no guide yet: SPEC-185 writes the Help content
for the whole feature once it is shipped end to end, and gains the `dataExplorer` guide row in
`GATED_SURFACES` there (SPEC-074 FR-005 — document only what is wired end to end). Adding a guide
for filtering alone would have to be rewritten twice, at 182 and at 184.

## Live checks owed

**None.** This spec adds no infra, no IAM and no AWS call the app did not already make: a filter,
a sort and an expression are the same `StartQueryExecution` the feature has been making since
SPEC-178. The CSS-only observations above ride SPEC-185's Safari pass.
