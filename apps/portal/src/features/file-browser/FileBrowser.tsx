import { useState } from 'react';
import { Button } from '../../components/Button';
import { Badge } from '../../components/Badge';
import { Banner } from '../../components/Banner';
import { useFileBrowser } from './useFileBrowser';
import { useFileUpload } from './useFileUpload';
import { useDelete } from './useDelete';
import { useMove } from './useMove';
import { useCopy } from './useCopy';
import { getDownloadUrl } from './fileBrowser.service';
import { formatSize } from './fileBrowser.format';
import { lastSegment, fileExtension } from './fileBrowser.paths';
import { UploadDropzone } from './UploadDropzone';
import { UploadDrawer } from './UploadDrawer';
import { UploadQueueProvider } from './UploadQueueProvider';
import { UploadQueuePanel } from './UploadQueuePanel';
import { useUploadQueue } from './uploadQueueContext';
import { CreateFolderDialog } from './CreateFolderDialog';
import { CollisionPrompt } from './CollisionPrompt';
import { MetadataPanel } from './MetadataPanel';
import { HIDDEN_BROWSER_FOLDERS, isRootFolderNamed } from './protectedFolders';
import { DeleteConfirmDialog } from './DeleteConfirmDialog';
import { OperationSummaryBanner } from './OperationSummaryBanner';
import { BatchOverwritePrompt } from './BatchOverwritePrompt';
import { RenameDialog } from './RenameDialog';
import { MoveDialog } from './MoveDialog';
import { CopyDialog } from './CopyDialog';
import { SelectionProvider } from './SelectionProvider';
import { useSelection, itemId, type SelectableItem } from './selectionContext';
import type { S3FileItem, S3FolderItem } from '../../types/s3.types';

// Open a presigned URL so the browser saves the file. `ResponseContentDisposition`
// (set on the URL) makes S3 return it as an attachment with the real filename, so
// a plain anchor click downloads rather than navigates. Survives the await before
// it because it's a programmatic download, not a popup.
function triggerBrowserDownload(url: string): void {
  const a = document.createElement('a');
  a.href = url;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// ─── Types ───────────────────────────────────────────────────────────────────

type Props = {
  bucket: string;
  prefix?: string;     // initial prefix; browser starts here on mount
  rootPrefix?: string; // navigation floor; defaults to prefix prop value
  rootLabel?: string;  // label for the root crumb; hides the raw prefix segment
                       // (e.g. "My Files" instead of the username) — SPEC-013
  markerKey?: string;  // exact key hidden from the listing — the prefix marker
                       // (SPEC-014 FR-002)
  writable?: boolean;  // show upload + create-folder controls (SPEC-016). Off in
                       // the dev-unauth path (no scoped write credentials).
  username?: string;   // authenticated username — required for delete's marker
                       // guard (SPEC-018). Present only in the authenticated flow.
};

type BreadcrumbItem = {
  label: string;
  prefix: string | undefined;
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function buildBreadcrumbs(
  prefix: string | undefined,
  rootPrefix: string,
  rootLabel?: string,
): BreadcrumbItem[] {
  if (!rootPrefix) {
    // No root clamping — standard Home-rooted breadcrumb
    const crumbs: BreadcrumbItem[] = [{ label: 'Home', prefix: undefined }];
    if (!prefix) return crumbs;

    const parts = prefix.split('/').filter(Boolean);
    parts.forEach((part, i) => {
      crumbs.push({
        label: part,
        prefix: parts.slice(0, i + 1).join('/') + '/',
      });
    });

    return crumbs;
  }

  // Root-clamped breadcrumb: show only segments at or below rootPrefix. The root
  // crumb uses rootLabel when provided (so the raw prefix segment — e.g. the
  // username — is never shown), otherwise the last path segment.
  const rootParts = rootPrefix.split('/').filter(Boolean);
  const label = rootLabel ?? rootParts[rootParts.length - 1] ?? rootPrefix;
  const crumbs: BreadcrumbItem[] = [{ label, prefix: rootPrefix }];

  if (!prefix || prefix === rootPrefix) return crumbs;

  const allParts = prefix.split('/').filter(Boolean);
  const subParts = allParts.slice(rootParts.length);
  subParts.forEach((part, i) => {
    crumbs.push({
      label: part,
      prefix: [...rootParts, ...subParts.slice(0, i + 1)].join('/') + '/',
    });
  });

  return crumbs;
}

function formatDate(date: Date): string {
  return date.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

// ─── Icons (inline, no icon library — SPEC-024) ───────────────────────────────

function FolderIcon({ className = 'h-5 w-5' }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="currentColor"
      className={`${className} flex-shrink-0 text-accent`}
      aria-hidden="true"
    >
      <path d="M2 6a2 2 0 012-2h3.586a1 1 0 01.707.293l1.414 1.414A1 1 0 0010.414 6H16a2 2 0 012 2v7a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
    </svg>
  );
}

function FileIcon({ className = 'h-5 w-5' }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      className={`${className} flex-shrink-0 text-text-3`}
      aria-hidden="true"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M13.5 3H7a2 2 0 00-2 2v10a2 2 0 002 2h6a2 2 0 002-2V7.5L13.5 3z"
      />
      <path strokeLinecap="round" strokeLinejoin="round" d="M13 3v4.5H17.5" />
    </svg>
  );
}

// Shared column widths so the header row and body rows line up.
const COL_SIZE = 'w-24';
const COL_MODIFIED = 'w-40';
const COL_TYPE = 'w-28';
// Trailing actions column. Files show an always-visible Details button (plus a
// Download button in read-only mode, where there's no selection toolbar). All
// other actions (move/copy/rename/delete/download) live in the selection toolbar.
const COL_ACTIONS = 'w-44';

// ─── Sub-components ──────────────────────────────────────────────────────────

function FolderRow({
  folder,
  onClick,
  selectable,
  isSelected,
  onToggleSelect,
}: {
  folder: S3FolderItem;
  onClick: () => void;
  selectable: boolean;
  isSelected: boolean;
  onToggleSelect: () => void;
}) {
  return (
    <li
      className={`flex h-12 items-center border-b border-border-2 last:border-0 ${
        isSelected ? 'bg-accent-soft' : 'hover:bg-surface-2'
      }`}
    >
      {selectable && (
        <span className="flex w-10 flex-shrink-0 items-center justify-center">
          <input
            type="checkbox"
            className="h-4 w-4 accent-accent"
            checked={isSelected}
            onChange={onToggleSelect}
            aria-label={`Select folder ${folder.name}`}
          />
        </span>
      )}
      <button
        className="flex min-w-0 flex-1 items-center gap-2.5 px-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent"
        onClick={onClick}
        aria-label={`Open folder ${folder.name}`}
      >
        <FolderIcon />
        <span className="truncate text-base font-medium text-text">
          {folder.name}
        </span>
      </button>
      <span className={`${COL_SIZE} pr-4 text-right text-sm text-text-3`}>—</span>
      <span className={`${COL_MODIFIED} pr-4 text-right text-sm text-text-2`} />
      <span className={`${COL_TYPE} pr-4 text-right`}>
        <Badge>Folder</Badge>
      </span>
      {/* Folders carry no per-row actions (Rename/Delete/Move/Copy live in the
          selection toolbar); empty cell keeps columns aligned with file rows. */}
      <span className={`${COL_ACTIONS} pr-4`} />
    </li>
  );
}

function FileRow({
  file,
  onDownload,
  onDetails,
  isDownloading,
  selectable,
  isSelected,
  onToggleSelect,
}: {
  file: S3FileItem;
  // Read-only fallback only: in the authenticated flow Download lives in the
  // selection toolbar, so this is undefined there and no row Download shows.
  onDownload?: (file: S3FileItem) => void;
  onDetails: (file: S3FileItem) => void;
  isDownloading: boolean;
  selectable: boolean;
  isSelected: boolean;
  onToggleSelect: () => void;
}) {
  return (
    <li
      className={`flex h-12 items-center border-b border-border-2 last:border-0 ${
        isSelected ? 'bg-accent-soft' : 'hover:bg-surface-2'
      }`}
    >
      {selectable && (
        <span className="flex w-10 flex-shrink-0 items-center justify-center">
          <input
            type="checkbox"
            className="h-4 w-4 accent-accent"
            checked={isSelected}
            onChange={onToggleSelect}
            aria-label={`Select ${file.name}`}
          />
        </span>
      )}
      <span className="flex min-w-0 flex-1 items-center gap-2.5 px-4">
        <FileIcon />
        <span className="truncate text-base font-medium text-text">
          {file.name}
        </span>
      </span>
      <span className={`${COL_SIZE} pr-4 text-right text-sm text-text-2`}>
        {formatSize(file.size)}
      </span>
      <span className={`${COL_MODIFIED} pr-4 text-right text-sm text-text-2`}>
        {formatDate(file.lastModified)}
      </span>
      <span className={`${COL_TYPE} pr-4 text-right`}>
        <Badge>{fileExtension(file.name)}</Badge>
      </span>
      {/* Always-visible Details (no hover menu). Download appears here only in
          read-only mode (no selection toolbar); otherwise it's a toolbar action. */}
      <span className={`${COL_ACTIONS} flex items-center justify-end gap-1 pr-4`}>
        <button
          className="h-7 rounded-md px-2 text-sm text-text-2 hover:bg-surface-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          onClick={() => onDetails(file)}
          aria-label={`Details for ${file.name}`}
        >
          Details
        </button>
        {onDownload && (
          <button
            className="h-7 rounded-md px-2 text-sm text-accent-text hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            onClick={() => onDownload(file)}
            disabled={isDownloading}
            aria-label={`Download ${file.name}`}
          >
            {isDownloading ? '…' : 'Download'}
          </button>
        )}
      </span>
    </li>
  );
}

// ─── Selection toolbar (SPEC-018 FR-001 UI / FR-004) ──────────────────────────

function SelectionToolbar({
  allItems,
  onRequestDelete,
  onRequestMove,
  onRequestCopy,
  onRequestRename,
  onRequestDownload,
  isBusy,
}: {
  allItems: SelectableItem[];
  onRequestDelete: () => void;
  onRequestMove: () => void;
  onRequestCopy: () => void;
  onRequestRename: () => void;
  onRequestDownload: () => void;
  isBusy: boolean;
}) {
  const { count, selected, isSelected, selectAll, clear } = useSelection();

  const allSelected =
    allItems.length > 0 && allItems.every((i) => isSelected(itemId(i)));
  const someSelected = allItems.some((i) => isSelected(itemId(i)));

  const active = count > 0;

  // Single-item actions: Rename targets one item (you can't rename many to one
  // name); Download is a single file at a time (folders aren't downloadable).
  const single = count === 1 ? [...selected.values()][0] : null;
  const canRename = single !== null;
  const canDownload = single?.type === 'file';

  return (
    <div
      className={`mb-4 flex h-11 items-center gap-3 rounded-lg border px-4 ${
        active
          ? 'border-accent bg-accent-soft'
          : 'border-border bg-surface'
      }`}
    >
      <input
        type="checkbox"
        className="h-4 w-4 accent-accent"
        checked={allSelected}
        ref={(el) => {
          if (el) el.indeterminate = someSelected && !allSelected;
        }}
        onChange={() => (allSelected ? clear() : selectAll(allItems))}
        aria-label="Select all"
      />

      <span
        aria-live="polite"
        className={`text-sm font-semibold ${active ? 'text-accent-text' : 'text-text-3'}`}
      >
        {active ? `${count} selected` : 'Select all'}
      </span>

      <div className="flex-1" />

      <Button
        variant="ghost"
        size="sm"
        onClick={onRequestDownload}
        disabled={!canDownload || isBusy}
        aria-label="Download selected items"
      >
        Download
      </Button>

      <Button
        variant="ghost"
        size="sm"
        onClick={onRequestCopy}
        disabled={count === 0 || isBusy}
        aria-label="Copy selected items"
      >
        Copy
      </Button>

      <Button
        variant="ghost"
        size="sm"
        onClick={onRequestMove}
        disabled={count === 0 || isBusy}
        aria-label="Move selected items"
      >
        Move
      </Button>

      <Button
        variant="ghost"
        size="sm"
        onClick={onRequestRename}
        disabled={!canRename || isBusy}
        aria-label="Rename selected item"
      >
        Rename
      </Button>

      <Button
        variant="ghost"
        size="sm"
        className="!text-danger hover:!bg-danger-soft hover:!text-danger"
        onClick={onRequestDelete}
        disabled={count === 0 || isBusy}
        aria-label="Delete selected items"
      >
        Delete
      </Button>
    </div>
  );
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
  markerKey,
  writable = false,
  username,
  prefix,
  setPrefix,
}: ContentProps) {
  const {
    files,
    folders: allFolders,
    isLoading,
    error,
    hasMore,
    loadMore,
    isLoadingMore,
  } = useFileBrowser(bucket, prefix, markerKey);

  // Hide app-managed root folders (e.g. user_settings/) from the listing so they
  // never surface to users; everything downstream uses the filtered list.
  const folders = allFolders.filter(
    (f) => !isRootFolderNamed(f.prefix, rootPrefix, HIDDEN_BROWSER_FOLDERS),
  );

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
    dismissError,
  } = useFileUpload(bucket, currentPrefix);
  // Multi-file upload queue (SPEC-020) — enqueue from the dropzone; progress,
  // cancel, and per-file collisions live in the non-blocking UploadQueuePanel.
  const { enqueue } = useUploadQueue();
  const [creatingFolder, setCreatingFolder] = useState(false);
  // Upload drawer (right slide-over) — the "add files" surface only.
  const [uploadOpen, setUploadOpen] = useState(false);

  // Multi-select + delete (SPEC-018). Selection comes from the surrounding
  // SelectionProvider; delete is only offered in the authenticated, writable flow
  // (a username is required for the marker guard).
  const selection = useSelection();
  const del = useDelete(bucket, currentPrefix, username);
  const move = useMove(bucket, currentPrefix, username);
  const copy = useCopy(bucket, currentPrefix, username);
  const canModify = writable && !!username;
  const [confirmOpen, setConfirmOpen] = useState(false);
  // The item being renamed (null = closed) and the items being moved (null = no
  // move dialog). Move is selection-driven (like delete); rename is per-row.
  const [renaming, setRenaming] = useState<{
    item: SelectableItem;
    name: string;
    kind: 'file' | 'folder';
  } | null>(null);
  const [moving, setMoving] = useState<SelectableItem[] | null>(null);
  // The items being copied (null = no copy dialog). Like move, selection- or
  // row-driven. Stays open across the same-folder name prompt (SPEC-039 FR-003).
  const [copying, setCopying] = useState<SelectableItem[] | null>(null);

  // Per-file download (SPEC-015 FR-003). Tracks the key being signed so its row
  // shows a busy state; surfaces a ServiceResult failure inline rather than
  // throwing. The hidden marker is filtered out, so it never exposes this action.
  const [downloadingKey, setDownloadingKey] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  // SPEC-017: the file whose read-only metadata drawer is open (null = closed).
  // Only files reach this — folders use FolderRow and the prefix marker is
  // already filtered out of `files`, so neither exposes a Details action.
  const [detailsFile, setDetailsFile] = useState<S3FileItem | null>(null);

  async function handleDownload(file: S3FileItem) {
    setDownloadingKey(file.key);
    setDownloadError(null);
    const result = await getDownloadUrl({ bucket, key: file.key, fileName: file.name });
    setDownloadingKey(null);
    if (result.success) {
      triggerBrowserDownload(result.data.url);
    } else {
      setDownloadError(`Could not download ${file.name}: ${result.error.message}`);
    }
  }

  async function handleConfirmDelete() {
    const items = [...selection.selected.values()];
    await del.runDelete(items);
    selection.clear();
    setConfirmOpen(false);
  }

  function handleConfirmMove(destPrefix: string) {
    const items = moving ?? [];
    setMoving(null);
    selection.clear();
    move.moveItems(items, destPrefix);
  }

  function handleConfirmCopy(destPrefix: string) {
    const items = copying ?? [];
    // A same-folder copy (destination = current parent) opens the editable
    // auto-number prompt inside the dialog (FR-003), so the dialog must stay open
    // — only close it for the ordinary different-folder case.
    const sameFolder = destPrefix === currentPrefix;
    if (!sameFolder) {
      setCopying(null);
      selection.clear();
    }
    copy.copyItems(items, destPrefix);
  }

  // Toolbar Rename (single selection): resolve the selected item's display name
  // so the dialog can pre-fill it, then open the rename dialog.
  function handleRequestRename() {
    const items = [...selection.selected.values()];
    if (items.length !== 1) return;
    const item = items[0];
    if (item.type === 'file') {
      const f = files.find((x) => x.key === item.key);
      setRenaming({ item, name: f?.name ?? lastSegment(item.key), kind: 'file' });
    } else {
      const f = folders.find((x) => x.prefix === item.prefix);
      setRenaming({
        item,
        name: f?.name ?? lastSegment(item.prefix),
        kind: 'folder',
      });
    }
  }

  // Toolbar Download (single file): look up the selected file and download it.
  function handleRequestDownload() {
    const items = [...selection.selected.values()];
    if (items.length !== 1 || items[0].type !== 'file') return;
    const item = items[0];
    const f = files.find((x) => x.key === item.key);
    if (f) void handleDownload(f);
  }

  const breadcrumbs = buildBreadcrumbs(prefix, rootPrefix, rootLabel);
  const destinationLabel = breadcrumbs[breadcrumbs.length - 1]?.label;
  const isEmpty =
    !isLoading && error === null && files.length === 0 && folders.length === 0;
  const hasContent =
    !isLoading && error === null && (files.length > 0 || folders.length > 0);

  // Every selectable row in the current view, for the header "select all".
  const allItems: SelectableItem[] = [
    ...folders.map((f) => ({ type: 'folder' as const, prefix: f.prefix })),
    ...files.map((f) => ({ type: 'file' as const, key: f.key })),
  ];
  const selectedItems = [...selection.selected.values()];

  return (
    <div>
      {/* Toolbar row — breadcrumbs (left) + primary actions (right). FR-002/003 */}
      <div className="mb-4 flex items-center gap-3">
        <nav aria-label="breadcrumb" className="min-w-0 flex-1">
          <ol className="flex items-center gap-1 text-sm">
            {breadcrumbs.map((crumb, i) => {
              const isLast = i === breadcrumbs.length - 1;
              return (
                <li key={crumb.prefix ?? 'root'} className="flex items-center gap-1">
                  {i > 0 && (
                    <span aria-hidden="true" className="mx-0.5 text-text-3">
                      /
                    </span>
                  )}
                  {isLast ? (
                    <span
                      aria-current="page"
                      className="max-w-[200px] truncate font-semibold text-text"
                    >
                      {crumb.label}
                    </span>
                  ) : (
                    <button
                      className="max-w-[160px] truncate text-text-2 hover:text-text hover:underline"
                      onClick={() => setPrefix(crumb.prefix)}
                    >
                      {crumb.label}
                    </button>
                  )}
                </li>
              );
            })}
          </ol>
        </nav>

        {writable && (
          <>
            <Button
              variant="default"
              className="flex-shrink-0"
              onClick={() => setCreatingFolder((v) => !v)}
              disabled={isBusy}
            >
              New folder
            </Button>
            <Button
              variant="primary"
              className="flex-shrink-0"
              onClick={() => setUploadOpen(true)}
            >
              Upload
            </Button>
          </>
        )}
      </div>

      {/* Write controls — create folder (modal dialog, SPEC-016); file uploads go
          to the SPEC-020 queue. Hidden in read-only (dev-unauth) mode. */}
      {writable && (
        <>
          {creatingFolder && (
            <CreateFolderDialog
              onCreate={(name) => {
                setCreatingFolder(false);
                createNewFolder(name);
              }}
              onCancel={() => setCreatingFolder(false)}
            />
          )}

          {/* Folder-name collision (SPEC-016) — Overwrite or pick a new name */}
          {pendingCollision && (
            <CollisionPrompt
              kind={pendingCollision.kind}
              name={pendingCollision.label}
              onOverwrite={() => pendingCollision.retry({ overwrite: true })}
              onRename={(newName) => pendingCollision.retry({ rename: newName })}
              onCancel={cancelCollision}
            />
          )}

          {/* Create-folder error (SPEC-016) */}
          {writeError && (
            <Banner variant="danger" onDismiss={dismissError} className="mb-4">
              {writeError}
            </Banner>
          )}

          {/* Add-files drawer (SPEC-020) — enqueues onto the upload queue, then
              closes so the non-blocking queue panel takes over. */}
          <UploadDrawer
            open={uploadOpen}
            onClose={() => setUploadOpen(false)}
            destinationLabel={destinationLabel}
          >
            <UploadDropzone
              onFiles={(files) => {
                enqueue(files);
                setUploadOpen(false);
              }}
            />
          </UploadDrawer>
        </>
      )}

      {/* Download error (SPEC-015) — dismissible, non-blocking */}
      {downloadError && (
        <Banner
          variant="danger"
          onDismiss={() => setDownloadError(null)}
          className="mb-4"
        >
          {downloadError}
        </Banner>
      )}

      {/* Delete systemic error (SPEC-018 FR-004) — dismissible */}
      {del.error && (
        <Banner variant="danger" onDismiss={del.dismissError} className="mb-4">
          {del.error}
        </Banner>
      )}

      {/* Delete result (SPEC-018 FR-004) — success count + any partial failures */}
      {del.summary && (
        <OperationSummaryBanner
          pastVerb="Deleted"
          failVerb="delete"
          count={del.summary.deletedCount}
          errors={del.summary.errors.map((e) => ({
            label: lastSegment(e.key),
            message: e.message,
          }))}
          onDismiss={del.dismissSummary}
        />
      )}

      {/* Move systemic error (SPEC-019 FR-004) — dismissible */}
      {move.error && (
        <Banner variant="danger" onDismiss={move.dismissError} className="mb-4">
          {move.error}
        </Banner>
      )}

      {/* Move result (SPEC-019 FR-004) — success count + any partial failures */}
      {move.summary && (
        <OperationSummaryBanner
          pastVerb="Moved"
          failVerb="move"
          count={move.summary.movedCount}
          errors={move.summary.errors.map((e) => ({
            label: lastSegment(e.key),
            message: e.message,
          }))}
          onDismiss={move.dismissSummary}
        />
      )}

      {/* Move progress for large folders (SPEC-019 FR-004) */}
      {move.isBusy && move.progress !== null && (
        <div role="status" className="mb-4 text-sm text-text-2">
          Moving… {move.progress}%
        </div>
      )}

      {/* Rename collision (SPEC-019 FR-005) — Overwrite or pick a new name */}
      {move.renameCollision && (
        <CollisionPrompt
          kind={move.renameCollision.kind}
          name={move.renameCollision.label}
          onOverwrite={move.renameCollision.onOverwrite}
          onRename={move.renameCollision.onRename}
          onCancel={move.renameCollision.onCancel}
        />
      )}

      {/* Move collision (SPEC-019 FR-005) — one Overwrite-all/Cancel for the batch */}
      {move.moveCollision && (
        <BatchOverwritePrompt
          count={move.moveCollision.count}
          onOverwriteAll={move.moveCollision.onOverwriteAll}
          onCancel={move.moveCollision.onCancel}
        />
      )}

      {/* Copy systemic error (SPEC-039 FR-004) — dismissible */}
      {copy.error && (
        <Banner variant="danger" onDismiss={copy.dismissError} className="mb-4">
          {copy.error}
        </Banner>
      )}

      {/* Copy result (SPEC-039 FR-004) — success count + any partial failures */}
      {copy.summary && (
        <OperationSummaryBanner
          pastVerb="Copied"
          failVerb="copy"
          count={copy.summary.copiedCount}
          errors={copy.summary.errors.map((e) => ({
            label: lastSegment(e.item),
            message: e.message,
          }))}
          onDismiss={copy.dismissSummary}
        />
      )}

      {/* Copy progress for large folders (SPEC-039 FR-004) */}
      {copy.isBusy && copy.progress !== null && (
        <div role="status" className="mb-4 text-sm text-text-2">
          Copying… {copy.progress}%
        </div>
      )}

      {/* Copy collision (SPEC-039 FR-005) — one Overwrite-all/Cancel for the batch */}
      {copy.copyCollision && (
        <BatchOverwritePrompt
          count={copy.copyCollision.count}
          onOverwriteAll={copy.copyCollision.onOverwriteAll}
          onCancel={copy.copyCollision.onCancel}
        />
      )}

      {/* Selection toolbar (SPEC-018 + SPEC-019 + SPEC-039) — select all + bulk copy/move/delete */}
      {canModify && hasContent && (
        <SelectionToolbar
          allItems={allItems}
          onRequestDelete={() => setConfirmOpen(true)}
          onRequestMove={() => setMoving([...selection.selected.values()])}
          onRequestCopy={() => setCopying([...selection.selected.values()])}
          onRequestRename={handleRequestRename}
          onRequestDownload={handleRequestDownload}
          isBusy={
            del.isDeleting || move.isBusy || copy.isBusy || downloadingKey !== null
          }
        />
      )}

      {/* Loading */}
      {isLoading && (
        <div
          role="status"
          aria-label="Loading"
          className="flex items-center justify-center py-16 text-sm text-text-3"
        >
          <span>Loading…</span>
        </div>
      )}

      {/* Error */}
      {!isLoading && error !== null && (
        <div
          role="alert"
          className="rounded-lg border border-danger-soft bg-danger-soft p-4 text-danger"
        >
          <p className="font-medium">Failed to load files</p>
          <p className="mt-1 text-sm">{error}</p>
        </div>
      )}

      {/* Empty state */}
      {isEmpty && (
        <div className="py-16 text-center">
          <svg
            viewBox="0 0 40 40"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            className="mx-auto h-10 w-10 text-text-3"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M4 12a4 4 0 014-4h7.172a2 2 0 011.414.586l2.828 2.828A2 2 0 0020.828 12H32a4 4 0 014 4v12a4 4 0 01-4 4H8a4 4 0 01-4-4V12z"
            />
          </svg>
          <p className="mt-4 text-xl font-semibold text-text">
            This folder is empty
          </p>
          {writable && (
            <p className="mx-auto mt-2 max-w-xs text-sm text-text-2">
              Upload a file or create a folder to get started.
            </p>
          )}
        </div>
      )}

      {/* File and folder list */}
      {hasContent && (
        <div className="overflow-hidden rounded-lg border border-border bg-surface">
          {/* Column header — visual only; the labels are not programmatically
              tied to the list rows below, so hide this decorative row from AT
              (each row already exposes its own values as text). */}
          <div
            aria-hidden="true"
            className="flex h-10 items-center border-b border-border bg-surface-2 text-xs font-semibold uppercase tracking-wide text-text-3"
          >
            {canModify && <span className="w-10 flex-shrink-0" />}
            <span className="min-w-0 flex-1 px-4">Name</span>
            <span className={`${COL_SIZE} pr-4 text-right`}>Size</span>
            <span className={`${COL_MODIFIED} pr-4 text-right`}>Modified</span>
            <span className={`${COL_TYPE} pr-4 text-right`}>Type</span>
            <span className={`${COL_ACTIONS} pr-4`} />
          </div>
          <ul aria-label="File list">
          {folders.map((folder) => (
            <FolderRow
              key={folder.prefix}
              folder={folder}
              onClick={() => setPrefix(folder.prefix)}
              selectable={canModify}
              isSelected={selection.isSelected(folder.prefix)}
              onToggleSelect={() =>
                selection.toggle({ type: 'folder', prefix: folder.prefix })
              }
            />
          ))}
          {files.map((file) => (
            <FileRow
              key={file.key}
              file={file}
              // Read-only browse has no selection toolbar, so keep a per-row
              // Download there; the authenticated flow downloads from the toolbar.
              onDownload={canModify ? undefined : handleDownload}
              onDetails={setDetailsFile}
              isDownloading={downloadingKey === file.key}
              selectable={canModify}
              isSelected={selection.isSelected(file.key)}
              onToggleSelect={() =>
                selection.toggle({ type: 'file', key: file.key })
              }
            />
          ))}
          </ul>
        </div>
      )}

      {/* Metadata drawer (SPEC-017) — shared Drawer; closes via button, Escape, or backdrop */}
      {detailsFile && (
        <MetadataPanel
          bucket={bucket}
          file={detailsFile}
          rootPrefix={rootPrefix}
          onClose={() => setDetailsFile(null)}
        />
      )}

      {/* Delete confirmation (SPEC-018 FR-004) — modal; nothing deleted until confirmed */}
      {confirmOpen && (
        <DeleteConfirmDialog
          items={selectedItems}
          isDeleting={del.isDeleting}
          onConfirm={handleConfirmDelete}
          onCancel={() => setConfirmOpen(false)}
        />
      )}

      {/* Rename dialog (SPEC-019 FR-002) — modal */}
      {renaming && (
        <RenameDialog
          kind={renaming.kind}
          currentName={renaming.name}
          isBusy={move.isBusy}
          onRename={(newName) => {
            move.renameItem(renaming.item, newName);
            setRenaming(null);
          }}
          onCancel={() => setRenaming(null)}
        />
      )}

      {/* Move dialog (SPEC-019 FR-003) — destination-folder picker */}
      {moving && (
        <MoveDialog
          bucket={bucket}
          items={moving}
          rootPrefix={rootPrefix}
          rootLabel={rootLabel}
          currentPrefix={currentPrefix}
          markerKey={markerKey}
          isBusy={move.isBusy}
          onMove={handleConfirmMove}
          onCancel={() => setMoving(null)}
        />
      )}

      {/* Copy dialog (SPEC-039 FR-004) — destination picker + same-folder name
          field. Stays open across the same-folder auto-number prompt (FR-003);
          the prompt's confirm/cancel close the dialog (and clear the selection). */}
      {copying && (
        <CopyDialog
          bucket={bucket}
          items={copying}
          rootPrefix={rootPrefix}
          rootLabel={rootLabel}
          currentPrefix={currentPrefix}
          markerKey={markerKey}
          isBusy={copy.isBusy}
          sameFolderPrompt={
            copy.sameFolderPrompt && {
              ...copy.sameFolderPrompt,
              onConfirm: (name) => {
                copy.sameFolderPrompt?.onConfirm(name);
                setCopying(null);
                selection.clear();
              },
              onCancel: () => {
                copy.sameFolderPrompt?.onCancel();
                setCopying(null);
              },
            }
          }
          onCopy={handleConfirmCopy}
          onCancel={() => {
            copy.cancelCollision();
            setCopying(null);
          }}
        />
      )}

      {/* Load more — only when the current prefix has further pages (SPEC-015) */}
      {hasContent && hasMore && (
        <div className="mt-4 flex justify-center">
          <button
            className="h-9 rounded-md border border-border px-4 text-sm font-medium text-text-2 hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            onClick={loadMore}
            disabled={isLoadingMore}
          >
            {isLoadingMore ? 'Loading…' : 'Load more'}
          </button>
        </div>
      )}

      {/* Upload queue (SPEC-020) — non-blocking floating panel; self-hides empty */}
      {writable && <UploadQueuePanel />}
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
}: Props) {
  const rootPrefix = rootPrefixProp ?? prefixProp;
  const [prefix, setPrefix] = useState<string | undefined>(
    prefixProp || undefined,
  );

  return (
    <SelectionProvider prefix={prefix}>
      {/* Queue persists across prefix navigation (the content never remounts on
          navigate), so uploads keep running while the user browses (SPEC-020). */}
      <UploadQueueProvider bucket={bucket} prefix={prefix ?? ''}>
        <FileBrowserContent
          bucket={bucket}
          rootPrefix={rootPrefix}
          rootLabel={rootLabel}
          markerKey={markerKey}
          writable={writable}
          username={username}
          prefix={prefix}
          setPrefix={setPrefix}
        />
      </UploadQueueProvider>
    </SelectionProvider>
  );
}
