# Spec: A Saved Exploration Reopens as an Exploration

**ID:** SPEC-247
**Status:** Completed
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

Any member of a shared space can write the files in its `saved_queries/` folder, and a view's filter
expression is raw SQL. So a view whose **file** was listed from a shared space's folder does not
run until the opener chooses **Run**, comes back without the two presentation features that act
on what its author typed (URL-link transformers and pattern Colors rules), and is not linked to
its file, so saving it never silently overwrites the author's version. A view from the opener's
personal folder, which only they can write, restores whole, runs, and stays linked.

## Scope

### In Scope

- A Data Explorer save of a **table** exploration appends one view line to the `.sql` file it
  already writes. It is still one file and one write.
- The line format, in `lib/` so both features' tests can reach it.
- An **Open saved view** entry beside the table picker, listing a space's saved queries.
- Restoring a view, strictly validated and rendered before any tab opens.
- The shared-folder guard: the tab opens held, unlinked, and without URL-link transformers or
  pattern rules.
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
- **Guarding the personal folder.** Only its owner can write its `saved_queries/`; file sends
  land in a separate inbox folder.
- **Signing the payload.** The checksum covers the SQL and detects an edit made in good faith. A
  hand-crafted payload that validates opens; in a shared folder the hold shows what it will run.

---

## Functional Requirements

### FR-001: A save from the Data Explorer carries the view

#### Description:

**Save as query** on a tab whose source is a table writes the SQL that ran, then `\n`, one view
line, then `\n`. The line (Data Model) holds a checksum of that SQL and the view: the source's
database and table, the exploration's query, and its presentation without `valuePanelOpen` and
`recordRowIndex`. If adding the line would take the file over Athena's 262,144-byte
`QueryString` limit, the file is written without it, and the toast says so. A successful save
invalidates that space's saved-query listing (`savedQueryKeys.list(spaceId)`), so the drawer
shows the file at once.

#### Acceptance Criteria:

- [ ] A save from a table tab calls `writeSavedQuery` once, with the body `{sql}\n{line}\n`.
- [ ] `parseViewLine` of that body returns kind `ok`, version 1, the SQL, and a payload equal to
      the tab's database, table, query and presentation minus the two excluded fields.
- [ ] A save from a `sql`-source tab writes the SQL only, byte-identical to today.
- [ ] A save that would exceed 262,144 UTF-8 bytes with the line is written without it, and the
      toast reads `Saved “{name}” to {space}. The view was too large to keep, so it opens in
      Query only.` (`appendViewLine` is unit-tested at 262,144 and 262,145 bytes.)
- [ ] A save from the Query page adds no line.
- [ ] With a query client whose stale time is the app's and whose `gcTime` is unbounded: list the
      drawer once, close it, save from the Data Explorer, reopen it, and the listing is fetched
      again and shows the new file. Deleting the invalidation turns this test red.
- [ ] Query's `splitSqlStatements` reads a body carrying a view line as ONE statement ending in
      that comment, and `isExplorableSql` accepts it (in `features/query/queryPure.test.ts`, with
      the body built by `lib/savedViewLine.appendViewLine`).
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
      carries a `sharedWorkspaces` row, "Shared spaces in the saved-view drawer".
- [ ] An empty folder shows `No saved queries in {space} yet.`; a failed listing shows a danger
      `Banner` with **Try again**, which fetches the listing again.
- [ ] The drawer closes on Escape and on its close control, and has no axe violations as driven.

### FR-003: An intact, unedited view reopens whole

#### Description:

Opening a file whose view line parses as `ok`, whose payload passes the **strict** reads, and
whose SQL renders within Athena's limit, opens a **new** tab labelled with the table name, holding
the recorded query and presentation, with empty history. A file listed from the opener's
**personal** folder opens linked to that file, so **Save as query** from it offers to replace it.

The source's space is found by **database** among the spaces the picker offers, once the
connections read has settled (the rule `useSpaceLinkPending` applies to a deep link); when a
shared space and the personal space share a name, the personal space wins, as in the picker.

**Strict** means the payload must equal, by order-insensitive deep equality, what the tab store's
own normalisers make of it, with `valuePanelOpen` and `recordRowIndex` left out of the comparison.
`readStrictQuery` and `readStrictPresentation` are new functions built on the store's validators;
the store's lenient read of `sessionStorage` is unchanged.

#### Acceptance Criteria:

- [ ] A view saved by this build, with two column filters, an expression, a sort, a grouping, a
      hidden column, a pinned column, a column width, a `regex` Colors rule, a URL-link
      transformer and a non-grid presentation, reopens from the personal folder with all of them; the new tab's stored exploration
      equals the saved one, the filters show as chips, and the tab runs its query once.
- [ ] That tab's **Save as query** dialog opens with the file's name and space, and saving
      replaces the file with no confirm.
- [ ] The restored tab's **Back** is disabled, and the drawer closes.
- [ ] A view from a shared space's folder over that space's database opens for another member.
- [ ] CRLF line endings, a byte-order mark, and trailing whitespace after the SQL or on the view
      line do not count as edits.
- [ ] A presentation holding a Colors rule with an operator this build does not know is refused
      under FR-005's unreadable reason, with no tab.
- [ ] Opened while the connections read is still pending, a view over a shared database waits
      for it and then opens, rather than being refused.

### FR-004: A view from a shared space's folder opens held, unlinked, and without two features

#### Description:

A file listed from a **shared** space's folder, whatever database its view names, opens as FR-003
describes with four differences.

- **Held.** `useExploration` gains a hold: the SQL renders, and the Generated SQL panel, **Save as
  query**, **Create view…** and **Open in Query** all work from it, but no execution starts, cached
  results for that statement are not shown, and the status line does not say it is running. The
  results area says `This view was saved in {space}, where any member can change it. Check its
  Generated SQL, then run it.` with a **Run** button.
- **Stripped.** It holds no URL-link transformers and no Colors rules whose operator is `regex`,
  `like` or `ilike`: all three compile an author-typed pattern into a backtracking expression
  that a crafted one can make freeze the tab. Under the held text, a note names what was left out, pluralised, omitting a zero part:
  `Left out: 1 link column, 2 pattern color rules.` No note when nothing was.
- **Unlinked.** The tab has no saved-query link, so **Save as query** asks for a name, and a
  same-name save meets the existing replace confirm.
- **Remembered.** The hold is stored on the tab as `awaitingRun`. **Run** clears it with a tab
  update; an `apply` that changes the query clears it in the same update; a no-op apply does not.
  The stored-document read treats a present but malformed `awaitingRun` as held with no note,
  never as absent.

#### Acceptance Criteria:

- [ ] Opening a shared-folder view starts no execution, the Generated SQL panel shows the rendered
      statement, the status line is not "Running", and **Run** starts one execution against a
      cold cache.
- [ ] A shared-folder file whose view names the **opener's personal** database is held too.
- [ ] A shared-folder view saved with one URL-link transformer, one `regex` and one `like` Colors
      rule opens without them, and the note reads `Left out: 1 link column, 2 pattern color rules.`
- [ ] Its **Save as query** dialog opens with an empty name.
- [ ] Reloading on a held tab starts no execution and still shows **Run**; a stored
      `awaitingRun` of `"garbage"` reads back as held.
- [ ] Changing a held tab's query (for example **Remove all filters and grouping**) runs the new
      statement once and ends the hold.
- [ ] The same file listed from the personal folder runs at once, keeps both features, and is
      linked.

### FR-005: Anything that cannot be restored is refused, with a way to Query

#### Description:

A file that cannot be restored opens no tab. A dialog says why and offers **Open in Query**, which
hands the file's SQL, without its view line, to a new Query tab through `buildOpenSqlHandoff`.

Only the **last non-blank line** is read as the view line. The checks run in this order and the
first that fails decides: the last line carries the marker (else, if an earlier line starts with
the marker, **edited**, since text was added after it; otherwise **none**); the line carries a
version (else **unreadable**), which is 1 (else **newer**, whatever else the line holds); it splits
into a checksum and a payload (else **unreadable**); its checksum matches (else **edited**); the payload decodes, reads strictly and
renders within Athena's limit (else **unreadable**); its database is among the picker's spaces
once they have settled (else **no access**).

#### Acceptance Criteria:

- [ ] None: `“{name}” has no Data Explorer view saved in it.`
- [ ] Edited, including SQL added after the line: `“{name}” has been edited since it was saved
      from the Data Explorer, so its view no longer describes it.`
- [ ] Newer: `“{name}” was saved by a newer version of Data Quarry.`
- [ ] Unreadable: `“{name}” carries a view that can’t be read.` No part of it is applied.
- [ ] No access: `You don’t have access to {database}, the database this view explores.`
- [ ] A marker-shaped line INSIDE the SQL (a multi-line literal) above a valid view line does not
      disturb the parse.
- [ ] A read failure shows a danger toast with the store's read error, leaves the drawer open,
      and offers no **Open in Query**.
- [ ] **Open in Query** lands on `/query` with a new tab holding the SQL without the view line,
      and nothing runs.

### FR-006: Help and the records say it

#### Description:

The Data Explorer's saving guide says a saved exploration reopens through **Open saved view**,
that a shared-space view opens held and unlinked, and that an edited file opens only in Query. The
records that say otherwise are marked superseded, and a new analytics.md entry records the line
format, the shared-folder guard, and that `ExplorationQuery` and `ExplorationPresentation` are now
a file format: a change to either type needs a reader for the old shape or a new line version.

#### Acceptance Criteria:

- [ ] The guide's steps name **Open saved view** and the held shared-space view; the warning
      callout no longer says a saved exploration cannot reopen here.
- [ ] Supersede markers naming this spec sit at: browser.md's "reopens in the Query workspace as
      SQL" paragraph, analytics.md's "SPEC-183's loaded file is a **source**, not a view state",
      analytics.md's "the *user's own SQL* and passes through verbatim" (it wraps a line),
      ARCS.md's "a saved exploration reloads as a query", and SPEC-183's Overview and its Out of
      Scope bullet on metadata.
- [ ] analytics.md carries the new entry, and its Fences gain one clause: a view read from a
      shared folder never runs, links or matches author-typed patterns unasked.

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
  | {kind: 'edited'; sql: string}
  | {kind: 'damaged'; sql: string} // the marker line does not split into version, checksum, payload
  | {kind: 'ok'; sql: string; version: 1; payload: unknown};
// A payload that will not decode is `ok` here with `payload: undefined`; meaning is the feature's.
```

```ts
// features/data-explorer/savedView.ts — what the payload means here

export type SavedView = {
  source: {database: string; table: string};
  query: ExplorationQuery;
  presentation: Omit<ExplorationPresentation, 'valuePanelOpen' | 'recordRowIndex'>;
};

// dataExplorer.types.ts — ExplorationTab gains
/** Set on a tab restored from a shared folder until the user runs it or changes its query. */
awaitingRun?: {space: string; leftOut: {links: number; patterns: number}};
```

---

## API / Interface Contract

```ts
// lib/savedViewLine.ts
export function appendViewLine(sql: string, payload: unknown): string | null; // null over the limit
export function parseViewLine(text: string): ParsedViewLine;

// features/data-explorer/explorationTabs.ts — strict reads on the store's own validators
export function readStrictQuery(value: unknown): ExplorationQuery | null;
export function readStrictPresentation(value: unknown): SavedView['presentation'] | null;

// features/data-explorer/useExplorationTabs.ts — openTab gains a seed
openTab(
  source: ExplorationSource,
  options?: {
    label?: string;
    seed?: Pick<Exploration, 'query' | 'presentation'>;
    awaitingRun?: ExplorationTab['awaitingRun'];
    savedQuery?: SavedQueryLink;
  }
): string | null;

// features/data-explorer/useExploration.ts — renders the SQL, starts nothing, shows no cached rows
useExploration(exploration: Exploration | null, tabId?: string, options?: {hold?: boolean});

// lib/athenaLimit.ts — moved from renderExplorationSql.ts so the line format can measure against it
export const ATHENA_QUERY_STRING_MAX = 262_144;
export function exceedsAthenaQueryLimit(sql: string): boolean;
```

---

## File & Folder Structure

```
apps/portal/src/
├── lib/
│   ├── athenaLimit.ts               (moved here from renderExplorationSql.ts; one home for 262,144)
│   ├── savedViewLine.ts             (new)
│   └── savedViewLine.test.ts        (new)
├── features/data-explorer/
│   ├── savedView.ts                 (new: build, strict read, render check, shared-folder strip)
│   ├── savedView.test.ts            (new)
│   ├── OpenSavedViewDrawer.tsx      (new)
│   ├── OpenSavedViewDrawer.test.tsx (new: FR-002)
│   ├── SavedViewRefusal.tsx         (new)
│   ├── useOpenSavedView.ts          (new: read, parse, resolve, open or refuse)
│   ├── openSavedView.test.tsx       (new: save-to-reopen journeys, personal and shared)
│   ├── savedViewRefusal.test.tsx    (new: FR-005, one table over the reasons, and the hand-off)
│   ├── heldTab.test.tsx             (new: FR-004's hold lifecycle)
│   ├── SaveExplorationDialog.tsx    (the line, the toast, the invalidation)
│   ├── SourcePicker.tsx             (the control)
│   ├── useExploration.ts            (the hold)
│   ├── ExplorationResultsRegion.tsx (the held body, the note, the status line)
│   ├── dataExplorer.types.ts        (awaitingRun)
│   ├── explorationTabs.ts           (strict reads; awaitingRun normalised fail-closed)
│   ├── useExplorationTabs.ts        (seed)
│   ├── useExplorationQuery.ts       (apply clears the hold)
│   └── DataExplorerWorkspace.tsx    (wiring)
├── features/saved-queries/useSaveQuery.ts   (success text)
├── features/query/queryPure.test.ts         (the splitter criterion)
└── features/feature-flags/gatedSurfaces.ts  (+ test)
```

## Implementation Phases

Phases 1 and 2 land together: the format must not ship before a reader exists.

### Phase 1: The line and the save

- `lib/savedViewLine.ts` and its tests, including every `ParsedViewLine` kind and the check order.
- The strict reads; the Data Explorer save appends the line for table sources, with the size
  fallback, the toast and the invalidation; the splitter test in Query.

### Phase 2: Opening

- `openTab` seed and `awaitingRun`; the hold in `useExploration`; the drawer; the refusal dialog;
  space resolution after the connections read settles; the shared-folder strip, hold and unlink;
  the hand-off to Query; the registry rows.
- The journeys from save to reopen, personal and shared, and the axe checks.

### Phase 3: Words

- Help; supersede markers; the analytics.md entry and Fences clause; the live check in e2e.md.
