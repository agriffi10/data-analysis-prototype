import {FileRowIcon, FolderRowIcon} from '../../components/icons';
import {cx} from '../../lib/cx';
import {ChevronRightIcon, InfoIcon} from '../../components/icons';
import {formatSize, formatDate} from './fileBrowser.format';
import {fileExtension} from './fileBrowser.paths';
import type {S3FileItem, S3FolderItem} from '../../types/s3.types';

export type FileListRowMobileProps =
  | {
      kind: 'file';
      file: S3FileItem;
      onActivate: () => void; // existing download-on-activate handler
      onDetails: (file: S3FileItem) => void;
      isDownloading?: boolean; // trailing "…" while a download is being signed
      selectable: boolean;
      isSelected: boolean;
      onToggleSelect: () => void;
    }
  | {
      kind: 'folder';
      folder: S3FolderItem;
      onOpen: () => void; // existing setPrefix(folder.prefix)
      onDetails: (folder: S3FolderItem) => void;
      selectable: boolean;
      isSelected: boolean;
      onToggleSelect: () => void;
    };

/**
 * Mobile (< tablet) two-line list row, `h-14` (49px) — the structural counterpart to the
 * `≥ tablet` table row. Tapping the row body activates it
 * (download a file / open a folder); a trailing size (file) or chevron (folder);
 * a per-object Details control; and, in writable flows, a selection checkbox with
 * an `accent-soft` + inset-`accent`-bar selected treatment. Driven by the same
 * `files`/`folders` data and handlers as the table — no forked logic.
 *
 * @example
 * <FileListRowMobile kind="file" file={f} onActivate={dl} onDetails={open} selectable isSelected={s} onToggleSelect={t} />
 */
export function FileListRowMobile(props: FileListRowMobileProps) {
  const isFolder = props.kind === 'folder';
  const name = isFolder ? props.folder.name : props.file.name;
  const meta = isFolder ? 'Folder' : `${fileExtension(props.file.name)} · ${formatDate(props.file.lastModified)}`;

  return (
    <li
      className={cx(
        'relative flex h-14 items-center border-b border-border-2 pr-2 last:border-0',
        props.isSelected ? 'bg-accent-soft' : 'hover:bg-surface-2'
      )}>
      {props.isSelected && (
        <span
          className="absolute inset-y-0 left-0 w-[3px] bg-accent"
          aria-hidden="true"
        />
      )}
      {props.selectable ? (
        <span className="flex w-11 shrink-0 items-center justify-center">
          <input
            type="checkbox"
            className="h-4 w-4 accent-accent"
            checked={props.isSelected}
            onChange={props.onToggleSelect}
            aria-label={`Select ${isFolder ? `folder ${name}` : name}`}
          />
        </span>
      ) : (
        <span
          className="w-3 shrink-0"
          aria-hidden="true"
        />
      )}

      <button
        type="button"
        className="flex min-w-0 flex-1 items-center gap-3 py-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent"
        onClick={isFolder ? props.onOpen : props.onActivate}
        aria-label={isFolder ? `Open folder ${name}` : `Download ${name}`}>
        {isFolder ? <FolderRowIcon /> : <FileRowIcon />}
        <span className="min-w-0 flex-1">
          <span className="block truncate text-base font-medium text-text">{name}</span>
          <span className="block truncate text-xs text-text-3">{meta}</span>
        </span>
      </button>

      {isFolder ? (
        <ChevronRightIcon className="h-4 w-4 shrink-0 text-text-3" />
      ) : props.isDownloading ? (
        <span className="shrink-0 text-sm text-text-3">
          <span aria-hidden="true">…</span>
          <span className="sr-only">Downloading</span>
        </span>
      ) : (
        <span className="shrink-0 text-sm text-text-2">{formatSize(props.file.size)}</span>
      )}

      <button
        type="button"
        className="ml-1 grid h-11 w-11 shrink-0 place-items-center rounded-md text-text-3 hover:bg-surface-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        onClick={() => (isFolder ? props.onDetails(props.folder) : props.onDetails(props.file))}
        aria-label={`Details for ${name}`}>
        <InfoIcon className="h-5 w-5" />
      </button>
    </li>
  );
}
