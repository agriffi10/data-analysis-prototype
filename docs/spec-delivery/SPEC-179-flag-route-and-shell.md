# Completed Spec — SPEC-179: the Feature Flag, the `/explore` Route and the Shell

## What was completed?

The Data Explorer became reachable. A user can open **Data Explorer** in the primary nav (or
**Explore data** on a table in the Query rail), pick a space and a table, and see rows — through
SPEC-178's engine.

- **A fifth `FeatureFlagKey`, `dataExplorer`**, wired end to end.
- **`/explore`** — lazy, `FeatureRoute` → `ErrorBoundary` → `Suspense`, in that nesting.
- **`PrimaryNav` + `AppNavDrawer`** gained the tab, gated through the existing predicate.
- **`features/data-explorer/`** gained its first surfaces: `DataExplorerWorkspace`,
  `SourcePicker`, `ExplorationTabStrip`, `ExplorationLimitDialog`, `ExplorationResultsTable`,
  `useExploreDeepLink` and the pure `exploreSources`.
- **`TableActions` gained `onExploreData`** — the rail item, gated by two flags.

## The results table is a PLACEHOLDER, and its emptiness is not a regression

`ExplorationResultsTable` is a plain table over `useQueryResults` and the shared `Pager`. No column
resize, reorder, pin or hide; no cell selection, Value panel, Record or Text presentation. **SPEC-180
replaces it wholesale.** Nothing about its markup is a contract, and a reviewer who finds it thin has
found the thing the spec said it was building.

## The flag is a SIX-place change, and TWO of them are Python

FR-001 listed the workflow matrix as the fifth site. The matrix is per **environment**, not per flag,
and needed no edit. The real sites are `scripts/validate_feature_flags.py`, which hard-codes
`FLAG_KEYS` and refuses an unknown key — left unchanged, the publish job would have failed on the
very document this spec added a key to — and `lambdas/test_feature_flags_config.py`, which
**re-states the same tuple on purpose** so a test cannot pass by agreeing with a mistake it imported.

**That second one went red in CI, and the reason is worth recording.** The four local gates this
repo names are `format:check`, `lint`, `build` and vitest; none of them run pytest, and the Python
half of a flag key lives entirely outside them. The test did exactly its job — it is the guard that
fails when a key is added in five places instead of six — but it failed on the PR rather than on the
laptop, because the change touched Python and the pre-push routine did not. **A change touching
`scripts/` or `lambdas/` needs `pytest lambdas/` before the push**, not just `ruff`. The compiler found the rest of the fan-out on
its own: `HelpPage`'s flag map is total over `FeatureFlagKey`, so a partial one type-errors rather
than silently answering `undefined` — falsy, therefore "hide every guide" — the day SPEC-185
registers the first Data Explorer guide.

`FEATURE_FLAG_KEYS` order is load-bearing beyond iteration: `FeatureRoute` offers the first ENABLED
feature as its fallback link, so the new key is appended **last** and no existing unavailable page
changed where it points.

## The picker has no database step, and that is a deviation with a reason

FR-005 specifies *space → database → table*. A space maps to exactly **one** Glue database here
(personal → the username, a shared space → its own name, both from `useConnections`), so a database
control would offer one option — the one-option control SPEC-163 declined to render for the share
dialog's recipient kind. The picker is two panes and the database is **shown** beside its space.
`?db=` survives as a **cross-check**, not a choice: a link naming a database that is not that space's
resolves to nothing and opens the picker. `spaceDatabase()` is the single definition of the mapping.

FR-005 AC3's "a database the user cannot see is absent rather than present-and-failing" is honoured
one step later than the wording implies: the space list comes from **memberships**, which are known
reachable, and an unreadable database renders "this space's tables aren't available right now"
instead of a failing table list. No table is ever offered that cannot be read.

## Two holes the tests found, both about asking Glue too early

**The picker mounted while a deep link was still resolving.** `useConnections` reports loading before
the shared spaces arrive, and the workspace rendered the picker in the meantime — which reads the
*personal* space's database. So the denied case issued a Glue call and then swapped to the refusal a
tick later: still an answer about a catalog, just about the wrong space. The workspace now renders
`LoadingState` while a resolution is pending, and the hook reports `loading` **only when a `?space=`
is actually present and `sharedWorkspaces` is on** — without one there is nothing to wait for, and
with the flag off the parameter is discarded unread, so either way the wait would be for a value that
cannot change the answer. This is `FeatureRoute`'s own rule, one layer down.

**The deep link had to stop re-opening.** Tab state survives a reload through `sessionStorage`
(FR-008 AC4), so a link left in the URL bar would stack a duplicate of the linked table on every
reload. The parameters are dropped with `replace` once acted on.

## Five registry rows, and one surface registered under TWO flags

`GATED_SURFACES` gained `Data Explorer` (nav), `/explore` (route) and `Explore data` (the rail item)
under `dataExplorer`; **`Explore data on the Query schema rail` under `query`**; and
**`Shared spaces in the Data Explorer source picker` under `sharedWorkspaces`**.

The rail item is the mirror image of "Create table" — a Data Explorer capability living on a Query
surface — so it is gated by `dataExplorer && queryEnabled` and registered under both. One row per
(surface, flag), because either gate can be deleted alone. **Verified by violation**: dropping
`explorerEnabled` from the condition reddened both the walking test's `dataExplorer off hides
"Explore data"` and the menu-shape test below; reverting restored green.

`schemaUi.test.tsx` gained the assertion the walking test cannot make — that with `dataExplorer` off
the rest of the menu is **unchanged**. A conditional written one bracket wide takes Refresh table and
Share table with it, and "the item is gone" would still pass.

## Verification

Every gate green locally **by exit code**, and these are the POST-REVIEW numbers — the run after the
findings below were applied: `format:check`, `lint`, `build` (`tsc -b` + vite), and vitest `0` at
**2270 tests / 100 files** (2238 / 99 on `origin/main`). `npx vitest run --coverage` exits `0` at
**93.04 / 88.92 / 92.57 / 94.81** against the SPEC-150 floors of 91/86/89/93 — no floor lowered.
`ruff check lambdas/ scripts/` passes, `python3 scripts/validate_feature_flags.py` exits `0` against
the updated document, and `pytest lambdas/` exits `0` at **3650 passed** — the gate that caught the
sixth flag site, and the one this change had to learn to run.

**One flake seen once and not reproduced**: `archiveJourney.test.tsx > takes the WHOLE selection`
failed in a single full run and passed on re-run, in isolation, and in every run since. Recorded
rather than hidden; it touches nothing this spec changed.

The `/explore` route's `ErrorBoundary` wrapping is asserted **structurally** (the route block's
wrapper order, with a guard-the-guard on the match) rather than by forcing a chunk rejection: the
boundary's own behaviour is covered in `layout.test.tsx`, and what only App can answer is whether
this route is inside one — and inside the gate.

**Nothing live is owed.** No infra, no IAM, no new AWS call: `getDatabase`/`listTables` and the
Athena trio the Query workspace already makes. The flag document's new key rides the next `config/**`
merge through `Deploy Config` — and note **CLAUDE.md's standing caveat** that a past hand-edit left a
git↔bucket drift, so the first publish after this merge is also the reconciliation.

**User-facing docs sweep: deliberately deferred, recorded here.** SPEC-074 FR-005 documents shipped,
wired-end-to-end behaviour, and the feature ships here with a placeholder grid; the spec puts Help
guides in SPEC-185, which is also where the `dataExplorer` guide row joins `GATED_SURFACES`. Nothing
in `helpContent.ts` or `lib/errorMessages.ts` changed.

## What the fresh-context review changed

Seven findings, all applied. Three were real defects:

- **A denied deep link started an Athena execution.** The guard read `denied ? null : …`, and
  `denied` is false during the resolution window — so a tab restored from `sessionStorage` minted a
  real `StartQueryExecution` for a page that then rendered nothing but the refusal. FR-006 AC2's
  letter survived (the execution is against the user's *own* table, and no Glue call was made), but
  cost is this feature's declared through-line and a billed query behind a refusal is the wrong kind
  of correct. The guard is now "the link is not settled", and the test that missed it seeded no tabs
  — the new one does. **Verified by reverting the fix**: the test reddens.
- **The tab strip shipped a WCAG violation the Query strip was written to avoid.** A focusable
  `<button>` close control inside `role="tab"` trips `aria-required-children` and
  `nested-interactive`; `QueryTabStrip` carries comments saying precisely this must not happen. The
  ✕ is now a non-focusable `role="presentation"` span with Delete on the focused tab as the
  operable path (WCAG 2.1.1), the tab carries `aria-controls`, and the results region is a real
  `tabpanel`. **There was no axe assertion anywhere in this feature** — there are two now, and
  restoring the button reddens them.
- **FR-003 AC1 was not asserted against the real route.** The structural test captured wrapper
  element names only, so changing `App.tsx`'s gate to `flag="query"` left the entire suite green —
  a flag bypass, because the walking test builds its own `<FeatureRoute>` around a stub and never
  reads App's. The test now pins the exact opening tag; the mutation reddens it.

The rest were accuracy: two comments that overstated what the code guarantees (closing the active
tab *can* run the neighbour that slides into view, if it was restored and never opened; the `+`'s
cap check reads state, which is honest for one human click but is not `openTab`'s authority), the
`?space=` loading gate now also checking `sharedWorkspaces` so FR-006 AC5's "not read at all" is
literally true of the page and not just the resolver, and a test for `SourcePicker`'s
database-unavailable branch.

**One finding was recorded rather than changed.** FR-006 AC2 says "zero Glue **and S3** calls", and
the denied path does make one S3 read: `readSharedConnectionsCache`. That document is the user's own
cache of their own memberships, it is what resolution is *made of*, and `useDataQualityReport` reads
it on the same path for the same reason — no request touches the space named in the link. Noted here
because the AC's wording and the build differ, and the difference should be visible.

## Notes for the next spec

- **SPEC-180 owns the grid** and replaces `ExplorationResultsTable` entirely. `EXPLORATION_PAGE_SIZE`
  (100) is the placeholder's, not a contract.
- **`valueKind` still has no producer** (SPEC-181), and `ExplorationRenderError`'s message is still
  operator text SPEC-106 forbids rendering — the results table maps every error through
  `toUserMessage`, so a refusal reaches the user as the generic sentence rather than a column name.
- **The `sql` source arm remains unreachable from any UI**: the picker offers tables and views only.
  SPEC-183.
- **`SourcePicker` re-fetches a schema per selected space** through `useSchema`, sharing SPEC-176's
  per-database query keys with the Query rail — a database already expanded there is already cached.
