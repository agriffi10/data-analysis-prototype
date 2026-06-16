import { useState } from 'react';
import { useFileBrowser } from './useFileBrowser';
import { useFileUpload } from './useFileUpload';
import { useDelete } from './useDelete';
import { useMove } from './useMove';
import { getDownloadUrl } from './fileBrowser.service';
import { UploadDropzone } from './UploadDropzone';
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
    <li className="flex items-center border-b border-gray-100 last:border-0">
      {selectable && (
        <input
          type="checkbox"
          className="ml-4 h-4 w-4 rounded border-gray-300 text-blue-600 focus-visible:ring-2 focus-visible:ring-blue-500"
          checked={isSelected}
          onChange={onToggleSelect}
          aria-label={`Select folder ${folder.name}`}
        />
      )}
      <button
        className="flex flex-1 items-center gap-3 px-4 py-3 text-left hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500"
        onClick={onClick}
        aria-label={`Open folder ${folder.name}`}
      >
        <span aria-hidden="true">📁</span>
        <span className="flex-1 font-medium text-gray-800">{folder.name}</span>
        <span className="text-gray-400" aria-hidden="true">›</span>
      </button>
      {onRename && (
        <button
          className="mr-2 rounded px-2 py-1 text-sm font-medium text-gray-600 hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          onClick={onRename}
          aria-label={`Rename folder ${folder.name}`}
        >
          Rename
        </button>
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
    <li className="flex items-center gap-3 border-b border-gray-100 px-4 py-3 last:border-0">
      {selectable && (
        <input
          type="checkbox"
          className="h-4 w-4 rounded border-gray-300 text-blue-600 focus-visible:ring-2 focus-visible:ring-blue-500"
          checked={isSelected}
          onChange={onToggleSelect}
          aria-label={`Select ${file.name}`}
        />
      )}
      <span aria-hidden="true">📄</span>
      <span className="flex-1 text-gray-800">{file.name}</span>
      <span className="w-20 text-right text-sm text-gray-500">
        {formatSize(file.size)}
      </span>
      <span className="w-32 text-right text-sm text-gray-400">
        {formatDate(file.lastModified)}
      </span>
      <button
        className="rounded px-2 py-1 text-sm font-medium text-gray-600 hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
        onClick={() => onDetails(file)}
        aria-label={`Details for ${file.name}`}
      >
        Details
      </button>
      {onRename && (
        <button
          className="rounded px-2 py-1 text-sm font-medium text-gray-600 hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          onClick={onRename}
          aria-label={`Rename ${file.name}`}
        >
          Rename
        </button>
      )}
      <button
        className="rounded px-2 py-1 text-sm font-medium text-blue-600 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
        onClick={() => onDownload(file)}
        disabled={isDownloading}
        aria-label={`Download ${file.name}`}
      >
        {isDownloading ? 'Downloading…' : 'Download'}
      </button>
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

  return (
    <div className="mb-3 flex items-center gap-3 text-sm">
      <label className="flex items-center gap-2 text-gray-700">
        <input
          type="checkbox"
          className="h-4 w-4 rounded border-gray-300 text-blue-600 focus-visible:ring-2 focus-visible:ring-blue-500"
          checked={allSelected}
          ref={(el) => {
            if (el) el.indeterminate = someSelected && !allSelected;
          }}
          onChange={() => (allSelected ? clear() : selectAll(allItems))}
          aria-label="Select all"
        />
        Select all
      </label>

      <span aria-live="polite" className="text-gray-500">
        {count > 0 ? `${count} selected` : ''}
      </span>

      <button
        className="ml-auto rounded-lg border border-gray-300 px-3 py-1.5 font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
        onClick={onRequestMove}
        disabled={count === 0 || isBusy}
      >
        Move
      </button>

      <button
        className="rounded-lg border border-red-300 px-3 py-1.5 font-medium text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
        onClick={onRequestDelete}
        disabled={count === 0 || isBusy}
      >
        Delete
      </button>
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

  // Write operations (SPEC-016) scoped to the folder currently being viewed.
  const currentPrefix = prefix ?? '';
  const {
    progress,
    pendingCollision,
    error: writeError,
    isBusy,
    uploadOne,
    createNewFolder,
    cancelCollision,
    dismissError,
  } = useFileUpload(bucket, currentPrefix);
  const [creatingFolder, setCreatingFolder] = useState(false);

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
      {/* Breadcrumb */}
      <nav aria-label="breadcrumb" className="mb-4">
        <ol className="flex flex-wrap items-center gap-1 text-sm text-gray-600">
          {breadcrumbs.map((crumb, i) => {
            const isLast = i === breadcrumbs.length - 1;
            return (
              <li key={crumb.prefix ?? 'root'} className="flex items-center gap-1">
                {i > 0 && (
                  <span aria-hidden="true" className="text-gray-300">
                    /
                  </span>
                )}
                {isLast ? (
                  <span
                    aria-current="page"
                    className="font-medium text-gray-900"
                  >
                    {crumb.label}
                  </span>
                ) : (
                  <button
                    className="hover:text-blue-600 hover:underline"
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

      {/* Write controls (SPEC-016) — upload + create folder. Hidden in read-only
          (dev-unauth) mode. */}
      {writable && (
        <div className="mb-4">
          <div className="mb-3 flex gap-2">
            <button
              className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              onClick={() => setCreatingFolder((v) => !v)}
              disabled={isBusy}
            >
              New folder
            </button>
          </div>

          {creatingFolder && (
            <CreateFolderDialog
              onCreate={(name) => {
                setCreatingFolder(false);
                createNewFolder(name);
              }}
              onCancel={() => setCreatingFolder(false)}
            />
          )}

          {pendingCollision && (
            <CollisionPrompt
              kind={pendingCollision.kind}
              name={pendingCollision.label}
              onOverwrite={() => pendingCollision.retry({ overwrite: true })}
              onRename={(newName) => pendingCollision.retry({ rename: newName })}
              onCancel={cancelCollision}
            />
          )}

          {writeError && (
            <div
              role="alert"
              className="mb-4 flex items-start justify-between gap-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
            >
              <span>{writeError}</span>
              <button
                className="font-medium text-red-600 hover:underline"
                onClick={dismissError}
                aria-label="Dismiss upload error"
              >
                Dismiss
              </button>
            </div>
          )}

          <UploadDropzone
            onFile={uploadOne}
            progress={progress}
            disabled={isBusy && progress === null}
          />
        </div>
      )}

      {/* Download error (SPEC-015) — dismissible, non-blocking */}
      {downloadError && (
        <div
          role="alert"
          className="mb-4 flex items-start justify-between gap-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
        >
          <span>{downloadError}</span>
          <button
            className="font-medium text-red-600 hover:underline"
            onClick={() => setDownloadError(null)}
            aria-label="Dismiss download error"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Delete systemic error (SPEC-018 FR-004) — dismissible */}
      {del.error && (
        <div
          role="alert"
          className="mb-4 flex items-start justify-between gap-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
        >
          <span>{del.error}</span>
          <button
            className="font-medium text-red-600 hover:underline"
            onClick={del.dismissError}
            aria-label="Dismiss delete error"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Delete result (SPEC-018 FR-004) — success count + any partial failures */}
      {del.summary && (
        <div
          role="status"
          className={`mb-4 flex items-start justify-between gap-3 rounded-lg border p-3 text-sm ${
            del.summary.errors.length === 0
              ? 'border-green-200 bg-green-50 text-green-800'
              : 'border-amber-300 bg-amber-50 text-amber-900'
          }`}
        >
          <div>
            <p className="font-medium">
              Deleted {del.summary.deletedCount}{' '}
              {del.summary.deletedCount === 1 ? 'item' : 'items'}.
            </p>
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
          </div>
          <button
            className="font-medium hover:underline"
            onClick={del.dismissSummary}
            aria-label="Dismiss delete result"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Move systemic error (SPEC-019 FR-004) — dismissible */}
      {move.error && (
        <div
          role="alert"
          className="mb-4 flex items-start justify-between gap-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
        >
          <span>{move.error}</span>
          <button
            className="font-medium text-red-600 hover:underline"
            onClick={move.dismissError}
            aria-label="Dismiss move error"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Move result (SPEC-019 FR-004) — success count + any partial failures */}
      {move.summary && (
        <div
          role="status"
          className={`mb-4 flex items-start justify-between gap-3 rounded-lg border p-3 text-sm ${
            move.summary.errors.length === 0
              ? 'border-green-200 bg-green-50 text-green-800'
              : 'border-amber-300 bg-amber-50 text-amber-900'
          }`}
        >
          <div>
            <p className="font-medium">
              Moved {move.summary.movedCount}{' '}
              {move.summary.movedCount === 1 ? 'item' : 'items'}.
            </p>
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
          </div>
          <button
            className="font-medium hover:underline"
            onClick={move.dismissSummary}
            aria-label="Dismiss move result"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Move progress for large folders (SPEC-019 FR-004) */}
      {move.isBusy && move.progress !== null && (
        <div role="status" className="mb-4 text-sm text-gray-600">
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
          className="mb-4 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900"
        >
          <p className="font-medium">
            {move.moveCollision.count} item(s) already exist at the destination.
          </p>
          <div className="mt-3 flex gap-2">
            <button
              className="rounded bg-amber-600 px-3 py-1 font-medium text-white hover:bg-amber-700"
              onClick={move.moveCollision.onOverwriteAll}
            >
              Overwrite all
            </button>
            <button
              className="rounded px-3 py-1 font-medium text-gray-600 hover:bg-gray-100"
              onClick={move.moveCollision.onCancel}
            >
              Cancel
            </button>
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
          className="flex justify-center py-12 text-gray-400"
        >
          <span>Loading…</span>
        </div>
      )}

      {/* Error */}
      {!isLoading && error !== null && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-700"
        >
          <p className="font-medium">Failed to load files</p>
          <p className="mt-1 text-sm">{error}</p>
        </div>
      )}

      {/* Empty state */}
      {isEmpty && (
        <p className="py-12 text-center text-gray-400">This folder is empty.</p>
      )}

      {/* File and folder list */}
      {hasContent && (
        <ul
          aria-label="File list"
          className="overflow-hidden rounded-lg border border-gray-200 bg-white"
        >
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
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            onClick={loadMore}
            disabled={isLoadingMore}
          >
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
}: Props) {
  const rootPrefix = rootPrefixProp ?? prefixProp;
  const [prefix, setPrefix] = useState<string | undefined>(
    prefixProp || undefined,
  );

  return (
    <SelectionProvider prefix={prefix}>
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
    </SelectionProvider>
  );
}
