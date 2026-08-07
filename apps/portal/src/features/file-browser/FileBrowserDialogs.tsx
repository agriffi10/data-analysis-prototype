import {MetadataPanel} from './MetadataPanel';
import {FolderDetailsPanel} from './FolderDetailsPanel';
import {DeleteConfirmDialog} from './DeleteConfirmDialog';
import {RenameDialog} from './RenameDialog';
import {MoveDialog} from './MoveDialog';
import {CopyDialog} from './CopyDialog';
import {DataQualityDialog} from '../data-quality';
import type {UseFileBrowserDialogsResult} from './useFileBrowserDialogs';
import type {useCopy} from './useCopy';
import type {useDelete} from './useDelete';
import type {useMove} from './useMove';
import type {FileSpaceKind, FileSpaceTarget} from './useFileSpace';
import type {SelectableItem} from './selectionContext';

type Props = {
  dialogs: UseFileBrowserDialogsResult;
  bucket: string;
  rootPrefix: string;
  rootLabel: string | undefined;
  currentPrefix: string;
  markerKey: string | undefined;
  /** The space's root-prefix owner; absent in the dev-unauth path. */
  username: string | undefined;
  spaceKind: FileSpaceKind | undefined;
  destinations: FileSpaceTarget[] | undefined;
  canModify: boolean;
  /** The current selection, for the delete confirmation's item list. */
  selectedItems: SelectableItem[];
  del: ReturnType<typeof useDelete>;
  move: ReturnType<typeof useMove>;
  copy: ReturnType<typeof useCopy>;
};

/**
 * The file browser's drawers and modals, in one mount point: the two details
 * panels, delete confirmation, rename, move, copy and the data-quality check.
 * State and handlers live in {@link useFileBrowserDialogs}; this file only mounts.
 */
export function FileBrowserDialogs({
  dialogs,
  bucket,
  rootPrefix,
  rootLabel,
  currentPrefix,
  markerKey,
  username,
  spaceKind,
  destinations,
  canModify,
  selectedItems,
  del,
  move,
  copy
}: Props) {
  return (
    <>
      {/* Metadata drawer (SPEC-017) — shared Drawer; closes via button, Escape, or backdrop */}
      {dialogs.detailsFile && (
        <MetadataPanel
          bucket={bucket}
          file={dialogs.detailsFile}
          rootPrefix={rootPrefix}
          canModify={canModify}
          onRequestRename={dialogs.openRenameFile}
          onClose={dialogs.closeFileDetails}
        />
      )}

      {/* Folder details drawer — synchronous, no metadata fetch */}
      {dialogs.detailsFolder && (
        <FolderDetailsPanel
          bucket={bucket}
          folder={dialogs.detailsFolder}
          rootPrefix={rootPrefix}
          canModify={canModify}
          onRequestRename={dialogs.openRenameFolder}
          onClose={dialogs.closeFolderDetails}
        />
      )}

      {/* Delete confirmation (SPEC-018 FR-004) — modal; nothing deleted until confirmed */}
      {dialogs.confirmDeleteOpen && (
        <DeleteConfirmDialog
          items={selectedItems}
          isDeleting={del.isBusy}
          onConfirm={dialogs.confirmDelete}
          onCancel={dialogs.closeConfirmDelete}
        />
      )}

      {/* Rename dialog (SPEC-019 FR-002) — modal */}
      {dialogs.renaming && (
        <RenameDialog
          kind={dialogs.renaming.kind}
          currentName={dialogs.renaming.name}
          isBusy={move.isBusy}
          onRename={dialogs.confirmRename}
          onCancel={dialogs.cancelRename}
        />
      )}

      {/* Move dialog (SPEC-019 FR-003) — destination-folder picker */}
      {dialogs.moving && (
        <MoveDialog
          bucket={bucket}
          items={dialogs.moving}
          rootPrefix={rootPrefix}
          rootLabel={rootLabel}
          currentPrefix={currentPrefix}
          markerKey={markerKey}
          isBusy={move.isBusy}
          destinations={destinations}
          onMove={dialogs.confirmMove}
          onCancel={dialogs.cancelMove}
        />
      )}

      {/* Copy dialog (SPEC-039 FR-004) — destination picker + same-folder name
          field. Stays open across the same-folder auto-number prompt (FR-003);
          the prompt's confirm/cancel close the dialog (and clear the selection). */}
      {dialogs.copying && (
        <CopyDialog
          bucket={bucket}
          items={dialogs.copying}
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
                dialogs.finishSameFolderCopy();
              },
              onCancel: () => {
                copy.sameFolderPrompt?.onCancel();
                dialogs.abandonSameFolderCopy();
              }
            }
          }
          onCopy={dialogs.confirmCopy}
          onCancel={dialogs.cancelCopy}
        />
      )}

      {/* SPEC-113: confirm a read-only data-quality check on the one selected item.
          The space root prefix (not the current folder) is what identifies the space
          to the control plane; `location` is the item itself. */}
      {dialogs.checkingQuality && username && (
        <DataQualityDialog
          target={{
            space: {kind: spaceKind ?? 'personal', bucket, prefix: rootPrefix},
            location:
              dialogs.checkingQuality.type === 'file' ? dialogs.checkingQuality.key : dialogs.checkingQuality.prefix
          }}
          kind={dialogs.checkingQuality.type}
          // Shown space-relative, matching the breadcrumbs — the raw `{space}/` prefix
          // is noise the user never sees anywhere else in the browser.
          displayPath={
            (dialogs.checkingQuality.type === 'file'
              ? dialogs.checkingQuality.key
              : dialogs.checkingQuality.prefix
            ).slice(rootPrefix.length) ||
            rootLabel ||
            rootPrefix
          }
          onClose={dialogs.closeQualityCheck}
          onStarted={dialogs.finishQualityCheck}
        />
      )}
    </>
  );
}
