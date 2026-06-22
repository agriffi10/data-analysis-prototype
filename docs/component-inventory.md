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
| `getAthenaClient(forceRefresh?)` / `getGlueClient(forceRefresh?)` | `lib/athenaClient.ts` / `lib/glueClient.ts` | Authenticated Athena/Glue clients from the same scoped Identity-Pool creds (SPEC-034); `ServiceResult<...Client>`. |
| `getSessionCredentials(forceRefresh?)` | `lib/awsCredentials.ts` | Fetch the signed-in user's scoped Identity-Pool credentials; shared by the Athena/Glue client builders (SPEC-034). |
| `withCredentialRetry(getClient, op)` / `isExpiryError(code?)` | `lib/credentialRetry.ts` | Run an authenticated op with one transparent refresh-and-retry on credential-expiry; shared by the S3/Athena/Glue services (SPEC-034). |
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
| `Sidebar` | `components/Sidebar.tsx` | Left nav for the authenticated shell — "My Files" user-space entry (shared-connections omitted until built). Rendered by `ProtectedLayout`. |
| `Button` (+ `ButtonVariant`/`ButtonSize`) | `components/Button.tsx` | Design-system button — `variant` primary/default/ghost/danger, `size` sm/md/lg, `forwardRef` (SPEC-028; `lg` added SPEC-029). |
| `IconButton` | `components/IconButton.tsx` | Ghost icon-only button; `label` → aria-label, `forwardRef` (SPEC-028). |
| `Input` | `components/Input.tsx` | Text input with `label` + `error` state, aria wiring, `forwardRef` (SPEC-028). |
| `Badge` | `components/Badge.tsx` | Neutral type pill (file/folder labels) (SPEC-028). |
| `Banner` (+ `BannerVariant`) | `components/Banner.tsx` | Dismissible status banner — success/warning/danger/info, optional `title`/`onDismiss` (SPEC-028). |
| `BrandMark` | `components/BrandMark.tsx` | Accent-square upload-arrow icon + wordmark; `size` sm/md, `showWordmark` (SPEC-028; used by Header + LandingPage). |
| `PrimaryNav` | `components/PrimaryNav.tsx` | Topbar Files \| Query underline tabs (`NavLink`-driven); rendered by `Header` only when authenticated (SPEC-035). |
| `Modal` | `components/Modal.tsx` | Centered modal shell (SPEC-026 pattern): scrim + surface card + role/aria + backdrop-dismiss + Escape (`useEscapeKey`); `dismissible` locks it during in-flight actions; `className` replaces the default `max-w-md`. Children supply body + footer. (react-best-practices pass) |
| `ConfirmDialog` | `components/ConfirmDialog.tsx` | Warn-and-confirm dialog over `Modal`: title (+ optional danger icon `tone`), body `children`, optional `irreversible` line, `confirmVariant`, `busy`/`busyLabel`, `dismissOnly` (single-button info), focus defaults to Cancel. Used by Clear/CloseTab/DropTable/TabLimit/delete-confirm/overwrite-confirm. (react-best-practices pass) |
| `Drawer` | `components/Drawer.tsx` | Right slide-over (SPEC-036): scrim + 440px panel + header (title, `headerAccessory`, close button) + scrollable body + optional `footer`; `closeOnEscape` yields Escape to a nested dialog. Used by history / saved-queries / upload drawers. (react-best-practices pass) |
| `Pager` | `components/Pager.tsx` | Prev / range-label / Next pager (SPEC-038 styling), `nextBusy` "Loading…" state. Shared by the query-results table + history drawer. (react-best-practices pass) |
| `LoadingState` | `components/LoadingState.tsx` | Centered `role="status"` "Loading…" indicator (route Suspense fallback + auth gate). (react-best-practices pass) |
| `FolderIcon` / `UploadIcon` / `DocumentIcon` | `components/icons.tsx` | Shared inline SVG icons (no icon lib); `className` for size/color; `FolderIcon` takes `filled`. (react-best-practices pass) |

## Shared hooks (`apps/portal/src/hooks/`)

| Symbol | File | Purpose |
|---|---|---|
| `useEscapeKey(onEscape, enabled?)` | `hooks/useEscapeKey.ts` | Calls `onEscape` on Escape while `enabled`; the keydown-listener Effect consolidated from every modal/drawer. (react-best-practices pass) |
| `usePageTitle(page)` | `hooks/usePageTitle.ts` | Syncs `document.title` for the page (SPEC-031). |

## UI primitive utility (`apps/portal/src/lib/`)

| Symbol | File | Purpose |
|---|---|---|
| `cx(...args)` | `lib/cx.ts` | Class-name join helper (filters falsy); used by all SPEC-028 primitives. No external dep. |
| `formatPageTitle(page?)` | `lib/formatPageTitle.ts` | Pure title formatter → `"{page} — S3 File Portal"` or the app name alone (SPEC-031). |
| `usePageTitle(page?)` | `hooks/usePageTitle.ts` | Sets `document.title` via `formatPageTitle`; call at the top of a page (SPEC-031). |

## Test utilities (`apps/portal/src/test/`)

| Symbol | File | Purpose |
|---|---|---|
| `expectNoA11yViolations(ui, axeOptions?)` + `ROUTE_AXE_OPTIONS` / `COMPONENT_AXE_OPTIONS` / `WCAG_TAGS` | `test/axe.ts` | Render a node and assert no `axe-core` violations; one centrally-defined WCAG A/AA config (`color-contrast` off — jsdom). Route preset enables landmark/heading/region rules; component preset disables `region`. Co-locate `*.a11y.test.tsx` checks; `npm run test:a11y` runs only those (SPEC-045). |

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
| `FileBrowser` | `FileBrowser.tsx` | Top-level browser: breadcrumbs, listing, upload/create-folder (when `writable`). Rows carry only an always-visible Details button (no hover menu); bulk/single actions (download/copy/move/rename/delete) live in the selection toolbar. Read-only rows keep a Download button (no toolbar there). |
| `MetadataPanel` | `MetadataPanel.tsx` | Read-only, non-blocking metadata drawer (close button + Escape). |
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

## Query feature (`apps/portal/src/features/query/`)

Public barrel: `features/query/index.ts`. Data layer for the Athena query workspace (SPEC-034); **no UI** (SPEC-035/036 build it). All services return `ServiceResult<T>`, never throw.

### Services

| Symbol | File | Purpose |
|---|---|---|
| `runQuery({ sql, database, username })` | `query.service.ts` | `StartQueryExecution` against the shared workgroup, results → the caller's own `{username}/athenaresults/`. Type-agnostic (SELECT + DDL). `ServiceResult<{ queryExecutionId }>`. |
| `getQueryStatus(id)` | `query.service.ts` | `GetQueryExecution` → `QueryStatus` (state/reason/stats/outputLocation). |
| `getQueryResults({ queryExecutionId, nextToken?, maxRows? })` | `query.service.ts` | `GetQueryResults` → typed `QueryResultPage` (first-page header row stripped; paginates via `nextToken`). DDL → empty page. |
| `getResultCsvUrl({ queryExecutionId, outputLocation })` | `query.service.ts` | Presigned CSV download of the raw result object (reuses `getDownloadUrl`). `ServiceResult<DownloadUrl>`. |
| `stopQuery(id)` | `query.service.ts` | `StopQueryExecution` → CANCELLED. |
| `isTerminalState(state)` | `query.service.ts` | Is a `QueryState` terminal (SUCCEEDED/FAILED/CANCELLED)? |
| `getDatabase(name)` / `listTables(name)` | `glue.service.ts` | The user's own Glue DB + its tables/columns (paginated). Missing DB → `NotFound` / empty list, never thrown. |
| `getQueryHistory(username)` / `appendQueryHistory(username, entry)` / `updateQueryHistoryEntry(username, id, patch)` | `queryHistory.service.ts` | Per-user history JSON at `{username}/user_settings/query-history.json` — read (missing/corrupt → empty), prepend+cap, in-place update. PutObject-only (no delete); read-only to the user. |

### Hooks, keys, types, constants

| Symbol | File | Purpose |
|---|---|---|
| `useQueryExecution(id \| null)` | `useQueryExecution.ts` | Polls `getQueryStatus` via `refetchInterval` until terminal or `MAX_POLL_DURATION_MS`; disabled when null. |
| `useQueryResults(id \| null, maxRows?)` | `useQueryResults.ts` | Prev/Next pager over results via `useInfiniteQuery` (20 rows/page, SPEC-038): exposes the current page's `columns`/`rows`, `pageIndex`/range, `hasPrev`/`hasNext`, `goPrev`/`goNext` (Next fetches forward, Prev from cache), and loaded/total counts. |
| `useSchema(db \| null)` + `invalidateSchema(client, db)` | `useSchema.ts` | DB + tables for the schema browser; invalidation helper to refresh after DDL. |
| `useQueryHistory(username \| null)` | `useQueryHistory.ts` | History list + `appendEntry`/`updateEntry` mutations (cache-seeding). |
| `getSavedQueries` / `upsertSavedQuery` / `removeSavedQuery` | `savedQueries.service.ts` | Per-user saved-queries JSON store at `{username}/user_settings/saved-queries.json`; PutObject overwrite only (remove rewrites, never an S3 delete), missing-file → empty store, `ServiceResult` (SPEC-043). |
| `useSavedQueries(username \| null)` | `useSavedQueries.ts` | Saved-queries list + `upsert`/`remove` mutations (cache-seeding), `queryKeys.savedQueries` (SPEC-043). |

### Workspace UI (SPEC-035)

| Symbol | File | Purpose |
|---|---|---|
| `QueryWorkspace` | `QueryWorkspace.tsx` | Top-level `/query` composition: schema rail + toolbar + editor + status + results, wired to the SPEC-034 layer. Rendered by the lazy `QueryPage` route. |
| `SqlEditor` (+ `SqlEditorHandle`) | `SqlEditor.tsx` | Lazy, self-hosted Monaco SQL editor; `value`/`onChange`/`onRun` (⌘⏎), ref exposes `insertAtCursor`. |
| `SchemaBrowser` | `SchemaBrowser.tsx` | Left rail: switchable **Database** list (SPEC-047 `connections`/`onSelectDatabase`, active via `aria-current`) + expandable tables/columns via `useSchema(activeDatabase)`; click-to-insert; loading/empty/setting-up/error states. |
| `QueryStatusBar` | `QueryStatusBar.tsx` | Slim live-region execution status (running/succeeded/failed/cancelled) + Download CSV. |
| `QueryResultsTable` | `QueryResultsTable.tsx` | File-table-styled results (dynamic columns + type, horizontal scroll, empty/loading state); shows one page at a time with a Prev/Next pager + "Rows X–Y" indicator (replace, not append — SPEC-038). |
| `QueryHistoryPanel` | `QueryHistoryPanel.tsx` | Right slide-over drawer listing per-user history (`useQueryHistory`); read-only, view/Open/Re-run; empty/loading/error states (SPEC-036). Client-side Prev/Next pager, 7/page newest-first, `"1–7 of N"`, reset-to-newest on open/append (SPEC-042). Header **Refresh** control re-reads from S3 (`useQueryHistory.refresh`/`isRefreshing`); reset-to-newest on success, non-destructive on error (SPEC-046). |
| `QueryHistoryRow` | `QueryHistoryRow.tsx` | One history entry: status badge, relative time, SQL preview, stats, Open/Re-run (SPEC-036). |
| `ClearQueryDialog` | `ClearQueryDialog.tsx` | Warn-and-confirm modal for the Clear-query action (SPEC-026 pattern; `alertdialog`, Escape/backdrop cancel, no undo) (SPEC-040; scoped to the active tab under SPEC-041). |
| `readTabsState` / `writeTabsState` / `initialTabsState` / `migrateDraftToTabs` | `queryTabs.ts` | Per-user `sessionStorage` wrapper for the multi-tab editor state (`s3portal.query.tabs.{username}`); structural validation (corrupt → null), error-swallowing, empty-username no-op, one-time SPEC-040 draft migration (SPEC-041; supersedes the removed `queryDraft.ts`). |
| `useConnections(username)` | `useConnections.ts` | **The** source of databases the user can query (`Connection[]`); personal-only today, the SPEC-052 extension point for shared connections (consumers unchanged) (SPEC-047). |
| `useActiveDatabase(username, connections)` | `useActiveDatabase.ts` | Workspace-global active DB, per-user `sessionStorage` (`s3portal.query.activeDatabase.{username}`), default = personal; pure-render reconcile → personal + dismissible `fellBack` when a stored DB is gone (SPEC-047). |
| `Connection` / `ConnectionKind` | `query.types.ts` | `{id,label,database,kind:'personal'\|'shared'}` — a targetable database (SPEC-047). |
| `useQueryTabs(username)` | `useQueryTabs.ts` | Owns `QueryTabsState` + persistence; `openTab({label?,sql?,savedQueryId?})` (returns id or **null at `QUERY_TABS_MAX`**; named tabs skip the `Query N` counter), monotonic labelling, `closeTab` (≥1-tab + adjacent-activate), `setActiveSql`/`setActiveTab`/`setActiveSavedQueryId`/`clearActive` (SPEC-041). |
| `QueryTabStrip` | `QueryTabStrip.tsx` | Card-tab strip above the editor: active = surface+border+accent dot, per-tab `×` (hidden when solo), always-enabled `+` (SPEC-041 §6). |
| `TabLimitDialog` / `CloseTabDialog` | `TabLimitDialog.tsx` / `CloseTabDialog.tsx` | FR-008 "close a tab first" alert; FR-005 warn-and-confirm before closing a non-empty tab (both SPEC-026 pattern) (SPEC-041). |
| `SavedQueriesPanel` | `SavedQueriesPanel.tsx` | Right drawer (mirrors history) listing saved queries (most-recently-updated first) with Open + Delete-with-confirm; presentational (workspace owns the data) (SPEC-043). |
| `SaveQueryDialog` | `SaveQueryDialog.tsx` | Name-prompt modal with an inline overwrite-confirm step on a name collision; pre-filled on re-save (SPEC-043). |
| `SavedQuery`, `SavedQueriesStore` | `query.types.ts` | Saved-query record + store types; `QueryHistoryEntry` also gained optional `savedQueryId`/`savedQueryName` (SPEC-043). |
| `TableActionsMenu` | `TableActionsMenu.tsx` | **Reusable** kebab (⋮) + accessible popover menu (the app's first menu primitive): `aria-haspopup`/`expanded`, focus-in, Escape/outside-click close, arrow-key nav, danger items + separators (SPEC-044). |
| `Toast` (+ `ToastState`) | `Toast.tsx` | **Reusable** minimal transient toast (success/danger auto-dismiss; `info` persists), accessible live region, fixed bottom-right (SPEC-044). |
| `DropTableDialog` | `DropTableDialog.tsx` | DROP TABLE warn-and-confirm (SPEC-026 alertdialog, danger, in-flight lock) (SPEC-044). |
| `getTableDdl` / `runStatementToCompletion` | `query.service.ts` | `SHOW CREATE TABLE` → assembled DDL; run-and-poll-to-terminal helper for background statements (View DDL, Drop) (SPEC-044). |
| `QueryTab`, `QueryTabsState`, `QUERY_TABS_MAX`, `DEFAULT_SQL` | `query.types.ts` / `query.constants.ts` | Tab data types, the soft tab cap, and the shared first-tab boilerplate (SPEC-041). |
| `formatBytes` / `formatDurationMs` / `formatRelativeTime` | `query.format.ts` | Display formatters for scanned-bytes / duration / relative timestamps. |
| `queryKeys` | `queryKeys.ts` | Key factory (`schema`/`execution`/`results`/`history`) — never hand-build keys. |
| `QueryState`, `QueryStatus`, `QueryColumn`, `QueryResultPage`, `GlueColumn`, `GlueTableSummary`, `QueryHistoryEntry`, `QueryHistory` | `query.types.ts` | Feature data types. |
| `POLL_INTERVAL_MS`, `MAX_POLL_DURATION_MS`, `DEFAULT_MAX_ROWS`, `QUERY_HISTORY_MAX` | `query.constants.ts` | Polling cadence/guard, default page size, history cap. |
