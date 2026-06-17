import { useState } from 'react';
import { Button } from '../../components/Button';
import { Badge } from '../../components/Badge';
import { Banner } from '../../components/Banner';
import { useFileBrowser } from './useFileBrowser';
import { useFileUpload } from './useFileUpload';
import { useDelete } from './useDelete';
import { useMove } from './useMove';
import { getDownloadUrl } from './fileBrowser.service';
import { UploadDropzone } from './UploadDropzone';
import { UploadDrawer } from './UploadDrawer';
import { UploadQueueProvider } from './UploadQueueProvider';
import { UploadQueuePanel } from './UploadQueuePanel';
import { useUploadQueue } from './uploadQueueContext';
import { CreateFolderDialog } from './CreateFolderDialog';
import { CollisionPrompt } from './CollisionPrompt';
import { MetadataPanel } from './MetadataPanel';
import { DeleteConfirmDialog } from './DeleteConfirmDialog';
import { RenameDialog } from './RenameDialog';
import { MoveDialog } from './MoveDialog';
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

function formatSize(bytes: number): string {
  if (bytes < 1_024) return `${bytes} B`;
  if (bytes < 1_048_576) return `${(bytes / 1_024).toFixed(1)} KB`;
  if (bytes < 1_073_741_824) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  return `${(bytes / 1_073_741_824).toFixed(1)} GB`;
}

function formatDate(date: Date): string {
  return date.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

// Last path segment of a key/prefix, for naming items in result messages.
function lastSegment(keyOrPrefix: string): string {
  return keyOrPrefix.replace(/\/$/, '').split('/').pop() ?? keyOrPrefix;
}

// Type-pill label: uppercased extension (e.g. "PDF", "TXT") or "File" if none.
function fileExtension(name: string): string {
  const dot = name.lastIndexOf('.');
  if (dot <= 0 || dot === name.length - 1) return 'File';
  return name.slice(dot + 1).toUpperCase();
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

// ─── Sub-components ──────────────────────────────────────────────────────────

function FolderRow({
  folder,
  onClick,
  selectable,
  isSelected,
  onToggleSelect,
  onRename,
}: {
  folder: S3FolderItem;
  onClick: () => void;
  selectable: boolean;
  isSelected: boolean;
  onToggleSelect: () => void;
  onRename?: () => void;
}) {
  return (
    <li
      className={`group relative flex h-12 items-center border-b border-border-2 last:border-0 ${
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
        className="flex min-w-0 flex-1 items-center gap-2.5 px-4 text-left focus-visible:outline-none"
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
      {onRename && (
        <span
          className={`absolute inset-y-0 right-2 flex items-center gap-1 pl-3 opacity-0 transition-opacity group-hover:opacity-100 ${
            isSelected ? 'bg-accent-soft' : 'bg-surface-2'
          }`}
        >
          <button
            className="h-7 rounded-md px-2 text-sm text-text-2 hover:bg-surface-2 hover:text-text focus-visible:outline-none"
            onClick={onRename}
            aria-label={`Rename folder ${folder.name}`}
          >
            Rename
          </button>
        </span>
      )}
    </li>
  );
}

function FileRow({
  file,
  onDownload,
  onDetails,
  onRename,
  isDownloading,
  selectable,
  isSelected,
  onToggleSelect,
}: {
  file: S3FileItem;
  onDownload: (file: S3FileItem) => void;
  onDetails: (file: S3FileItem) => void;
  onRename?: () => void;
  isDownloading: boolean;
  selectable: boolean;
  isSelected: boolean;
  onToggleSelect: () => void;
}) {
  return (
    <li
      className={`group relative flex h-12 items-center border-b border-border-2 last:border-0 ${
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
      <span
        className={`absolute inset-y-0 right-2 flex items-center gap-1 pl-3 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100 ${
          isSelected ? 'bg-accent-soft' : 'bg-surface-2'
        }`}
      >
        <button
          className="h-7 rounded-md px-2 text-sm text-text-2 hover:bg-surface-2 hover:text-text focus-visible:outline-none"
          onClick={() => onDetails(file)}
          aria-label={`Details for ${file.name}`}
        >
          Details
        </button>
        {onRename && (
          <button
            className="h-7 rounded-md px-2 text-sm text-text-2 hover:bg-surface-2 hover:text-text focus-visible:outline-none"
            onClick={onRename}
            aria-label={`Rename ${file.name}`}
          >
            Rename
          </button>
        )}
        <button
          className="h-7 rounded-md px-2 text-sm text-accent-text hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none"
          onClick={() => onDownload(file)}
          disabled={isDownloading}
          aria-label={`Download ${file.name}`}
        >
          {isDownloading ? '…' : 'Download'}
        </button>
      </span>
    </li>
  );
}

// ─── Selection toolbar (SPEC-018 FR-001 UI / FR-004) ──────────────────────────

function SelectionToolbar({
  allItems,
  onRequestDelete,
  onRequestMove,
  isBusy,
}: {
  allItems: SelectableItem[];
  onRequestDelete: () => void;
  onRequestMove: () => void;
  isBusy: boolean;
}) {
  const { count, isSelected, selectAll, clear } = useSelection();

  const allSelected =
    allItems.length > 0 && allItems.every((i) => isSelected(itemId(i)));
  const someSelected = allItems.some((i) => isSelected(itemId(i)));

  const active = count > 0;

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
        onClick={onRequestMove}
        disabled={count === 0 || isBusy}
      >
        Move
      </Button>

      <Button
        variant="ghost"
        size="sm"
        className="!text-danger hover:!bg-danger-soft hover:!text-danger"
        onClick={onRequestDelete}
        disabled={count === 0 || isBusy}
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
  const { files, folders, isLoading, error, hasMore, loadMore, isLoadingMore } =
    useFileBrowser(bucket, prefix, markerKey);

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

      {/* Write controls — create folder inline (SPEC-016); file uploads go to the
          SPEC-020 queue. Hidden in read-only (dev-unauth) mode. */}
      {writable && (
        <>
          {creatingFolder && (
            <div className="mb-4">
              <CreateFolderDialog
                onCreate={(name) => {
                  setCreatingFolder(false);
                  createNewFolder(name);
                }}
                onCancel={() => setCreatingFolder(false)}
              />
            </div>
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
        <Banner
          variant={del.summary.errors.length === 0 ? 'success' : 'warning'}
          role="status"
          onDismiss={del.dismissSummary}
          className="mb-4"
          title={`Deleted ${del.summary.deletedCount} ${del.summary.deletedCount === 1 ? 'item' : 'items'}.`}
        >
          {del.summary.errors.length > 0 && (
            <>
              <p className="mt-1">
                Could not delete {del.summary.errors.length}:
              </p>
              <ul className="mt-1 list-disc pl-5">
                {del.summary.errors.map((e) => (
                  <li key={e.key}>
                    {lastSegment(e.key)} — {e.message}
                  </li>
                ))}
              </ul>
            </>
          )}
        </Banner>
      )}

      {/* Move systemic error (SPEC-019 FR-004) — dismissible */}
      {move.error && (
        <Banner variant="danger" onDismiss={move.dismissError} className="mb-4">
          {move.error}
        </Banner>
      )}

      {/* Move result (SPEC-019 FR-004) — success count + any partial failures */}
      {move.summary && (
        <Banner
          variant={move.summary.errors.length === 0 ? 'success' : 'warning'}
          role="status"
          onDismiss={move.dismissSummary}
          className="mb-4"
          title={`Moved ${move.summary.movedCount} ${move.summary.movedCount === 1 ? 'item' : 'items'}.`}
        >
          {move.summary.errors.length > 0 && (
            <>
              <p className="mt-1">Could not move {move.summary.errors.length}:</p>
              <ul className="mt-1 list-disc pl-5">
                {move.summary.errors.map((e) => (
                  <li key={e.key}>
                    {lastSegment(e.key)} — {e.message}
                  </li>
                ))}
              </ul>
            </>
          )}
        </Banner>
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
        <div
          role="alertdialog"
          aria-label="Destination already has items"
          className="mb-4 rounded-lg border border-warning-soft bg-warning-soft p-4 text-sm text-warning"
        >
          <p className="font-medium">
            {move.moveCollision.count} item(s) already exist at the destination.
          </p>
          <div className="mt-3 flex gap-2">
            <Button
              variant="danger"
              size="sm"
              onClick={move.moveCollision.onOverwriteAll}
            >
              Overwrite all
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={move.moveCollision.onCancel}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}

      {/* Selection toolbar (SPEC-018 + SPEC-019) — select all + bulk move/delete */}
      {canModify && hasContent && (
        <SelectionToolbar
          allItems={allItems}
          onRequestDelete={() => setConfirmOpen(true)}
          onRequestMove={() => setMoving([...selection.selected.values()])}
          isBusy={del.isDeleting || move.isBusy}
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
          {/* Column header */}
          <div className="flex h-10 items-center border-b border-border bg-surface-2 text-xs font-semibold uppercase tracking-wide text-text-3">
            {canModify && <span className="w-10 flex-shrink-0" />}
            <span className="min-w-0 flex-1 px-4">Name</span>
            <span className={`${COL_SIZE} pr-4 text-right`}>Size</span>
            <span className={`${COL_MODIFIED} pr-4 text-right`}>Modified</span>
            <span className={`${COL_TYPE} pr-4 text-right`}>Type</span>
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
              onRename={
                canModify
                  ? () =>
                      setRenaming({
                        item: { type: 'folder', prefix: folder.prefix },
                        name: folder.name,
                        kind: 'folder',
                      })
                  : undefined
              }
            />
          ))}
          {files.map((file) => (
            <FileRow
              key={file.key}
              file={file}
              onDownload={handleDownload}
              onDetails={setDetailsFile}
              isDownloading={downloadingKey === file.key}
              selectable={canModify}
              isSelected={selection.isSelected(file.key)}
              onToggleSelect={() =>
                selection.toggle({ type: 'file', key: file.key })
              }
              onRename={
                canModify
                  ? () =>
                      setRenaming({
                        item: { type: 'file', key: file.key },
                        name: file.name,
                        kind: 'file',
                      })
                  : undefined
              }
            />
          ))}
          </ul>
        </div>
      )}

      {/* Metadata drawer (SPEC-017) — non-blocking; closes via button or Escape */}
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

      {/* Load more — only when the current prefix has further pages (SPEC-015) */}
      {hasContent && hasMore && (
        <div className="mt-4 flex justify-center">
          <button
            className="h-9 rounded-md border border-border px-4 text-sm font-medium text-text-2 hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-45 focus-visible:outline-none"
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
