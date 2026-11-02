---
type: Spec
id: SPEC-173
title: "Saved Queries as Files — the `saved_queries/` Folder, Its Protections and the Space-Scoped Store"
description: "Turns saved queries into .sql files in a protected saved_queries/ folder at a space's root, with a space-scoped store, and cuts the query editor over to it for the user's own space."
spec_status: Completed
depends_on: [SPEC-043, SPEC-057, SPEC-150, SPEC-163]
arc: saved-queries-in-spaces
arc_order: 1
---

**Dependency notes:** SPEC-043 (the store this replaces), SPEC-057 (shared spaces in the file browser), SPEC-150 (the protected-folder refusals), SPEC-163 (the gated-surface registry)
## Overview

Today a user's saved queries are rows in one private JSON document (`{username}/user_settings/saved-queries.json`) that only the query editor can read and only its author can reach. A saved query is a *file* — it is SQL, it has a name, and the person who wrote it usually wants to keep it beside the data it queries and often wants a teammate to be able to run it. This spec turns saved queries into real `.sql` objects in a real folder, `saved_queries/`, at the root of a space — the user's own space today, any space they belong to once the rest of the arc lands. It is an ordinary folder in every respect a user can see — browsable, uploadable into, a valid move/copy destination, its files openable, downloadable and deletable by anyone with access to the space — with exactly one protection: the folder itself cannot be deleted or renamed. It is kept alive by the same hidden `DO_NOT_DELETE.txt` marker every space root already uses. What keeps the query editor's load list coherent is not a lock on the folder but a filter: the editor offers top-level `.sql` files and nothing else.

This spec builds the folder, its protections and the store, and cuts the existing query-editor surfaces over to it for the user's **own** space. SPEC-174 adds choosing which space to load from; SPEC-175 adds choosing which space to save into.

## Scope

### In Scope

- The `saved_queries/` folder at a space root, created on demand, kept alive by a hidden `DO_NOT_DELETE.txt` marker.
- File-browser posture for that folder: an **ordinary folder** in every respect — visible, browsable, uploadable into, a valid move/copy destination — except that the folder **itself** can be neither deleted nor renamed.
- Hiding every `DO_NOT_DELETE.txt` marker from the file-browser listing, at any depth, in either bucket — not just the one at a user's root.
- A space-scoped saved-queries store over `.sql` objects: list (paginated), read, write, delete, and the name↔key rules.
- `QuerySpace` as the one space shape the query feature uses, replacing `SaveResultsDialog`'s `DestinationSpace`.
- Cutting the existing Save dialog, saved-queries drawer and mobile Saved list over to the new store, scoped to the user's own space.
- Retiring the SPEC-043 JSON store: `SavedQueriesStore`, its service functions and its callers are deleted.
- Hiding `saved_queries/` from the file browser when the `query` feature flag is off, while its protections stay in force regardless.
- Confirming — not assuming — that no IAM change is required.

### Out of Scope

- **Choosing a space** on save or on load. This spec always uses the user's own space. SPEC-174/175.
- **The paginated load surface.** The drawer keeps its current single-list shape here; SPEC-174 replaces it.
- Migrating the queries in the existing JSON store. They are **abandoned by decision** — see FR-007.
- Any change to query history (`user_settings/query-history.json`), which stays a JSON document.
- Any server-side or control-plane component. This is a browser-only feature; there is no Lambda, queue or state machine.
- **Restricting what a user may put in the folder.** It is an ordinary folder: any file may be uploaded, moved or copied into it, and subfolders may be created. The store filters what it *offers as a saved query* instead — FR-004.
- **Recursing into subfolders.** The listing is one level: `saved_queries/` itself. A `.sql` file the user tucks into `saved_queries/archive/` is a normal file in a normal folder, reachable from the file browser and not from the query editor.
- Writing a file from the editor at any moment other than an explicit Save — FR-010.

---

## Functional Requirements

### FR-001: The `saved_queries/` folder and its marker

#### Description:

Each space gets one flat folder at its root: `{rootPrefix}saved_queries/`, where `rootPrefix` is `{username}/` for the user's own space and `{space}/` for a shared space. S3 has no folders — a prefix exists only while an object lives under it — so the folder is held open by a marker object at `{rootPrefix}saved_queries/DO_NOT_DELETE.txt`, exactly the mechanism SPEC-014 uses at a user's root.

The marker is written idempotently and best-effort, on the same once-per-session HEAD-guarded pattern as `ensurePrefixMarker`: at most one existence check per space per session no matter how many times the workspace mounts. A failure to create it is not fatal to anything the user is doing — writing a saved query creates the prefix on its own.

The marker body is its own constant, not `PREFIX_MARKER_BODY`: that text says the file keeps *your personal storage space* active, which is wrong in a shared space and wrong about what this folder is.

#### Acceptance Criteria:

- [ ] `ensureSavedQueriesFolder(space)` issues a `HeadObject` on `{space.rootPrefix}saved_queries/DO_NOT_DELETE.txt` and, only when it is absent, a `PutObject` writing `SAVED_QUERIES_MARKER_BODY`.
- [ ] A second call for the same space in the same session issues **no** further S3 request.
- [ ] Calls for two different spaces each issue their own check.
- [ ] A failed head or put returns a failed `ServiceResult`; no caller in this spec treats that as fatal — the surface it was called from still renders.
- [ ] `SAVED_QUERIES_MARKER_BODY` is a distinct exported constant whose text does not claim the file keeps a *personal* space active, and a test asserts it is not equal to `PREFIX_MARKER_BODY`.
- [ ] The marker filename is `PREFIX_MARKER_FILENAME` (`DO_NOT_DELETE.txt`) — reused, not re-declared. A test asserts the two are the same string, because the IAM protection in FR-009 keys on that exact basename.

### FR-002: An ordinary folder that cannot be deleted or renamed

#### Description:

`saved_queries` joins `UNDELETABLE_ROOT_FOLDERS` and **nothing else**. It stays out of `HIDDEN_BROWSER_FOLDERS` and out of `PICKER_LOCKED_FOLDERS`. Those lists answer three different questions and are deliberately not a union (see the note at the top of `protectedFolders.ts`); this folder's answers are: *visible* — yes; *pasteable* — **yes**, it behaves like any other folder the user owns; *destroyable* — no.

Everything inside it is ordinary. Files may be uploaded, moved and copied in, individual files may be deleted, subfolders may be created, and none of that is the store's business. The store's business is deciding what to *offer as a saved query*, and it does that by extension (FR-004) — the filter, not a write lock, is what keeps a CSV out of the load list.

Only the folder itself is protected, and only at a **space root**: `alice/reports/saved_queries/` is an ordinary user folder with no special status at all. Rename is a move (S3 has no rename — it is a copy plus a delete of the source), so `moveFolder`'s existing `isUndeletableRootFolder` refusal covers renaming with no new guard.

#### Acceptance Criteria:

- [ ] `deleteFolder` on `{root}saved_queries/` returns a `ProtectedObject` failure with a message naming saved queries, and issues **no** S3 request.
- [ ] `moveFolder` with `sourcePrefix = {root}saved_queries/` returns the same refusal before any request — covering rename and move alike.
- [ ] The refusal holds for a shared-space root (`project_alpha/saved_queries/`) given that space's `rootPrefix`, and does **not** fire for `alice/reports/saved_queries/`.
- [ ] `DestinationPicker` **does** offer `{root}saved_queries/` as a move and copy destination, and moving or copying a file into it succeeds.
- [ ] Uploading a file into `{root}saved_queries/`, creating a subfolder in it, and deleting an individual file from it all succeed — no path in the app refuses an ordinary operation on the folder's *contents*.
- [ ] The folder **is** listed in the main file browser (with the `query` flag on — FR-008).
- [ ] A multi-select delete of every visible file in the folder succeeds and leaves the folder present (the marker is hidden from selection — FR-003).
- [ ] A test asserts `saved_queries` is present in `UNDELETABLE_ROOT_FOLDERS` and **absent** from both `HIDDEN_BROWSER_FOLDERS` and `PICKER_LOCKED_FOLDERS`, so a later edit that "tidies" the lists into a union fails.

### FR-003: Every `DO_NOT_DELETE.txt` is invisible, at any depth

#### Description:

`useFileBrowser` hides one exact key today — the user's own root marker — so a marker inside `saved_queries/` would be a visible file. It must not be: it is not the user's file, it carries no information they need, and offering it is offering an action the app's own IAM refuses.

That last clause generalises further than this folder. Both bucket policies deny `s3:DeleteObject` on `*/DO_NOT_DELETE.txt`, and `*` in an S3 resource ARN matches `/` — so **any** object with that basename, at any depth, in either bucket, is already undeletable. Showing one is the SPEC-150 FR-007 mistake (offering Delete for a rule this application authored) waiting to happen. The listing therefore hides by **basename**, not by exact key.

#### Acceptance Criteria:

- [ ] `isMarkerName(key)` is exported from `fileBrowser.constants.ts` and returns true exactly when the key's last path segment equals `PREFIX_MARKER_FILENAME`.
- [ ] The file-browser listing omits `alice/DO_NOT_DELETE.txt`, `alice/saved_queries/DO_NOT_DELETE.txt` and `project_alpha/saved_queries/DO_NOT_DELETE.txt`.
- [ ] It does **not** omit `alice/DO_NOT_DELETE.txt.bak` or `alice/notes/do_not_delete.txt` (the match is exact and case-sensitive, as S3 keys are).
- [ ] Select-all in a folder containing only `.sql` files and a marker selects the `.sql` files only, and deleting the selection succeeds with no partial-failure error.
- [ ] `useFileBrowser`'s `markerKey` parameter is removed and its callers updated; a test asserts no caller passes a marker key.

### FR-004: The space-scoped saved-queries store

#### Description:

`savedQueries.service.ts` is rewritten from a JSON read-modify-write into a set of operations over `.sql` objects. A saved query has no id and no record: its **key is its identity**, its **filename is its name**, and its `LastModified` is when it changed. Nothing else is stored, because nothing else can be stored in a `.sql` file without inventing a sidecar.

Listing pages through `ListObjectsV2` with `Delimiter: '/'` at `LISTING_PAGE_SIZE` and returns S3's own order — lexicographic by key. It returns only objects whose basename ends `.sql` (case-insensitively) and is not the marker.

**That filter is the whole defence, so it is a requirement rather than a precaution.** FR-002 makes this an ordinary folder: a user may upload a CSV into it, copy a whole folder tree in, or create a subfolder, and nothing stops them. What keeps the load list coherent is that the store offers `.sql` files at the top level of `saved_queries/` and nothing else — every other object is a normal file that belongs to the file browser and is invisible to the query editor. The `Delimiter: '/'` is load-bearing for the same reason: the listing is one level deep, so `saved_queries/archive/old.sql` is a file in a folder, not a saved query.

Writing is a `PutObject` of the editor buffer as `text/plain; charset=utf-8` at `{prefix}{name}.sql`. Unless `overwrite` is true the key is HEAD-checked first and a `Collision` failure returned rather than clobbering — the same shape `uploadFile` already uses, so the caller resolves it the same way.

Names are validated before any request. The rule is the leaf-name rule (`validateFolderName`'s: non-empty, no leading/trailing whitespace, no `/`, no control characters) plus a length ceiling of 128 characters, and a `.sql` suffix the user may type or omit without getting `foo.sql.sql`.

#### Acceptance Criteria:

- [ ] `savedQueriesPrefix(rootPrefix)` returns `{rootPrefix}saved_queries/`; `savedQueryKey(rootPrefix, name)` returns `{rootPrefix}saved_queries/{name}.sql`; `savedQueryName(key)` returns the basename with a trailing `.sql` removed. Round-tripping a name through key-then-name returns the original.
- [ ] A name already ending `.sql` or `.SQL` produces `{name}` unchanged as the key's basename — never a doubled suffix — and `savedQueryName` strips it case-insensitively.
- [ ] `validateSavedQueryName` returns a message for: empty/whitespace-only, leading or trailing whitespace, a name containing `/`, a name containing a control character, and a name whose resulting basename exceeds 128 characters. It returns `null` for `Monthly revenue`, `q1-2026_report` and a name containing `.`, spaces or unicode.
- [ ] `listSavedQueries({space, continuationToken})` issues one `ListObjectsV2` on `{prefix}` with `Delimiter: '/'` and `MaxKeys: LISTING_PAGE_SIZE`, and returns `{queries, isTruncated, nextContinuationToken}`.
- [ ] The returned `queries` exclude `DO_NOT_DELETE.txt`, exclude `notes.csv`, exclude an extensionless `README`, exclude any `CommonPrefixes` entry (a subfolder is never a saved query), and include `report.sql` and `REPORT.SQL`.
- [ ] A `.sql` file nested one level down (`saved_queries/archive/old.sql`) is **not** returned — the `Delimiter: '/'` is asserted, not incidental.
- [ ] Each returned item carries `spaceId`, `bucket`, `key`, `name` (no `.sql`), `updatedAt` (ISO string from `LastModified`) and `size`.
- [ ] The order returned is S3's order, unmodified — a test with keys returned as `b.sql, a.sql` asserts the service does **not** re-sort.
- [ ] A missing folder (`ListObjectsV2` returning no contents) yields an empty list and a successful result, not an error.
- [ ] `readSavedQuery({bucket, key})` returns the object body as a string; a `NoSuchKey` returns a failed `ServiceResult` with the key's name in a user-safe message (via `toUserMessage`, never raw AWS text — SPEC-106).
- [ ] `writeSavedQuery({space, name, sql})` calls `validateSavedQueryName` first and returns its message as a failed result with **no** S3 request when it is non-null.
- [ ] `writeSavedQuery` without `overwrite` HEAD-checks the key and returns a `Collision` failure when it exists; with `overwrite: true` it puts unconditionally.
- [ ] A successful write returns the `SavedQuery` for the key just written.
- [ ] `deleteSavedQuery({bucket, key, username})` delegates to `deleteObject`, so the existing prefix-marker refusal applies unchanged.
- [ ] Every function returns `ServiceResult` and never throws, including when the S3 client itself fails to initialise.

### FR-005: `QuerySpace`, the one space shape, and the spaces hook

#### Description:

`SaveResultsDialog` already computes "the user's own space, then every usable shared space they belong to" as `DestinationSpace[]`, inside `useSaveResults`. This spec needs the same list, and SPEC-174/175 need it again. It becomes `QuerySpace` and `useQuerySpaces()`, and `useSaveResults` consumes the hook rather than rebuilding the list — one definition of what a space is, for the whole query feature.

A space is usable when it is the personal one or a shared connection with `status === 'active'` (`isConnectionUsable`). An unset shared-space bucket yields the personal space alone; an unset user-space bucket yields an empty list.

#### Acceptance Criteria:

- [ ] `QuerySpace` is exported from `query.types.ts` with `{id, label, bucket, rootPrefix, rootLabel}`.
- [ ] `DestinationSpace` is deleted; `SaveResultsDialog` and `useSaveResults` take `QuerySpace`. A repo-wide search finds no remaining reference to `DestinationSpace`.
- [ ] `useQuerySpaces()` returns the personal space first (`id: 'personal'`, `label: 'My files'`, `rootPrefix: '{username}/'`), then one entry per usable shared connection in `useConnections` order, each with `id`/`label`/`rootPrefix` from the space name and the shared bucket.
- [ ] A shared connection whose `status` is `provisioning`, `failed` or `leaving` is omitted.
- [ ] With `VITE_S3_SHARED_SPACE_BUCKET` unset the result is the personal space alone; with `VITE_S3_USER_SPACE_BUCKET` unset the result is empty.
- [ ] `useSaveResults` produces the same destination list it does today, now via `useQuerySpaces`, and its existing tests pass unchanged apart from the type name.

### FR-006: The workspace reads and writes saved queries as files, in the user's own space

#### Description:

`useSavedQueries` takes a `QuerySpace | null` instead of a username and is backed by the store. In this spec its caller always passes the personal space; SPEC-174 passes the chosen one, so the hook does not change again.

The drawer's list becomes name + last-modified + size. **The SQL preview line is removed** — it is a deliberate, user-visible change: rendering it would mean a `GetObject` per row on every open, twenty-five round trips to show twenty-five one-line snippets. The body is fetched only when a query is opened.

Opening a saved query fetches its body and opens a tab linked to it. The link is `{spaceId, bucket, key, name}`, not an id.

#### Acceptance Criteria:

- [ ] `useSavedQueries(space | null)` is disabled while `space` is null, and keys on `queryKeys.savedQueries(spaceId)`.
- [ ] It exposes `queries`, `isLoading`, `error`, `hasMore`, `loadMore`, `isLoadingMore`, `refresh`, and `remove(query)`.
- [ ] `remove` deletes the object and invalidates the list key; the drawer reflects the deletion without a manual refresh.
- [ ] Saving from the editor writes `{username}/saved_queries/{name}.sql` and the drawer shows it after the write, without a page reload.
- [ ] The drawer renders each query's name, a relative last-modified time (`formatRelativeTime`) with an absolute `title`, and its size (`formatSize`/`formatBytes`); it renders **no** SQL preview and issues no `GetObject` while merely open.
- [ ] Opening a query issues exactly one `GetObject`, opens a tab whose SQL is the object body and whose label is **the file's name without its `.sql` extension**, and links the tab to `{spaceId, bucket, key, name}`. `Q1 revenue.sql` opens a tab labelled `Q1 revenue`.
- [ ] The label comes from `savedQueryName(key)` — the same function the store uses — so a file whose extension is `.SQL` still yields a label with no extension, and the tab label and the saved query's name can never disagree.
- [ ] A failed body fetch leaves the drawer open, opens no tab, and shows the mapped message (`toUserMessage`).
- [ ] `QueryTab.savedQueryId` is replaced by `savedQuery?: SavedQueryLink`. `readTabsState` keeps `version: 1` and ignores an unknown `savedQueryId` on a persisted state: the tabs and their SQL survive, the link does not.
- [ ] The mobile Saved list (`QueryMobileView`) renders the same records with Run and View, and issues no `GetObject` until one is chosen.
- [ ] `ensureSavedQueriesFolder` is called for the personal space when the workspace mounts, and its failure does not block the workspace rendering.

### FR-007: The SPEC-043 JSON store is retired

#### Description:

`{username}/user_settings/saved-queries.json` stops being read and written. Its code is deleted — not left dormant — so there is one saved-queries system in the codebase and no second definition of what a saved query is.

The queries inside an existing document are **abandoned by decision**, not migrated. The portal is pre-production with no real users; a migration path would be code with one execution and no way to test its second run. The object itself is left in place: `user_settings/` denies delete, and deleting it is neither possible nor necessary.

#### Acceptance Criteria:

- [ ] `SavedQueriesStore` and the `getSavedQueries` / `upsertSavedQuery` / `removeSavedQuery` JSON functions are deleted.
- [ ] No module reads or writes `saved-queries.json`; a repo-wide search for the string finds it only in docs.
- [ ] `useSavedQueries`'s `recovered` flag and the SPEC-159 quarantine handling for **this** document are removed along with it. `quarantineDocument` itself stays — query history and the other `user_settings/` documents still use it, and a test asserts those callers are untouched.
- [ ] The `SavedQuery` type no longer carries `id`, `database`, `createdAt` or `sql`.
- [ ] `apps/portal/info/component-inventory/query-feature.md`'s `savedQueries.service.ts` and `useSavedQueries` rows describe the new surface.

### FR-008: `saved_queries/` is hidden when the `query` flag is off, and protected either way

#### Description:

The folder is a Query feature wearing a file-browser row, so it is gated on `query` — with `query` off, the file browser lists it no more than the Query tab appears. It is a **registry** row (`GATED_SURFACES.query`), not a per-component opt-in, because that is the whole point of SPEC-163's registry: the entry points that are easy to miss are the ones in another feature's screen.

With the flag off the folder is hidden from the destination picker too — a destination the user cannot see is not a destination — which is the one place the gate touches an otherwise ordinary folder operation. That is presentation: it removes a way of *asking*, and revokes no grant.

The FR-002 refusal, by contrast, is **unconditional**. With the flag off the folder is not shown and it is *also* not deletable and not renameable. A test asserts that directly, because "you can't see it" and "you can't destroy it" are different guarantees and only one of them survives a stale cached flag document.

`FileBrowser` composes the hidden-folder list from `HIDDEN_BROWSER_FOLDERS` plus `saved_queries` when the flag is off. It reads the flag through the one public door (`useFeature`) — `features/file-browser/` importing `features/feature-flags/` is a feature-to-feature import, which the SPEC-155 ESLint rule permits; the rule it must not break is `components/`, `lib/` and `hooks/` importing a feature.

#### Acceptance Criteria:

- [ ] With `query` **on**, the `/files` listing shows a `saved_queries` row for a listing that contains the folder.
- [ ] With `query` **off**, that row is absent from the same listing — removed from the DOM, not hidden or disabled (SPEC-163).
- [ ] With `query` off, `deleteFolder` and `moveFolder` on `{root}saved_queries/` still return `ProtectedObject` — asserted with the flag off, because that refusal is not a gate.
- [ ] With `query` off, `DestinationPicker` does not offer the folder; with `query` on it does (FR-002).
- [ ] A `GATED_SURFACES.query` row exists for the folder, and `gatedSurfaces.test.tsx` makes it disappear by rendering the **real** `/files` page against a listing containing the folder — not a re-implementation of the gate.
- [ ] The off-half of that row's assertion runs after the page has settled, never inside `waitFor` (SPEC-163: a `waitFor` whose first attempt lands while everything is legitimately absent passes vacuously).
- [ ] `FileBrowser` reads the flag via `useFeature`; no module outside `features/feature-flags/` names `useFeatureFlags`, and the existing tripwire still passes.
- [ ] Nothing in `components/`, `lib/` or `hooks/` gained an import from `features/`; the SPEC-155 ESLint rule passes.

### FR-009: No IAM change is required — verified, not assumed

#### Description:

Every grant this feature needs already exists, and the claim is checkable rather than plausible:

- **Read/write/list under a space prefix.** `UserPrefixObjects` grants `GetObject`/`PutObject`/`DeleteObject` on `{user-bucket}/${aws:PrincipalTag/username}/*`, and `SharedSpaceObjects` grants the same on each `shared_space_{k}` prefix. `saved_queries/` is inside both. `UserPrefixList`/`SharedSpaceList` already permit the listing prefixes.
- **The marker cannot be deleted.** `ProtectPrefixMarker` denies `s3:DeleteObject` on `{user-bucket}/*/DO_NOT_DELETE.txt` and `SharedMarkerNoDelete` denies it on `{shared-bucket}/*/DO_NOT_DELETE.txt`. `*` in an S3 resource ARN matches `/`, so both already cover `{root}saved_queries/DO_NOT_DELETE.txt` at that depth and any other.

That second bullet is the one this spec leans on hardest and is the one an ARN wildcard reading could get wrong, so it is not taken on documentation. This spec ships **no** `.tftpl` change and instead owes a live confirmation: a real delete of a real marker, refused.

#### Acceptance Criteria:

- [ ] No file under `infra/` changes in this spec. A reviewer can confirm the diff touches no `.tf` or `.tftpl`.
- [ ] A test pins the two Deny statements by reading the two `.tftpl` files and asserting each contains a `DeleteObject` Deny whose `Resource` ends `/*/DO_NOT_DELETE.txt` — so a later IAM edit that narrows the wildcard fails here rather than in production.
- [ ] **Live check (owed, cannot be discharged offline):** signed in through the portal, attempt to delete `{username}/saved_queries/DO_NOT_DELETE.txt` — via the file browser after temporarily unhiding it, or by an equivalent `DeleteObject` under the portal role — and confirm `AccessDenied`. Repeat in a shared space. Record the result in the delivery doc; until it is run, FR-009 is corroborated, not discharged.

### FR-010: A saved query changes only when the user saves it

#### Description:

Editing a tab's SQL is editing a buffer, never the file. A tab opened from `report.sql` and then typed into is a modified buffer linked to an unmodified object: nothing writes on keystroke, on blur, on tab switch, on running the query, on closing the tab, or on leaving the page. The only `PutObject` in this feature is the one an explicit Save issues.

This is how the workspace behaves today — there is no autosave anywhere in it — so the requirement is a **tripwire**, not new behaviour. It is written down because the failure mode is silent and expensive: a shared space's saved query that rewrites itself because a colleague opened it and typed, and nothing in the app would report it. Tab state persistence is unaffected: `queryTabs.ts` keeps buffers in `sessionStorage`, which is not the file and never was.

#### Acceptance Criteria:

- [ ] Typing into a tab opened from a saved query issues **no** S3 request of any kind.
- [ ] Running the query, switching tabs, closing the tab, and unmounting the workspace each issue no `PutObject` to `saved_queries/`.
- [ ] After any of those, a fresh `GetObject` on the file returns the original body.
- [ ] The tab keeps its link and its edited buffer across a tab switch; the link is not cleared by editing.
- [ ] A test asserts the total count of `PutObject` calls to `saved_queries/` across an edit-run-switch-close sequence is zero — a count, so a write added later fails here rather than in a shared space.

---

## Data Model

```ts
// apps/portal/src/features/query/query.types.ts

/**
 * A space a saved query (or a saved result) can live in: the user's own space, or a
 * shared space they are an active member of. Replaces SPEC-049's `DestinationSpace`.
 */
export type QuerySpace = {
  /** 'personal' for the user's own space; the shared-space name otherwise. */
  id: string;
  /** Display label: 'My files', or the space name. */
  label: string;
  bucket: string;
  /** The space root, trailing slash: `alice/` or `project_alpha/`. */
  rootPrefix: string;
  /** Label for the root row in a folder picker. */
  rootLabel: string;
};

/**
 * One `.sql` object in a space's `saved_queries/` folder. The key IS the identity and
 * the filename IS the name — there is no id and no record, because a `.sql` file cannot
 * carry one without a sidecar this feature deliberately does not have.
 */
export type SavedQuery = {
  spaceId: string;
  bucket: string;
  /** `{rootPrefix}saved_queries/{name}.sql` */
  key: string;
  /** The filename without its `.sql` suffix. */
  name: string;
  /** S3 LastModified, ISO 8601. */
  updatedAt: string;
  /** Object size in bytes. */
  size: number;
};

/** One `ListObjectsV2` page of a space's saved queries, in S3's own (lexicographic) order. */
export type SavedQueryPage = {
  queries: SavedQuery[];
  isTruncated: boolean;
  nextContinuationToken?: string;
};

/** What a tab remembers about the saved query it was opened from. */
export type SavedQueryLink = {
  spaceId: string;
  bucket: string;
  key: string;
  name: string;
};

export type QueryTab = {
  id: string;
  label: string;
  sql: string;
  /** Set when opened from a saved query (replaces `savedQueryId`). */
  savedQuery?: SavedQueryLink;
};

// DELETED: SavedQueriesStore
```

---

## API / Interface Contract

```ts
// apps/portal/src/features/file-browser/fileBrowser.constants.ts
export const SAVED_QUERIES_FOLDER = 'saved_queries';
export const SAVED_QUERIES_MARKER_BODY: string;
/** True when the key's last segment is exactly `DO_NOT_DELETE.txt`. */
export function isMarkerName(key: string): boolean;

// apps/portal/src/features/query/savedQueries.service.ts
export function savedQueriesPrefix(rootPrefix: string): string;
export function savedQueryKey(rootPrefix: string, name: string): string;
export function savedQueryName(key: string): string;
/** Error message, or null when valid. */
export function validateSavedQueryName(name: string): string | null;

export function ensureSavedQueriesFolder(space: QuerySpace): Promise<ServiceResult<void>>;

export function listSavedQueries(params: {
  space: QuerySpace;
  continuationToken?: string;
  signal?: AbortSignal;
}): Promise<ServiceResult<SavedQueryPage>>;

export function readSavedQuery(params: {bucket: string; key: string}): Promise<ServiceResult<string>>;

export function writeSavedQuery(params: {
  space: QuerySpace;
  name: string;
  sql: string;
  overwrite?: boolean;
}): Promise<ServiceResult<SavedQuery>>;

export function deleteSavedQuery(params: {
  bucket: string;
  key: string;
  username: string;
}): Promise<ServiceResult<void>>;

// apps/portal/src/features/query/useQuerySpaces.ts
export function useQuerySpaces(): QuerySpace[];

// apps/portal/src/features/query/useSavedQueries.ts
export type UseSavedQueriesResult = {
  queries: SavedQuery[];
  isLoading: boolean;
  error: unknown;
  hasMore: boolean;
  loadMore: () => void;
  isLoadingMore: boolean;
  refresh: () => void;
  remove: (query: SavedQuery) => Promise<void>;
};
export function useSavedQueries(space: QuerySpace | null): UseSavedQueriesResult;

// apps/portal/src/features/query/queryKeys.ts — changed
savedQueries: (spaceId: string) => [...queryKeys.all, 'savedQueries', spaceId] as const;
```

## Environment Variables

None. This spec introduces no new `VITE_` variable and changes no existing one.

## File & Folder Structure

```
apps/portal/src/
├── features/
│   ├── file-browser/
│   │   ├── fileBrowser.constants.ts      # + SAVED_QUERIES_FOLDER, SAVED_QUERIES_MARKER_BODY, isMarkerName
│   │   ├── protectedFolders.ts           # + saved_queries in UNDELETABLE_ROOT_FOLDERS only
│   │   ├── useFileBrowser.ts             # markerKey removed; basename marker filter
│   │   └── FileBrowser.tsx               # flag-composed hidden-folder list
│   ├── feature-flags/
│   │   ├── gatedSurfaces.ts              # + the saved_queries row under `query`
│   │   └── gatedSurfaces.test.tsx        # + its reach recipe
│   └── query/
│       ├── savedQueries.service.ts       # rewritten: .sql objects, not a JSON store
│       ├── savedQueries.service.test.ts
│       ├── useSavedQueries.ts            # space-scoped, paginated
│       ├── useSavedQueries.test.ts
│       ├── useQuerySpaces.ts             # new
│       ├── useQuerySpaces.test.ts
│       ├── useSaveResults.ts             # consumes useQuerySpaces
│       ├── SavedQueriesPanel.tsx         # name/modified/size rows, no SQL preview
│       ├── SaveResultsDialog.tsx         # DestinationSpace → QuerySpace
│       ├── queryTabs.ts                  # savedQueryId → savedQuery link
│       ├── queryKeys.ts
│       └── query.types.ts
```

## Implementation Phases

### Phase 1: The folder, the marker and the protections

- `SAVED_QUERIES_FOLDER`, `SAVED_QUERIES_MARKER_BODY`, `isMarkerName` in `fileBrowser.constants.ts`.
- `saved_queries` into `UNDELETABLE_ROOT_FOLDERS` only, with the divergence test asserting its absence from the other two lists.
- `useFileBrowser`: drop `markerKey`, filter by basename; update callers.
- The `.tftpl` pinning test for the two Deny statements (FR-009).

### Phase 2: The store and the space shape

- Rewrite `savedQueries.service.ts` over `.sql` objects: prefix/key/name helpers, `validateSavedQueryName`, `ensureSavedQueriesFolder`, `listSavedQueries`, `readSavedQuery`, `writeSavedQuery`, `deleteSavedQuery`.
- `QuerySpace` + `useQuerySpaces`; delete `DestinationSpace` and re-point `useSaveResults` / `SaveResultsDialog`.
- `queryKeys.savedQueries` keyed on space id.

### Phase 3: The workspace cutover and the retirement

- `useSavedQueries(space | null)` over the store, with `loadMore`.
- `SavedQueriesPanel` rows: name, relative time, size; no preview. Open fetches the body.
- `SaveQueryDialog` writes through `writeSavedQuery`; collision confirm maps onto the `Collision` failure.
- `queryTabs.ts`: `savedQuery` link replaces `savedQueryId`, old field ignored.
- `QueryMobileView` Saved list onto the same records.
- Delete the JSON store, its types and its quarantine handling; update the component inventory.

### Phase 4: The flag gate

- `FileBrowser` composes the hidden list from `useFeature('query')`.
- The `GATED_SURFACES.query` row and its reach recipe against the real `/files` page.
- The unconditional-protection tests (delete/move/paste refused with the flag off).
