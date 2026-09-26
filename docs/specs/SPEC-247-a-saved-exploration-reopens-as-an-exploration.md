# Spec: A Saved Exploration Reopens as an Exploration

**ID:** SPEC-247
**Status:** Draft
**Last Updated:** 2026-09-25
**Depends On:** SPEC-183, SPEC-242, SPEC-243

## Overview

A tester asked on 2026-09-15 to save a Data Explorer filter and come back to it later. Today
**Save as query** writes only the SQL the filters produced, so the file reopens in the Query tab
as a statement to edit, and the filters, sort, grouping and column layout are gone. The Data
Explorer cannot rebuild them from the SQL without a SQL parser, which is why SPEC-183 left
loading out.

This spec keeps the file a single `.sql` file, but a save from the Data Explorer adds one comment
line at the end. That line records the view and a checksum of the SQL above it. A new **Open saved
view** entry in the Data Explorer lists a space's saved queries. Choosing one whose view line is
intact, and whose SQL has not been edited since, opens a tab with every filter, the sort, the
grouping and the column layout back, all still editable. Anything else is refused with the reason
and an offer to open the file in Query. The Data Explorer never reads filters back out of SQL.

A file in a shared space can be written by any member, and a view's filter expression is raw SQL.
So a view opened from a **shared** space does not run until the opener chooses **Run**, and it
comes back without the two presentation features that act on what a view's author typed: URL-link
transformers and pattern Colors rules. A view from the opener's personal space, which only they
can write, restores whole and runs.

## Scope

### In Scope

- A Data Explorer save of a **table** exploration appends one view line to the `.sql` file it
  already writes. It is still one file and one write.
- The line format, in `lib/` so both features' tests can reach it.
- An **Open saved view** entry beside the table picker, listing a space's saved queries.
- Restoring a view, strictly validated and rendered before any tab opens.
- The shared-space guard: the tab opens paused, without URL-link transformers or pattern rules.
- Refusing every file that cannot be restored, with the reason and **Open in Query**.
- Help, the flag registry and the decision records that currently promise the opposite.

### Out of Scope

- **Reading SQL back into filters.** SPEC-243's rule stands: a file whose SQL was edited is
  refused, never partly restored.
- **A sidecar or any second object.** storage.md's "do NOT build a sidecar" still holds; the view
  lives inside the `.sql` file.
- **Views for a `sql`-source tab** (one opened from a Query result). Such a save writes SQL only,
  as today.
- **Listing only files that carry a view.** Telling them apart means reading every body, so the
  list shows every saved query, and a file without a view is refused when opened.
- **Opening a view from Query's Saved queries panel or from Files.**
- **Moving Query's Saved queries panel into the store.** The drawer is built from the store's
  exported pieces; Query's panel is untouched.
- **Query hiding or preserving the view line.** Query shows it as the comment it is, and a save
  from Query writes whatever the editor holds.
- **Restoring history**, the scanned-bytes ledger, the value panel's open state or the record
  view's row. A restored tab starts with empty history.
- **Keeping tabs across browser sessions.** Tabs still live in `sessionStorage`.
- **Upgrading files saved before this spec.** They carry no view line and are refused.
- **Guarding the personal space.** Only its owner can write its `saved_queries/`; file sends
  land in a separate inbox folder.

---

## Functional Requirements

### FR-001: A save from the Data Explorer carries the view

#### Description:

**Save as query** on a tab whose source is a table writes the SQL that ran, then `\n`, one view
line, then `\n`. The line (Data Model) holds a checksum of that SQL and the view: the source's
database and table, the exploration's query, and its presentation without `valuePanelOpen` and
`recordRowIndex`. If adding the line would take the file over Athena's 262,144-byte
`QueryString` limit, the file is written without it, and the toast says so. A successful save
refreshes that space's saved-query listing, so the drawer shows the file at once.

#### Acceptance Criteria:

- [ ] A save from a table tab issues exactly one write, whose body is `{sql}\n{line}\n`.
- [ ] `parseViewLine` of that body returns the SQL, version 1, and a payload equal to the tab's
      database, table, query and presentation minus the two excluded fields.
- [ ] A save from a `sql`-source tab writes the SQL only, byte-identical to today.
- [ ] A save that would exceed 262,144 UTF-8 bytes with the line is written without it, and the
      toast reads `Saved “{name}” to {space}. The view was too large to keep, so it opens in
      Query only.`
- [ ] A save from the Query page adds no line.
- [ ] After a Data Explorer save, the drawer's listing for that space includes the file without
      waiting for the listing's stale time.
- [ ] Query's `splitSqlStatements` reads a body carrying a view line as ONE statement ending in
      that comment, and `isExplorableSql` accepts it (tested in `features/query`, with the body
      built by `lib/savedViewLine.appendViewLine`).
- [ ] Live, in `docs/testing/e2e.md`: a saved view opened in Query and run returns the same rows
      as the tab it was saved from.

### FR-002: The Data Explorer lists saved queries to open as a view

#### Description:

Next to the table picker, where a new tab starts, **Open saved view** opens a drawer listing the
`.sql` files of a space's `saved_queries/` folder, from the store's `useSavedQueriesPager` and
`SavedQuerySpaceSelect`. The spaces offered are the ones the table picker offers, so a shared
space appears only with `sharedWorkspaces` on. The control exists only with `query` on.

#### Acceptance Criteria:

- [ ] With `query` on, the picker shows **Open saved view**; with it off, the control is absent,
      and the flag registry carries a `query` row for it on `/explore`.
- [ ] The drawer lists the space's files ten per page, each with **Open**, and remembers the
      space through the shared saved-query space key.
- [ ] With `sharedWorkspaces` off, the space select offers no shared space, and the registry
      carries a `sharedWorkspaces` row for shared spaces in the drawer.
- [ ] An empty folder shows `No saved queries in {space} yet.`; a failed listing shows a danger
      `Banner` with **Try again**, which refetches.
- [ ] The drawer closes on Escape and on its close control, and has no axe violations as driven.

### FR-003: An intact, unedited view reopens whole

#### Description:

Opening a file whose view line parses, whose checksum matches the SQL above it, whose payload
passes the tab store's validators **strictly**, and whose SQL renders, opens a **new** tab
labelled with the table name. The tab holds the recorded query and presentation and is linked
to the file, so **Save as query** from it offers to replace that file. The source's space is found
by **database** among the spaces the picker offers; when a shared space and the personal space
share the name, the personal space wins, as it does in the picker. Strict means the payload
must round-trip through the store's normalisers unchanged: a presentation the normaliser would
default or drop is refused, not quietly repaired.

#### Acceptance Criteria:

- [ ] From the personal space, a view saved with two column filters, an expression, a sort, a
      grouping, a hidden column, a pinned column and a Colors rule opens with all seven back, the
      filters shown as chips, and the tab runs its query.
- [ ] The new tab's **Save as query** dialog opens with the file's name and space, and saving
      replaces that file.
- [ ] The restored tab's history is empty, and the drawer closes.
- [ ] A view whose database is a shared space's opens for another member of that space.
- [ ] CRLF line endings, a byte-order mark, and trailing whitespace after the SQL or on the view
      line do not count as edits.
- [ ] A view whose presentation holds a Colors rule with an operator this build does not know is
      refused under FR-005's unreadable reason, with no tab.

### FR-004: A view from a shared space opens paused and without two features

#### Description:

A view opened from a **shared** space opens as FR-003 describes, with three differences. It does
not run: the results area says `This view was saved in {space}, where any member can change it.
Check its Generated SQL, then run it.` with a **Run** button. It holds no URL-link transformers
and no pattern (regex) Colors rules; a note under that text lists how many of each were left
out. The paused state is stored on the tab, so a reload does not run it either. **Run**, or any
change to the filters, expression, sort or grouping, ends the pause.

#### Acceptance Criteria:

- [ ] Opening a view from a shared space starts no query execution; the Generated SQL panel shows
      the statement; **Run** starts exactly one.
- [ ] A shared-space view saved with one URL-link transformer and one pattern Colors rule opens
      without either, and the note reads `Left out: 1 link column, 1 pattern color rule.`
- [ ] Reloading the page on a paused tab starts no execution and still shows **Run**.
- [ ] Adding a filter to a paused tab runs the new statement and removes the pause.
- [ ] The same view opened from the personal space runs at once and keeps both features.

### FR-005: Anything that cannot be restored is refused, with a way to Query

#### Description:

A file that cannot be restored opens no tab. A dialog says why and offers **Open in Query**, which
hands the file's SQL, without any view line, to a new Query tab through `buildOpenSqlHandoff`.
A line is recognised by its marker whatever its version, so one from a newer build is both named
as newer and stripped.

#### Acceptance Criteria:

- [ ] No view line: `“{name}” has no Data Explorer view saved in it.`
- [ ] Checksum mismatch: `“{name}” has been edited since it was saved from the Data Explorer, so
      its view no longer describes it.`
- [ ] A version above 1: `“{name}” was saved by a newer version of Data Quarry.`
- [ ] A line that does not decode, fails strict validation, or whose SQL does not render:
      `“{name}” carries a view that can’t be read.` No part of it is applied.
- [ ] A database that is not among the picker's spaces: `You don’t have access to {database},
      the database this view explores.`
- [ ] A read failure shows the store's read error and opens no tab.
- [ ] **Open in Query** lands on `/query` with a new tab holding the SQL without the view line, and
      nothing runs.

### FR-006: Help and the records say it

#### Description:

The Data Explorer's saving guide says a saved exploration reopens through **Open saved view**,
that a shared-space view opens paused, and that an edited file opens only in Query. The decision
records that say otherwise are marked superseded, and a new analytics.md entry records the line
format, the shared-space guard, and that `ExplorationQuery` and `ExplorationPresentation` are now
a file format: a change to either type needs a reader for the old shape or a new line version.

#### Acceptance Criteria:

- [ ] The guide's steps name **Open saved view** and the paused shared-space view; the warning
      callout no longer says a saved exploration cannot reopen here.
- [ ] Supersede markers naming this spec sit at: browser.md's "reopens in the Query workspace as
      SQL" paragraph, analytics.md's "SPEC-183's loaded file is a **source**, not a view state",
      analytics.md's "the *user's own SQL* and passes through verbatim", ARCS.md's "a saved
      exploration reloads as a query", and SPEC-183's Overview and its Out of Scope bullet on
      metadata.
- [ ] analytics.md carries the new entry, and its Fences gain one clause: a view read from a
      shared space never runs or renders author-typed links or patterns unasked.

---

## Data Model

```ts
// lib/savedViewLine.ts — the format, knowing nothing of either feature's types

export const VIEW_LINE_MARKER = '-- dataquarry-view:';
export const VIEW_LINE_VERSION = 1;
// `${VIEW_LINE_MARKER}v${version}:${checksum}:${base64url(utf8(JSON.stringify(payload)))}`
// base64url, so the line holds no quote, semicolon, `*/` or newline for any lexer to trip on.

/** FNV-1a 32-bit, 8 lowercase hex, over the UTF-8 bytes of `sql` after dropping a leading BOM,
 *  turning CRLF into LF, and trimming trailing whitespace. Detects an edit; it is not a signature. */
export function viewChecksum(sql: string): string;

export type ParsedViewLine =
  | {kind: 'none'; sql: string}
  | {kind: 'newer'; sql: string; version: number}
  | {kind: 'damaged'; sql: string}
  | {kind: 'edited'; sql: string}
  | {kind: 'ok'; sql: string; payload: unknown};
```

```ts
// features/data-explorer/savedView.ts — what the payload means here

export type SavedView = {
  source: {database: string; table: string};
  query: ExplorationQuery;
  presentation: Omit<ExplorationPresentation, 'valuePanelOpen' | 'recordRowIndex'>;
};

// dataExplorer.types.ts — ExplorationTab gains
/** Set on a tab restored from a shared space until the user runs it or changes its query. */
awaitingRun?: {space: string; leftOut: {links: number; patterns: number}};
```

---

## API / Interface Contract

```ts
// lib/savedViewLine.ts
export function appendViewLine(sql: string, payload: unknown): string | null; // null over the limit
export function parseViewLine(text: string): ParsedViewLine;

// features/data-explorer/explorationTabs.ts — the store's own validators, exported and reused
export function readStoredQuery(value: unknown): ExplorationQuery | null;
export function readStoredPresentation(value: unknown): ExplorationPresentation | null; // strict: null when normalising would change it

// features/data-explorer/useExplorationTabs.ts — openTab gains a seed
openTab(
  source: ExplorationSource,
  options?: {label?: string; seed?: Pick<Exploration, 'query' | 'presentation'>; awaitingRun?: ExplorationTab['awaitingRun']}
): string | null;
```

`readStoredPresentation`'s strictness applies to the saved-view path only; the tab store keeps
its lenient read of `sessionStorage`, so this spec changes nothing about restoring a session.

---

## File & Folder Structure

```
apps/portal/src/
├── lib/
│   ├── savedViewLine.ts            (new)
│   └── savedViewLine.test.ts       (new)
├── features/data-explorer/
│   ├── savedView.ts                (new: build, validate, render-check, shared-space strip)
│   ├── savedView.test.ts           (new)
│   ├── OpenSavedViewDrawer.tsx     (new)
│   ├── SavedViewRefusal.tsx        (new)
│   ├── openSavedView.test.tsx      (new: the journeys)
│   ├── SaveExplorationDialog.tsx   (the line, the toast)
│   ├── SourcePicker.tsx            (the control)
│   ├── ExplorationResultsRegion.tsx (the paused body)
│   ├── explorationTabs.ts          (validators exported; awaitingRun persisted)
│   ├── useExplorationTabs.ts       (seed)
│   └── DataExplorerWorkspace.tsx   (wiring; a paused tab runs nothing)
├── features/saved-queries/useSaveQuery.ts   (success text and listing refresh)
├── features/query/queryPure.test.ts          (the splitter criterion)
└── features/feature-flags/gatedSurfaces.ts (+ test)
```

## Implementation Phases

Phases 1 and 2 land together: the format must not ship before a reader exists.

### Phase 1: The line and the save

- `lib/savedViewLine.ts` and its tests, including every `ParsedViewLine` kind.
- Export the store's validators; add the strict presentation read.
- The Data Explorer save appends the line for table sources, with the size fallback, the toast
  and the listing refresh; the splitter test in Query.

### Phase 2: Opening

- `openTab` seed and `awaitingRun`; the drawer; the refusal dialog; space resolution; the
  shared-space strip and pause; the hand-off to Query; the registry rows.
- The journeys from save to reopen, personal and shared, and the axe checks.

### Phase 3: Words

- Help; supersede markers; the analytics.md entry and Fences clause; the live check in e2e.md.
