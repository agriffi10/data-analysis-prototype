# File-browser feature (`apps/portal/src/features/file-browser/`)

Part of the component inventory (`docs/component-inventory.md` is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.


Public barrel: `features/file-browser/index.ts`.

### Services — `fileBrowser.service.ts` (all return `ServiceResult<T>`, never throw)

| Symbol | Purpose |
|---|---|
| `listFiles(bucket, prefix?, continuationToken?)` | Paginated `ListObjectsV2` (folders + files), 1000/page. |
| `getDownloadUrl({ bucket, key, fileName?, expiresInSeconds? })` | Short-lived presigned `GetObject` URL (attachment disposition), capped to credential TTL. |
| `uploadFile({ bucket, key, body, contentType, overwrite?, onProgress?, signal? })` | Managed `lib-storage` upload — single request ≤5 MiB, auto-multipart above; progress + cancel + collision guard. |
| `createFolder({ bucket, prefix, name, overwrite? })` | Zero-byte `{prefix}{name}/` marker (`application/x-directory`). |
| `deleteObject({ bucket, key, username })` | Single-object delete; refuses the prefix marker. |
| `deleteObjects({ bucket, keys, username })` | Batch delete via `DeleteObjects`, chunked ≤1000/req; refuses the marker, aggregates per-key failures (never throws). `ServiceResult<DeleteResult>`. |
| `deleteFolder({ bucket, prefix, username })` | Recursive folder delete: paginated delimiter-less listing → `deleteObjects`. `ServiceResult<DeleteResult>`. |
| `copyObject({ bucket, sourceKey, destKey, username, destBucket?, overwrite? })` | `CopyObject` (URL-encoded CopySource); marker + collision guards. `destBucket` defaults to `bucket` (same-bucket); pass it for a cross-bucket copy, e.g. saving a shared-space result into the user space (SPEC-055). `ServiceResult<{ destKey }>`. |
| `moveObject({ bucket, sourceKey, destKey, username, overwrite? })` | Copy-then-delete-source; same-key no-op; copy-failure leaves source. `ServiceResult<{ destKey }>`. |
| `moveFolder({ bucket, sourcePrefix, destPrefix, username, overwrite?, onProgress? })` | Recursive folder move (per-key copy+delete); partial-failure + into-itself guards + collision pre-check. `ServiceResult<MoveResult>`. |
| `copyFolder({ bucket, sourcePrefix, destPrefix, username, overwrite?, onProgress? })` | Recursive folder copy — `moveFolder` minus the deletes (additive, best-effort, no rollback); into-itself guard + collision pre-check. `ServiceResult<CopyResult>` (SPEC-039). |
| `objectExists({ bucket, key })` | `HeadObject` → bool (404 → `false`, not an error). Collision pre-check. |
| `getObjectMetadata({ bucket, key })` | `HeadObject` → `ObjectMetadata` (size/type/mtime/etag/storage class/custom). 404 → error. |
| `ensurePrefixMarker({ bucket, username })` | Idempotently create the user's `DO_NOT_DELETE.txt` root marker (once/session). |
| `isPrefixMarkerKey(key, username)` | Is this exact key the user's root marker? |
| `validateFolderName(name)` | Client-side folder-name validation → error string \| null. |
| `uploadPercent(loaded, total)` | Clamp loaded/total to a 0–100 whole percent (zero-byte → 100). |

### Hooks

| Symbol | File | Purpose |
|---|---|---|
| `useFileBrowser(bucket, prefix?, markerKey?)` | `useFileBrowser.ts` | Paginated listing via `useInfiniteQuery`; merges/sorts pages, hides the marker. |
| `useFileSpace({username, connections, isLoading, userSpaceBucket, sharedSpaceBucket})` | `useFileSpace.ts` | Active file-browser **space** from `useConnections` + the `?space=` route param → `FileSpaceTarget {id,bucket,rootPrefix,kind,label}`; `selectSpace`/`fellBack`/`dismissFellBack`. Gone/revoked/not-yet-active space reconciles to personal (file-side analogue of `useActiveDatabase`) (SPEC-057). |
| `useFileUpload(bucket, prefix)` | `useFileUpload.ts` | Upload + create-folder orchestration: progress, collision warn-and-confirm, listing invalidation. |
| `useObjectMetadata(bucket, key \| null)` | `useObjectMetadata.ts` | Per-object `HeadObject` metadata via `useQuery`, keyed per object; disabled when key is null. |
| `useDelete(bucket, prefix, username?)` | `useDelete.ts` | Deletes a mixed file/folder selection (files batched, folders recursive); aggregates a `DeleteSummary`, invalidates the listing. Never throws. |
| `useMove(bucket, sourcePrefix, username?)` | `useMove.ts` | Rename (single) + move (multi-select) orchestration; collision warn-and-confirm, folder progress, source/dest invalidation. Aggregates a `MoveSummary`. |
| `useCopy(bucket, sourcePrefix, username?)` | `useCopy.ts` | Copy (multi-select) orchestration; **destination-only** invalidation (additive), collision warn-and-confirm, folder progress, and the same-folder auto-number `{name} (N)` flow (HEAD-checked, editable). Aggregates a `CopySummary` (SPEC-039). |
| `useSelection()` | `selectionContext.ts` | Read/mutate the current view's multi-select set (`toggle`/`selectAll`/`clear`, `count`, `isSelected`). Must be under a `SelectionProvider`. |
| `useUploadQueue()` | `uploadQueueContext.ts` | Read/drive the multi-file upload queue (`items`, `enqueue`, `cancel`, `dismiss`, `resolveOverwrite`, `resolveRename`, `clearFinished`). Must be under an `UploadQueueProvider` (SPEC-020). |

### Components

| Symbol | File | Purpose |
|---|---|---|
| `FileBrowser` | `FileBrowser.tsx` | Top-level browser: breadcrumbs, listing, upload/create-folder (when `writable`). Rows carry only an always-visible Details button (no hover menu). Bulk **Copy / Move / Delete** live in the selection toolbar (SPEC-096); single-item **Download / Rename** live in the details panel (SPEC-097). Read-only rows keep a per-row Download (no toolbar there); double-click a row to download (SPEC-081). |
| `MetadataPanel` | `MetadataPanel.tsx` | File details drawer (close button + Escape): read-only metadata + a **Download** (primary) + **Rename** (secondary, `canModify`) action pair — 50/50 desktop, stacked mobile. Download is internal (presigned URL + in-drawer error); Rename via `onRequestRename` (SPEC-097). |
| `FolderDetailsPanel` | `FolderDetailsPanel.tsx` | Folder details drawer (synchronous, no HeadObject): name/paths + a full-width **Rename** action (`canModify`; folders aren't downloadable) via `onRequestRename` (SPEC-097). |
| `triggerBrowserDownload` | `fileBrowser.download.ts` | Programmatic attachment download of a presigned URL (anchor click). Shared by `FileBrowser` (rows/double-click) + `MetadataPanel` (SPEC-097). |
| `ParentFolderRow` | `ParentFolderRow.tsx` | The `..` parent-folder row — first listing row below the space root (SPEC-098). Non-selectable navigation (whole row is a button → up one level); no checkbox/type-pill/Details. `variant: 'grid'` (≥ tablet table) \| `'mobile'` (56px two-line, SPEC-099). Uses `isAtRoot` / `parentPrefix`. |
| `FileListRowMobile` | `FileListRowMobile.tsx` | Mobile (< tablet) 56px two-line file/folder row (SPEC-099 FR-003) — the structural counterpart to the ≥ tablet table row; same data + handlers. Tap body activates (download file / open folder); trailing size (file) / chevron (folder); Details control; selection checkbox + `accent-soft`/inset-bar selected treatment. |
| `UploadDropzone`, `CreateFolderDialog`, `CollisionPrompt` | (same folder) | Upload picker/drag-drop + progress, folder-name dialog, overwrite/rename prompt. (Used by `FileBrowser`; not barrel-exported.) |
| `SelectionProvider` | `SelectionProvider.tsx` | Multi-select state provider (SPEC-018); clears selection on prefix change. Wrap a view, consume via `useSelection`. |
| `UploadQueueProvider` | `UploadQueueProvider.tsx` | Upload-queue state + concurrency gate (≤`UPLOAD_CONCURRENCY` in flight) calling SPEC-016 `uploadFile`; per-file cancel via `AbortController`, listing invalidation per completion (SPEC-020). Wrap a view, consume via `useUploadQueue`. |
| `UploadQueuePanel` | `UploadQueuePanel.tsx` | Non-blocking floating queue panel — per-file chip/progress/status, cancel/dismiss, inline collision prompt, clear-finished (SPEC-020). Self-hides when empty; must be under `UploadQueueProvider`. |
| `DeleteConfirmDialog` | `DeleteConfirmDialog.tsx` | Modal confirm naming item(s)/count, recursive-folder + irreversible warnings. (Used by `FileBrowser`; not barrel-exported.) |
| `RenameDialog`, `MoveDialog`, `CopyDialog` | (same folder) | Rename modal (validated leaf name); move + copy modals, both shells over `DestinationPicker`. `CopyDialog` adds the same-folder editable-name field (SPEC-039). (Used by `FileBrowser`; not barrel-exported.) |
| `DestinationPicker` | `DestinationPicker.tsx` | Shared destination-folder picker for Move + Copy (extracted from `MoveDialog`, SPEC-039 FR-006): navigable folders within the user's space, excludes operated subtrees + the protected `athenaresults/` folder; `allowCurrentParent` toggles Move (forbidden) vs Copy (same-folder). |
| `OperationSummaryBanner` | `OperationSummaryBanner.tsx` | Result banner for a bulk delete/move/copy — success count + per-item failures; `pastVerb`/`failVerb`/`count`/`errors`. (react-best-practices pass) |
| `BatchOverwritePrompt` | `BatchOverwritePrompt.tsx` | Overwrite-all / Cancel confirmation for a batch whose destination already has matching items; shared by Move + Copy. (react-best-practices pass) |
| `UploadDrawer` | `UploadDrawer.tsx` | Upload slide-over — thin wrapper over the shared `Drawer` (destination hint + larger body spacing). |

### Utils — formatting & paths

| Symbol | File | Purpose |
|---|---|---|
| `formatSize(bytes)` | `fileBrowser.format.ts` | Human-readable file size (B/KB/MB/GB); shared by the listing, metadata panel, upload queue. (Distinct from query's `formatBytes`.) |
| `leafName` / `fileParent` / `folderParts` / `lastSegment` / `fileExtension` | `fileBrowser.paths.ts` | S3 key/prefix path helpers (leaf, parent, folder split, trailing-slash-tolerant last segment, type-chip extension). Shared by `useMove`/`useCopy`/`FileBrowser`/`UploadQueuePanel`. (react-best-practices pass) |

### Query keys, types, constants

| Symbol | File | Purpose |
|---|---|---|
| `fileBrowserKeys.list(bucket, prefix)` / `.metadata(bucket, key)` | `fileBrowserKeys.ts` | Single source of truth for query keys — never hand-build key arrays. |
| `ObjectMetadata`, `DownloadUrl`, `UploadResult`, `CreateFolderResult`, `DeleteResult`, `MoveResult`, `CopyResult` | `fileBrowser.types.ts` | Feature result/data types. |
| `SelectableItem`, `SelectionContextValue`, `itemId` | `selectionContext.ts` | Multi-select item shape (file key \| folder prefix), context value, id helper. |
| `DeleteSummary` | `useDelete.ts` | Aggregated delete outcome (`deletedCount` + per-item `errors`). |
| `MoveSummary` | `useMove.ts` | Aggregated move/rename outcome (`movedCount` + per-item `errors`). |
| `CopySummary` | `useCopy.ts` | Aggregated copy outcome (`copiedCount` + per-item `errors`). |
| `MULTIPART_PART_SIZE`, `MAX_UPLOAD_BYTES`, `PART_CONCURRENCY` | `fileBrowser.types.ts` | Managed-upload tuning constants. |
| `UploadItem`, `UploadStatus`, `UPLOAD_CONCURRENCY`, `TERMINAL_STATUSES` | `upload.types.ts` | Upload-queue item shape, lifecycle status (`queued`→`uploading`→`collision`→`done`/`failed`/`cancelled`), file-concurrency limit (SPEC-020). |
| `prefixMarkerKey(username)`, `PREFIX_MARKER_FILENAME`, `PREFIX_MARKER_BODY` | `fileBrowser.constants.ts` | Prefix-marker (`DO_NOT_DELETE.txt`) helpers. |

