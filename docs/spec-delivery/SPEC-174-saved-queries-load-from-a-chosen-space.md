# Completed Spec — SPEC-174: Saved Queries — Loading from a Chosen Space

## What was completed?

Loading a saved query now starts with a question — *which space?* — and the answer's `.sql` files
are shown a page at a time. A user who belongs to three shared spaces can open a colleague's saved
query from any of them without leaving the editor.

- **`savedQuerySpace.ts`** — `readSavedQuerySpaceId` / `writeSavedQuerySpaceId`, the degrade-safe
  `sessionStorage` wrapper (`s3portal.query.savedQuerySpace.{username}`), on the same pattern as
  `useResultsPageSize`.
- **`useSavedQuerySpace(username, spaces)`** — the selection, its persistence, and one fallback
  path that covers a stored id naming nothing offered: a revoked membership and a flag turning off
  resolve identically, to personal.
- **`SavedQuerySpaceSelect`** — the labelled control, shared by the drawer and the mobile Saved tab.
- **`useSavedQueriesPager`** — the display window over the accumulated rows, the `Z+` label, the
  clamp, the reset key, and the keep-fetching rule. Shared by both surfaces, so the two cannot
  drift apart about what a page is.
- **`SAVED_QUERIES_PAGE_SIZE` (10)** and `QUERY_SAVED_QUERY_SPACE_STORAGE_PREFIX`.
- **`SavedQueriesPanel`** — the selector above every body state, the shared `Pager` in the footer, a
  Retry on the error banner, an empty state that names the space, and `SavedQueryDeleteConfirm`
  exported so the mobile card raises the same wording.
- **`QueryMobileView`** — the same selector, pager and delete on the Saved tab; one tree, no twin.
- **`QueryWorkspace`** — wires the chosen space into `useSavedQueries`, and checks the tab cap
  **before** the `GetObject`.
- **Help** — a `load-saved-query` guide, and `save-query` corrected where it called the list private.
- **No `infra/` change anywhere in the diff.**

## A listing page and a display page are different things

SPEC-173's store returns only the top-level `.sql` files of an otherwise ordinary folder, so an S3
page of 25 keys can yield 25 rows, three, or **zero** while more pages remain. A folder holding two
hundred CSVs and one saved query would otherwise have rendered as empty with a "Load more" the user
had to guess at. `useSavedQueriesPager` therefore keeps fetching while the listing is truncated and
it holds fewer rows than the page in view needs — bounded by the listing's own end, and **stopped by
an error**, or a failed fetch that leaves `hasNextPage` true would spin forever.

While it fills, the surface reads as **loading**: not empty (the listing is not exhausted) and not a
pager over nothing (`0–0 of 0+` is a worse answer than a spinner). That is `isFilling`, and it is
distinct from `isEmpty`.

The label says `Z+` while pages remain because S3 reports no total — the difference between "there
are 24" and "there are at least 24".

### Deliberate deviations

- **FR-001's "exactly the spaces `useQuerySpaces()` returns" is gated.** With `sharedWorkspaces`
  off, the selector offers **My files alone**. SPEC-163 already filters the connections list and the
  schema rail on that flag at the *view*; leaving this one ungated would name a colleague's space in
  a dropdown moments after the rest of the app stopped showing it. Filtered in `QueryWorkspace`,
  never in `useQuerySpaces` and never in a service (SPEC-162 FR-006), and a **new
  `GATED_SURFACES.sharedWorkspaces` row** — *Shared spaces in the saved-queries selector* — walks it
  in both states through the real workspace and the real drawer. It is not a duplicate of *Shared
  databases in the schema rail*: that row gates the connections the rail browses, this one gates a
  control that reads `useQuerySpaces`.
- **`useSavedQuerySpace` takes its spaces as a parameter** rather than calling `useQuerySpaces`
  itself, which is what makes the gate above possible without the hook learning about flags. It
  still returns `spaces`, so the spec's `UseSavedQuerySpaceResult` is unchanged.
- **The pager lives in its own hook**, not inside `SavedQueriesPanel`, because FR-007 needs the
  identical arithmetic on the mobile surface. The panel's props are the spec's.
- **`ensureSavedQueriesFolder` still runs for the personal space only.** Nothing in this spec writes
  to a shared space; a shared space with no folder lists as an empty page, which is the store's
  documented behaviour. SPEC-175 owns the write.

## What changed from earlier specs?

- **`SavedQueriesPanel`'s props**: `loadMore` → `onLoadMore`, plus `spaces` / `space` /
  `onSelectSpace` / `onRetry`. Its empty state now names the space ("No saved queries in My files").
- **`QueryMobileView`'s props**: `spaces`, `space`, `onSelectSpace`, `savedHasMore`,
  `onLoadMoreSaved`, `savedLoadingMore`, `onDeleteSaved`. The Saved tab gained a Delete control and
  a pager; its empty state names the space too.
- **`QueryWorkspace.handleOpenSaved`** checks `QUERY_TABS_MAX` before reading the body — at the cap
  it now issues **no** `GetObject` where SPEC-173 issued one and discarded it.
- `useSavedQueries` is unchanged, as SPEC-173 predicted: it was already space-keyed and paginated.

## What the review changed

A fresh-context review against the acceptance criteria found one real defect and three tests that
could not fail. All four are fixed in the branch:

- **A failed load-more took the loaded rows with it.** The drawer's error branch replaced the list
  *and* the pager, so a `ListObjectsV2` failure on page 3 of 25 rows left a banner and nothing else
  — FR-002 AC5 says the opposite. The banner now sits **above** the list, the pager follows the
  **rows** rather than the error, and `hasNext` accounts for the stopped fill so Next is not offered
  as a control that could never advance. The mobile surface had the mirror half (rows kept, pager
  gated on the error) and is fixed the same way.
- **The fill ran with the drawer closed.** A closed `Drawer` renders `null` but still runs its
  hooks, so a folder of two hundred CSVs walked its whole listing on every visit to `/query`. The
  pager takes an `enabled` flag — `open` in the drawer, `tab === 'saved'` on mobile.
- **Both reset-to-page-1 rules were untested where they can break.** The hook's own test changes the
  key it asserts on, so replacing both call sites with a constant left the suite green (measured).
  The rules are now asserted at the **caller**, and that assertion was re-checked against the same
  mutation.
- **The "bounded continuation" test was stopped by the `hasMore` guard alone** and passed with the
  row-count condition deleted. A test now walks several yield-nothing listing pages and stops.

Also added: FR-004 AC4's sweep (nothing outside the store strips a `.sql` extension — verified
against a deliberate violation), FR-005 AC3 (a shared space's delete targets that space's bucket
and takes the marker guard's owner from the key), FR-006 AC4's second half, and FR-009 AC3's Escape
ordering.

## Verification

`npm run format`, `lint`, the full portal suite (1992 tests, 80 files) and `npm run build` green
locally. Nothing here makes an AWS call that offline tests cannot stand in for, so **no live check
is owed by this spec** — the arc's owed check is still SPEC-173's marker-delete refusal, personal
and shared.
