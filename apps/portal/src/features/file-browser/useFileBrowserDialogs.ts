import {useState} from 'react';
import {useSelection, type SelectableItem} from './selectionContext';
import type {useCopy} from './useCopy';
import type {useDelete} from './useDelete';
import type {useMove} from './useMove';
import type {S3FileItem, S3FolderItem} from '../../types/s3.types';

/** The item being renamed, with the fields the dialog needs. */
export type RenameTarget = {item: SelectableItem; name: string; kind: 'file' | 'folder'};

export type UseFileBrowserDialogsResult = {
  /** SPEC-016: the create-folder dialog. */
  creatingFolder: boolean;
  toggleCreateFolder: () => void;
  closeCreateFolder: () => void;
  /** SPEC-020: the add-files drawer. */
  uploadOpen: boolean;
  openUpload: () => void;
  closeUpload: () => void;
  /** SPEC-017: the file whose read-only metadata drawer is open (null = closed). */
  detailsFile: S3FileItem | null;
  openFileDetails: (file: S3FileItem) => void;
  closeFileDetails: () => void;
  /** The folder whose details drawer is open; renders synchronously from the listing. */
  detailsFolder: S3FolderItem | null;
  openFolderDetails: (folder: S3FolderItem) => void;
  closeFolderDetails: () => void;
  /** SPEC-018 FR-004: nothing is deleted until this is confirmed. */
  confirmDeleteOpen: boolean;
  openConfirmDelete: () => void;
  closeConfirmDelete: () => void;
  confirmDelete: () => Promise<void>;
  /** SPEC-019 FR-002: rename = move within the same parent. */
  renaming: RenameTarget | null;
  openRenameFile: (file: S3FileItem) => void;
  openRenameFolder: (folder: S3FolderItem) => void;
  confirmRename: (newName: string) => void;
  cancelRename: () => void;
  /** SPEC-019 FR-003: the items being moved (null = no move dialog). */
  moving: SelectableItem[] | null;
  openMove: () => void;
  cancelMove: () => void;
  confirmMove: (destPrefix: string, destBucket: string) => void;
  /** SPEC-039 FR-004: the items being copied (null = no copy dialog). */
  copying: SelectableItem[] | null;
  openCopy: () => void;
  cancelCopy: () => void;
  confirmCopy: (destPrefix: string, destBucket: string) => void;
  /** SPEC-039 FR-003: the same-folder auto-number prompt's confirm closes the dialog. */
  finishSameFolderCopy: () => void;
  /** The same-folder prompt's cancel — closes the dialog, keeps the selection. */
  abandonSameFolderCopy: () => void;
  /** SPEC-113: the one selected item awaiting a data-quality check (null = closed). */
  checkingQuality: SelectableItem | null;
  openQualityCheck: () => void;
  closeQualityCheck: () => void;
  /** The check was enqueued: close and drop the selection (it has served its purpose). */
  finishQualityCheck: () => void;
};

type Params = {
  bucket: string;
  /** The folder currently being viewed. */
  currentPrefix: string;
  del: ReturnType<typeof useDelete>;
  move: ReturnType<typeof useMove>;
  copy: ReturnType<typeof useCopy>;
};

/**
 * Every dialog and drawer the file browser can raise, and the handlers that
 * resolve one into an operation (SPEC-155 FR-009).
 *
 * The selection-clearing rules live here because they belong to the dialog's
 * outcome, not to the row: delete, move, rename, a different-folder copy and a
 * started data-quality check all clear it, while a same-folder copy keeps the
 * dialog (and the selection) until its auto-number prompt settles. A dialog that
 * was cancelled — or whose request failed — never clears.
 */
export function useFileBrowserDialogs({bucket, currentPrefix, del, move, copy}: Params): UseFileBrowserDialogsResult {
  const selection = useSelection();
  const [creatingFolder, setCreatingFolder] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [detailsFile, setDetailsFile] = useState<S3FileItem | null>(null);
  const [detailsFolder, setDetailsFolder] = useState<S3FolderItem | null>(null);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [renaming, setRenaming] = useState<RenameTarget | null>(null);
  const [moving, setMoving] = useState<SelectableItem[] | null>(null);
  const [copying, setCopying] = useState<SelectableItem[] | null>(null);
  const [checkingQuality, setCheckingQuality] = useState<SelectableItem | null>(null);

  return {
    creatingFolder,
    toggleCreateFolder: () => setCreatingFolder((v) => !v),
    closeCreateFolder: () => setCreatingFolder(false),

    uploadOpen,
    openUpload: () => setUploadOpen(true),
    closeUpload: () => setUploadOpen(false),

    detailsFile,
    openFileDetails: setDetailsFile,
    closeFileDetails: () => setDetailsFile(null),

    detailsFolder,
    openFolderDetails: setDetailsFolder,
    closeFolderDetails: () => setDetailsFolder(null),

    confirmDeleteOpen,
    openConfirmDelete: () => setConfirmDeleteOpen(true),
    closeConfirmDelete: () => setConfirmDeleteOpen(false),
    confirmDelete: async () => {
      const items = [...selection.selected.values()];
      await del.runDelete(items);
      selection.clear();
      setConfirmDeleteOpen(false);
    },

    renaming,
    // Rename from a details panel (SPEC-097): open the rename dialog pre-scoped to
    // that object and close the panel.
    openRenameFile: (file) => {
      setRenaming({item: {type: 'file', key: file.key}, name: file.name, kind: 'file'});
      setDetailsFile(null);
    },
    openRenameFolder: (folder) => {
      setRenaming({item: {type: 'folder', prefix: folder.prefix}, name: folder.name, kind: 'folder'});
      setDetailsFolder(null);
    },
    confirmRename: (newName) => {
      if (!renaming) return;
      move.renameItem(renaming.item, newName);
      setRenaming(null);
      // The renamed item's key/prefix changes, so its stale id would linger
      // in the selection as a ghost selection (the row is gone from the
      // listing). Clear the selection like move/delete/copy do.
      selection.clear();
    },
    cancelRename: () => setRenaming(null),

    moving,
    openMove: () => setMoving([...selection.selected.values()]),
    cancelMove: () => setMoving(null),
    confirmMove: (destPrefix, destBucket) => {
      const items = moving ?? [];
      setMoving(null);
      selection.clear();
      move.moveItems(items, destPrefix, destBucket);
    },

    copying,
    openCopy: () => setCopying([...selection.selected.values()]),
    cancelCopy: () => {
      copy.cancelCollision();
      setCopying(null);
    },
    confirmCopy: (destPrefix, destBucket) => {
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
    },
    finishSameFolderCopy: () => {
      setCopying(null);
      selection.clear();
    },
    abandonSameFolderCopy: () => setCopying(null),

    checkingQuality,
    openQualityCheck: () => setCheckingQuality([...selection.selected.values()][0] ?? null),
    closeQualityCheck: () => setCheckingQuality(null),
    finishQualityCheck: () => {
      selection.clear();
      setCheckingQuality(null);
    }
  };
}
