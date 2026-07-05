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
| `getSessionCredentials(forceRefresh?)` / `getIdToken(forceRefresh?)` | `lib/awsCredentials.ts` | Fetch the signed-in user's scoped Identity-Pool credentials (shared by the Athena/Glue/SQS client builders, SPEC-034); `getIdToken` returns the Cognito ID token JWT for server-side trusted-actor binding (SPEC-051/056). |
| `getSqsClient(forceRefresh?)` | `lib/sqsClient.ts` | Authenticated SQS client from Identity-Pool creds; `ServiceResult<SQSClient>`. The browser's only shared-space write is `sqs:SendMessage` to the control queue (SPEC-051). |
| `withCredentialRetry(getClient, op)` / `isExpiryError(code?)` | `lib/credentialRetry.ts` | Run an authenticated op with one transparent refresh-and-retry on credential-expiry; shared by the S3/Athena/Glue/SQS services (SPEC-034). |
| `queryClient` | `lib/queryClient.ts` | App-wide TanStack `QueryClient` (staleTime 30s, retry 1, no refetch-on-focus). |
| `invalidateListing(client, bucket, prefix)` | `lib/queryClient.ts` | Invalidate one prefix listing so the next read refetches (call after a mutation). |
| `isAmplifyConfigured` | `lib/amplify.ts` | Boolean — whether Cognito/Amplify env is configured. |
| `setReturnPath(path)` / `setReturnPathIfAbsent(path)` / `takeReturnPath()` | `lib/returnPath.ts` | Stash (always / only-if-empty) + consume a post-login return path. `IfAbsent` seeds a default (e.g. `/files`) at sign-in/up without clobbering an auth-gate-captured path. |
| `useCopyToClipboard(resetMs?)` | `lib/useCopyToClipboard.ts` | `{copied, copy(text)}` — writes to the clipboard and flags a transient confirm; never throws (insecure-context/denied = silent no-op). |

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
| `Sidebar` | `components/Sidebar.tsx` | Left nav for the authenticated shell — a **Spaces** list (`{connections, activeSpaceId, onSelectSpace}`): personal first, active shared A–Z, pending/failed disabled with status; "Manage connections →" link. Rendered by `FilesPage` (SPEC-057). Renders through `CollapsibleRail` (SPEC-085). |
| `CollapsibleRail` | `components/CollapsibleRail.tsx` | Shared 248px left-rail chrome (`{ariaLabel, title?, children}`) for the Files `Sidebar` + Query `SchemaBrowser`: `hidden … md:flex` panel + header collapse control + a reopen handle when collapsed; collapse = `display:none` (panel kept mounted so in-rail state + `aria-controls` survive). Collapse state via `useRailCollapsed` (SPEC-085). |
| `useRailCollapsed()` | `components/useRailCollapsed.ts` | `localStorage`-backed rail collapse state under one shared key (`RAIL_COLLAPSED_STORAGE_KEY`) so it carries across both rails; `{collapsed, toggle, setCollapsed}`; guarded access → default expanded when storage is unavailable (SPEC-085). |
| `Button` (+ `ButtonVariant`/`ButtonSize`) | `components/Button.tsx` | Design-system button — `variant` primary/default/ghost/danger, `size` sm/md/lg, `forwardRef` (SPEC-028; `lg` added SPEC-029). |
| `IconButton` | `components/IconButton.tsx` | Ghost icon-only button; `label` → aria-label, `forwardRef` (SPEC-028). |
| `Input` | `components/Input.tsx` | Text input with `label` + `error` state, aria wiring, `forwardRef` (SPEC-028). |
| `Badge` | `components/Badge.tsx` | Neutral type pill (file/folder labels) (SPEC-028). |
| `Banner` (+ `BannerVariant`) | `components/Banner.tsx` | Dismissible status banner — success/warning/danger/info, optional `title`/`onDismiss` (SPEC-028). |
| `BrandMark` | `components/BrandMark.tsx` | Accent-square upload-arrow icon + wordmark; `size` sm/md, `showWordmark` (SPEC-028; used by Header + LandingPage). |
| `PrimaryNav` | `components/PrimaryNav.tsx` | Topbar Files \| Query underline tabs (`NavLink`-driven); rendered by `Header` only when authenticated (SPEC-035). |
| `Modal` | `components/Modal.tsx` | Centered modal shell (SPEC-026 pattern): scrim + surface card + role/aria + backdrop-dismiss + Escape (`useEscapeKey`); `dismissible` locks it during in-flight actions; `className` replaces the default `max-w-md`. Children supply body + footer. (react-best-practices pass) |
| `ConfirmDialog` | `components/ConfirmDialog.tsx` | Warn-and-confirm dialog over `Modal`: title (+ optional danger icon `tone`), body `children`, optional `irreversible` line, `confirmVariant`, `busy`/`busyLabel`, `confirmDisabled` (gate confirm only — e.g. type-the-name, SPEC-054), `dismissOnly` (single-button info), focus defaults to Cancel. Used by Clear/CloseTab/DropTable/TabLimit/delete-confirm/overwrite-confirm. (react-best-practices pass) |
| `Drawer` | `components/Drawer.tsx` | Right slide-over (SPEC-036): scrim + 440px panel + header (title, `headerAccessory`, close button) + scrollable body + optional `footer`; `closeOnEscape` yields Escape to a nested dialog. Used by history / saved-queries / upload drawers. (react-best-practices pass) |
| `Pager` | `components/Pager.tsx` | Prev / range-label / Next pager (SPEC-038 styling), `nextBusy` "Loading…" state. Shared by the query-results table + history drawer. (react-best-practices pass) |
| `LoadingState` | `components/LoadingState.tsx` | Centered `role="status"` "Loading…" indicator (route Suspense fallback + auth gate). (react-best-practices pass) |
| `FolderIcon` / `UploadIcon` / `DocumentIcon` / `CopyIcon` / `CheckIcon` | `components/icons.tsx` | Shared inline SVG icons (no icon lib); `className` for size/color; `FolderIcon` takes `filled`. (react-best-practices pass) |
| `CopyButton` | `components/CopyButton.tsx` | Icon-only copy-to-clipboard button; `value` + `label` (→ `Copy {label}` aria-label), swaps to a check + polite live-region announce on success. Built on `useCopyToClipboard`. |

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
| `runQuery({ sql, database, username, outputLocation? })` | `query.service.ts` | `StartQueryExecution` against the shared workgroup. `outputLocation` omitted → the caller's own `{username}/athenaresults/`; pass a shared path for a shared-DB query (SPEC-055). Type-agnostic (SELECT + DDL). `ServiceResult<{ queryExecutionId }>`. |
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
| `useResultRowCount(id \| null)` | `useResultRowCount.ts` | Background page-walk that counts a succeeded query's exact total rows via `GetQueryResults` (free, no extra scan) at `ROW_COUNT_PAGE_SIZE`, keyed on the execution id (separate from the visible pager key so it never perturbs it); returns `{total, isCounting, atCeiling}`, stops at `ROW_COUNT_CEILING`, degrades to `null` on a failed page, recomputes on id change. Pass `null` to disable (in-flight / DDL / no result set) — SPEC-080. |
| `useColumnWidths(executionId, columnCount)` | `useColumnWidths.ts` | In-memory `Record<executionId, number[]>` column-width store keyed by query execution id, so widths survive Prev/Next paging **and** query-tab switches; exposes the current execution's `widths`/`setWidth` (clamped ≥ `MIN_COLUMN_WIDTH`)/`resetColumn`; render-phase seed → defaults for a new id (within an entry, keyed by column index). Called in `QueryWorkspace` (above the table that unmounts), outputs passed down (SPEC-064). |
| `useEditorLayout(username \| null, containerHeight)` | `useEditorLayout.ts` | SPEC-079 editor/results layout preset (`editor`/`even`/`results`): per-user `sessionStorage` persistence (degrade-safe, default `even`) + the editor pane's derived px height, capped at `container − MIN_RESULTS_HEIGHT` then floored at `MIN_EDITOR_HEIGHT` (editor floor wins on short viewports); `clampEditorHeight` exported for reuse/tests. |
| `useSchema(db \| null)` + `invalidateSchema(client, db)` | `useSchema.ts` | DB + tables for the schema browser; invalidation helper to refresh after DDL. |
| `useAllSchemas(databaseNames)` | `useSchema.ts` | Loads every accessible database's schema at once (`useQueries`, shares `useSchema`'s per-DB cache keys) → `DatabaseSchema[]` for multi-database autocomplete; failed DBs omitted (SPEC-077). |
| `useQueryHistory(username \| null)` | `useQueryHistory.ts` | History list + `appendEntry`/`updateEntry` mutations (cache-seeding). |
| `getSavedQueries` / `upsertSavedQuery` / `removeSavedQuery` | `savedQueries.service.ts` | Per-user saved-queries JSON store at `{username}/user_settings/saved-queries.json`; PutObject overwrite only (remove rewrites, never an S3 delete), missing-file → empty store, `ServiceResult` (SPEC-043). |
| `useSavedQueries(username \| null)` | `useSavedQueries.ts` | Saved-queries list + `upsert`/`remove` mutations (cache-seeding), `queryKeys.savedQueries` (SPEC-043). |

### Workspace UI (SPEC-035)

| Symbol | File | Purpose |
|---|---|---|
| `QueryWorkspace` | `QueryWorkspace.tsx` | Top-level `/query` composition: schema rail + toolbar + editor + status + results, wired to the SPEC-034 layer. Rendered by the lazy `QueryPage` route. |
| `SqlEditor` (+ `SqlEditorHandle`) | `SqlEditor.tsx` | Lazy, self-hosted Monaco SQL editor; `value`/`onChange`/`onRun` (⌘⏎), ref exposes `insertAtCursor`. |
| `SchemaBrowser` | `SchemaBrowser.tsx` | Left rail: a **browse-only tree** of `DatabaseNode`s (SPEC-063/077); props `{connections?, actions}` (no active-database selection). Renders unusable shared connections as static status rows. |
| `DatabaseNode` | `DatabaseNode.tsx` | One database in the rail (SPEC-063/077): disclosure node + per-node `useSchema` (fetched only when expanded) + two collapsible **Tables**/**Views** groups (counts + empty states). Browse-only — columns are non-interactive rows (no insert); per-table actions menu (View DDL/data/Drop) invoked with the node's database. Header **Refresh** `IconButton` (expanded nodes only) re-reads just this database via `invalidateSchema`, disabled/spinning on the node's `isFetching` (SPEC-086). |
| `partitionSchema(tables)` | `schema.partition.ts` | Pure split of Glue objects into `{tables, views}` (`tableType === 'VIRTUAL_VIEW'` → views); single source of truth for the rail's two groups (SPEC-063). |
| `QueryStatusBar` | `QueryStatusBar.tsx` | Slim live-region execution status (running/succeeded/failed/cancelled) + **Save results to my files** (`onSaveResults`/`canSaveResults`, shown only for a row-returning success — SPEC-049). |
| `SaveResultsDialog` / `DestinationSpace` (+ `normalizeCsvName` in `query.format.ts`) | `SaveResultsDialog.tsx` | Destination-space selector (personal + member-of shared spaces, SPEC-055) + folder `DestinationPicker` + validated filename modal; `onSave` returns `{destBucket, destPrefix, filename}` for a same- or cross-bucket full-result `copyObject`, `.csv`-normalized (SPEC-049). |
| `QueryResultsTable` | `QueryResultsTable.tsx` | File-table-styled results (dynamic columns + type, horizontal scroll, empty/loading state); shows one page at a time with a Prev/Next pager + "Rows X–Y" indicator (replace, not append — SPEC-038). Columns are **user-resizable** via `<colgroup>` + `table-fixed`, no-wrap + ellipsis + `title` on cells/headers; **controlled** — `widths`/`onResize`/`onResetColumn` come from the parent's `useColumnWidths` (SPEC-064). |
| `EditorLayoutControl` | `EditorLayoutControl.tsx` | Three-option segmented control (labeled `role="group"` + `aria-pressed` toggle buttons) snapping the editor/results vertical split to a preset; controlled `{preset, onChange}`, heights owned by the parent's `useEditorLayout` (SPEC-079). |
| `ColumnResizeHandle` | `ColumnResizeHandle.tsx` | Focusable `role="separator"` resize handle on a data-column header: pointer drag (clamped at `MIN_COLUMN_WIDTH`), double-click reset, Arrow Left/Right keyboard nudge by `COLUMN_RESIZE_STEP_PX`, column-naming `aria-label` (SPEC-064). |
| `QueryHistoryPanel` | `QueryHistoryPanel.tsx` | Right slide-over drawer listing per-user history (`useQueryHistory`); read-only, view/Open/Re-run; empty/loading/error states (SPEC-036). Client-side Prev/Next pager, 7/page newest-first, `"1–7 of N"`, reset-to-newest on open/append (SPEC-042). Header **Refresh** control re-reads from S3 (`useQueryHistory.refresh`/`isRefreshing`); reset-to-newest on success, non-destructive on error (SPEC-046). |
| `QueryHistoryRow` | `QueryHistoryRow.tsx` | One history entry: status badge, relative time, SQL preview, stats, Open/Re-run (SPEC-036). |
| `ClearQueryDialog` | `ClearQueryDialog.tsx` | Warn-and-confirm modal for the Clear-query action (SPEC-026 pattern; `alertdialog`, Escape/backdrop cancel, no undo) (SPEC-040; scoped to the active tab under SPEC-041). |
| `readTabsState` / `writeTabsState` / `initialTabsState` / `migrateDraftToTabs` | `queryTabs.ts` | Per-user `sessionStorage` wrapper for the multi-tab editor state (`s3portal.query.tabs.{username}`); structural validation (corrupt → null), error-swallowing, empty-username no-op, one-time SPEC-040 draft migration (SPEC-041; supersedes the removed `queryDraft.ts`). |
| `useConnections(username)` | `useConnections.ts` | **The** source of databases the user can query (`Connection[]` + `refresh`/`isRefreshing`): merges the personal DB with shared entries read from the per-user cache (personal first, shared A–Z); `refresh` forces a credential refresh then refetches; missing/corrupt cache → personal-only. One hook feeds the schema rail, Files list, and Connections tab (SPEC-047/052). |
| `Connection` / `ConnectionKind` / `isConnectionUsable` | `query.types.ts` | `{id,label,database,kind:'personal'\|'shared',status?,role?,reason?,members?}` — a targetable database; `members?` is the owner-readable projection (SPEC-053); `isConnectionUsable` = personal or `active` shared (SPEC-047/052). |
| `useQueryTabs(username)` | `useQueryTabs.ts` | Owns `QueryTabsState` + persistence; `openTab({label?,sql?,savedQueryId?})` (returns id or **null at `QUERY_TABS_MAX`**; named tabs skip the `Query N` counter), monotonic labelling, `closeTab` (≥1-tab + adjacent-activate), `setActiveSql`/`setActiveTab`/`setActiveSavedQueryId`/`clearActive` (SPEC-041). |
| `QueryTabStrip` | `QueryTabStrip.tsx` | Card-tab strip above the editor: active = surface+border+accent dot, per-tab `×` (hidden when solo), always-enabled `+` (SPEC-041 §6). |
| `TabLimitDialog` / `CloseTabDialog` | `TabLimitDialog.tsx` / `CloseTabDialog.tsx` | FR-008 "close a tab first" alert; FR-005 warn-and-confirm before closing a non-empty tab (both SPEC-026 pattern) (SPEC-041). |
| `SavedQueriesPanel` | `SavedQueriesPanel.tsx` | Right drawer (mirrors history) listing saved queries (most-recently-updated first) with Open + Delete-with-confirm; presentational (workspace owns the data) (SPEC-043). |
| `SaveQueryDialog` | `SaveQueryDialog.tsx` | Name-prompt modal with an inline overwrite-confirm step on a name collision; pre-filled on re-save (SPEC-043). |
| `SavedQuery`, `SavedQueriesStore` | `query.types.ts` | Saved-query record + store types; `QueryHistoryEntry` also gained optional `savedQueryId`/`savedQueryName` (SPEC-043). |
| `TableActionsMenu` | `TableActionsMenu.tsx` | **Reusable** kebab (⋮) + accessible popover menu (the app's first menu primitive): `aria-haspopup`/`expanded`, focus-in, Escape/outside-click close, arrow-key nav, danger items + separators (SPEC-044). |
| `Toast` (+ `ToastState`) | `Toast.tsx` | **Reusable** minimal transient toast (success/danger auto-dismiss; `info` persists), accessible live region, fixed bottom-right; optional inline `action` (e.g. "View in Files"; suppresses auto-dismiss) (SPEC-044/049). |
| `DropTableDialog` | `DropTableDialog.tsx` | DROP TABLE / DROP VIEW warn-and-confirm (SPEC-026 alertdialog, danger, in-flight lock); `isView` switches the copy/labels (SPEC-044/048). |
| `CreateViewDialog` | `CreateViewDialog.tsx` | Name-prompt modal for Create view; validates the catalog-safe identifier rule; busy-locks while the background `CREATE OR REPLACE VIEW` runs (SPEC-048). |
| `getTableDdl` / `runStatementToCompletion` | `query.service.ts` | `SHOW CREATE TABLE` (or `SHOW CREATE VIEW` when `isView`) → assembled DDL; run-and-poll-to-terminal helper for background statements (View DDL, Drop, Create view) (SPEC-044/048). |
| `CATALOG_IDENTIFIER_RE` / `stripTrailingSemicolons` | `query.constants.ts` / `query.sql.ts` | Shared catalog-safe identifier rule (`^[a-z][a-z0-9_]{2,62}$`, = SPEC-033 username rule); strip trailing `;`/whitespace for embedding a SELECT as a view body (SPEC-048). |
| `QueryTab`, `QueryTabsState`, `QUERY_TABS_MAX`, `DEFAULT_SQL` | `query.types.ts` / `query.constants.ts` | Tab data types, the soft tab cap, and the shared first-tab boilerplate (SPEC-041). |
| `formatBytes` / `formatDurationMs` / `formatRelativeTime` | `query.format.ts` | Display formatters for scanned-bytes / duration / relative timestamps. |
| `queryKeys` | `queryKeys.ts` | Key factory (`schema`/`execution`/`results`/`history`/`savedQueries`/`connections`) — never hand-build keys. |
| `QueryState`, `QueryStatus`, `QueryColumn`, `QueryResultPage`, `GlueColumn`, `GlueTableSummary`, `QueryHistoryEntry`, `QueryHistory` | `query.types.ts` | Feature data types. |
| `POLL_INTERVAL_MS`, `MAX_POLL_DURATION_MS`, `DEFAULT_MAX_ROWS`, `QUERY_HISTORY_MAX` | `query.constants.ts` | Polling cadence/guard, default page size, history cap. |

## Shared-spaces feature (`apps/portal/src/features/shared-spaces/`)

| Symbol | File | Purpose |
|---|---|---|
| `enqueueSharedSpaceRequest(input)` | `sharedSpaces.service.ts` | Enqueue one shared-space request (FIFO `SendMessage`, constant MessageGroupId = serial intake, requestId dedup) carrying the verified ID token; `ServiceResult<{requestId}>`, never throws. The browser's only shared-space write (SPEC-051/056). |
| `readSharedConnectionsCache(username)` | `sharedSpaces.service.ts` | Read-only `GetObject` of the per-user cache (`{username}/user_settings/shared-connections.json`); forgiving parse (missing/corrupt → empty, drops malformed entries); `ServiceResult`, never throws. Source for `useConnections` (SPEC-052). |
| `ConnectionsPage` | `ConnectionsPage.tsx` | The `/connections` management view: lists shared connections (mono name, role pill, status badge text+icon), Refresh control, empty state, read-error `Banner`, failed-entry reason + Dismiss/Retry; merges cache + local optimistic pending (SPEC-052). |
| `RefreshConnectionsButton` | `RefreshConnectionsButton.tsx` | `IconButton` affordance (SPEC-046 pattern) for `useConnections().refresh`; spins + disables while in-flight (SPEC-052). |
| `connectionStatusLabel(status)` | `connectionStatus.ts` | Human label for a shared connection's lifecycle status (Provisioning…/Active/Failed/Leaving…/Deleting…); shared by the Connections badge + the disabled schema-rail hint (SPEC-052; `deleting` added SPEC-054). |
| `useLeaveOrDeleteSharedSpace(username)` | `useLeaveOrDeleteSharedSpace.ts` | `{leave(space), remove(space), busy}` — enqueue `leave` (member self-revoke) / `delete` (owner cascade); no payload; the browser makes no direct AWS call; no-op when signed out (SPEC-054). |
| `LeaveSharedSpaceDialog` | `LeaveSharedSpaceDialog.tsx` | Member's leave confirm (shared danger `ConfirmDialog`); copy notes no data is deleted (SPEC-054). |
| `DeleteSharedSpaceDialog` | `DeleteSharedSpaceDialog.tsx` | Owner's irreversible delete confirm — **type-the-name** guard (via `ConfirmDialog.confirmDisabled`) + Enter-to-confirm-on-match; names the cascade (SPEC-054). |
| `useManageMembers(username)` | `useManageMembers.ts` | `{addMembers, removeMembers, busy}` — enqueue `add_members`/`remove_members` (payload.members); the browser makes no direct AWS call; no-op when signed out/empty (SPEC-053). |
| `useAcknowledgeMembership(username, connections, activeSpaceId)` | `useAcknowledgeMembership.ts` | Effect hook: when a member resolves an `active` shared space they belong to (not owner), enqueues one `acknowledge_membership` per space per browser session (sessionStorage dedup), flipping them Pending → Active in the owner projection. Called from `FilesPage` (SPEC-073). |
| `MembersList` | `MembersList.tsx` | Shared presentational roster: owner tagged + first, others A–Z, per-member Pending/Active chip; optional `onRemove` renders per-member Remove (read-only without it). Used by both member-drawers (SPEC-075). |
| `ManageMembersDrawer` | `ManageMembersDrawer.tsx` | Owner-only member-management slide-over (SPEC-036 `Drawer`) over `MembersList` (read-write): per-member Remove (SPEC-026 confirm), Add, Refresh; renders the owner-readable `Member[]` projection (SPEC-053/073). |
| `MemberRosterDrawer` | `MemberRosterDrawer.tsx` | Read-only member roster over `MembersList` for non-owner members (Refresh + legacy "not available yet" note); no Add/Remove. Opened by "View members" on an active member card (SPEC-075). |
| `AddMembersDialog` / `parseMemberInput` | `AddMembersDialog.tsx` / `memberInput.ts` | Single-or-bulk add modal + the parse util (split on comma/space/newline, trim, lowercase, de-dupe, drop tokens failing `CATALOG_IDENTIFIER_RE`, exclude existing) (SPEC-053). |
| `useCreateSharedConnection(username)` | `useCreateSharedConnection.ts` | `{create(name), busy, pending}` — enqueue a `create` + hold an optimistic LOCAL provisioning entry (no S3 write; the pipeline writes the cache) (SPEC-051). |
| `CreateSharedConnectionDialog` | `CreateSharedConnectionDialog.tsx` | Name-prompt modal for a new shared connection; validates `CATALOG_IDENTIFIER_RE`; "permanent + globally unique" copy; busy-locks (SPEC-051). |
| `SharedConnectionEntry`, `SharedConnectionsCache`, `SharedSpaceRequest`, `SharedSpaceAction`, `SharedConnectionRole/Status`, `Member`/`MemberStatus` | `sharedSpaces.types.ts` | Per-user cache entry/cache shapes + the SQS request contract types (SPEC-051/056). SPEC-052 reads the cache; `members?` on the owner entry is the owner-readable projection, now `Member[]` with per-member `pending`/`active` join status (SPEC-053/073). |

## Notifications feature (`apps/portal/src/features/notifications/`)

| Symbol | File | Purpose |
|---|---|---|
| `getNotifications(username)` | `notifications.service.ts` | Read-only `GetObject` of `{username}/user_settings/notifications.json`; forgiving parse (missing/corrupt/non-array → empty, drops malformed rows, coerces `read`), returns rows newest-first; `ServiceResult<Notification[]>`, never throws (SPEC-059). |
| `enqueueNotificationAction(input)` | `notifications.service.ts` | Enqueue one user-action (`markRead`/`markAllRead`) onto the SPEC-058 FIFO queue (`MessageGroupId` = username, body carries the verified ID token, never a body username); `ServiceResult<void>` (enqueued ≠ applied), never throws. The browser's only notifications write (SPEC-059). |
| `useNotifications(username, options?)` | `useNotifications.ts` | `{notifications, unreadCount, hasUnread, isLoading, isError, refresh, markRead, markAllRead}` — TanStack read + optimistic mark-read mutations (rollback + delayed reconcile) + a 60s self-limiting poll (suspends while unread); `options.onMutationError` for the SPEC-060 toast (SPEC-059). |
| `prefetchNotifications(queryClient, username)` | `useNotifications.ts` | One-shot graceful prefetch of the inbox read for first-paint indicator accuracy; no-op when signed out, never throws (wired in `ProtectedLayout`, SPEC-059). |
| `notificationsKeys` | `notificationsKeys.ts` | TanStack query-key factory (`all`, `list(username)`) for the notifications read (SPEC-059). |
| `Notification`, `NotificationAction`, `EnqueueNotificationInput`, `NotificationsStore` | `notifications.types.ts` | Inbox row + the two browser action names + enqueue input + the on-S3 array shape; match the SPEC-058 wire contract (SPEC-059). |

| `NotificationsBell` | `NotificationsBell.tsx` | Header bell **link** (react-router `NavLink` → `/notifications`) with a presence-only accent dot when `hasUnread`; count carried in the aria-label (never color-only); `aria-current` on route (SPEC-060). |
| `NotificationsPage` | `NotificationsPage.tsx` | Routed page (via `routes/NotificationsPage.tsx` wrapper): newest-first list, 10/page `Pager`, Mark-all-read + Refresh, empty/loading/error states, optimistic actions + danger `Toast`; owns `useNotifications` + its document title (SPEC-060). |
| `NotificationRow` | `NotificationRow.tsx` | One notification row — unread accent dot + sr-only "Unread:", message, `formatRelativeTime`, Mark-read on unread rows (read rows de-emphasized, no control); no delete (SPEC-060). |
| `BellIcon` | `components/icons.tsx` | Shared inline bell SVG for the notifications header link (SPEC-060). |
| `buildSqlCompletions`, `createSqlCompletionProvider`, `DatabaseSchema` | `features/query/sqlCompletions.ts` | Pure, Monaco-free builder mapping `DatabaseSchema[]` (per-DB tables) → completion descriptors: **fully-qualified** `database.table` for tables/views, bare de-duped columns with type detail; plus the Monaco provider factory reading a live `schemaRef`. Feeds multi-database autocomplete (SPEC-065/077). |
| `deriveViewTargetDatabase(body)`, `schemaChangingDatabase(sql)` | `features/query/query.sql.ts` | Pure SQL heuristics: the single database of a view body's fully-qualified base tables (error when ambiguous/none), and the target DB of a schema-changing DDL statement — both used now that there's no active database (SPEC-077). |
| `splitSqlStatements(buffer)`, `resolveRunStatements(buffer, stmts, sel, cursor)`, `isResultProducingSql(sql)`, `statementHint(sql)` | `features/query/query.sql.ts` | Pure multi-statement helpers (SPEC-078): split a buffer into `ParsedStatement[]` (string/comment/backtick-aware, source offsets); resolve Run Statement's scope (selection → cursor statement → sole); classify row-returning statements; short label for result tabs. |
| `ResultTabs` | `features/query/ResultTabs.tsx` | Result-tab strip for a "tab per statement" script run (SPEC-078): WAI-ARIA tablist (roving tabindex, Arrow/Home/End), one labeled tab per `ResultTab`, controlled `activeIndex`/`onSelect`. |
| `useResultsPageSize(username)`, `clampPageSize(n)` | `features/query/useResultsPageSize.ts` | Workspace-global "Rows per page" value (default 100, clamped 1–1000), per-user sessionStorage persistence (defensive read, degrade-safe); `clampPageSize` is the pure validator (null for non-integers) (SPEC-087). |
| `ResultsPageSizeControl` | `features/query/ResultsPageSizeControl.tsx` | Labeled "Rows per page" integer input for the results header: commit on blur/Enter (never per keystroke), Escape abandons the draft, invalid input reverts / out-of-range clamps, `disabled` renders non-interactive but visible (SPEC-087). |

## Table-builder feature (`apps/portal/src/features/table-builder/`)

| Symbol | File | Purpose |
|---|---|---|
| `enqueueTableBuild(req)` | `tableBuild.service.ts` | The browser's only table-builder call: builds the SPEC-067 envelope (`idToken` + `space` + `tableName` + `partitionKeys` + `requestId`) and FIFO-sends to `VITE_TABLE_BUILD_QUEUE_URL` (`MessageGroupId` = `space.database`, dedup = `requestId`) via `getSqsClient`; `ServiceResult<void>` (enqueued ≠ created), never throws (SPEC-071). |
| `suggestTableName(folder)`, `isValidTableName(name)` | `tableBuild.service.ts` | Pure: sanitize a folder name to a catalog-safe suggestion / test a name against `CATALOG_IDENTIFIER_RE` (UX only — server re-validates) (SPEC-071). |
| `buildPartitionKeys`, `buildPartitionKey`, `validateDraftKey`, `emptyDraftKey`, `parseValues` | `partitionKeys.ts` | Pure draft→wire partition-key logic + per-row validation (name/uniqueness, integer/date/string-enum config); empty list ⇒ valid flat `[]` (SPEC-071). |
| `CreateTableButton` | `CreateTableButton.tsx` | File-browser toolbar action → opens the dialog, enqueues for the active space + prefix, success/error `Toast` (SPEC-071). |
| `CreateTableDialog` | `CreateTableDialog.tsx` | Name prompt (suggested + validated) + optional partition-keys section; Confirm gated on name **and** keys valid; inline submit-error banner (SPEC-071). |
| `PartitionKeysField` | `PartitionKeysField.tsx` | Controlled, ordered, reorderable/removable partition-key rows (name + type `<select>` + per-type projection config) with focus management + labelled dynamic rows (SPEC-071). |
| `TableBuildRequest`, `PartitionKey`, `DraftPartitionKey`, `PartitionKeyErrors`, `PartitionType`, `PartitionKeysResult` | `tableBuild.types.ts`, `partitionKeys.ts` | The request + wire partition-key shapes (match the SPEC-067 contract) + the editor's draft/error/result types (SPEC-071). |

## Help feature (`apps/portal/src/features/help/`)

| Symbol | File | Purpose |
|---|---|---|
| `HELP_SECTIONS` | `helpContent.ts` | Static, code-grounded Help & guides content (Files incl. table builder, Query, Shared connections incl. join status, Notifications). Update on every spec that changes a user-facing feature (SPEC-074 FR-005) (SPEC-074). |
| `HelpPage` | `HelpPage.tsx` | Section sidebar + accordion cards; active section synced to the URL hash (`/help#query`), first-section fallback, first card default-open (SPEC-074). |
| `HelpSidebar` | `HelpSidebar.tsx` | Left rail mirroring `Sidebar`: one item per section with feature icon, label, and content-derived guide count; `aria-current` on active (SPEC-074). |
| `HelpGuideCard` | `HelpGuideCard.tsx` | One accordion guide: header button (`aria-expanded`/`aria-controls`), numbered steps, at most one Tip/Careful callout; independent open state (SPEC-074). |
| `HelpLink` | `HelpLink.tsx` | Header help control — `NavLink` to `/help` styled like `NotificationsBell`, active on `/help` (SPEC-074). |
| `renderInline(text)` | `inlineMarkup.tsx` | Parses `<b>`/`<kbd>` markup in guide step + callout strings into `<strong>`/keyed elements (no `dangerouslySetInnerHTML`) (SPEC-074). |
