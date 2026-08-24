import {useState} from 'react';
import {FEATURE_FLAG_DEFAULTS, useFeatureSet} from '../feature-flags';
import {useSelection, type SelectableItem} from './selectionContext';
import {requiresControlPlane} from './fileOpRouting';
import {
  buildResubmitRequest,
  containingFolder,
  toFileOpItems,
  type FileOpDestination,
  type FileOpGesture
} from './fileOps.request';
import {useFileOpSubmit} from './useFileOpSubmit';
import type {SameFolderPrompt} from './useCopy';
import type {useCopy} from './useCopy';
import type {useDelete} from './useDelete';
import type {useMove} from './useMove';
import type {ConflictResolution} from './FileOpConflictsDialog';
import type {NotificationPayload} from '../notifications';
import type {FileOpSpace} from './fileOps.types';
import type {FileSpaceTarget} from './useFileSpace';
import type {S3FileItem, S3FolderItem} from '../../types/s3.types';

/** The item being renamed, with the fields the dialog needs. */
export type RenameTarget = {item: SelectableItem; name: string; kind: 'file' | 'folder'};

/** The same-folder prompt as the dialog consumes it: the probe's data plus this module's answers. */
export type SameFolderPromptControls = SameFolderPrompt & {
  onConfirm: (name: string) => void;
  onCancel: () => void;
};

export type UseFileBrowserDialogsResult = {
  /** the create-folder dialog. */
  creatingFolder: boolean;
  toggleCreateFolder: () => void;
  closeCreateFolder: () => void;
  /** the add-files drawer. */
  uploadOpen: boolean;
  openUpload: () => void;
  closeUpload: () => void;
  /** the file whose read-only metadata drawer is open (null = closed). */
  detailsFile: S3FileItem | null;
  openFileDetails: (file: S3FileItem) => void;
  closeFileDetails: () => void;
  /** The folder whose details drawer is open; renders synchronously from the listing. */
  detailsFolder: S3FolderItem | null;
  openFolderDetails: (folder: S3FolderItem) => void;
  closeFolderDetails: () => void;
  /** nothing is deleted until this is confirmed. */
  confirmDeleteOpen: boolean;
  openConfirmDelete: () => void;
  closeConfirmDelete: () => void;
  confirmDelete: () => Promise<void>;
  /** rename = move within the same parent. */
  renaming: RenameTarget | null;
  openRenameFile: (file: S3FileItem) => void;
  openRenameFolder: (folder: S3FolderItem) => void;
  confirmRename: (newName: string) => void;
  cancelRename: () => void;
  /** the items being moved (null = no move dialog). */
  moving: SelectableItem[] | null;
  openMove: () => void;
  cancelMove: () => void;
  confirmMove: (destPrefix: string, destBucket: string) => void;
  /** the items being copied (null = no copy dialog). */
  copying: SelectableItem[] | null;
  openCopy: () => void;
  cancelCopy: () => void;
  confirmCopy: (destPrefix: string, destBucket: string) => void;
  /** The same-folder auto-number prompt, wired — the dialog mounts it as it is. */
  sameFolderPrompt: SameFolderPromptControls | null;
  /** the one selected item awaiting a data-quality check (null = closed). */
  checkingQuality: SelectableItem | null;
  openQualityCheck: () => void;
  closeQualityCheck: () => void;
  /** The check was enqueued: close and drop the selection (it has served its purpose). */
  finishQualityCheck: () => void;
  /**
   * Re-submits the items a run could not place, from the notification payload alone.
   *
   * Reports whether the enqueue worked, so the caller closes the view only on the way out of a
   * successful one — reading a rendered error would read the value from before the submit.
   */
  resolveConflict: (payload: NotificationPayload, choice: ConflictResolution) => Promise<boolean>;
  /** True while an enqueue is resolving — what the four dialogs' busy states read on this path. */
  submitting: boolean;
  /** Why this space will not take another operation from this session right now, if it will not. */
  spaceBusyReason: string | undefined;
};

type Params = {
  bucket: string;
  /** The folder currently being viewed. */
  currentPrefix: string;
  /** The space being browsed — what the plane's request names as its source. Null in dev-unauth. */
  space: FileOpSpace | null;
  /** Every space move/copy can target, for resolving a chosen destination bucket to a space. */
  destinations: FileSpaceTarget[] | undefined;
  del: ReturnType<typeof useDelete>;
  move: ReturnType<typeof useMove>;
  copy: ReturnType<typeof useCopy>;
};

/**
 * Every dialog and drawer the file browser can raise, the handlers that resolve one into an
 * operation, and **the one place that decides whether an operation runs here or on the plane**.
 *
 * The selection-clearing rules live here because they belong to the dialog's outcome, not to the
 * row: delete, move, rename, a different-folder copy and a started data-quality check all clear
 * it, while a same-folder copy keeps the dialog (and the selection) until its auto-number prompt
 * settles. A dialog that was cancelled — or whose request failed — never clears.
 *
 * **THIS IS THE ONLY MODULE THAT IMPORTS `requiresControlPlane`, and it consults it once.** A
 * sweep enforces the first half; the second is why the same-folder prompt's confirm was moved
 * here out of `FileBrowserDialogs.tsx`. The gestures are five, not four, and they are not
 * symmetric: a same-folder copy is submitted from the prompt, in a different module from the
 * other four, and it is where a copy of a folder actually starts.
 *
 * **The probe resolves BEFORE the routing decision.** `startSameFolderCopy` HEAD-probes for the
 * first free `{name} (N)`; its answer IS the `targetName` of whatever follows, so the dispatcher
 * cannot be consulted at `confirmCopy` for that path. Only after the user has confirmed a name
 * does the fork happen — a single FILE takes the synchronous same-folder copy, a single FOLDER is
 * enqueued with the probed name.
 */
export function useFileBrowserDialogs({
  bucket,
  currentPrefix,
  space,
  destinations,
  del,
  move,
  copy
}: Params): UseFileBrowserDialogsResult {
  const selection = useSelection();
  const submit = useFileOpSubmit();
  const {isEnabled, status: flagsStatus} = useFeatureSet();
  // The compiled-in default rather than `useFeature`'s conservative `false` while the flags are
  // in flight. The conservative answer elsewhere is "do not offer a control yet"; here it is "run
  // a folder move as up to three round trips per contained object from the user's laptop", which
  // is the cost this plane exists to remove.
  const asyncFileOps =
    flagsStatus === 'loading' ? FEATURE_FLAG_DEFAULTS.asyncFileOperations : isEnabled('asyncFileOperations');

  const [creatingFolder, setCreatingFolder] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [detailsFile, setDetailsFile] = useState<S3FileItem | null>(null);
  const [detailsFolder, setDetailsFolder] = useState<S3FolderItem | null>(null);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [renaming, setRenaming] = useState<RenameTarget | null>(null);
  const [moving, setMoving] = useState<SelectableItem[] | null>(null);
  const [copying, setCopying] = useState<SelectableItem[] | null>(null);
  const [checkingQuality, setCheckingQuality] = useState<SelectableItem | null>(null);

  // The chosen destination bucket, as a space. A move or copy across connections names another
  // space entirely, and the plane resolves a bucket from the space rather than the other way
  // round — so an unknown bucket has no answer, and the caller falls back to running it here.
  function destinationSpaceFor(destBucket: string, destPrefix: string): FileOpDestination | null {
    const target = (destinations ?? []).find((d) => d.bucket === destBucket && destPrefix.startsWith(d.rootPrefix));
    if (!target) return null;
    return {space: {kind: target.kind, name: target.label}, prefix: destPrefix};
  }

  /**
   * The single routing decision, above all five submission points.
   *
   * `runHere` is the synchronous path exactly as it was — the same hook call with the same
   * arguments — so a selection of one file behaves byte for byte as it did before this plane
   * existed.
   */
  function dispatch(gesture: FileOpGesture, runHere: () => void): Promise<boolean> {
    if (gesture.items.length === 0) return Promise.resolve(false);
    // AFTER the emptiness guard, never before it: the predicate throws on an empty selection
    // rather than answering for one, because the plane refuses an empty source minutes later by
    // notification.
    if (!asyncFileOps || !space || !requiresControlPlane(toFileOpItems(gesture.items, gesture.targetName))) {
      runHere();
      return Promise.resolve(false);
    }
    return submit.submitGesture(gesture, space);
  }

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
    // Awaited by its dialog where the other three are fire-and-forget, so the close-and-clear
    // timing has to survive the dispatch: closing first would dismiss the dialog before the
    // enqueue resolves and lose the busy state the confirm control reads.
    confirmDelete: async () => {
      const items = [...selection.selected.values()];
      await dispatch({operation: 'delete', items}, () => void del.runDelete(items));
      selection.clear();
      setConfirmDeleteOpen(false);
    },

    renaming,
    // Rename from a details panel: open the rename dialog pre-scoped to
    // that object and close the panel.
    openRenameFile: (file) => {
      setRenaming({item: {type: 'file', key: file.key}, name: file.name, kind: 'file'});
      setDetailsFile(null);
    },
    openRenameFolder: (folder) => {
      setRenaming({item: {type: 'folder', prefix: folder.prefix}, name: folder.name, kind: 'folder'});
      setDetailsFolder(null);
    },
    // The one gesture whose item comes from dialog state rather than the selection: a rename is
    // raised from a details panel, on a row that need never have been ticked.
    confirmRename: (newName) => {
      if (!renaming) return;
      const item = renaming.item;
      void dispatch(
        {
          operation: 'move',
          items: [item],
          destination: space ? {space, prefix: containingFolder(item)} : undefined,
          targetName: newName
        },
        () => move.renameItem(item, newName)
      );
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
      const destination = destinationSpaceFor(destBucket, destPrefix);
      void dispatch({operation: 'move', items, destination: destination ?? undefined}, () =>
        move.moveItems(items, destPrefix, destBucket)
      );
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
      // the editable auto-number prompt inside the dialog, so the dialog
      // must stay open — only close it for the ordinary different-folder / different-
      // connection case. It is NOT dispatched here: the probe has to resolve first.
      if (destBucket === bucket && destPrefix === currentPrefix) {
        if (items.length > 0) copy.startSameFolderCopy(items[0], destPrefix);
        return;
      }
      setCopying(null);
      selection.clear();
      const destination = destinationSpaceFor(destBucket, destPrefix);
      void dispatch({operation: 'copy', items, destination: destination ?? undefined}, () =>
        copy.copyItems(items, destPrefix, destBucket)
      );
    },

    sameFolderPrompt: copy.sameFolderPrompt && {
      ...copy.sameFolderPrompt,
      onConfirm: (name) => {
        const item = copying?.[0];
        const targetName = name.trim();
        copy.clearSameFolderPrompt();
        setCopying(null);
        selection.clear();
        if (!item) return;
        void dispatch(
          {
            operation: 'copy',
            items: [item],
            destination: space ? {space, prefix: currentPrefix} : undefined,
            targetName
          },
          () => copy.runSameFolderCopy(item, currentPrefix, targetName)
        );
      },
      onCancel: () => {
        copy.clearSameFolderPrompt();
        setCopying(null);
      }
    },

    checkingQuality,
    openQualityCheck: () => setCheckingQuality([...selection.selected.values()][0] ?? null),
    closeQualityCheck: () => setCheckingQuality(null),
    finishQualityCheck: () => {
      selection.clear();
      setCheckingQuality(null);
    },

    resolveConflict: async (payload, choice) => {
      // BOTH spaces and the destination prefix come from the PAYLOAD, never from the space this
      // browser happens to be showing. The control that lands here falls back to a bare `/files`
      // whenever its notification carried no usable prefix, and that page resolves the user's
      // personal space — so a source taken from the mount would hash to the wrong FIFO group,
      // take the wrong per-space lock, and be refused for a space the items were never in.
      //
      // A new request id and a fresh `submittedAt`, never a redrive: the queue would swallow a
      // reused id, and a stale timestamp makes the plane refuse the very objects the user has
      // just agreed to overwrite.
      let request;
      try {
        request = buildResubmitRequest(
          payload,
          {requestId: crypto.randomUUID(), submittedAt: new Date().toISOString()},
          choice
        );
      } catch {
        request = undefined;
      }
      // Never a delete: `buildResubmitRequest` answers only for a copy or a move, because a
      // delete has no destination to conflict with.
      if (!request || request.operation === 'delete') return false;
      return submit.submitRequest(request, {
        verb: choice.targetName ? 'Rename' : request.operation === 'move' ? 'Move' : 'Copy',
        itemCount: request.source.items.length,
        label: request.source.items.length === 1 ? choice.targetName : undefined,
        destinationSpace: request.destination.space
      });
    },
    submitting: submit.pending,
    spaceBusyReason: submit.busyReason(space ?? undefined)
  };
}
