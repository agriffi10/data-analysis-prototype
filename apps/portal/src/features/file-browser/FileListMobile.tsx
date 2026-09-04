import {ParentFolderRow} from './ParentFolderRow';
import {FileListRowMobile} from './FileListRowMobile';
import {SystemFolderGroupRow} from './SystemFolderGroupRow';
import type {FileListProps} from './FileListTable';

/**
 * The below-`tablet` file list: a compact two-line card list carrying the same
 * data and handlers as the table. Mount-gated by the caller,
 * not CSS-hidden, so the two structurally-distinct markups never both live in
 * the DOM.
 */
export function FileListMobile({
  folders,
  files,
  systemFolders,
  systemExpanded,
  onToggleSystem,
  selectable,
  atRoot,
  onNavigateUp,
  onOpenFolder,
  onFolderDetails,
  onFileDetails,
  onActivateFile,
  downloadingKey,
  isSelected,
  onToggleSelect
}: FileListProps) {
  return (
    <ul
      aria-label="File list"
      className="overflow-hidden rounded-lg border border-border bg-surface">
      {!atRoot && (
        <ParentFolderRow
          variant="mobile"
          selectable={selectable}
          onNavigateUp={onNavigateUp}
        />
      )}
      {folders.map((folder) => (
        <FileListRowMobile
          key={folder.prefix}
          kind="folder"
          folder={folder}
          onOpen={() => onOpenFolder(folder)}
          onDetails={onFolderDetails}
          selectable={selectable}
          isSelected={isSelected(folder.prefix)}
          onToggleSelect={() => onToggleSelect({type: 'folder', prefix: folder.prefix})}
        />
      ))}
      {systemFolders.length > 0 && (
        <SystemFolderGroupRow
          variant="mobile"
          count={systemFolders.length}
          expanded={systemExpanded}
          onToggle={onToggleSystem}
          selectable={selectable}
        />
      )}
      {systemExpanded &&
        systemFolders.map((folder) => (
          <FileListRowMobile
            key={folder.prefix}
            kind="folder"
            folder={folder}
            onOpen={() => onOpenFolder(folder)}
            onDetails={onFolderDetails}
            selectable={selectable}
            isSelected={isSelected(folder.prefix)}
            onToggleSelect={() => onToggleSelect({type: 'folder', prefix: folder.prefix})}
          />
        ))}
      {files.map((file) => (
        <FileListRowMobile
          key={file.key}
          kind="file"
          file={file}
          onActivate={() => onActivateFile(file)}
          onDetails={onFileDetails}
          isDownloading={downloadingKey === file.key}
          selectable={selectable}
          isSelected={isSelected(file.key)}
          onToggleSelect={() => onToggleSelect({type: 'file', key: file.key})}
        />
      ))}
    </ul>
  );
}
