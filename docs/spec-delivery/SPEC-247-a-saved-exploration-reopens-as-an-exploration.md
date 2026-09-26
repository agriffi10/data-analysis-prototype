# Completed Spec — SPEC-247: A Saved Exploration Reopens as an Exploration

## What was completed?

- **Save carries the view.** A Data Explorer **Save as query** on a table tab writes the SQL that ran
  and one `-- dataquarry-view:v1:…` comment line recording the view: source, filters, expression,
  sort, grouping, column layout and formatting. It is still one object. The format lives in
  `lib/savedViewLine.ts` (`appendViewLine`, `parseViewLine`, `viewChecksum`); what the payload
  means is `features/data-explorer/savedView.ts`.
- **Open saved view.** The source picker's new control opens `OpenSavedViewDrawer`, a list of a
  space's saved queries built from the store's own pieces. `useOpenSavedView` reads, parses,
  strictly validates and renders the view, finds its space by database once the connections read
  settles, and opens a tab or shows `SavedViewRefusal` with **Open in Query**.
- **Trust follows the file's folder.** From the personal folder the view restores whole, runs and
  is linked. From a shared space's folder it opens **held** (`ExplorationTab.awaitingRun`,
  `useExploration`'s `hold`), without URL transformers or `regex`/`like`/`ilike` Colors rules (a
  note counts them), and **unlinked**.
- Strict reads `readStrictQuery` / `readStrictPresentation` in `explorationTabs.ts`: the store's
  normalisers must leave the payload unchanged, no level may hold an undeclared key, and widths are
  the resize handle's whole pixels. A file over Athena's limit is refused before it is read. The
  store's lenient `sessionStorage` read is unchanged apart from reading `awaitingRun` fail-closed.
- Trust is judged by the file's BUCKET. A file copied into the user's own folder is fully trusted,
  an accepted residual recorded in analytics.md.
- A held tab's status line says "Not run yet."; **Run** hands focus to the filter expression; the
  drawer's Open buttons use `aria-disabled` while a file opens, so focus stays put.
- Flag registry rows "Open saved view" (`query`) and "Shared spaces in the saved-view drawer"
  (`sharedWorkspaces`). Help's saving guide and callout rewritten.

### Deliberate deviations

- **`like`/`ilike` Colors rules are stripped too**, not only `regex`: both compile an author-typed
  pattern into a backtracking expression that can stall a tab (plan review, measured). A gradient
  rule stays, whatever its operator: it shades by number and never runs the pattern.
- **FR-004's apply criterion is proven with Remove all filters and grouping** rather than the Order
  and filter dialog; both go through the one `apply` door, which is what ends the hold.
- **The line's version is read before its structure**, so a newer line that is shaped differently
  is still named as newer rather than unreadable. The spec's check order was amended to match.

## What changed from earlier specs?

- SPEC-183: a Data Explorer save now writes a view line after the SQL; its "no metadata" Out of
  Scope bullet and Overview carry supersede markers, as do browser.md, analytics.md and ARCS.md.
- `ATHENA_QUERY_STRING_MAX` / `exceedsAthenaQueryLimit` moved to `lib/athenaLimit.ts`, re-exported
  from `renderExplorationSql.ts`.
- `useSaveQuery`'s payload takes an optional `successNote` for the toast.
- `useExploration` takes a third argument; `openTab` takes `seed`, `awaitingRun` and `savedQuery`;
  `useExplorationTabs` gains `releaseHold`.
- The source picker's top row now holds **Open saved view** even with no tab open.

## Verification

Format, lint, typecheck, build, the portal suite and the doc/flag/path validators ran green
locally. Owed after deploy: the §4.7 rows in `docs/testing/e2e.md` (a saved view run in Query
returns the tab's rows; the personal and shared reopen; an edited file refused).
