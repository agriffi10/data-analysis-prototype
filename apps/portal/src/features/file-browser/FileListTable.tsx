import {Badge} from '../../components/Badge';
import {FileRowIcon, FolderRowIcon} from '../../components/icons';
import {ParentFolderRow} from './ParentFolderRow';
import {formatSize, formatDate} from './fileBrowser.format';
import {fileExtension} from './fileBrowser.paths';
import type {SelectableItem} from './selectionContext';
import type {S3FileItem, S3FolderItem} from '../../types/s3.types';
import {SECTION_CAPTION} from '../../components/fieldStyles';

/**
 * The data every file-list surface needs. Shared by the ≥ tablet table and the
 * mobile card list, which render the SAME items and handlers through
 * structurally distinct markup — not a `*Mobile`/`*Desktop`
 * twin of one tree.
 */
export type FileListProps = {
  folders: S3FolderItem[];
  files: S3FileItem[];
  /** Rows carry a checkbox — the authenticated, writable flow only. */
  selectable: boolean;
  /** At the space root the `..` row is omitted. */
  atRoot: boolean;
  onNavigateUp: () => void;
  onOpenFolder: (folder: S3FolderItem) => void;
  onFolderDetails: (folder: S3FolderItem) => void;
  onFileDetails: (file: S3FileItem) => void;
  /** SPEC-081: double-click (table) / tap (mobile) downloads the row. */
  onActivateFile: (file: S3FileItem) => void;
  /** The key currently being signed, so its row shows a busy state. */
  downloadingKey: string | null;
  isSelected: (id: string) => boolean;
  onToggleSelect: (item: SelectableItem) => void;
};

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
        <FolderRowIcon />
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
  // Double-click anywhere on the row downloads it (both flows), reusing
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
        <FileRowIcon />
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

/**
 * The ≥ tablet file list: a data table whose Type column sheds at tablet
 * (`hidden desktop:block`) while the columns stay aligned.
 */
export function FileListTable({
  folders,
  files,
  selectable,
  atRoot,
  onNavigateUp,
  onOpenFolder,
  onFolderDetails,
  onFileDetails,
  onRowDownload,
  onActivateFile,
  downloadingKey,
  isSelected,
  onToggleSelect
}: FileListProps & {
  /**
   * Read-only browse only: there is no selection toolbar there, so Download
   * stays on the row. Undefined in the authenticated flow.
   */
  onRowDownload?: (file: S3FileItem) => void;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface">
      {/* Column header — visual only; the labels are not programmatically
          tied to the list rows below, so hide this decorative row from AT
          (each row already exposes its own values as text). */}
      <div
        aria-hidden="true"
        className={`flex h-10 items-center border-b border-border bg-surface-2 ${SECTION_CAPTION}`}>
        {selectable && <span className="w-10 shrink-0" />}
        <span className="min-w-0 flex-1 px-4">Name</span>
        <span className={`${COL_SIZE} pr-4 text-right`}>Size</span>
        <span className={`${COL_MODIFIED} pr-4 text-right`}>Modified</span>
        <span className={`hidden ${COL_TYPE} pr-4 text-right desktop:block`}>Type</span>
        <span className={`${COL_ACTIONS} pr-4`} />
      </div>
      <ul aria-label="File list">
        {/* Parent-folder (`..`) row — first row when below the space root
            . Navigation only: non-selectable, excluded from
            select-all (it's never in `allItems`). */}
        {!atRoot && (
          <ParentFolderRow
            selectable={selectable}
            onNavigateUp={onNavigateUp}
          />
        )}
        {folders.map((folder) => (
          <FolderRow
            key={folder.prefix}
            folder={folder}
            onClick={() => onOpenFolder(folder)}
            onDetails={onFolderDetails}
            selectable={selectable}
            isSelected={isSelected(folder.prefix)}
            onToggleSelect={() => onToggleSelect({type: 'folder', prefix: folder.prefix})}
          />
        ))}
        {files.map((file) => (
          <FileRow
            key={file.key}
            file={file}
            // Read-only browse has no selection toolbar, so keep a per-row
            // Download there; the authenticated flow downloads from the toolbar.
            onDownload={onRowDownload}
            // Double-click downloads in both flows.
            onActivate={() => onActivateFile(file)}
            onDetails={onFileDetails}
            isDownloading={downloadingKey === file.key}
            selectable={selectable}
            isSelected={isSelected(file.key)}
            onToggleSelect={() => onToggleSelect({type: 'file', key: file.key})}
          />
        ))}
      </ul>
    </div>
  );
}
