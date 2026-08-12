# Completed Spec — SPEC-173: Saved Queries as Files — the `saved_queries/` Folder, Its Protections and the Space-Scoped Store

## What was completed?

A saved query stopped being a row in a private JSON document and became a `.sql` file in a folder
the user can see. `{username}/user_settings/saved-queries.json` is no longer read or written by
anything; the store, its types and its quarantine handling are deleted.

- **`fileBrowser.constants.ts`** — `SAVED_QUERIES_FOLDER`, `SAVED_QUERIES_MARKER_BODY`, and
  `isMarkerName(key)`, which matches a prefix marker by **basename** at any depth in either bucket.
- **`protectedFolders.ts`** — `saved_queries` in `UNDELETABLE_ROOT_FOLDERS` **alone**, plus
  `undeletableRootFolderRefusal(prefix, root, action)` so the refusal names the folder it is about.
- **`useFileBrowser(bucket, prefix?)`** — the `markerKey` parameter is gone, and with it the prop
  threaded from four dialogs and two pages; every marker is hidden by basename instead.
- **`savedQueries.service.ts`** — rewritten over `.sql` objects: prefix/key/name helpers,
  `validateSavedQueryName`, `ensureSavedQueriesFolder`, `listSavedQueries`, `readSavedQuery`,
  `writeSavedQuery`, `deleteSavedQuery`.
- **`QuerySpace` + `useQuerySpaces()`** — one definition of a space for the whole query feature;
  `DestinationSpace` is deleted and `useSaveResults` consumes the hook.
- **`useSavedQueries(space | null)`**, `SavedQueriesPanel`, `SaveQueryDialog`, `QueryMobileView`
  and the tab link (`savedQuery`, replacing `savedQueryId`) cut over to the store.
- **A `GATED_SURFACES.query` row** for the folder, walked by the registry test against the real
  `/files` page.
- **No `infra/` change anywhere in the diff.**

## The filter is the defence, and that is deliberate

The folder is ordinary in every respect a user can see: browsable, uploadable into, a valid
move/copy destination, subfolders allowed, individual files deletable. Only the folder itself
cannot be deleted or renamed — one entry, in one list, and a test asserts its **absence** from
`HIDDEN_BROWSER_FOLDERS` and `PICKER_LOCKED_FOLDERS` so a later edit that tidies the three lists
into a union fails.

What keeps the query editor's load list coherent is therefore the store's own filter: **top-level
`.sql` files and nothing else**. `Delimiter: '/'` is load-bearing beside it, and the depth check is
belt to its braces — asserted in the service rather than left as a property of one request's
parameters, so `saved_queries/archive/old.sql` is a file in a folder and never a saved query.

## Three deliberate, user-visible changes

- **The drawer lost its SQL preview.** A `.sql` object carries no body until it is read, so a
  preview line means a `GetObject` per row on every open — twenty-five round trips for
  twenty-five one-line snippets. A row is name, relative modified time and size.
- **Every Save asks for a name**, a linked tab's included, pre-filled and selected. SPEC-043 wrote
  back silently; a user about to overwrite a file should be told which file, in which space.
- **`Report` and `report` are two saved queries.** The collision check moved from a
  case-insensitive scan of the loaded array to a HEAD on the exact key, because the list is
  paginated now and the target space may not be the one on screen. S3 keys are case-sensitive.

## The dirty marker is a session snapshot

SPEC-043's marker compared the tab's buffer with the `sql` field on the store's row. There is no
such field: a `.sql` object has a body only once it has been read. The workspace therefore keeps a
`key → sql` map of what **this session last saw** — the body fetched when a query was opened, or
the buffer just written by a save — and marks a tab dirty against that.

The cost is stated rather than hidden: a tab restored from `sessionStorage` after a reload has no
snapshot and shows no marker until it is opened or saved again. The alternative was a `GetObject`
per linked tab on every mount, which is the same trade the preview line lost.

## Two things that fell out of the marker rule

`useFileBrowser` used to hide one exact key, supplied by its caller. Both bucket policies deny
`s3:DeleteObject` on a wildcard resource ending `/*/DO_NOT_DELETE.txt`, and `*` in an S3 resource
ARN matches `/` — so **any** object with that basename, anywhere in either bucket, is already
undeletable, and showing one offers an action this application's own IAM refuses (the SPEC-150
FR-007 mistake). Hiding by basename made the caller-supplied key dead weight, so it is gone from
`DestinationPicker`, `MoveDialog`, `CopyDialog`, `FileBrowserDialogs`, `FilesPage` and
`StartQualityCheckDialog`, and `DestinationPicker`'s props stopped being a union. A source sweep
asserts no caller passes one.

## The gate touches one ordinary folder operation, and the refusal is not part of it

With `query` off the folder leaves the file-browser listing **and** the destination picker together
— a destination the user cannot see is not a destination. The picker reads the flag itself rather
than taking it from four callers, which is the same reasoning the registry exists for; the cost is
that `DestinationPicker` now needs an auth context, which one bespoke a11y tree had to be given.

The delete/rename refusal is **unconditional** and structurally so: `deleteFolder`/`moveFolder`
take no flag, so there is no state in which the gate reaches them. FR-008 AC3 asks for a test "with
the flag off"; a service-level test cannot render a flag state at all, so the refusal is tested
directly and the structural argument is recorded beside it. "You cannot see it" and "you cannot
destroy it" are different guarantees, and only one survives a stale cached flag document.

## What is owed

**FR-009's live check, and it is the arc's load-bearing premise.** Signed in through the portal,
attempt to delete `{username}/saved_queries/DO_NOT_DELETE.txt` — via the file browser after
temporarily unhiding it, or an equivalent `DeleteObject` under the portal role — and confirm
`AccessDenied`. Repeat in a shared space. Until it is run, the ARN-wildcard reading is
**corroborated, not discharged**: it is pinned by a test over the two `.tftpl` files (which fails
if a later IAM edit narrows the wildcard) and by AWS's documented wildcard semantics, and neither
is a real refusal.

Worth doing in the same pass, since they are the same session: save a query and confirm the file
appears in the file browser under `saved_queries/`; upload a CSV into that folder and confirm the
Query drawer does not offer it; try to delete the folder and confirm the refusal names saved
queries.

## Found in review, and fixed

- **An unhandled rejection reddened the whole suite.** `ensureSavedQueriesFolder` was called with
  a `.then` and no `.catch`, so a service that breached its never-throw contract became an
  unhandled rejection rather than a logged, non-fatal one — and `gatedSurfaces.test.tsx`'s bare
  `objectExists: vi.fn()` did exactly that from a recipe with nothing to do with saved queries.
  The suite still reported **1950 passed** while exiting **1**, which is how it was missed: a test
  count is not an exit code. Both halves are closed, and a test now pins the REJECTION path, not
  just the failed-`ServiceResult` path.
- **`useQuerySpaces` built a personal space from an empty username.** On the dev-unauth path the
  workspace mounts with no user, so the space's root was the BUCKET root — a marker held open and
  a `saved_queries/` listing there, where SPEC-043's hook was simply disabled. It now returns an
  empty list without a username, with a test.
- **Backing out of the replace confirm discarded the typed name**, returning an empty field on a
  new save; and a non-`Collision` failure on the overwrite path left the confirm on screen. Both
  fixed, and the collision test now models the service (every non-overwrite write collides) rather
  than colliding once and letting the second attempt through.

## Two assertions that are proxied, not literal

- **FR-010's tripwire counts `writeSavedQuery` calls, not `PutObject`s.** The module is mocked at
  the service boundary, per the repo's testing rule, so a new write through a *different* path
  would not trip it. The service-level tests pin the commands separately.
- **FR-002 AC5/AC7 are implied, not performed.** The individual-file delete and the subfolder move
  are tested, and the marker is proven hidden from selection, but no test performs an upload into
  the folder or a select-all-then-delete. Nothing in the app refuses either.

## Notes for SPEC-174/175

`useSavedQueries` already takes a `QuerySpace` and pages S3's listing, so 174 changes the surface
and not the hook. The drawer's Load more is a stopgap for the one thing a display page and an S3
page disagree about — a listing page of 25 keys can hold no `.sql` file at all — and 174 replaces
it with the real pager and the `X–Y of Z+` label the arc describes.
