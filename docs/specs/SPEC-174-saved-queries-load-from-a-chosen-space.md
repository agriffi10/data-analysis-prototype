# Spec: Saved Queries — Loading from a Chosen Space

**ID:** SPEC-174
**Status:** Draft
**Last Updated:** 2026-08-11
**Depends On:** SPEC-173 (the store and the folder), SPEC-163 (the gated-surface registry), SPEC-042 (the drawer pager pattern), SPEC-100 (the mobile query surface)

## Overview

SPEC-173 made a saved query a `.sql` file in a space's `saved_queries/` folder, but the query editor still only ever looks in one place: the user's own space. This spec makes loading a saved query start with a question — *which space?* — and then show every saved query in that space, a page at a time. A user who belongs to three shared spaces can open a colleague's saved query from any of them without leaving the editor, and a space with two hundred saved queries pages rather than dumping a wall of rows.

## Scope

### In Scope

- A space selector on the saved-queries surface: the user's own space plus every shared space they are an active member of.
- A paginated list of every `.sql` file at the top level of the chosen space's `saved_queries/` folder — Prev/Next over accumulated `ListObjectsV2` pages. Only `.sql` files are offered; everything else in the folder belongs to the file browser.
- Remembering the last space chosen, per user, for the session.
- Opening a saved query from any space into a linked tab.
- Deleting a saved query from any space, with confirm, from the same list.
- Empty, loading, error and unreachable-space states for a chosen space.
- The same space selector and pager on the mobile Saved surface.
- The Help guide for loading a saved query.

### Out of Scope

- **Choosing a space on save.** Saving still writes to the user's own space; SPEC-175 completes the loop. A shared space will therefore be empty until 175 lands — see the note in `ARCS.md` on why this ordering is deliberate.
- Search, filter or sort controls over the list. The order is S3's own — FR-003.
- A preview of a query's SQL in the list. SPEC-173 removed it deliberately; showing it here would mean one `GetObject` per row.
- Renaming or duplicating a saved query from the list.
- Opening anything that is not a top-level `.sql` file. `saved_queries/` is an ordinary folder (SPEC-173 FR-002) and may hold a CSV, a subfolder or an extensionless file; the load list ignores all of it. Those are files in the file browser, and that is the only place they appear.
- **Writing to a query file.** Opening one and editing it changes a buffer, never the object — SPEC-173 FR-010, restated here as FR-010 because this is the surface that opens them.
- Any change to `saved_queries/`'s protections, the store, or the marker — all SPEC-173, all unchanged.
- Loading a query from a space the user is not an active member of. Only spaces `useQuerySpaces` returns are offered.

---

## Functional Requirements

### FR-001: The space selector

#### Description:

The saved-queries drawer opens on a space selector listing `useQuerySpaces()` — the user's own space first (labelled *My files*), then each active shared space by name. Choosing one loads that space's saved queries. The chosen space is the drawer's state, not the workspace's: it does not change which database a query runs against, and it does not affect the schema rail.

The last space chosen is remembered per user in `sessionStorage`, on the same degrade-safe pattern as `useResultsPageSize` and `useEditorLayout` — a read that throws or returns junk falls back to the personal space rather than breaking the drawer. A remembered space the user no longer belongs to also falls back to personal.

#### Acceptance Criteria:

- [ ] The drawer renders a labelled space control listing exactly the spaces `useQuerySpaces()` returns, personal first.
- [ ] Choosing a space loads that space's `saved_queries/` listing and shows its rows; the previously shown rows do not persist into the new space's list.
- [ ] With no shared spaces the control still renders, showing *My files* alone (never a hidden or zero-option control).
- [ ] The chosen space is written to `sessionStorage` under a per-user key and restored the next time the drawer opens in that session.
- [ ] A stored value that is absent, unparseable, or names a space not in the current list resolves to the personal space, and the drawer renders normally.
- [ ] A `sessionStorage` read or write that throws is swallowed; the drawer renders with the personal space.
- [ ] Changing the space resets the list to page 1.

### FR-002: The paginated list

#### Description:

The list pages over what has been loaded, and loads more when the user runs off the end. `useSavedQueries` accumulates `ListObjectsV2` pages of `LISTING_PAGE_SIZE` (25); the drawer shows `SAVED_QUERIES_PAGE_SIZE` (10) at a time through the shared `Pager`, exactly as `QueryHistoryPanel` does with history.

S3 does not report a total, so the range label must not pretend to know one. It reads `X–Y of Z` when everything has been loaded and `X–Y of Z+` while more pages remain — the `+` is the honest part, and it is the difference between "there are 24" and "there are at least 24".

Pressing Next on the last loaded page while more pages remain fetches the next `ListObjectsV2` page; Next is disabled and reads busy while that request is in flight.

**A listing page and a display page are different things, and the filter is why.** SPEC-173 FR-004 returns only `.sql` files, and SPEC-173 FR-002 makes this an ordinary folder — so an S3 page of 25 keys can yield 25 rows, or 3, or **zero** while more pages remain. A folder holding two hundred CSVs and one saved query must not render as empty with a Load-more the user has to guess at. The hook therefore keeps fetching while `isTruncated` is true and it has fewer than one display page of rows, and only then resolves.

#### Acceptance Criteria:

- [ ] With 24 saved queries in one S3 page, the drawer shows 10 rows and the label `1–10 of 24`.
- [ ] Next advances to `11–20 of 24`, then `21–24 of 24`; Next is disabled on the last page and Prev is disabled on the first.
- [ ] With more S3 pages remaining, the label carries a trailing `+` (`1–10 of 25+`), and it loses the `+` once the final page has been loaded.
- [ ] Next on the last loaded page with `hasMore` true issues one further `ListObjectsV2` with the continuation token and then advances.
- [ ] While that fetch is in flight Next is disabled and shows the `Pager`'s busy state; on failure the list stays on its current page and shows the mapped error without losing the loaded rows.
- [ ] Opening the drawer resets to page 1.
- [ ] A first S3 page whose 25 keys contain no `.sql` file, with `isTruncated` true, does **not** render the empty state: the hook fetches on until it has a display page of rows or the listing is exhausted.
- [ ] A folder with 200 non-`.sql` files and one `.sql` file renders one row and the empty state never appears.
- [ ] A folder with 200 non-`.sql` files and no `.sql` file renders the empty state — after the listing is exhausted, not before.
- [ ] That continuation is bounded: a test asserts it stops at the end of the listing rather than looping, and that each fetch threads the previous continuation token.
- [ ] Each row shows the query's name **without its `.sql` extension**, a relative last-modified time with an absolute `title`, and its size.
- [ ] A folder holding `a.sql`, `notes.csv`, `README`, a `charts/` subfolder and the marker shows exactly one row. The page-count arithmetic is over the filtered rows, so a folder of 30 files of which 8 are `.sql` reads `1–8 of 8`, not `1–10 of 30`.
- [ ] The pager region announces page changes (`aria-live="polite"` — the shared `Pager` already provides this).

### FR-003: The order is S3's own

#### Description:

The list is ordered lexicographically by key — which is to say, it is not ordered at all, it is simply shown in the order S3 returns it. That is deliberate. Sorting by last-modified across a paginated listing would be a lie of the same kind SPEC-123 records about the data-quality runs index: S3 pages lexicographically, so the *newest* query may sit on page nine, and a client-side re-sort of the loaded pages makes rows the user has already seen jump between pages as later pages arrive.

#### Acceptance Criteria:

- [ ] Given keys returned as `alpha.sql, beta.sql, gamma.sql`, the drawer renders them in that order.
- [ ] Loading a further page appends its rows; no row already displayed changes position.
- [ ] A test asserts the drawer applies no sort of its own — feeding it rows whose `updatedAt` order contradicts their key order renders them in **key** order.
- [ ] The drawer's empty state and its copy make no claim about recency (no "most recent first").

### FR-004: Opening a saved query from any space

#### Description:

Opening a row fetches that object's body and opens a new tab whose SQL is the body, whose label is **the file's name with its `.sql` extension removed**, and which is linked to `{spaceId, bucket, key, name}`. A tab opened from a shared space is linked to that space, so SPEC-175's save defaults back to where the query came from rather than to the user's own space.

The label comes from `savedQueryName(key)` — the store's own function, not a second `replace` at the call site — so the tab and the row can never show different names for one file.

Opening is the only operation in this spec that reads an object body, and it reads exactly one.

#### Acceptance Criteria:

- [ ] Opening a row issues exactly one `GetObject`, on that row's `bucket`/`key`.
- [ ] A tab is opened with the object body as its SQL, `savedQueryName(key)` as its label, and `savedQuery` set to the row's link, including the shared `spaceId` and `bucket` for a shared-space query.
- [ ] `Q1 revenue.sql` opens a tab labelled `Q1 revenue`; `REPORT.SQL` opens one labelled `REPORT`. No tab label anywhere in the workspace shows a `.sql` extension.
- [ ] The label is produced by `savedQueryName`; a test asserts the extension-stripping is not duplicated at the call site.
- [ ] The drawer closes on a successful open.
- [ ] At `QUERY_TABS_MAX` the existing tab-limit dialog appears, no tab is opened, and **no** `GetObject` is issued — the limit is checked before the fetch.
- [ ] A failed fetch opens no tab, leaves the drawer open on its current page, and renders the mapped message (`toUserMessage`; never raw AWS text).
- [ ] Opening the same query twice opens two tabs, each linked; nothing de-duplicates.

### FR-005: Deleting a saved query from the list

#### Description:

Each row offers Delete behind the existing warn-and-confirm. Deleting works in any space the user can reach — a shared space's saved queries belong to the space, so any active member may remove one, which is the same posture the file browser already takes toward every other file in a shared space.

After a delete the list stays where the user was, unless that page no longer exists.

#### Acceptance Criteria:

- [ ] Delete raises `ConfirmDialog` naming the query; cancelling issues no request.
- [ ] Confirming issues one `DeleteObject` on the row's key and removes the row from the list without a manual refresh.
- [ ] Deleting a row from a shared space works and targets that space's bucket.
- [ ] Deleting the only row on the last page moves the view to the new last page rather than showing an empty page.
- [ ] Deleting the last remaining query in a space shows the empty state, and the `saved_queries/` folder still exists (the marker is not touched — SPEC-173 FR-001).
- [ ] A failed delete leaves the row present and shows the mapped message.
- [ ] A tab linked to the deleted query keeps its SQL and loses its link (the tab is not closed).

### FR-006: Empty, loading, error and unreachable-space states

#### Description:

Four states, each distinguishable, and none of them silent. The one that needs care is a shared space the user can no longer reach — a membership revoked mid-session — which returns `AccessDenied` on the listing. That is an error about *that space*, not a broken drawer: the space selector stays usable so the user can pick another.

#### Acceptance Criteria:

- [ ] While the first page loads the drawer shows a loading state and no empty state.
- [ ] A space with no saved queries shows an empty state naming the space and explaining that saving a query from the editor puts it there.
- [ ] A failed listing shows the mapped message in a `Banner` with a Retry control; Retry re-issues the listing.
- [ ] An `AccessDenied` listing for a shared space renders that message, keeps the space selector interactive, and choosing another space loads it normally.
- [ ] No state renders raw AWS or Athena text (SPEC-106).
- [ ] The drawer never shows an empty state and an error at the same time.

### FR-007: The mobile Saved surface

#### Description:

Below `tablet`, `QueryMobileView`'s Saved tab shows the same records through the same hook: the space selector, one card per saved query, and the shared `Pager`. It reflows on the one tree — no `*Mobile` twin of the list (SPEC-095).

#### Acceptance Criteria:

- [ ] The mobile Saved tab renders the space selector and the same rows as the drawer, paged with the shared `Pager`.
- [ ] Run and View work from a card in a shared space as they do in the personal one, each issuing one `GetObject`.
- [ ] Delete is available from the mobile card behind the same confirm.
- [ ] At 400px the selector, the rows and the pager are all reachable and nothing overflows horizontally.
- [ ] The list is not mounted twice — a test asserts one saved-queries listing request when the mobile surface renders.

### FR-008: Help and the flag

#### Description:

A guide for loading a saved query joins the Query section of `helpContent.ts`, and the existing `save-query` guide is corrected where it describes the old private list.

No new `GATED_SURFACES` row is needed for either guide: both live in the `query` help section, which the registry already gates whole (`{name: 'Query help section', helpId: 'query'}`), and every surface this spec builds lives inside `/query`, which the registry already gates as a route. That is a claim to **verify**, not assume — the registry test must still make this spec's surfaces disappear with the flag off.

#### Acceptance Criteria:

- [ ] A `load-saved-query` guide exists in the `query` section describing: pick a space, page the list, Open, Delete — steps that match the shipped UI exactly (SPEC-074 FR-005: document only what is wired end to end).
- [ ] The `save-query` guide no longer describes saved queries as private to the user, and says where the `.sql` file lands.
- [ ] With `query` off, `/help` shows neither guide, via the existing section row — asserted, not assumed.
- [ ] With `query` off, `/query` renders the unavailable page and this spec's surfaces are unreachable; a test asserts it after the page settles, not inside `waitFor`.
- [ ] `GATED_SURFACES` gains no row that duplicates an existing one — one surface per row (SPEC-163).

### FR-009: Accessibility

#### Description:

The drawer already traps focus and owns Escape through the SPEC-155 depth registry; the new controls join it without changing that.

#### Acceptance Criteria:

- [ ] The space selector has a visible, programmatically associated label.
- [ ] `vitest-axe` reports no violations for the open drawer with rows, for its empty state, and for its error state — each asserted against the **driven container** (the element the interaction opened), not a fresh render of the closed component.
- [ ] Escape closes the drawer; with the delete confirm open, Escape closes the confirm only (innermost handler wins — SPEC-155).
- [ ] Every row control has an accessible name naming its query (`Open saved query {name}`, `Delete saved query {name}`).

### FR-010: An opened query is a buffer, not a file handle

#### Description:

SPEC-173 FR-010 states the rule; this spec is the surface that opens files from **other people's spaces**, so it re-asserts it here where the failure would be worst. A user who opens a colleague's saved query out of a shared space and edits it has changed nothing that anyone else can see. The file changes when they save (SPEC-175), and not before.

#### Acceptance Criteria:

- [ ] Editing the SQL of a tab opened from this surface issues no S3 request; a subsequent `GetObject` on that key returns the original body.
- [ ] That holds for a tab opened from a **shared** space, asserted separately from the personal-space case.
- [ ] The tab keeps both its edited buffer and its link across a tab switch and a drawer reopen.
- [ ] Re-opening the same saved query while an edited tab is linked to it opens a **second** tab carrying the file's stored body — the edited buffer is not treated as the file's contents.

---

## Data Model

No new persisted shape. The types are SPEC-173's (`QuerySpace`, `SavedQuery`, `SavedQueryPage`, `SavedQueryLink`), plus two pieces of local UI state:

```ts
// apps/portal/src/features/query/query.constants.ts
/** Rows per page in the saved-queries list — a UI page size, unrelated to LISTING_PAGE_SIZE (25). */
export const SAVED_QUERIES_PAGE_SIZE = 10;

// apps/portal/src/features/query/savedQuerySpace.ts
/** `s3portal.query.savedQuerySpace.{username}` — the last space chosen, this session. */
export function readSavedQuerySpaceId(username: string): string | null;
export function writeSavedQuerySpaceId(username: string, spaceId: string): void;
```

---

## API / Interface Contract

```ts
// apps/portal/src/features/query/useSavedQuerySpace.ts
export type UseSavedQuerySpaceResult = {
  /** The resolved space — never null while at least one space exists. */
  space: QuerySpace | null;
  spaces: QuerySpace[];
  selectSpace: (spaceId: string) => void;
};
/** Owns the selector's state, its sessionStorage persistence and the fallback to personal. */
export function useSavedQuerySpace(username: string | null): UseSavedQuerySpaceResult;

// apps/portal/src/features/query/SavedQueriesPanel.tsx — props
type Props = {
  open: boolean;
  onClose: () => void;
  spaces: QuerySpace[];
  space: QuerySpace | null;
  onSelectSpace: (spaceId: string) => void;
  queries: SavedQuery[];
  isLoading: boolean;
  error: unknown;
  hasMore: boolean;
  onLoadMore: () => void;
  isLoadingMore: boolean;
  onRetry: () => void;
  onOpen: (query: SavedQuery) => void;
  onDelete: (query: SavedQuery) => void;
};
```

## Environment Variables

None.

## File & Folder Structure

```
apps/portal/src/features/query/
├── SavedQueriesPanel.tsx            # space selector + paged list + states
├── SavedQueriesPanel.test.tsx
├── SavedQuerySpaceSelect.tsx        # the labelled space control, shared with the mobile surface
├── useSavedQuerySpace.ts            # selection + sessionStorage + fallback
├── useSavedQuerySpace.test.ts
├── savedQuerySpace.ts               # the degrade-safe sessionStorage wrapper
├── useSavedQueries.ts               # unchanged from SPEC-173 (already space-scoped + paginated)
├── QueryMobileView.tsx              # selector + pager on the Saved tab
├── QueryWorkspace.tsx               # wires the space selection into the drawer and Open
├── query.constants.ts               # + SAVED_QUERIES_PAGE_SIZE
└── savedQueries.a11y.test.tsx

apps/portal/src/features/help/helpContent.ts   # + load-saved-query, corrected save-query
```

## Implementation Phases

### Phase 1: Space selection

- `savedQuerySpace.ts` (degrade-safe sessionStorage) and `useSavedQuerySpace`.
- `SavedQuerySpaceSelect`, wired into `SavedQueriesPanel`; the drawer loads the chosen space.
- Fallbacks: unknown stored id, revoked membership, storage that throws.

### Phase 2: The paged list

- `SAVED_QUERIES_PAGE_SIZE`, the client-side page window over the accumulated rows, the shared `Pager`, and the `Z+` label.
- The keep-fetching rule for filtered-empty S3 pages, and its bound.
- Next-at-the-boundary triggering `loadMore`, with the busy and failure behaviour.
- The no-sort assertion and the reset-to-page-1 rules.

### Phase 3: Open, delete and the four states

- Open: tab-limit check, one `GetObject`, the linked tab labelled `savedQueryName(key)`, the failure path.
- The buffer-not-a-file-handle assertions (FR-010), personal and shared.
- Delete: confirm, removal, page clamping, the unlinked tab.
- Loading / empty / error / unreachable-space, each distinguishable.

### Phase 4: Mobile, help and gating

- The mobile Saved tab onto the same hook and controls.
- The `load-saved-query` guide and the `save-query` correction.
- The gating assertions and the axe passes against driven containers.
