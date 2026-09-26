# Spec: A Saved Exploration Reopens as an Exploration

**ID:** SPEC-247
**Status:** Draft
**Last Updated:** 2026-09-25
**Depends On:** SPEC-183, SPEC-243

## Overview

A tester asked on 2026-09-15 to save a Data Explorer filter and come back to it later. Today
**Save as query** writes only the SQL the filters produced, so the file reopens in the Query tab
as a statement to edit, and the filters, sort, grouping and column layout are gone. The Data
Explorer can't rebuild them from the SQL without a SQL parser, which is why SPEC-183 left
loading out.

This spec keeps the file a single `.sql` file, but a save from the Data Explorer adds one comment
line at the end. That line records the view itself and a checksum of the SQL above it. A new
**Open saved view** entry in the Data Explorer lists the space's saved queries. Choosing one
whose view line is intact, and whose SQL has not been edited since, opens a tab with every filter,
the sort, the grouping and the column layout back as they were, all still editable. Anything else
is refused with the reason and an offer to open the file in Query. The Data Explorer never reads
filters back out of the SQL.

## Scope

### In Scope

- A Data Explorer save of a **table** exploration appends one view line to the `.sql` file it
  already writes. It is still one file and one write.
- An **Open saved view** entry beside the table picker, listing a space's saved queries.
- Restoring a view: source, column filters, filter expression, sort, grouping, column
  layout and formatting, in a new tab linked to the file.
- Refusing every file that cannot be restored, with the reason and an **Open in Query** action.
- Help and the decision records, which currently promise that a saved exploration reopens only in
  Query.

### Out of Scope

- **Reading SQL back into filters.** SPEC-243's rule stands: a file whose SQL was edited is
  refused, never partly restored.
- **A sidecar or any second object.** storage.md's "do NOT build a sidecar" still holds. The view
  lives inside the `.sql` file, which is the one thing this spec changes from SPEC-183's Out of
  Scope.
- **Views for a `sql`-source tab** (one opened from a Query result). Such a save writes SQL only,
  as today. Restoring one would re-run a statement taken from a file anyone in the space can
  write, as soon as the file was opened.
- **Listing only the files that carry a view.** Telling them apart means reading every body, so
  the list shows every saved query, and a file without a view is refused when it is opened.
- **Opening a view from Query's Saved queries panel or from Files.** The one entry is in the Data
  Explorer.
- **Query hiding or preserving the view line.** Query shows it as the comment it is, and a save
  from Query writes whatever text the editor holds.
- **Restoring history** (back/forward), the scanned-bytes ledger, the value panel's open state or
  the record view's row. A restored tab starts with empty history.
- **Keeping tabs across browser sessions.** Tabs still live in `sessionStorage`.
- **Upgrading files saved before this spec.** They carry no view line and are refused with
  **Open in Query**.

---

## Functional Requirements

### FR-001: A save from the Data Explorer carries the view

#### Description:

**Save as query** on a tab whose source is a table writes the SQL that ran, as today, then a
newline and one view line (Data Model). The view line holds the source's database and table,
the exploration's query, and its presentation minus the value panel's open state and the record
row. It also holds a checksum of the SQL above it. If adding the line would take the file over
Athena's 262,144-byte `QueryString` limit, the file is written without it, and the success toast
says the view was too large to keep.

#### Acceptance Criteria:

- [ ] A save from a table tab issues exactly one write, whose body is the SQL that ran, a
      `\n`, the view line, and a final `\n`.
- [ ] Decoding the view line gives back the tab's database, table, query and presentation
      (without `valuePanelOpen` and `recordRowIndex`), and a checksum equal to `viewChecksum`
      of the SQL that ran.
- [ ] A save from a `sql`-source tab writes the SQL only, byte-identical to today.
- [ ] A save whose file would exceed 262,144 UTF-8 bytes with the view line is written without
      it, and the toast reads `Saved “{name}” to {space}. The view was too large to keep, so it
      opens in Query only.`
- [ ] A save from the Query page is unchanged: no view line is added.
- [ ] Query's statement splitter reads a file carrying a view line as ONE statement, with the
      line kept as its trailing comment, and `isExplorableSql` still accepts it.
- [ ] Live, in `docs/testing/e2e.md`: a saved view opened in Query and run returns the same rows
      as the Data Explorer tab it was saved from.

### FR-002: The Data Explorer lists saved queries to open as a view

#### Description:

Next to the table picker, where a new tab starts, an **Open saved view** control opens a drawer
listing the saved queries in a space. It uses the saved-queries store's own space select and pager
(the list Query's panel shows, one level of `saved_queries/`, in S3's order). The control appears
only when the `query` flag is on, because the store is hidden when it is off.

#### Acceptance Criteria:

- [ ] With `query` on, the picker shows **Open saved view**; with it off, the control is absent.
- [ ] The drawer lists the `.sql` files of the selected space's `saved_queries/` folder, ten per
      page, each with an **Open** action, and remembers the space through the shared saved-query
      space key.
- [ ] An empty folder shows an empty state naming the space; a failed listing shows the
      store's error banner with **Retry**.
- [ ] The drawer closes on Escape and on its close control, and passes axe as driven.

### FR-003: An intact, unedited view reopens whole

#### Description:

Opening a file whose last non-empty line is a view line that decodes, validates and carries a
checksum equal to `viewChecksum` of the text above it opens a **new** tab. The tab has the
recorded source, query and presentation, and is linked to the file, so **Save as query** from it
offers to replace that file. The source's space is resolved from its **database** against the
spaces the table picker offers the opener (`useQuerySpaces`), never from anything else the file
names. The view is validated by the same rules
the tab store applies to `sessionStorage`, so an operator one accepts the other accepts.

#### Acceptance Criteria:

- [ ] Opening a view saved from a tab with two column filters, an expression, a sort, a grouping,
      a hidden column, a pinned column and a Colors rule opens a tab with all seven back, the
      filters shown as chips, and the tab runs its query.
- [ ] The new tab's **Save as query** dialog opens with the file's name and space, and
      saving replaces that file (the existing linked-replace behaviour).
- [ ] The restored tab's history is empty, and the drawer closes.
- [ ] A view saved in a shared space by one member opens for another member of that space.
- [ ] Trailing whitespace added after the SQL does not count as an edit.
- [ ] A restored filter on a column the table no longer has opens the tab and shows the
      tab's existing failure banner, with the filter still listed so it can be removed.

### FR-004: Anything that cannot be restored is refused, with a way to Query

#### Description:

A file that cannot be restored opens no tab. A dialog says why, and offers **Open in Query**, which
hands the file's SQL (without any view line) to a new Query tab through the existing
`buildOpenSqlHandoff`, as the Generated SQL panel's control does. The reasons are closed and
distinct.

#### Acceptance Criteria:

- [ ] A file with no view line: `“{name}” was saved from Query, so it has no Data Explorer view.`
- [ ] A file whose SQL no longer matches the checksum: `“{name}” has been edited since it was
      saved from the Data Explorer, so its view no longer describes it.`
- [ ] A view line that does not decode, fails validation, or names a version other than `1`:
      `“{name}” carries a view this version of Data Quarry can’t read.` No part of it is
      applied.
- [ ] A view whose database is not one of the opener's spaces: `You don’t have access to
      {database}, the database this view explores.`
- [ ] A file that fails to read shows the store's read error and no tab.
- [ ] At the ten-tab cap, the existing limit dialog appears before the file is read.
- [ ] **Open in Query** lands on `/query` with a new tab holding the SQL without the view line,
      and nothing runs.

### FR-005: Help and the records say it

#### Description:

The Data Explorer's saving guide says a saved exploration reopens here through **Open saved
view** and that an edited file reopens only in Query, replacing the callout that says it cannot.
The decision records that say otherwise get supersede markers.

#### Acceptance Criteria:

- [ ] The guide's steps name **Open saved view** and say that editing the SQL in Query means the
      file opens only in Query afterwards; the warning callout at `helpContent.ts` no longer says a
      saved exploration cannot reopen here.
- [ ] `docs/decisions/browser.md` (the "reopens in the Query workspace as SQL" paragraph) and
      SPEC-183's Out of Scope bullet on metadata carry a supersede marker naming this spec, and
      `docs/decisions/analytics.md` gains the entry for the view line.

---

## Data Model

```ts
// features/data-explorer/savedView.ts

/** The one line a Data Explorer save appends. Everything after the second colon is opaque. */
export const VIEW_LINE_PREFIX = '-- dataquarry-view:v1:';
// Line: `${VIEW_LINE_PREFIX}${checksum}:${base64url(JSON.stringify(SavedView))}`
// base64url, so the line holds no quote, semicolon, `*/` or newline for any SQL lexer to trip on.

export type SavedView = {
  version: 1;
  source: {database: string; table: string};
  query: ExplorationQuery;
  presentation: Omit<ExplorationPresentation, 'valuePanelOpen' | 'recordRowIndex'>;
};

/** FNV-1a 32-bit over the UTF-8 bytes of `sql` with trailing whitespace removed, 8 lowercase hex. */
export function viewChecksum(sql: string): string;

export type ParsedSavedFile =
  | {kind: 'view'; sql: string; view: SavedView}
  | {kind: 'refused'; reason: 'no-view' | 'edited' | 'unreadable'; sql: string};
```

The checksum detects an edit made in good faith; it is not a signature. A view line someone
crafts by hand is still validated like any stored document, and it can only describe a table
exploration, whose SQL the renderer builds.

---

## API / Interface Contract

```ts
// features/data-explorer/savedView.ts
export function appendViewLine(sql: string, view: SavedView): string | null; // null when over the limit
export function parseSavedFile(text: string): ParsedSavedFile;

// features/data-explorer/explorationTabs.ts: the validators the tab store already runs, exported
export function readStoredQuery(value: unknown): ExplorationQuery | null;
export function readStoredPresentation(value: unknown): ExplorationPresentation;

// features/data-explorer/useExplorationTabs.ts: openTab gains a whole exploration
openTab(source: ExplorationSource, options?: {label?: string; seed?: Pick<Exploration, 'query' | 'presentation'>}): string | null;
```

---

## File & Folder Structure

```
apps/portal/src/features/data-explorer/
├── savedView.ts                 (new: line format, checksum, parse)
├── savedView.test.ts            (new)
├── OpenSavedViewDrawer.tsx      (new: the list, from saved-queries pieces)
├── SavedViewRefusal.tsx         (new: the FR-004 dialog)
├── openSavedView.test.tsx       (new: the journey)
├── SaveExplorationDialog.tsx    (the body gains the view line)
├── SourcePicker.tsx             (the Open saved view control)
├── explorationTabs.ts           (validators exported)
├── useExplorationTabs.ts        (openTab seed)
└── DataExplorerWorkspace.tsx    (wiring)
```

## Implementation Phases

### Phase 1: The line and the save

- `savedView.ts` with its tests: format, checksum, parse, every refusal reason.
- Export the stored-document validators, and have the tab store call the exported ones.
- The Data Explorer save appends the line for table sources, with the size fallback and toast.

### Phase 2: Opening

- `openTab` seed; the drawer; the refusal dialog; the space resolution by database; the
  hand-off to Query.
- The journey test from save to reopen, and the axe checks.

### Phase 3: Words

- Help steps and callout; supersede markers; the analytics.md entry.
