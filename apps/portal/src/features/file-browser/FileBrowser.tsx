import {useState} from 'react';
import {Button} from '../../components/Button';
import {Banner} from '../../components/Banner';
import {useFileBrowser} from './useFileBrowser';
import {useFileUpload} from './useFileUpload';
import {useDelete} from './useDelete';
import {useMove} from './useMove';
import {useCopy} from './useCopy';
import {useFileDownload} from './useFileDownload';
import {buildBreadcrumbs, isAtRoot, parentPrefix} from './fileBrowser.paths';
import {UploadDropzone} from './UploadDropzone';
import {UploadDrawer} from './UploadDrawer';
import {UploadList} from './UploadList';
import {useUploadQueue} from './uploadQueueContext';
import {CreateFolderDialog} from './CreateFolderDialog';
import {CollisionPrompt} from './CollisionPrompt';
import {MobileActionBar} from '../../components/MobileActionBar';
import {HIDDEN_BROWSER_FOLDERS, isRootFolderNamed} from './protectedFolders';
import {OperationFeedback} from './OperationFeedback';
import {SelectionToolbar} from './SelectionToolbar';
import {FileListTable, type FileListProps} from './FileListTable';
import {FileListMobile} from './FileListMobile';
import {FileBrowserDialogs} from './FileBrowserDialogs';
import {useFileBrowserDialogs} from './useFileBrowserDialogs';
import {useSharedSpaceAccessRecovery} from './useSharedSpaceAccessRecovery';
import {SelectionProvider} from './SelectionProvider';
import {CreateTableButton} from '../table-builder';
import {useFeature} from '../feature-flags';
import {useSelection, type SelectableItem} from './selectionContext';
import type {FileSpaceTarget, FileSpaceKind} from './useFileSpace';
import {toUserText} from '../../lib/errorMessages';
import {useIsMobile} from '../../lib/useBreakpoint';

// ─── Types ───────────────────────────────────────────────────────────────────

type Props = {
  bucket: string;
  prefix?: string; // initial prefix; browser starts here on mount
  rootPrefix?: string; // navigation floor; defaults to prefix prop value
  rootLabel?: string; // label for the root crumb; hides the raw prefix segment
  // (e.g. "My Files" instead of the username) — SPEC-013
  markerKey?: string; // exact key hidden from the listing — the prefix marker
  // (SPEC-014 FR-002)
  writable?: boolean; // show upload + create-folder controls (SPEC-016). Off in
  // the dev-unauth path (no scoped write credentials).
  username?: string; // the space's root-prefix owner — the marker guard protects
  // `{username}/DO_NOT_DELETE.txt` and it gates the modify controls (SPEC-018).
  // The signed-in username for the personal space; the shared-space name for a
  // shared space (SPEC-057). Present only in the authenticated flow.
  destinations?: FileSpaceTarget[]; // connections move/copy can target (feedback
  // 2026-06-30): personal + active shared spaces. Omitted in the dev-unauth path.
  spaceKind?: FileSpaceKind; // 'shared' enables the "just added → refresh access"
  // affordance when a listing is denied because the membership tag hasn't propagated
  // to this session's token yet (shared-spaces architecture §3).
};

// ─── Browser content (inside the SelectionProvider) ───────────────────────────

type ContentProps = Omit<Props, 'prefix'> & {
  rootPrefix: string;
  prefix: string | undefined;
  setPrefix: (prefix: string | undefined) => void;
};

function FileBrowserContent({
  bucket,
  rootPrefix,
  rootLabel,
  markerKey,
  writable = false,
  username,
  destinations,
  spaceKind,
  prefix,
  setPrefix
}: ContentProps) {
  const {
    files,
    folders: allFolders,
    isLoading,
    error,
    refresh: refreshListing,
    hasMore,
    loadMore,
    isLoadingMore
  } = useFileBrowser(bucket, prefix, markerKey);

  const access = useSharedSpaceAccessRecovery({error, spaceKind, refreshListing});

  // Hide app-managed root folders (e.g. user_settings/) from the listing so they
  // never surface to users; everything downstream uses the filtered list.
  const folders = allFolders.filter((f) => !isRootFolderNamed(f.prefix, rootPrefix, HIDDEN_BROWSER_FOLDERS));

  // Create-folder (SPEC-016) scoped to the folder currently being viewed. File
  // uploads are now owned by the SPEC-020 queue, so useFileUpload is used here
  // only for create-folder (and its folder-name collision / error).
  const currentPrefix = prefix ?? '';
  const {
    pendingCollision,
    error: writeError,
    isBusy,
    createNewFolder,
    cancelCollision,
    dismissError
  } = useFileUpload(bucket, currentPrefix);
  // Multi-file upload queue (SPEC-020) — enqueue from the dropzone; progress,
  // cancel, and per-file collisions now live in the in-drawer UploadList.
  const {enqueue} = useUploadQueue();
  // Multi-select + delete (SPEC-018). Selection comes from the surrounding
  // SelectionProvider; delete is only offered in the authenticated, writable flow
  // (a username is required for the marker guard).
  const selection = useSelection();
  // Mount-gate the table-vs-card list swap (SPEC-099); matchMedia reads correctly
  // on first paint in the browser, so no flash and only one markup ever mounts.
  const isMobile = useIsMobile();
  // SPEC-163 FR-005: two CROSS-FEATURE entry points live on this page — "Create table" is a
  // Query capability and "Check quality" is a Data Quality one. Neither belongs to the file
  // browser, which is exactly why a per-component gating pass misses them.
  const queryEnabled = useFeature('query');
  const dataQualityEnabled = useFeature('dataQuality');
  // `rootPrefix` is the space root, not the browsed folder: it is what tells the
  // delete/move services that a folder is the space's own `athenaresults/` rather
  // than a user folder that happens to share the name (SPEC-150 FR-007).
  const del = useDelete(bucket, currentPrefix, username, rootPrefix);
  const move = useMove(bucket, currentPrefix, username, rootPrefix);
  const copy = useCopy(bucket, currentPrefix, username);
  const canModify = writable && !!username;

  // Per-file download (SPEC-015 FR-003). Tracks the key being signed so its row
  // shows a busy state; surfaces a ServiceResult failure inline rather than
  // throwing. The hidden marker is filtered out, so it never exposes this action.
  const dl = useFileDownload(bucket);

  // SPEC-155 FR-009: every dialog/drawer flag, and the handlers that turn one
  // into an operation (including who clears the selection).
  const dialogs = useFileBrowserDialogs({bucket, currentPrefix, del, move, copy});

  const breadcrumbs = buildBreadcrumbs(prefix, rootPrefix, rootLabel);
  const destinationLabel = breadcrumbs[breadcrumbs.length - 1]?.label;
  // The `..` row shows below the space root only (SPEC-098).
  const atRoot = isAtRoot(currentPrefix, rootPrefix);
  const isEmpty = !isLoading && error === null && files.length === 0 && folders.length === 0;
  const hasContent = !isLoading && error === null && (files.length > 0 || folders.length > 0);

  // Every selectable row in the current view, for the header "select all".
  const allItems: SelectableItem[] = [
    ...folders.map((f) => ({type: 'folder' as const, prefix: f.prefix})),
    ...files.map((f) => ({type: 'file' as const, key: f.key}))
  ];
  const selectedItems = [...selection.selected.values()];

  // Same data + handlers for both list surfaces (SPEC-099 FR-002/003); the caller
  // mount-gates which markup renders.
  const fileListProps: FileListProps = {
    folders,
    files,
    selectable: canModify,
    atRoot,
    onNavigateUp: () => setPrefix(parentPrefix(currentPrefix, rootPrefix) || undefined),
    onOpenFolder: (folder) => setPrefix(folder.prefix),
    onFolderDetails: dialogs.openFolderDetails,
    onFileDetails: dialogs.openFileDetails,
    onActivateFile: (file) => void dl.download(file),
    downloadingKey: dl.downloadingKey,
    isSelected: selection.isSelected,
    onToggleSelect: selection.toggle
  };

  return (
    // Writable mobile flows get bottom padding so the fixed MobileActionBar never
    // occludes the last list row (SPEC-099 FR-005).
    <div className={writable ? 'pb-24 tablet:pb-0' : undefined}>
      {/* Toolbar row — breadcrumbs (left) + primary actions (right). FR-002/003 */}
      <div className="mb-4 flex items-center gap-3">
        <nav
          aria-label="breadcrumb"
          className="min-w-0 flex-1">
          <ol className="flex items-center gap-1 text-sm">
            {breadcrumbs.map((crumb, i) => {
              const isLast = i === breadcrumbs.length - 1;
              return (
                <li
                  key={crumb.prefix ?? 'root'}
                  className="flex items-center gap-1">
                  {i > 0 && (
                    <span
                      aria-hidden="true"
                      className="mx-0.5 text-text-3">
                      /
                    </span>
                  )}
                  {isLast ? (
                    <span
                      aria-current="page"
                      className="max-w-[200px] truncate font-semibold text-text">
                      {crumb.label}
                    </span>
                  ) : (
                    <button
                      className="max-w-[160px] truncate text-text-2 hover:text-text hover:underline"
                      onClick={() => setPrefix(crumb.prefix)}>
                      {crumb.label}
                    </button>
                  )}
                </li>
              );
            })}
          </ol>
        </nav>

        {/* Primary actions on the top toolbar at ≥ tablet; on mobile they move to
            the fixed MobileActionBar below (SPEC-099 FR-005). Mount-gated (not
            CSS-hidden) so the two never both live in the DOM. */}
        {writable && !isMobile && (
          <div className="flex items-center gap-3">
            {/* SPEC-071: turn the current folder into a Glue/Athena table. Needs the
                space's database (= the marker owner: username | shared name), so it's
                gated on `username` like the other space-scoped actions. */}
            {username && queryEnabled && (
              <CreateTableButton
                spaceKind={spaceKind ?? 'personal'}
                bucket={bucket}
                database={username}
                prefix={currentPrefix}
              />
            )}
            <Button
              variant="default"
              className="shrink-0"
              onClick={dialogs.toggleCreateFolder}
              disabled={isBusy}>
              New folder
            </Button>
            <Button
              variant="primary"
              className="shrink-0"
              onClick={dialogs.openUpload}>
              Upload
            </Button>
          </div>
        )}
      </div>

      {/* Mobile bottom action bar (writable only) — New folder + Upload, ≥44px
          (SPEC-099 FR-005). Same handlers as the top-toolbar buttons. */}
      {writable && isMobile && (
        <MobileActionBar ariaLabel="File actions">
          <Button
            variant="default"
            className="!h-11 flex-1"
            onClick={dialogs.toggleCreateFolder}
            disabled={isBusy}>
            New folder
          </Button>
          <Button
            variant="primary"
            className="!h-11 flex-1"
            onClick={dialogs.openUpload}>
            Upload
          </Button>
        </MobileActionBar>
      )}

      {/* Write controls — create folder (modal dialog, SPEC-016); file uploads go
          to the SPEC-020 queue. Hidden in read-only (dev-unauth) mode. */}
      {writable && (
        <>
          {dialogs.creatingFolder && (
            <CreateFolderDialog
              onCreate={(name) => {
                dialogs.closeCreateFolder();
                createNewFolder(name);
              }}
              onCancel={dialogs.closeCreateFolder}
            />
          )}

          {/* Folder-name collision (SPEC-016) — Overwrite or pick a new name */}
          {pendingCollision && (
            <CollisionPrompt
              kind={pendingCollision.kind}
              name={pendingCollision.label}
              onOverwrite={() => pendingCollision.retry({overwrite: true})}
              onRename={(newName) => pendingCollision.retry({rename: newName})}
              onCancel={cancelCollision}
            />
          )}

          {/* Create-folder error (SPEC-016) */}
          {writeError && (
            <Banner
              variant="danger"
              onDismiss={dismissError}
              className="mb-4">
              {writeError}
            </Banner>
          )}

          {/* Add-files drawer (SPEC-020) — the dropzone enqueues onto the
              session-scoped upload queue; the in-progress list sits right below it
              (feedback 2026-06-30) and persists for the session, so the drawer can
              be closed and reopened without losing or interrupting uploads. */}
          <UploadDrawer
            open={dialogs.uploadOpen}
            onClose={dialogs.closeUpload}
            destinationLabel={destinationLabel}>
            <UploadDropzone onFiles={(files) => enqueue(files, {bucket, prefix: currentPrefix})} />
            <UploadList />
          </UploadDrawer>
        </>
      )}

      {/* Download error (SPEC-015) — dismissible, non-blocking */}
      {dl.error && (
        <Banner
          variant="danger"
          onDismiss={dl.dismissError}
          className="mb-4">
          {dl.error}
        </Banner>
      )}

      {/* Delete / move / copy feedback (SPEC-018 FR-004, SPEC-019 FR-004, SPEC-039 FR-004):
          the systemic error, the result summary, progress and the batch overwrite
          confirmation. One component, three operations — see OperationFeedback. */}
      <OperationFeedback
        op={del}
        pastVerb="Deleted"
        failVerb="delete"
      />
      <OperationFeedback
        op={move}
        pastVerb="Moved"
        failVerb="move"
        progressVerb="Moving">
        {/* Rename collision (SPEC-019 FR-005) — Overwrite or pick a new name. Not part
            of the shared state: it is single-item, so a new name is offered too. */}
        {move.renameCollision && (
          <CollisionPrompt
            kind={move.renameCollision.kind}
            name={move.renameCollision.label}
            onOverwrite={move.renameCollision.onOverwrite}
            onRename={move.renameCollision.onRename}
            onCancel={move.renameCollision.onCancel}
          />
        )}
      </OperationFeedback>

      <OperationFeedback
        op={copy}
        pastVerb="Copied"
        failVerb="copy"
        progressVerb="Copying"
      />

      {/* Selection toolbar (SPEC-018 + SPEC-019 + SPEC-039 + SPEC-113) — select all +
          bulk copy/move/delete + the single-item data-quality check */}
      {canModify && hasContent && (
        <SelectionToolbar
          allItems={allItems}
          onRequestDelete={dialogs.openConfirmDelete}
          onRequestMove={dialogs.openMove}
          onRequestCopy={dialogs.openCopy}
          onRequestQualityCheck={username && dataQualityEnabled ? dialogs.openQualityCheck : undefined}
          isBusy={del.isBusy || move.isBusy || copy.isBusy || dl.downloadingKey !== null}
        />
      )}

      {/* Loading */}
      {isLoading && (
        <div
          role="status"
          aria-label="Loading"
          className="flex items-center justify-center py-16 text-sm text-text-3">
          <span>Loading…</span>
        </div>
      )}

      {/* Error */}
      {!isLoading && error !== null && (
        <div
          role="alert"
          className="rounded-lg border border-danger-soft bg-danger-soft p-4 text-danger">
          {access.justAddedToShared ? (
            <>
              <p className="font-medium">Applying your access…</p>
              <p className="mt-1 text-sm">
                You were just added to this space. Access applies once your session refreshes — this can take a moment
                after being added.
              </p>
              <Button
                variant="default"
                size="sm"
                className="mt-3"
                onClick={() => void access.refreshAccess()}
                disabled={access.refreshing}>
                {access.refreshing ? 'Refreshing…' : 'Refresh access'}
              </Button>
            </>
          ) : (
            <>
              <p className="font-medium">Failed to load files</p>
              <p className="mt-1 text-sm">{toUserText(error)}</p>
            </>
          )}
        </div>
      )}

      {/* Empty state — at the space root only; a non-root empty folder still
          renders the list so its `..` row is reachable (SPEC-098). */}
      {isEmpty && atRoot && (
        <div className="py-16 text-center">
          <svg
            viewBox="0 0 40 40"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            className="mx-auto h-10 w-10 text-text-3"
            aria-hidden="true">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M4 12a4 4 0 014-4h7.172a2 2 0 011.414.586l2.828 2.828A2 2 0 0020.828 12H32a4 4 0 014 4v12a4 4 0 01-4 4H8a4 4 0 01-4-4V12z"
            />
          </svg>
          <p className="mt-4 text-xl font-semibold text-text">This folder is empty</p>
          {writable && (
            <p className="mx-auto mt-2 max-w-xs text-sm text-text-2">
              Upload a file or create a folder to get started.
            </p>
          )}
        </div>
      )}

      {/* File and folder list. Also renders for an empty non-root folder so the
          `..` row stays reachable (SPEC-098). Structural markup swap (SPEC-099
          FR-002/003): a data table at ≥ tablet, a compact two-line card list on
          mobile — same data + handlers. */}
      {(hasContent || (isEmpty && !atRoot)) &&
        (isMobile ? (
          <FileListMobile {...fileListProps} />
        ) : (
          <FileListTable
            {...fileListProps}
            // Read-only browse has no selection toolbar, so keep a per-row Download
            // there; the authenticated flow downloads from the toolbar.
            onRowDownload={canModify ? undefined : dl.download}
          />
        ))}

      <FileBrowserDialogs
        dialogs={dialogs}
        bucket={bucket}
        rootPrefix={rootPrefix}
        rootLabel={rootLabel}
        currentPrefix={currentPrefix}
        markerKey={markerKey}
        username={username}
        spaceKind={spaceKind}
        destinations={destinations}
        canModify={canModify}
        selectedItems={selectedItems}
        del={del}
        move={move}
        copy={copy}
      />

      {/* Load more — only when the current prefix has further pages (SPEC-015) */}
      {hasContent && hasMore && (
        <div className="mt-4 flex justify-center">
          <button
            className="h-9 rounded-md border border-border px-4 text-sm font-medium text-text-2 hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            onClick={loadMore}
            disabled={isLoadingMore}>
            {isLoadingMore ? 'Loading…' : 'Load more'}
          </button>
        </div>
      )}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

// Owns prefix navigation state and provides selection state to the content. The
// SelectionProvider lives here (above the content) so navigating to a new prefix
// clears the selection (SPEC-018 FR-001), and so the content can consume
// useSelection() as a descendant.
export function FileBrowser({
  bucket,
  prefix: prefixProp = '',
  rootPrefix: rootPrefixProp,
  rootLabel,
  markerKey,
  writable = false,
  username,
  destinations,
  spaceKind
}: Props) {
  const rootPrefix = rootPrefixProp ?? prefixProp;
  const [prefix, setPrefix] = useState<string | undefined>(prefixProp || undefined);

  return (
    <SelectionProvider prefix={prefix}>
      {/* The upload queue lives at the app shell (ProtectedLayout), not here, so it
          survives this component remounting on a `?space=`/prefix change and keeps
          uploads running for the whole session (feedback 2026-06-30). */}
      <FileBrowserContent
        bucket={bucket}
        rootPrefix={rootPrefix}
        rootLabel={rootLabel}
        markerKey={markerKey}
        writable={writable}
        username={username}
        destinations={destinations}
        spaceKind={spaceKind}
        prefix={prefix}
        setPrefix={setPrefix}
      />
    </SelectionProvider>
  );
}
