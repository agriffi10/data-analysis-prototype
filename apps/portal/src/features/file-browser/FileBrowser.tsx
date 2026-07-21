import {useState} from 'react';
import {Button} from '../../components/Button';
import {Badge} from '../../components/Badge';
import {Banner} from '../../components/Banner';
import {useFileBrowser} from './useFileBrowser';
import {useFileUpload} from './useFileUpload';
import {useDelete} from './useDelete';
import {useMove} from './useMove';
import {useCopy} from './useCopy';
import {getDownloadUrl} from './fileBrowser.service';
import {triggerBrowserDownload} from './fileBrowser.download';
import {formatSize, formatDate} from './fileBrowser.format';
import {lastSegment, fileExtension, isAtRoot, parentPrefix} from './fileBrowser.paths';
import {UploadDropzone} from './UploadDropzone';
import {UploadDrawer} from './UploadDrawer';
import {UploadList} from './UploadList';
import {useUploadQueue} from './uploadQueueContext';
import {CreateFolderDialog} from './CreateFolderDialog';
import {CollisionPrompt} from './CollisionPrompt';
import {MetadataPanel} from './MetadataPanel';
import {FolderDetailsPanel} from './FolderDetailsPanel';
import {ParentFolderRow} from './ParentFolderRow';
import {FileListRowMobile} from './FileListRowMobile';
import {MobileActionBar} from '../../components/MobileActionBar';
import {HIDDEN_BROWSER_FOLDERS, isRootFolderNamed} from './protectedFolders';
import {DeleteConfirmDialog} from './DeleteConfirmDialog';
import {OperationSummaryBanner} from './OperationSummaryBanner';
import {BatchOverwritePrompt} from './BatchOverwritePrompt';
import {RenameDialog} from './RenameDialog';
import {MoveDialog} from './MoveDialog';
import {CopyDialog} from './CopyDialog';
import {DataQualityDialog} from '../data-quality';
import {SelectionProvider} from './SelectionProvider';
import {CreateTableButton} from '../table-builder';
import {useSelection, itemId, type SelectableItem} from './selectionContext';
import type {FileSpaceTarget, FileSpaceKind} from './useFileSpace';
import {getSessionCredentials} from '../../lib/awsCredentials';
import {toUserMessage} from '../../lib/errorMessages';
import {useIsMobile} from '../../lib/useBreakpoint';
import type {S3FileItem, S3FolderItem} from '../../types/s3.types';

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

type BreadcrumbItem = {
  label: string;
  prefix: string | undefined;
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function buildBreadcrumbs(prefix: string | undefined, rootPrefix: string, rootLabel?: string): BreadcrumbItem[] {
  if (!rootPrefix) {
    // No root clamping — standard Home-rooted breadcrumb
    const crumbs: BreadcrumbItem[] = [{label: 'Home', prefix: undefined}];
    if (!prefix) return crumbs;

    const parts = prefix.split('/').filter(Boolean);
    parts.forEach((part, i) => {
      crumbs.push({
        label: part,
        prefix: parts.slice(0, i + 1).join('/') + '/'
      });
    });

    return crumbs;
  }

  // Root-clamped breadcrumb: show only segments at or below rootPrefix. The root
  // crumb uses rootLabel when provided (so the raw prefix segment — e.g. the
  // username — is never shown), otherwise the last path segment.
  const rootParts = rootPrefix.split('/').filter(Boolean);
  const label = rootLabel ?? rootParts[rootParts.length - 1] ?? rootPrefix;
  const crumbs: BreadcrumbItem[] = [{label, prefix: rootPrefix}];

  if (!prefix || prefix === rootPrefix) return crumbs;

  const allParts = prefix.split('/').filter(Boolean);
  const subParts = allParts.slice(rootParts.length);
  subParts.forEach((part, i) => {
    crumbs.push({
      label: part,
      prefix: [...rootParts, ...subParts.slice(0, i + 1)].join('/') + '/'
    });
  });

  return crumbs;
}

// ─── Icons (inline, no icon library — SPEC-024) ───────────────────────────────

function FolderIcon({className = 'h-5 w-5'}: {className?: string}) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="currentColor"
      className={`${className} shrink-0 text-accent`}
      aria-hidden="true">
      <path d="M2 6a2 2 0 012-2h3.586a1 1 0 01.707.293l1.414 1.414A1 1 0 0010.414 6H16a2 2 0 012 2v7a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
    </svg>
  );
}

function FileIcon({className = 'h-5 w-5'}: {className?: string}) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      className={`${className} shrink-0 text-text-3`}
      aria-hidden="true">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M13.5 3H7a2 2 0 00-2 2v10a2 2 0 002 2h6a2 2 0 002-2V7.5L13.5 3z"
      />
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M13 3v4.5H17.5"
      />
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
  onDetails,
  selectable,
  isSelected,
  onToggleSelect
}: {
  folder: S3FolderItem;
  onClick: () => void;
  onDetails: (folder: S3FolderItem) => void;
  selectable: boolean;
  isSelected: boolean;
  onToggleSelect: () => void;
}) {
  return (
    <li
      className={`flex h-12 items-center border-b border-border-2 last:border-0 ${
        isSelected ? 'bg-accent-soft' : 'hover:bg-surface-2'
      }`}>
      {selectable && (
        <span className="flex w-10 shrink-0 items-center justify-center">
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
        aria-label={`Open folder ${folder.name}`}>
        <FolderIcon />
        <span className="truncate text-base font-medium text-text">{folder.name}</span>
      </button>
      <span className={`${COL_SIZE} pr-4 text-right text-sm text-text-3`}>—</span>
      <span className={`${COL_MODIFIED} pr-4 text-right text-sm text-text-2`} />
      <span className={`hidden ${COL_TYPE} pr-4 text-right desktop:block`}>
        <Badge>Folder</Badge>
      </span>
      {/* Always-visible Details (mirrors file rows). Rename/Delete/Move/Copy
          still live in the selection toolbar. */}
      <span className={`${COL_ACTIONS} flex items-center justify-end gap-1 pr-4`}>
        <button
          className="h-7 rounded-md px-2 text-sm text-text-2 hover:bg-surface-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          onClick={() => onDetails(folder)}
          aria-label={`Details for ${folder.name}`}>
          Details
        </button>
      </span>
    </li>
  );
}

function FileRow({
  file,
  onDownload,
  onActivate,
  onDetails,
  isDownloading,
  selectable,
  isSelected,
  onToggleSelect
}: {
  file: S3FileItem;
  // Read-only fallback only: in the authenticated flow Download lives in the
  // selection toolbar, so this is undefined there and no row Download shows.
  onDownload?: (file: S3FileItem) => void;
  // SPEC-081: double-click anywhere on the row downloads it (both flows), reusing
  // the same presigned-URL path as the Download control.
  onActivate: () => void;
  onDetails: (file: S3FileItem) => void;
  isDownloading: boolean;
  selectable: boolean;
  isSelected: boolean;
  onToggleSelect: () => void;
}) {
  // Double-click to download. `select-none` keeps the gesture from leaving the
  // filename text highlighted; clearing any range is a belt-and-suspenders.
  function handleActivate() {
    window.getSelection()?.removeAllRanges();
    onActivate();
  }
  return (
    <li
      onDoubleClick={handleActivate}
      title={`Double-click to download ${file.name}`}
      className={`flex h-12 cursor-pointer items-center select-none border-b border-border-2 last:border-0 ${
        isSelected ? 'bg-accent-soft' : 'hover:bg-surface-2'
      }`}>
      {selectable && (
        // Double-clicking the checkbox must not download (it retains its own
        // toggle behavior); stop the row's dblclick from firing.
        <span
          className="flex w-10 shrink-0 items-center justify-center"
          onDoubleClick={(e) => e.stopPropagation()}>
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
        <span className="truncate text-base font-medium text-text">{file.name}</span>
      </span>
      <span className={`${COL_SIZE} pr-4 text-right text-sm text-text-2`}>{formatSize(file.size)}</span>
      <span className={`${COL_MODIFIED} pr-4 text-right text-sm text-text-2`}>{formatDate(file.lastModified)}</span>
      <span className={`hidden ${COL_TYPE} pr-4 text-right desktop:block`}>
        <Badge>{fileExtension(file.name)}</Badge>
      </span>
      {/* Always-visible Details (no hover menu). Download appears here only in
          read-only mode (no selection toolbar); otherwise it's a toolbar action.
          Double-clicking a button runs its own action, not the row download. */}
      <span
        className={`${COL_ACTIONS} flex items-center justify-end gap-1 pr-4`}
        onDoubleClick={(e) => e.stopPropagation()}>
        <button
          className="h-7 rounded-md px-2 text-sm text-text-2 hover:bg-surface-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          onClick={() => onDetails(file)}
          aria-label={`Details for ${file.name}`}>
          Details
        </button>
        {onDownload && (
          <button
            className="h-7 rounded-md px-2 text-sm text-accent-text hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            onClick={() => onDownload(file)}
            disabled={isDownloading}
            aria-label={`Download ${file.name}`}>
            {isDownloading ? '…' : 'Download'}
          </button>
        )}
      </span>
    </li>
  );
}

// ─── Selection toolbar (SPEC-018 FR-001 UI / FR-004) ──────────────────────────

// Bulk-action glyphs (icon-only on mobile, SPEC-099 FR-006).
function BulkCopyIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className="h-[15px] w-[15px]"
      aria-hidden="true">
      <rect
        x="9"
        y="9"
        width="11"
        height="11"
        rx="2"
      />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  );
}

function QualityCheckIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className="h-[15px] w-[15px]"
      aria-hidden="true">
      {/* A magnifier over a document — inspecting, not changing. */}
      <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h6" />
      <circle
        cx="16"
        cy="13"
        r="4"
      />
      <path d="M19 16l3 3" />
    </svg>
  );
}

function BulkMoveIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-[15px] w-[15px]"
      aria-hidden="true">
      <path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4" />
      <path d="M10 8l4 4-4 4" />
      <path d="M14 12H3" />
    </svg>
  );
}

function BulkTrashIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-[15px] w-[15px]"
      aria-hidden="true">
      <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m2 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
    </svg>
  );
}

function SelectionToolbar({
  allItems,
  onRequestDelete,
  onRequestMove,
  onRequestCopy,
  onRequestQualityCheck,
  isBusy
}: {
  allItems: SelectableItem[];
  onRequestDelete: () => void;
  onRequestMove: () => void;
  onRequestCopy: () => void;
  /** Absent when the space can't be resolved (no space name) — the action is then omitted. */
  onRequestQualityCheck?: () => void;
  isBusy: boolean;
}) {
  const {count, isSelected, selectAll, clear} = useSelection();

  const allSelected = allItems.length > 0 && allItems.every((i) => isSelected(itemId(i)));
  const someSelected = allItems.some((i) => isSelected(itemId(i)));

  const active = count > 0;

  // A focused bulk-action bar (SPEC-096): whole-selection Copy / Move / Delete
  // only (Download + Rename live in the details panel, SPEC-097). Labelled at
  // ≥ tablet, icon-only on mobile (SPEC-099 FR-006).
  return (
    <div
      className={`mb-4 flex h-11 items-center gap-2 rounded-lg border px-3 tablet:gap-3 tablet:px-4 ${
        active ? 'border-accent bg-accent-soft' : 'border-border bg-surface'
      }`}>
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
        className={`text-sm font-semibold ${active ? 'text-accent-text' : 'text-text-3'}`}>
        {active ? `${count} selected` : 'Select all'}
      </span>

      <div className="flex-1" />

      {/* SPEC-113: a read-only diagnostic on ONE file or folder. It lives here rather
          than on the top toolbar because it is scoped to the SELECTION, like its
          neighbours — and here it is already reachable at every breakpoint (labelled
          at ≥ tablet, icon-only on mobile) without a second mount. `user_settings` and
          `_data-quality-reports` need no guard: they are filtered out of the listing
          entirely, so they can never be selected. */}
      {onRequestQualityCheck && (
        <Button
          variant="ghost"
          size="sm"
          className="gap-1.5 !h-9 !px-2.5 tablet:!h-8 tablet:!px-3"
          onClick={onRequestQualityCheck}
          disabled={count !== 1 || isBusy}
          aria-label="Check data quality of the selected item">
          <QualityCheckIcon />
          <span className="hidden tablet:inline">Check quality</span>
        </Button>
      )}

      <Button
        variant="ghost"
        size="sm"
        className="gap-1.5 !h-9 !px-2.5 tablet:!h-8 tablet:!px-3"
        onClick={onRequestCopy}
        disabled={count === 0 || isBusy}
        aria-label="Copy selected items">
        <BulkCopyIcon />
        <span className="hidden tablet:inline">Copy</span>
      </Button>

      <Button
        variant="ghost"
        size="sm"
        className="gap-1.5 !h-9 !px-2.5 tablet:!h-8 tablet:!px-3"
        onClick={onRequestMove}
        disabled={count === 0 || isBusy}
        aria-label="Move selected items">
        <BulkMoveIcon />
        <span className="hidden tablet:inline">Move</span>
      </Button>

      <Button
        variant="ghost"
        size="sm"
        className="gap-1.5 !h-9 !px-2.5 !text-danger hover:!bg-danger-soft hover:!text-danger tablet:!h-8 tablet:!px-3"
        onClick={onRequestDelete}
        disabled={count === 0 || isBusy}
        aria-label="Delete selected items">
        <BulkTrashIcon />
        <span className="hidden tablet:inline">Delete</span>
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

  // A shared space the user was just added to can list-deny until their session's
  // token is re-minted with the new membership-slot tag (architecture §3). Detect
  // that case so we can offer a one-click "refresh access" instead of a dead error.
  const accessError = error as {message?: string; code?: string} | null;
  const isAccessDenied =
    !!accessError &&
    (accessError.code === 'AccessDenied' || /not authorized|access denied|listbucket/i.test(accessError.message ?? ''));
  const justAddedToShared = spaceKind === 'shared' && isAccessDenied;
  const [refreshingAccess, setRefreshingAccess] = useState(false);
  const refreshAccess = async () => {
    setRefreshingAccess(true);
    // Re-mint the ID token so the Identity Pool stamps the new shared_space_k tag,
    // then re-list. A failed re-mint just leaves the error in place.
    await getSessionCredentials(true);
    refreshListing();
    setRefreshingAccess(false);
  };

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
  const [creatingFolder, setCreatingFolder] = useState(false);
  // Upload drawer (right slide-over) — the "add files" surface only.
  const [uploadOpen, setUploadOpen] = useState(false);

  // Multi-select + delete (SPEC-018). Selection comes from the surrounding
  // SelectionProvider; delete is only offered in the authenticated, writable flow
  // (a username is required for the marker guard).
  const selection = useSelection();
  // Mount-gate the table-vs-card list swap (SPEC-099); matchMedia reads correctly
  // on first paint in the browser, so no flash and only one markup ever mounts.
  const isMobile = useIsMobile();
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
  const [detailsFile, setDetailsFile] = useState<S3FileItem | null>(null);
  // The folder whose read-only details drawer is open (null = closed). Folders
  // carry no HeadObject metadata, so this renders synchronously from the listing.
  const [detailsFolder, setDetailsFolder] = useState<S3FolderItem | null>(null);
  // SPEC-113: the one selected file/folder awaiting a data-quality check (null = closed).
  const [checkingQuality, setCheckingQuality] = useState<SelectableItem | null>(null);

  async function handleDownload(file: S3FileItem) {
    // Don't start a second download for a key already in flight (SPEC-081 FR-002:
    // a rapid second double-click is a no-op; the button flow uses `disabled`).
    if (downloadingKey === file.key) return;
    setDownloadingKey(file.key);
    setDownloadError(null);
    const result = await getDownloadUrl({bucket, key: file.key, fileName: file.name});
    setDownloadingKey(null);
    if (result.success) {
      triggerBrowserDownload(result.data.url);
    } else {
      setDownloadError(`Could not download ${file.name}. ${toUserMessage(result.error).message}`);
    }
  }

  async function handleConfirmDelete() {
    const items = [...selection.selected.values()];
    await del.runDelete(items);
    selection.clear();
    setConfirmOpen(false);
  }

  function handleConfirmMove(destPrefix: string, destBucket: string) {
    const items = moving ?? [];
    setMoving(null);
    selection.clear();
    move.moveItems(items, destPrefix, destBucket);
  }

  function handleConfirmCopy(destPrefix: string, destBucket: string) {
    const items = copying ?? [];
    // A same-folder copy (destination = current parent in the SAME bucket) opens
    // the editable auto-number prompt inside the dialog (FR-003), so the dialog
    // must stay open — only close it for the ordinary different-folder / different-
    // connection case.
    const sameFolder = destBucket === bucket && destPrefix === currentPrefix;
    if (!sameFolder) {
      setCopying(null);
      selection.clear();
    }
    copy.copyItems(items, destPrefix, destBucket);
  }

  // Rename from a details panel (SPEC-097): open the rename dialog pre-scoped to
  // that object and close the panel. Rename = move within the same parent.
  function openRenameFile(file: S3FileItem) {
    setRenaming({item: {type: 'file', key: file.key}, name: file.name, kind: 'file'});
    setDetailsFile(null);
  }

  function openRenameFolder(folder: S3FolderItem) {
    setRenaming({item: {type: 'folder', prefix: folder.prefix}, name: folder.name, kind: 'folder'});
    setDetailsFolder(null);
  }

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
            {username && (
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
              onClick={() => setCreatingFolder((v) => !v)}
              disabled={isBusy}>
              New folder
            </Button>
            <Button
              variant="primary"
              className="shrink-0"
              onClick={() => setUploadOpen(true)}>
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
            onClick={() => setCreatingFolder((v) => !v)}
            disabled={isBusy}>
            New folder
          </Button>
          <Button
            variant="primary"
            className="!h-11 flex-1"
            onClick={() => setUploadOpen(true)}>
            Upload
          </Button>
        </MobileActionBar>
      )}

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
            open={uploadOpen}
            onClose={() => setUploadOpen(false)}
            destinationLabel={destinationLabel}>
            <UploadDropzone onFiles={(files) => enqueue(files, {bucket, prefix: currentPrefix})} />
            <UploadList />
          </UploadDrawer>
        </>
      )}

      {/* Download error (SPEC-015) — dismissible, non-blocking */}
      {downloadError && (
        <Banner
          variant="danger"
          onDismiss={() => setDownloadError(null)}
          className="mb-4">
          {downloadError}
        </Banner>
      )}

      {/* Delete systemic error (SPEC-018 FR-004) — dismissible */}
      {del.error && (
        <Banner
          variant="danger"
          onDismiss={del.dismissError}
          className="mb-4">
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
            code: e.code
          }))}
          onDismiss={del.dismissSummary}
        />
      )}

      {/* Move systemic error (SPEC-019 FR-004) — dismissible */}
      {move.error && (
        <Banner
          variant="danger"
          onDismiss={move.dismissError}
          className="mb-4">
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
            code: e.code
          }))}
          onDismiss={move.dismissSummary}
        />
      )}

      {/* Move progress for large folders (SPEC-019 FR-004) */}
      {move.isBusy && move.progress !== null && (
        <div
          role="status"
          className="mb-4 text-sm text-text-2">
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
        <Banner
          variant="danger"
          onDismiss={copy.dismissError}
          className="mb-4">
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
            code: e.code
          }))}
          onDismiss={copy.dismissSummary}
        />
      )}

      {/* Copy progress for large folders (SPEC-039 FR-004) */}
      {copy.isBusy && copy.progress !== null && (
        <div
          role="status"
          className="mb-4 text-sm text-text-2">
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

      {/* Selection toolbar (SPEC-018 + SPEC-019 + SPEC-039 + SPEC-113) — select all +
          bulk copy/move/delete + the single-item data-quality check */}
      {canModify && hasContent && (
        <SelectionToolbar
          allItems={allItems}
          onRequestDelete={() => setConfirmOpen(true)}
          onRequestMove={() => setMoving([...selection.selected.values()])}
          onRequestCopy={() => setCopying([...selection.selected.values()])}
          onRequestQualityCheck={username ? () => setCheckingQuality(selectedItems[0] ?? null) : undefined}
          isBusy={del.isDeleting || move.isBusy || copy.isBusy || downloadingKey !== null}
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
          {justAddedToShared ? (
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
                onClick={() => void refreshAccess()}
                disabled={refreshingAccess}>
                {refreshingAccess ? 'Refreshing…' : 'Refresh access'}
              </Button>
            </>
          ) : (
            <>
              <p className="font-medium">Failed to load files</p>
              <p className="mt-1 text-sm">{toUserMessage(error).message}</p>
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
          // Mobile (< tablet): compact two-line card list — same data + handlers
          // as the table (SPEC-099 FR-003). Mount-gated (not CSS-hidden) so the
          // two structurally-distinct markups never both live in the DOM.
          <ul
            aria-label="File list"
            className="overflow-hidden rounded-lg border border-border bg-surface">
            {!atRoot && (
              <ParentFolderRow
                variant="mobile"
                selectable={canModify}
                onNavigateUp={() => setPrefix(parentPrefix(currentPrefix, rootPrefix) || undefined)}
              />
            )}
            {folders.map((folder) => (
              <FileListRowMobile
                key={folder.prefix}
                kind="folder"
                folder={folder}
                onOpen={() => setPrefix(folder.prefix)}
                onDetails={setDetailsFolder}
                selectable={canModify}
                isSelected={selection.isSelected(folder.prefix)}
                onToggleSelect={() => selection.toggle({type: 'folder', prefix: folder.prefix})}
              />
            ))}
            {files.map((file) => (
              <FileListRowMobile
                key={file.key}
                kind="file"
                file={file}
                onActivate={() => void handleDownload(file)}
                onDetails={setDetailsFile}
                isDownloading={downloadingKey === file.key}
                selectable={canModify}
                isSelected={selection.isSelected(file.key)}
                onToggleSelect={() => selection.toggle({type: 'file', key: file.key})}
              />
            ))}
          </ul>
        ) : (
          // Desktop/tablet: data table. Type column sheds at tablet (`hidden
          // desktop:block`); columns stay aligned (SPEC-099 FR-002).
          <div className="overflow-hidden rounded-lg border border-border bg-surface">
            {/* Column header — visual only; the labels are not programmatically
                tied to the list rows below, so hide this decorative row from AT
                (each row already exposes its own values as text). */}
            <div
              aria-hidden="true"
              className="flex h-10 items-center border-b border-border bg-surface-2 text-xs font-semibold uppercase tracking-wide text-text-3">
              {canModify && <span className="w-10 shrink-0" />}
              <span className="min-w-0 flex-1 px-4">Name</span>
              <span className={`${COL_SIZE} pr-4 text-right`}>Size</span>
              <span className={`${COL_MODIFIED} pr-4 text-right`}>Modified</span>
              <span className={`hidden ${COL_TYPE} pr-4 text-right desktop:block`}>Type</span>
              <span className={`${COL_ACTIONS} pr-4`} />
            </div>
            <ul aria-label="File list">
              {/* Parent-folder (`..`) row — first row when below the space root
                  (SPEC-098). Navigation only: non-selectable, excluded from
                  select-all (it's never in `allItems`). */}
              {!atRoot && (
                <ParentFolderRow
                  selectable={canModify}
                  onNavigateUp={() => setPrefix(parentPrefix(currentPrefix, rootPrefix) || undefined)}
                />
              )}
              {folders.map((folder) => (
                <FolderRow
                  key={folder.prefix}
                  folder={folder}
                  onClick={() => setPrefix(folder.prefix)}
                  onDetails={setDetailsFolder}
                  selectable={canModify}
                  isSelected={selection.isSelected(folder.prefix)}
                  onToggleSelect={() => selection.toggle({type: 'folder', prefix: folder.prefix})}
                />
              ))}
              {files.map((file) => (
                <FileRow
                  key={file.key}
                  file={file}
                  // Read-only browse has no selection toolbar, so keep a per-row
                  // Download there; the authenticated flow downloads from the toolbar.
                  onDownload={canModify ? undefined : handleDownload}
                  // SPEC-081: double-click downloads in both flows.
                  onActivate={() => void handleDownload(file)}
                  onDetails={setDetailsFile}
                  isDownloading={downloadingKey === file.key}
                  selectable={canModify}
                  isSelected={selection.isSelected(file.key)}
                  onToggleSelect={() => selection.toggle({type: 'file', key: file.key})}
                />
              ))}
            </ul>
          </div>
        ))}

      {/* Metadata drawer (SPEC-017) — shared Drawer; closes via button, Escape, or backdrop */}
      {detailsFile && (
        <MetadataPanel
          bucket={bucket}
          file={detailsFile}
          rootPrefix={rootPrefix}
          canModify={canModify}
          onRequestRename={openRenameFile}
          onClose={() => setDetailsFile(null)}
        />
      )}

      {/* Folder details drawer — synchronous, no metadata fetch */}
      {detailsFolder && (
        <FolderDetailsPanel
          bucket={bucket}
          folder={detailsFolder}
          rootPrefix={rootPrefix}
          canModify={canModify}
          onRequestRename={openRenameFolder}
          onClose={() => setDetailsFolder(null)}
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
            // The renamed item's key/prefix changes, so its stale id would linger
            // in the selection as a ghost selection (the row is gone from the
            // listing). Clear the selection like move/delete/copy do.
            selection.clear();
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
          destinations={destinations}
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
          destinations={destinations}
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
              }
            }
          }
          onCopy={handleConfirmCopy}
          onCancel={() => {
            copy.cancelCollision();
            setCopying(null);
          }}
        />
      )}

      {/* SPEC-113: confirm a read-only data-quality check on the one selected item.
          The space root prefix (not the current folder) is what identifies the space
          to the control plane; `location` is the item itself. */}
      {checkingQuality && username && (
        <DataQualityDialog
          target={{
            space: {kind: spaceKind ?? 'personal', bucket, prefix: rootPrefix},
            location: checkingQuality.type === 'file' ? checkingQuality.key : checkingQuality.prefix
          }}
          kind={checkingQuality.type}
          // Shown space-relative, matching the breadcrumbs — the raw `{space}/` prefix
          // is noise the user never sees anywhere else in the browser.
          displayPath={
            (checkingQuality.type === 'file' ? checkingQuality.key : checkingQuality.prefix).slice(rootPrefix.length) ||
            rootLabel ||
            rootPrefix
          }
          onClose={() => setCheckingQuality(null)}
        />
      )}

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
