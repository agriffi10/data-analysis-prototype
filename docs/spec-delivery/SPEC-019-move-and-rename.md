# Completed Spec - Move & Rename (files and folders, recursive)

## What was completed from this spec?

Move and rename are now first-class actions in the file browser, implemented as
copy-then-delete (S3 has neither operation). Rename changes an item's leaf name in
place; move relocates items under another folder in the user's own space. Files
and folders are both supported; folder operations are recursive and non-atomic
(a source whose copy fails is left in place and reported). Delivered in two phases.

### Phase 1 — Copy/move service + recursion + collision

**FR-001 — copy/move primitives** (`fileBrowser.service.ts`):
- `copyObject({ bucket, sourceKey, destKey, username, overwrite? })` — `CopyObjectCommand`
  with a per-segment URL-encoded `CopySource` (`buildCopySource`). Marker guard
  (source or destination = the root marker → `ProtectedObject`). Collision guard via
  `objectExists` unless `overwrite` (mirrors SPEC-016 `uploadFile`). Expiry retry via
  `withAuthenticatedClient`.
- `moveObject({ ... })` — `sourceKey === destKey` is a no-op success; marker guard;
  `copyObject` then `deleteObject(source)` **only on copy success** (a failed copy
  leaves the source intact).

**FR-004 — recursive folder move + partial failure:**
- `moveFolder({ bucket, sourcePrefix, destPrefix, username, overwrite?, onProgress? })`
  reuses the SPEC-018 `listAllKeysUnderPrefix` to enumerate every source key, maps
  each to `destPrefix + key.slice(sourcePrefix.length)`, and moves per key via
  `moveObject(overwrite: true)`. A per-key copy failure is recorded and never aborts
  the rest; `onProgress(processed, total)` is emitted. Guards `sourcePrefix === destPrefix`
  (no-op) and `destPrefix.startsWith(sourcePrefix)` (move into own subtree →
  `InvalidDestination`).

**FR-005 — collision (service):** `moveFolder` does a one-shot pre-flight count of
existing destination keys (lists the destination subtree once, intersects) and
returns a `Collision` error naming the count, so the UI can confirm Overwrite-all
once. `copyObject`/`moveObject` use the per-object `Collision` guard.
- New `MoveResult` type.

### Phase 2 — Rename + move UI

**FR-002 / FR-003 / FR-005 (UI):**
- `useMove(bucket, sourcePrefix, username?)` — orchestrates rename (single item) and
  move (single + multi-select), aggregating a `MoveSummary` (`movedCount` + per-item
  `errors`). Rename collisions surface a `RenameCollision` (Overwrite / pick a new
  name, like `useFileUpload`); move collisions surface one `MoveCollision`
  (Overwrite-all / cancel) — collided items did nothing (collision is checked before
  any write), so only they are re-run on overwrite, accumulating with the first pass.
  Invalidates the source prefix (rename) or source + destination prefixes (move) on
  completion. Folder progress mapped to a percent.
- `RenameDialog.tsx` — modal; new name validated with `validateFolderName`
  (same rules as create-folder/upload); Rename disabled until valid and changed;
  Escape cancels.
- `MoveDialog.tsx` — destination-folder picker (a mini browser over `useFileBrowser`),
  breadcrumb-navigable within the user's space. Hides the folders being moved (can't
  descend into them) and disables "Move here" at the current parent or inside a moved
  folder's own subtree.
- `FileBrowser.tsx` — per-row **Rename** action on files and folders; **Move** added
  to the SPEC-018 selection toolbar (selection-driven, like Delete). Renders the
  rename/move dialogs, the rename- and move-collision prompts, a move progress
  indicator, and dismissible move success / partial-failure / error banners. All
  gated on `canModify = writable && !!username`. After a move the selection clears
  and both listings refetch.

## What has changed?

- **No new dependencies, no new env vars, no IaC change.** Same-bucket `CopyObject`
  is authorized by the existing `s3:GetObject` (source) + `s3:PutObject` (destination)
  and delete by `s3:DeleteObject`, all within the user's prefix (SPEC-013).
- **Deviations from the spec's API sketch** (consistent with SPEC-018): the three
  service fns take an extra `username` (marker guard), and `copyObject`/`moveObject`
  take an `overwrite` flag while `moveFolder` adds `overwrite` + `onProgress`
  (collision guard + FR-004 progress) — matching the `uploadFile`/`deleteObjects`
  conventions.
- **Collision UX interpretation:** rename uses the per-item Overwrite/Rename prompt;
  multi-select move uses a single batched **Overwrite-all / Cancel** confirmation
  (rather than per-item prompts) — simpler and still never silently overwrites.
- **`FileBrowser` row signatures:** `FileRow`/`FolderRow` gained an optional
  `onRename`; the selection toolbar gained `onRequestMove` and a unified `isBusy`
  (was `isDeleting`). No other component contracts changed.

## Verification

- **Unit/build**: 225 tests pass (19 files); `lint`, `tsc`, and production `build`
  clean. Coverage:
  - `copyObject` — CopySource encoding, marker-as-source/dest rejection, collision
    refusal, HEAD-404→copy.
  - `moveObject` — copy-then-delete, same-key no-op, copy-failure-leaves-source,
    marker rejection.
  - `moveFolder` — recursive multi-page move (no source left behind), per-key copy
    failure isolation, destination collision pre-check, move-into-itself guard,
    same-prefix no-op, progress.
  - `useMove` — file/folder rename + invalidation, rename collision → overwrite,
    no-username guard; mixed move + dual-prefix invalidation, move collision →
    overwrite-just-collided, per-key folder failure aggregation.
  - `RenameDialog` — prefill/disabled-until-changed, valid submit, invalid-name
    rejection, Escape, busy state.
  - `MoveDialog` — folder listing, move-to-browsed-prefix, disabled at current
    parent, hides moved folders, navigate-and-move.
  - `FileBrowser` — Rename action gating + opens dialog + calls `renameItem`; Move
    toolbar gating + opens picker + calls `moveItems`; move summary + rename-collision
    prompt render.
- **Live signed-in checkpoint** (rename file/folder; move into another folder with
  source emptied; move-into-itself prevented; destination collision prompts; forced
  mid-operation failure leaves the un-copied source): validated against the deployed
  authenticated environment — the move/rename UI and service are authenticated-only
  (a `username` is required, no dev-unauth write path), so the happy path needs an
  interactive sign-in; all UI states and service paths above are unit-covered.

### Follow-ups / notes

- **Non-atomic by design** — no transactional rollback; the summary reports which
  keys succeeded/failed (architecture.md Known Constraints).
- **Drag-and-drop move** and **cross-user/shared-space (Bucket 2) moves** remain out
  of scope.
- SPEC-020 (upload queue) is the last file-ops-arc spec and is independent of this one.

## Later changes

- **Move-dialog folder picker gained a ".." parent row (PR #57).** As delivered, the destination
  picker could only descend into subfolders, so once below the root there was no way back up except
  the breadcrumb — and the **root prefix could not be selected as a move destination** from within
  a subfolder. A ".." parent-folder row (the entry the SPEC-026 dialog design specified but that was
  never implemented) now appears whenever the browse prefix is below the navigation floor and climbs
  one level, clamped to the user's own-space root. A `MoveDialog` test covering descend → ".." →
  move-to-root was added.
