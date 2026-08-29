# Saved-queries feature (`apps/portal/src/features/saved-queries/`)

Part of the component inventory (`INDEX.md`, beside this file, is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.

Public barrel: `features/saved-queries/index.ts`. The shared `.sql` store (SPEC-177, out of
`features/query/`): `.sql` objects in `{root}saved_queries/`, the per-session space memory, the
display pager and the whole save path — everything the Query workspace and the Data Explorer both
need to load and save a saved query. The space a query lives in is a `QuerySpace` from
`features/catalog/`. `features/query/` and `features/data-explorer/` compose this feature and it may
import neither (enforced by the ESLint layering rule). All services return `ServiceResult<T>`, never
throw.

> The Query workspace's rail panel (`SavedQueriesPanel`) is **not** here — it is a workspace surface
> with tab-opening affordances, and stays in `query-feature.md`.

### Services

| Symbol | File | Purpose |
|---|---|---|
| `savedQueriesPrefix` / `savedQueryKey` / `savedQueryName` / `validateSavedQueryName` / `isLinkedSavedQuery` / `ensureSavedQueriesFolder` / `listSavedQueries` / `readSavedQuery` / `writeSavedQuery` / `deleteSavedQuery` | `savedQueries.service.ts` | The space-scoped saved-queries store over `.sql` OBJECTS in `{root}saved_queries/` (SPEC-173, replacing SPEC-043's JSON store). The key is the identity and the filename is the name; the listing is one level, top-level `.sql` only (the filter stays in TypeScript), in S3's own order; the write is ONE call whose `Conflict` becomes `Collision` naming the query; the delete delegates to `deleteObject`. `isLinkedSavedQuery(link, space, name)` answers "does saving this land on the file the buffer is linked to?" by KEY — the one rule behind the dialog's sentence and the host's `overwrite` (SPEC-175 FR-004). |

### Hooks

| Symbol | File | Purpose |
|---|---|---|
| `useSavedQueries(space \| null)` | `useSavedQueries.ts` | A space's saved queries, paginated over S3's listing, keyed on `savedQueryKeys.list(spaceId)`; exposes `hasMore`/`loadMore`/`refresh` and a `remove` that deletes the object. Fetches no bodies — the SQL is read when a query is OPENED (SPEC-173). |
| `useSavedQuerySpace(username, spaces)` | `useSavedQuerySpace.ts` | Which space the saved-queries surfaces read from: the resolved space, the list to render and a `selectSpace` that remembers it for the session. The spaces are handed IN, so the caller applies the `sharedWorkspaces` gate at the view without the hook learning about flags; an id naming nothing offered — a revoked membership, a flag turning off — falls back to personal (SPEC-174 FR-001). |
| `useSavedQueriesPager({queries, hasMore, loadMore, isLoadingMore, error, resetKey})` | `useSavedQueriesPager.ts` | The display window every saved-queries surface pages through: ten rows at a time, the honest `X–Y of Z` / `Z+` label, the clamp that survives a delete, reset-to-page-1 on `resetKey`, and the keep-fetching rule for listing pages the `.sql` filter empties — bounded by the listing's end and stopped by an error. `isFilling` (rows not in yet) is distinct from `isEmpty` (listing exhausted) (SPEC-174 FR-002). |
| `useSaveQuery({spaces, defaultSpace, payload, onSaved, toast})` | `useSaveQuery.ts` | The whole save path for a saved query: the dialog's open state and its inputs (`initialName` / `initialSpace` — the link's own space, else the remembered one), validation before any request, `ensureSavedQueriesFolder` for the CHOSEN space, the write, the `Collision` round-trip that survives a cancelled Replace, the busy/error state and the toast. An unchanged re-save of a linked buffer writes with `overwrite` and raises no second confirm (SPEC-175). **`payload` is `{sql, link?}`, not a `QueryTab`** (SPEC-177 FR-002) — `onSaved(query, sql)` hands back the bytes that were written, because a caller's dirty marker must clear against those and not against its live buffer. |

### Components

| Symbol | File | Purpose |
|---|---|---|
| `SaveQueryDialog` | `SaveQueryDialog.tsx` | Destination-and-name modal, pre-filled and selected on re-save — EVERY save asks. The space control is SPEC-174's `SavedQuerySpaceSelect`; the name is validated ON SUBMIT (never by disabling it — SPEC-167); a write failure renders inline on the field; with no writable space it explains itself instead of offering a control. The collision confirm belongs to the host, raised by `writeSavedQuery`'s `Collision` rather than a scan of the loaded list (SPEC-043, SPEC-173, SPEC-175). |
| `SavedQuerySpaceSelect` | `SavedQuerySpaceSelect.tsx` | The labelled "Space" control shared by the drawer, the mobile Saved tab and the save dialog. Rendered even with one option — a control that appears only once a user joins a shared space is one they never learn to look for (SPEC-174 FR-001). |

### Types, constants & keys

| Symbol | File | Purpose |
|---|---|---|
| `SavedQuery`, `SavedQueryPage`, `SavedQueryLink` | `savedQueries.types.ts` | One `.sql` object (key = identity, filename = name); one listing page; and what a caller remembers about the file its buffer was opened from. `QueryTab.savedQuery` is a `SavedQueryLink` (SPEC-043, SPEC-173 — `SavedQueriesStore` is deleted). |
| `readSavedQuerySpaceId` / `writeSavedQuerySpaceId` | `savedQuerySpace.ts` | The degrade-safe `sessionStorage` wrapper behind `useSavedQuerySpace` (`s3portal.query.savedQuerySpace.{username}`); a read or write that throws degrades to "not remembered" (SPEC-174 FR-001). |
| `SAVED_QUERIES_PAGE_SIZE`, `QUERY_SAVED_QUERY_SPACE_STORAGE_PREFIX` | `savedQueries.constants.ts` | Ten display rows per page (filtered rows, never keys); and the storage prefix above. The prefix's `query.` segment is a **live key**, not a description of where the module lives — SPEC-177 moved the module and deliberately left the value alone. |
| `savedQueryKeys` | `savedQueryKeys.ts` | Key factory (`all` / `list(spaceId)`), rooted at `['saved-queries']` — never hand-build keys. Keyed by SPACE, not by user: the same user reads a different list per space (SPEC-173). |
