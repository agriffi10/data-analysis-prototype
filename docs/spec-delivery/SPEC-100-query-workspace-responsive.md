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

## Correction — review findings fixed after merge

The fresh-context review ran **after** `#337` merged (it should have run before). It found two real
defects, fixed in the follow-up PR; both are worth knowing because they are the kind a mobile branch
invites.

1. **The mobile results view could wear another query's outcome.** The gate keyed on the SQL *text*
   plus "a run was requested", while `status`/`results` came through ungated. `submitBatch` installs
   its run **asynchronously** (it awaits `runQuery` *and* the history append), so between the tap and
   that commit the view showed the new query's title over the previous run's Succeeded strip and rows
   — and if `runQuery` failed outright, that pairing was permanent. Crossing the breakpoint mid-run
   left the same mismatch. Fixed with a **run token**: `submitBatch` takes an optional caller token,
   stores it on the `TabRun`, and returns whether the submit began; the view adopts status/rows only
   while `activeRun.token` is its own, treats "requested, not yet installed" as in-flight, and its
   state resets when the viewport leaves mobile. **SQL text is not a run identity.**
2. **Running a card overwrote the editor's persisted draft.** `handleMobileRun` called
   `tabs.setActiveSql(sql)`, which `useQueryTabs` persists to sessionStorage — so a run from a narrow
   window destroyed a draft the user left on a wide one. `submitBatch` takes its statements
   explicitly and never read that buffer, so the write served nothing. Removed.

Further review passes hardened it. The next rejected the first attempt at (1): the token closed the wrong-data hole but
derived "pending" by elimination (*token set, no run, no error*), so **dismissing a failed run's
banner flipped the view into a permanent "Running your query…"**, as did any change of active tab
under the view. `phase` is now reported by the submit itself (`submitBatch` takes an `onOutcome`
callback) and the ownership check is scoped to the tab the run was submitted into. The same pass
found the drawer's **View data / View DDL** are reachable on a phone, where they opened a tab nothing
can display — both now route into the mobile results view.

A later pass found the fix had **moved** the mismatch rather than removed it: a mobile run
deliberately leaves the editor buffer alone, so crossing back up to `tablet` paired the editor's
draft with the mobile run's results. The editor shell now **disowns any run carrying a token** — status strip, error banner, results
grid, result tabs, page-size control and the empty-state line (`editorOwnsRun`), with one line
explaining the locked toolbar while such a run is still in flight — the run itself keeps polling, finalizes and lands in history,
exactly as a closed tab's does. The same pass caught that an unreported submit (a service that
*throws* rather than returning a failed `ServiceResult`) would leave the view waiting forever, that
Run stayed enabled while the view said "Running your query…", and that the editor-shell drawers
(history / saved queries) stayed mounted on mobile where their Open/Re-run actions write the editor
buffer. All three fixed; `submitBatch`'s run identity is now a single `{token, onOutcome}` object so
a token can't be passed without the callback that settles it.

A final pass closed the last of the family: a mobile submit that fails **never installs a run**, so
no token can mark it and its banner landed on the editor shell — clearing it at the crossing only
narrowed the race rather than removing it. An owned submit's failure now travels through
`onOutcome(false, message)` into the mobile view's own state and **never touches the tab's
`runErrors`**, so there is no moment at which it can be read as the editor's.

Also fixed: Back now returns to the list the run started from (it always landed on Saved);
`useAllSchemas` is skipped below `tablet` (2 Glue calls per database for an autocomplete that can't
exist there); history-row and card actions are ≥44px on a phone (they were 24px/36px, missing Phase
4's own target).

> **Correction (2026-09-01) — the ≥44px claim in the sentence above is false, and was false when
> written.** The controls carry `min-h-11`, whose px value was read off the class at an assumed 16px
> root. This app's root is **14px** and the spacing scale is rem-derived, so `min-h-11` draws
> **38.5px**, measured in a browser. The intent was explicit — the commit adding it said "≥44px touch
> target on a phone" — and it missed. Left at 38.5px deliberately: 44×44 is SC **2.5.5**, which is
> **AAA**, and this project targets A + AA
> (`apps/portal/info/best-practices/accessibility/accessibility.md`). 38.5px clears SC 2.5.8's AA
> floor of 24 comfortably, so nothing here fails the level the project holds itself to, and raising
> seven call sites — both history-row actions, the mobile card action, the nav drawer, the header
> nav link and the username combobox rows — would be a visual change to buy a criterion that is not
> a target. The AAA gap is recorded as consciously not met rather than fixed. **`MobileQueryView` is now `{kind:'home'} | {kind:'results',…}`** with the home tab
held beside it — the spec's shape kept the tab inside `home`, which made Back's target a second
source of truth.

**Known, accepted:** a submit that fails *after* the user has left the results view (Back, or the
viewport growing past `tablet`) is now silent — its error belongs to that view's state, which is
gone. The window is one `runQuery` round trip, and the alternative that was rejected is worse: the
banner reappearing beside SQL that didn't produce it. A toast would close it; the ownership check
lives inside a state updater, where a side effect doesn't belong, so it wants a small refactor rather
than a one-liner.

**Correction to this document:** the Verification line below originally said lint includes the React
Compiler. It does not — this repo has no `babel-plugin-react-compiler` and `vite.config.ts` uses bare
`@vitejs/plugin-react`; only `eslint-plugin-react-hooks`' compiler-backed *lint rules* run.

## Verification

`format:check` + `lint` (incl. the security plugins) + `tsc -b` + `build` clean;
full suite green — **1216 tests** (+23 with the spec, +9 more with the review fixes: cross-query
outcome, editor draft untouched, Back's target, a dismissed failure not claiming to be running, an
honest in-flight state before the run installs, a throwing submit still settling, View data from the
drawer landing somewhere visible, and two crossing-the-breakpoint handoffs). New: `QueryMobileView.test.tsx` (8), `QueryResultsMobile.test.tsx`
(8), a `QueryWorkspace` responsive block (mobile pares to browse-first, rail off-canvas via a
`NavRailProvider` probe, saved-card Run → row cards + pager → back, tablet toolbar labels) and a
mobile route-level axe case. **On testing a breakpoint crossing:** the harness's `matchMedia` stub has no-op listeners, but its
`matches` is a live getter over `window.innerWidth` and `useBreakpoint` re-reads the snapshot on every
render — so setting the width and re-rendering the tree *does* cross the tier. An earlier draft of
this doc claimed it couldn't be done, and both defects the last review found were in exactly that
path; the leaving-mobile handoff is now covered by two tests.
**Not browser-verified:** `/query` is auth-gated and the preview can't
hold a Cognito session (same limitation recorded in SPEC-099); the breakpoint tokens themselves are
browser-verified via SPEC-095.
