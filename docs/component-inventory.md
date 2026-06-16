# Component Inventory

A flat, always-cheap lookup of the **reusable** building blocks already in the app,
so a new spec can find what to reuse without re-reading every delivery doc.

**Keep it current:** when a spec adds a reusable service / hook / component / type /
utility, add a one-line row here (session-start checklist step 9d in `CLAUDE.md`).
This lists the *public surface* — the code is the source of truth; verify signatures
before relying on them. Paths are relative to the repo root.

> Convention reminders (see `CLAUDE.md`): services return `ServiceResult<T>` and never
> throw; all S3 calls go through service files; clients are instantiated in `src/lib/`,
> never in components; server state goes through TanStack Query.

---

## Foundations (`apps/portal/src/lib/`)

| Symbol | File | Purpose |
|---|---|---|
| `getS3Client(forceRefresh?)` | `lib/s3Client.ts` | Authenticated S3 client from Amplify/Identity-Pool creds; `ServiceResult<S3Client>`. Pass `true` to force a credential refresh on expiry. |
| `s3Client` | `lib/s3Client.ts` | Dev-only unsigned/static-cred S3 client singleton (SPEC-002 dev-unauth path). |
| `queryClient` | `lib/queryClient.ts` | App-wide TanStack `QueryClient` (staleTime 30s, retry 1, no refetch-on-focus). |
| `invalidateListing(client, bucket, prefix)` | `lib/queryClient.ts` | Invalidate one prefix listing so the next read refetches (call after a mutation). |
| `isAmplifyConfigured` | `lib/amplify.ts` | Boolean — whether Cognito/Amplify env is configured. |
| `setReturnPath(path)` / `takeReturnPath()` | `lib/returnPath.ts` | Stash + consume a post-login return path. |

## Shared types (`apps/portal/src/types/`)

| Symbol | File | Purpose |
|---|---|---|
| `ServiceResult<T>` | `types/service.types.ts` | The canonical discriminated-union result for every service fn (success/data \| error). |
| `S3FileItem`, `S3FolderItem`, `S3Item` | `types/s3.types.ts` | Listing row shapes. |
| `FileList`, `FileListPage` | `types/s3.types.ts` | Listing + one paginated page (with `isTruncated`/`nextContinuationToken`). |

## Shared components (`apps/portal/src/components/`)

| Symbol | File | Purpose |
|---|---|---|
| `RootLayout` | `components/RootLayout.tsx` | Top-level route layout. |
| `ProtectedLayout` | `components/ProtectedLayout.tsx` | Auth-gated layout wrapper (redirects unauthenticated users). |
| `Header` | `components/Header.tsx` | App header (sign-in/out, identity). |
| `Button` (+ `ButtonVariant`/`ButtonSize`) | `components/Button.tsx` | Design-system button — `variant` primary/default/ghost/danger, `size` sm/md/lg, `forwardRef` (SPEC-028; `lg` added SPEC-029). |
| `IconButton` | `components/IconButton.tsx` | Ghost icon-only button; `label` → aria-label, `forwardRef` (SPEC-028). |
| `Input` | `components/Input.tsx` | Text input with `label` + `error` state, aria wiring, `forwardRef` (SPEC-028). |
| `Badge` | `components/Badge.tsx` | Neutral type pill (file/folder labels) (SPEC-028). |
| `Banner` (+ `BannerVariant`) | `components/Banner.tsx` | Dismissible status banner — success/warning/danger/info, optional `title`/`onDismiss` (SPEC-028). |
| `BrandMark` | `components/BrandMark.tsx` | Accent-square upload-arrow icon + wordmark; `size` sm/md, `showWordmark` (SPEC-028; used by Header + LandingPage). |

## UI primitive utility (`apps/portal/src/lib/`)

| Symbol | File | Purpose |
|---|---|---|
| `cx(...args)` | `lib/cx.ts` | Class-name join helper (filters falsy); used by all SPEC-028 primitives. No external dep. |

## Auth feature (`apps/portal/src/features/auth/`)

| Symbol | File | Purpose |
|---|---|---|
| `useAuth()` | `features/auth/useAuth.ts` | Access auth status + user + sign-in/out actions. |
| `AuthProvider` | `features/auth/AuthProvider.tsx` | Context provider wiring Amplify auth state. |
| `getCurrentAuthUser()` | `features/auth/auth.service.ts` | Current user as `ServiceResult<AuthUser>`. |
| `startSignIn()` / `startSignUp()` / `startSignOut()` | `features/auth/auth.service.ts` | Hosted-UI auth flows (`ServiceResult`). |
| `AuthStatus`, `AuthUser`, `AuthContextValue` | `features/auth/auth.types.ts` | Auth types. |

## File-browser feature (`apps/portal/src/features/file-browser/`)

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
| `copyObject({ bucket, sourceKey, destKey, username, overwrite? })` | Same-bucket `CopyObject` (URL-encoded CopySource); marker + collision guards. `ServiceResult<{ destKey }>`. |
| `moveObject({ bucket, sourceKey, destKey, username, overwrite? })` | Copy-then-delete-source; same-key no-op; copy-failure leaves source. `ServiceResult<{ destKey }>`. |
| `moveFolder({ bucket, sourcePrefix, destPrefix, username, overwrite?, onProgress? })` | Recursive folder move (per-key copy+delete); partial-failure + into-itself guards + collision pre-check. `ServiceResult<MoveResult>`. |
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
| `useFileUpload(bucket, prefix)` | `useFileUpload.ts` | Upload + create-folder orchestration: progress, collision warn-and-confirm, listing invalidation. |
| `useObjectMetadata(bucket, key \| null)` | `useObjectMetadata.ts` | Per-object `HeadObject` metadata via `useQuery`, keyed per object; disabled when key is null. |
| `useDelete(bucket, prefix, username?)` | `useDelete.ts` | Deletes a mixed file/folder selection (files batched, folders recursive); aggregates a `DeleteSummary`, invalidates the listing. Never throws. |
| `useMove(bucket, sourcePrefix, username?)` | `useMove.ts` | Rename (single) + move (multi-select) orchestration; collision warn-and-confirm, folder progress, source/dest invalidation. Aggregates a `MoveSummary`. |
| `useSelection()` | `selectionContext.ts` | Read/mutate the current view's multi-select set (`toggle`/`selectAll`/`clear`, `count`, `isSelected`). Must be under a `SelectionProvider`. |

### Components

| Symbol | File | Purpose |
|---|---|---|
| `FileBrowser` | `FileBrowser.tsx` | Top-level browser: breadcrumbs, listing, download, upload/create-folder (when `writable`), Details. |
| `MetadataPanel` | `MetadataPanel.tsx` | Read-only, non-blocking metadata drawer (close button + Escape). |
| `UploadDropzone`, `CreateFolderDialog`, `CollisionPrompt` | (same folder) | Upload picker/drag-drop + progress, folder-name dialog, overwrite/rename prompt. (Used by `FileBrowser`; not barrel-exported.) |
| `SelectionProvider` | `SelectionProvider.tsx` | Multi-select state provider (SPEC-018); clears selection on prefix change. Wrap a view, consume via `useSelection`. |
| `DeleteConfirmDialog` | `DeleteConfirmDialog.tsx` | Modal confirm naming item(s)/count, recursive-folder + irreversible warnings. (Used by `FileBrowser`; not barrel-exported.) |
| `RenameDialog`, `MoveDialog` | (same folder) | Rename modal (validated leaf name) + move destination-folder picker. (Used by `FileBrowser`; not barrel-exported.) |

### Query keys, types, constants

| Symbol | File | Purpose |
|---|---|---|
| `fileBrowserKeys.list(bucket, prefix)` / `.metadata(bucket, key)` | `fileBrowserKeys.ts` | Single source of truth for query keys — never hand-build key arrays. |
| `ObjectMetadata`, `DownloadUrl`, `UploadResult`, `CreateFolderResult`, `DeleteResult`, `MoveResult` | `fileBrowser.types.ts` | Feature result/data types. |
| `SelectableItem`, `SelectionContextValue`, `itemId` | `selectionContext.ts` | Multi-select item shape (file key \| folder prefix), context value, id helper. |
| `DeleteSummary` | `useDelete.ts` | Aggregated delete outcome (`deletedCount` + per-item `errors`). |
| `MoveSummary` | `useMove.ts` | Aggregated move/rename outcome (`movedCount` + per-item `errors`). |
| `MULTIPART_PART_SIZE`, `MAX_UPLOAD_BYTES`, `PART_CONCURRENCY` | `fileBrowser.types.ts` | Managed-upload tuning constants. |
| `prefixMarkerKey(username)`, `PREFIX_MARKER_FILENAME`, `PREFIX_MARKER_BODY` | `fileBrowser.constants.ts` | Prefix-marker (`DO_NOT_DELETE.txt`) helpers. |
