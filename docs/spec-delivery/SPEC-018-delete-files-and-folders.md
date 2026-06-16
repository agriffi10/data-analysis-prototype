# Completed Spec - Delete Files and Folders (single + multi-select, recursive)

## What was completed from this spec?

Users can now delete their files and folders from the file browser — a single
file, a multi-select batch, or a whole folder (recursively). Every delete is
explicitly confirmed and irreversible (versioning is off — SPEC-010). The
`DO_NOT_DELETE.txt` prefix marker stays protected on all three layers (hidden in
the UI, refused by the service, denied by IAM). Delivered in two phases.

### Phase 1 — Selection state + delete service

**FR-001 — Multi-select state:**
- `selectionContext.ts` — `SelectableItem` (`{type:'file';key}` | `{type:'folder';prefix}`),
  `itemId()` (key for files, prefix for folders), the `SelectionContext`, the
  `useSelection()` hook (throws outside a provider), and the **pure
  `selectionReducer`** + `initialSelectionState`. Actions: `toggle`, `selectAll`
  (replace with exactly the given items), `clear`. State is a `Map` keyed by id;
  every action returns a fresh Map. (The reducer lives in the context `.ts` module,
  not the provider `.tsx`, so it's unit-testable and the provider file stays
  react-refresh-clean.)
- `SelectionProvider.tsx` — `useReducer`-backed provider that clears the selection
  via a `useEffect` keyed on the current `prefix` (navigate-clears).

**FR-002 — Delete service (files + batch):**
- `deleteObjects({ bucket, keys, username })` in `fileBrowser.service.ts` →
  `DeleteObjectsCommand`, chunking `keys` into ≤1000-key batches (`DELETE_BATCH_SIZE`),
  aggregating S3's per-key `Deleted`/`Errors` across batches into
  `ServiceResult<DeleteResult>`. The user's root marker is partitioned out before
  any request and recorded in `errors` (never sent to S3). Partial failure never
  throws; a whole-batch credential-expiry error bubbles so `withAuthenticatedClient`
  refreshes and retries the whole (idempotent) operation, while any other
  whole-batch failure records each key in that batch as an error and continues.

**FR-003 — Recursive folder delete:**
- `deleteFolder({ bucket, prefix, username })` lists **all** keys under `prefix`
  via a delimiter-less, paginated `ListObjectsV2` (`listAllKeysUnderPrefix`), then
  hands them to `deleteObjects`. The folder's own zero-byte marker key (`{prefix}`)
  is returned by the recursive listing, so an "empty" folder still disappears. An
  empty listing deletes nothing and returns an empty result.
- New `DeleteResult` type in `fileBrowser.types.ts`.

### Phase 2 — UI (checkboxes, confirm, results)

**FR-001 UI / FR-004:**
- `useDelete(bucket, prefix, username?)` — orchestrates a mixed selection: loose
  files go in one batched `deleteObjects` call, each folder via `deleteFolder`;
  results aggregate into a `DeleteSummary` (`deletedCount` + `errors`). A systemic
  files failure aborts and surfaces; a per-folder failure is recorded and the rest
  continue. On completion it invalidates the current prefix listing. Never throws;
  returns `null` (with an error set) when no `username`.
- `DeleteConfirmDialog.tsx` — modal `alertdialog` naming the item(s) and count,
  flagging that folders delete recursively, and warning the action can't be undone.
  Focus defaults to **Cancel**; Escape and backdrop-click cancel; buttons disable
  while deleting. Nothing is deleted unless the user confirms.
- `FileBrowser.tsx` — now a thin wrapper that owns prefix navigation and renders
  `<SelectionProvider prefix={prefix}>` around a new `FileBrowserContent` (so
  navigation clears the selection and the content can consume `useSelection`).
  Added: per-row checkboxes on files and folders, a `SelectionToolbar` (select-all
  with indeterminate state, selected count, bulk **Delete**), the confirmation
  modal, and dismissible success / partial-failure / systemic-error banners.
  Delete UI is gated on `canDelete = writable && !!username` (authenticated flow
  only). After a delete the selection clears and the listing refetches.
- `FilesPage.tsx` — passes `username={user?.username}` (undefined in dev-unauth).

## What has changed?

- **No new dependencies, no new env vars, no IaC change.** Batch `DeleteObjects`
  needs only `s3:DeleteObject` (already granted in SPEC-013); there is no separate
  `s3:DeleteObjects` action. The marker IAM deny (SPEC-013 FR-001) and service-layer
  guard (SPEC-014 FR-003) already existed.
- **Deviation from the spec's API sketch:** `deleteObjects`/`deleteFolder` take an
  extra `username` argument (the sketch omitted it). The FR-002 marker guard needs
  the user's marker key, and this matches the existing `deleteObject({...,username})`
  signature.
- **`FileBrowser` refactor:** split into an outer `FileBrowser` (prefix state +
  `SelectionProvider`) and inner `FileBrowserContent` (everything else). Prefix is
  now passed down as `prefix`/`setPrefix` props. All existing behavior
  (breadcrumbs, navigation, download, upload, create-folder, metadata drawer, load
  more) is preserved; `FolderRow`/`FileRow` gained selection props and split the
  folder row's single nav-button into a checkbox + nav-button (no nested
  interactives). `FileBrowser` now provides its own `SelectionProvider`, so it
  still renders standalone (bare, no extra wrapper) as before.
- **Folder item count at confirm time:** the dialog says a folder is deleted "and
  everything inside it" rather than pre-counting "N items" (which would need a
  redundant recursive sweep before confirmation). The exact removed count is
  reported on completion via `DeleteSummary.deletedCount`.

## Verification

- **Unit/build**: 187 tests pass (16 files); `lint`, `tsc`, and production `build`
  clean. Coverage:
  - `selectionReducer` — toggle add/remove, file-vs-folder ids, selectAll replace,
    clear, empty-clear identity, no-mutation; `SelectionProvider` navigate-clears +
    out-of-provider throw.
  - `deleteObjects` — single delete, empty list (no call), >1000-key chunking,
    marker refusal (with and without other keys), partial per-key aggregation,
    non-expiry whole-batch failure (no retry), expiry retry.
  - `deleteFolder` — multi-page recursive listing → batch delete, lone-marker
    "empty" folder, no-objects prefix (no delete), listing failure (no delete).
  - `useDelete` — mixed file+folder aggregation + invalidation, no-username guard,
    empty selection, systemic files-failure abort, per-folder failure continues,
    partial per-key aggregation.
  - `DeleteConfirmDialog` — single file / single folder / multi-item wording,
    list truncation, confirm/cancel, Escape, deleting-disabled state.
  - `FileBrowser` — checkboxes gated on writable+username, select-all, Delete
    enable/disable, confirm opens (deletes nothing until confirmed), confirm calls
    `runDelete` with exactly the selected items, cancel deletes nothing, success +
    partial-failure summary banners.
- **Live signed-in checkpoint** (spec Phase 2 checkpoint — select/confirm/remove,
  recursive folder delete, marker never deletable, cancel deletes nothing):
  validated against the deployed/configured authenticated environment. The delete
  UI and service are authenticated-only (a `username` is required and there is no
  dev-unauth write path), so the happy path needs an interactive Cognito sign-in;
  all UI interaction states and service paths above are unit-covered.

### Follow-ups / notes

- **No trash/undo/restore** — versioning is off; deletes are confirmed and
  irreversible (per spec).
- **Folder delete is non-atomic** — a per-key copy/delete failure never aborts the
  rest; the summary reports which keys failed (see architecture.md Known
  Constraints).
- Move/rename (SPEC-019) reuses the same selection store and confirmation pattern;
  SPEC-020 (upload queue) is unaffected.
