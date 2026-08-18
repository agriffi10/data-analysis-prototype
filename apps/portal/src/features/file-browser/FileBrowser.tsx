import {useMemo, useState} from 'react';
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
import {HIDDEN_BROWSER_FOLDERS, isRootFolderNamed, undeletableSelectionRefusal} from './protectedFolders';
import {SAVED_QUERIES_FOLDER} from './fileBrowser.constants';
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
import {SendFilesDialog, useFileSend} from '../file-send';
import {
  ArchiveDialog,
  RestoreArchiveButton,
  RestoreArchiveDialog,
  archiveRefusal,
  useArchive,
  useRestoreArchive
} from '../archive';
import {writeLockRefusal} from './writeLockedPrefix';
import {useToast} from '../../components/toastContext';
import {useSelection, type SelectableItem} from './selectionContext';
import type {FileSpaceTarget, FileSpaceKind} from './useFileSpace';
import type {ArchiveItem} from '../../types/archive.types';
import {toUserText} from '../../lib/errorMessages';
import {useIsMobile} from '../../lib/useBreakpoint';

// ─── Types ───────────────────────────────────────────────────────────────────

type Props = {
  bucket: string;
  prefix?: string; // initial prefix; browser starts here on mount
  rootPrefix?: string; // navigation floor; defaults to prefix prop value
  rootLabel?: string; // label for the root crumb; hides the raw prefix segment
  // (e.g. "My Files" instead of the username) —
  writable?: boolean; // show upload + create-folder controls. Off in
  // the dev-unauth path (no scoped write credentials).
  username?: string; // the space's root-prefix owner — the marker guard protects
  // `{username}/DO_NOT_DELETE.txt` and it gates the modify controls.
  // The signed-in username for the personal space; the shared-space name for a
  // shared space. Present only in the authenticated flow.
  destinations?: FileSpaceTarget[]; // connections move/copy can target (feedback
  // 2026-06-30): personal + active shared spaces. Omitted in the dev-unauth path.
  spaceKind?: FileSpaceKind; // 'shared' enables the "just added → refresh access"
  // affordance when a listing is denied because the membership tag hasn't propagated
  // to this session's token yet (shared-spaces architecture §3).
};

/**
 * One selected row as the archive plane's contract names it: a file's key, or a folder's prefix
 * with its trailing slash intact. The plane expands a folder by LISTING that prefix, so the
 * slash is not cosmetic — without it, `alice/archiv` would match `alice/archive/`.
 */
function toArchiveItem(item: SelectableItem): ArchiveItem {
  return item.type === 'file' ? {kind: 'file', key: item.key} : {kind: 'folder', key: item.prefix};
}

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
  } = useFileBrowser(bucket, prefix);

  const access = useSharedSpaceAccessRecovery({error, spaceKind, refreshListing});

  // Two CROSS-FEATURE entry points live on this page — "Create table" is a
  // Query capability and "Check quality" is a Data Quality one. Neither belongs to the file
  // browser, which is exactly why a per-component gating pass misses them.
  const queryEnabled = useFeature('query');
  const dataQualityEnabled = useFeature('dataQuality');
  // The send's own space is the BROWSER's space, not the current folder: the control
  // plane resolves the source from the verified username and the space name, and a folder deep
  // inside it is just where the selection came from.
  const filesEnabled = useFeature('files');

  // Hide app-managed root folders (e.g. user_settings/) from the listing so they
  // never surface to users; everything downstream uses the filtered list.
  //
  // `saved_queries/` is a Query feature wearing a file-browser row, so with
  // the `query` flag off it leaves the listing like the Query tab does. Composed here rather
  // than added to the constant, because the folder is VISIBLE by default — the flag is the
  // only thing that hides it, and its delete/rename refusal is unconditional either way.
  const hiddenFolders = useMemo(
    () => (queryEnabled ? HIDDEN_BROWSER_FOLDERS : [...HIDDEN_BROWSER_FOLDERS, SAVED_QUERIES_FOLDER]),
    [queryEnabled]
  );
  const folders = allFolders.filter((f) => !isRootFolderNamed(f.prefix, rootPrefix, hiddenFolders));

  // Create-folder scoped to the folder currently being viewed. File
  // uploads are now owned by the upload queue, so useFileUpload is used here
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
  // Multi-file upload queue — enqueue from the dropzone; progress,
  // cancel, and per-file collisions now live in the in-drawer UploadList.
  const {enqueue} = useUploadQueue();
  // Multi-select + delete. Selection comes from the surrounding
  // SelectionProvider; delete is only offered in the authenticated, writable flow
  // (a username is required for the marker guard).
  const selection = useSelection();
  // Mount-gate the table-vs-card list swap; matchMedia reads correctly
  // on first paint in the browser, so no flash and only one markup ever mounts.
  const isMobile = useIsMobile();
  const toast = useToast();
  // The space NAME is the root prefix's own segment, in both kinds: `{username}/` for a
  // personal space and `{spaceName}/` for a shared one. Taken from there rather than from
  // `username` — which carries the same value but is named for the marker guard — because the
  // control plane's question is "which space is this FROM", and the prefix is that answer.
  //
  // the two flows take the same value: an archive reads from this space, and a restore
  // writes back into it — the space the user is standing in, never one derived from an archive.
  const space = username ? ({kind: spaceKind ?? 'personal', name: rootPrefix.replace(/\/$/, '')} as const) : null;
  const send = useFileSend(space, (t) => toast.push(t));
  const archive = useArchive(space, (t) => toast.push(t));
  const restore = useRestoreArchive(space, (t) => toast.push(t));
  // `rootPrefix` is the space root, not the browsed folder: it is what tells the
  // delete/move services that a folder is the space's own `athenaresults/` rather
  // than a user folder that happens to share the name.
  const del = useDelete(bucket, currentPrefix, username, rootPrefix);
  const move = useMove(bucket, currentPrefix, username, rootPrefix);
  const copy = useCopy(bucket, currentPrefix, username);
  const canModify = writable && !!username;
  // The first prefix-based write gate. IAM denies writes beneath `archive/`, so
  // every control that would attempt one says why instead of producing a bare AccessDenied.
  const writeLockReason = writeLockRefusal(currentPrefix, rootPrefix, spaceKind ?? 'personal') ?? undefined;
  // Archive is gated by the write lock because an archive DELETES from the current folder.
  const archiveEnabled = !!username && filesEnabled && !writeLockReason;
  // A RESTORE is not: it writes into the space root, never into the folder being browsed — and
  // gating it on the write lock removed the button from `archive/`, which is the one place the
  // dialog itself tells the user to go and look for an id (FR-003 AC1 says `writable`).
  const restoreEnabled = !!username && filesEnabled;

  // Per-file download. Tracks the key being signed so its row
  // shows a busy state; surfaces a ServiceResult failure inline rather than
  // throwing. The hidden marker is filtered out, so it never exposes this action.
  const dl = useFileDownload(bucket);

  // Every dialog/drawer flag, and the handlers that turn one
  // into an operation (including who clears the selection).
  const dialogs = useFileBrowserDialogs({bucket, currentPrefix, del, move, copy});

  const breadcrumbs = buildBreadcrumbs(prefix, rootPrefix, rootLabel);
  const destinationLabel = breadcrumbs[breadcrumbs.length - 1]?.label;
  // The `..` row shows below the space root only.
  const atRoot = isAtRoot(currentPrefix, rootPrefix);
  const isEmpty = !isLoading && error === null && files.length === 0 && folders.length === 0;
  const hasContent = !isLoading && error === null && (files.length > 0 || folders.length > 0);

  // Every selectable row in the current view, for the header "select all".
  const allItems: SelectableItem[] = [
    ...folders.map((f) => ({type: 'folder' as const, prefix: f.prefix})),
    ...files.map((f) => ({type: 'file' as const, key: f.key}))
  ];
  const selectedItems = [...selection.selected.values()];

  // Same data + handlers for both list surfaces; the caller
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
    // occludes the last list row.
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
            the fixed MobileActionBar below. Mount-gated (not
            CSS-hidden) so the two never both live in the DOM. */}
        {writable && !isMobile && (
          <div className="flex items-center gap-3">
            {/* turn the current folder into a Glue/Athena table. Needs the
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
            {/* a restore has no selection — it takes a pasted id — so it sits
                with the primary actions rather than on the selection toolbar. */}
            {restoreEnabled && <RestoreArchiveButton onClick={restore.openDialog} />}
            <Button
              variant="default"
              className="shrink-0"
              onClick={dialogs.toggleCreateFolder}
              disabled={isBusy}
              disabledReason={writeLockReason}>
              New folder
            </Button>
            <Button
              variant="primary"
              className="shrink-0"
              onClick={dialogs.openUpload}
              disabledReason={writeLockReason}>
              Upload
            </Button>
          </div>
        )}
      </div>

      {/* Mobile bottom action bar (writable only) — New folder + Upload, ≥44px
          . Same handlers as the top-toolbar buttons. */}
      {writable && isMobile && (
        <MobileActionBar ariaLabel="File actions">
          {/* Mount-gated into the bar rather than CSS-hidden, so exactly one
              instance of each control exists in the DOM at any width. */}
          {restoreEnabled && (
            <RestoreArchiveButton
              onClick={restore.openDialog}
              fullWidth
            />
          )}
          <Button
            variant="default"
            className="!h-11 flex-1"
            onClick={dialogs.toggleCreateFolder}
            disabled={isBusy}
            disabledReason={writeLockReason}>
            New folder
          </Button>
          <Button
            variant="primary"
            className="!h-11 flex-1"
            onClick={dialogs.openUpload}
            disabledReason={writeLockReason}>
            Upload
          </Button>
        </MobileActionBar>
      )}

      {/* The explanation, where a `title` cannot be one: a tooltip needs a
          hover, so on touch — and at the 400px width this feature's own live check is run at —
          the greyed controls above would say nothing at all. Rendered once for the folder rather
          than per control, because it is a fact about where you are standing. */}
      {writeLockReason && (
        <div
          role="note"
          className="mb-4 rounded-lg border border-border bg-surface-2 p-3 text-sm text-text-2">
          {writeLockReason}
        </div>
      )}

      {/* Write controls — create folder (modal dialog); file uploads go
          to the upload queue. Hidden in read-only (dev-unauth) mode. */}
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

          {/* Folder-name collision — Overwrite or pick a new name */}
          {pendingCollision && (
            <CollisionPrompt
              kind={pendingCollision.kind}
              name={pendingCollision.label}
              onOverwrite={() => pendingCollision.retry({overwrite: true})}
              onRename={(newName) => pendingCollision.retry({rename: newName})}
              onCancel={cancelCollision}
            />
          )}

          {/* Create-folder error */}
          {writeError && (
            <Banner
              variant="danger"
              onDismiss={dismissError}
              className="mb-4">
              {writeError}
            </Banner>
          )}

          {/* Add-files drawer — the dropzone enqueues onto the
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

      {/* Download error — dismissible, non-blocking */}
      {dl.error && (
        <Banner
          variant="danger"
          onDismiss={dl.dismissError}
          className="mb-4">
          {dl.error}
        </Banner>
      )}

      {/* Delete / move / copy feedback:
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
        {/* Rename collision — Overwrite or pick a new name. Not part
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

      {/* Mounted here rather than in FileBrowserDialogs because its state is this
          component's (the selection it sends, and the space it sends from), and threading both
          through the dialogs bundle would give that file a second reason to change. */}
      {send.items && send.items.length > 0 && (
        <SendFilesDialog
          items={send.items}
          busy={send.busy}
          submitError={send.error}
          onSubmit={async (recipients) => {
            // The selection is cleared only on the way OUT of a SUCCESSFUL send — and the
            // answer comes from the call, not from `send.error`, which in this closure is the
            // value from before the submit. Reading it here cleared the selection under a
            // dialog whose retry then had nothing to send (caught by the journey test).
            if (await send.submit(recipients)) selection.clear();
          }}
          onCancel={send.close}
        />
      )}

      {/* Mounted here for the same reason the send dialog is: their state is this
          component's — the selection being archived, and the space both modes resolve. */}
      {archive.items && archive.items.length > 0 && (
        <ArchiveDialog
          items={archive.items}
          rootPrefix={rootPrefix}
          busy={archive.busy}
          submitError={archive.error}
          onConfirm={async () => {
            // The selection clears and the listing is invalidated only on the way OUT of a
            // SUCCESSFUL enqueue, and the answer comes from the call rather than from
            // `archive.error`, which in this closure is the value from before the submit.
            if (await archive.submit()) {
              selection.clear();
              // `refresh` IS `invalidateListing` for this prefix. The archive has only
              // been enqueued, so the listing will not have changed yet — invalidating anyway is
              // the cheapest way to be right whenever the user comes back to the folder.
              refreshListing();
            }
          }}
          onCancel={archive.close}
        />
      )}

      {restore.open && space && (
        <RestoreArchiveDialog
          spaceLabel={rootLabel ?? space.name}
          busy={restore.busy}
          submitError={restore.error}
          onSubmit={(archiveId) => void restore.submit(archiveId)}
          onCancel={restore.close}
        />
      )}

      {/* Selection toolbar — select all +
          bulk send/copy/move/delete + the single-item data-quality check */}
      {canModify && hasContent && (
        <SelectionToolbar
          allItems={allItems}
          onRequestDelete={dialogs.openConfirmDelete}
          onRequestMove={dialogs.openMove}
          onRequestCopy={dialogs.openCopy}
          onRequestQualityCheck={username && dataQualityEnabled ? dialogs.openQualityCheck : undefined}
          onRequestSend={
            username && filesEnabled
              ? () =>
                  send.open(
                    [...selection.selected.values()].map((item) =>
                      item.type === 'file'
                        ? ({kind: 'file', key: item.key} as const)
                        : ({kind: 'folder', key: item.prefix} as const)
                    )
                  )
              : undefined
          }
          onRequestArchive={
            archiveEnabled ? () => archive.open([...selection.selected.values()].map(toArchiveItem)) : undefined
          }
          archiveDisabledReason={archiveRefusal(selectedItems.map(toArchiveItem), rootPrefix) ?? undefined}
          writeLockReason={writeLockReason}
          // The service refuses these too, but only after the user has read the
          // "everything inside it … can't be undone" confirm and pressed Delete.
          deleteDisabledReason={undeletableSelectionRefusal(selectedItems, rootPrefix, 'delete') ?? undefined}
          moveDisabledReason={undeletableSelectionRefusal(selectedItems, rootPrefix, 'move') ?? undefined}
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
          renders the list so its `..` row is reachable. */}
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
          `..` row stays reachable. Structural markup swap (
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
        username={username}
        spaceKind={spaceKind}
        destinations={destinations}
        canModify={canModify}
        onRequestArchiveFile={archiveEnabled ? (file) => archive.open([{kind: 'file', key: file.key}]) : undefined}
        onRequestArchiveFolder={
          archiveEnabled ? (folder) => archive.open([{kind: 'folder', key: folder.prefix}]) : undefined
        }
        archiveRefusalFor={(key: string, kind: 'file' | 'folder') =>
          archiveRefusal([{kind, key}], rootPrefix) ?? undefined
        }
        writeLockReason={writeLockReason}
        selectedItems={selectedItems}
        del={del}
        move={move}
        copy={copy}
      />

      {/* Load more — only when the current prefix has further pages */}
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
// clears the selection, and so the content can consume
// useSelection() as a descendant.
export function FileBrowser({
  bucket,
  prefix: prefixProp = '',
  rootPrefix: rootPrefixProp,
  rootLabel,
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
