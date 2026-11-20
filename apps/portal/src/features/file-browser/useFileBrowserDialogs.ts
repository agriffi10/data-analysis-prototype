import {useEffect, useRef, useState} from 'react';
import {useToast} from '../../components/toastContext';
import {useSelection, type SelectableItem} from './selectionContext';
import {useAsyncFileOperations} from './useAsyncFileOperations';
import {requiresControlPlane} from './fileOpRouting';
import {lastSegment} from './fileBrowser.paths';
import {
  buildResubmitRequest,
  containingFolder,
  requestVerb,
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
  /**
   * Why this SELECTION cannot be acted on right now, if it cannot.
   *
   * Two reasons, and they are different in kind. Either an operation of this session's is still
   * with the plane in one of the spaces this one would touch — temporary, and "try again when it
   * finishes" is true. Or the plane is not taking work at all, and a folder or multi-item gesture
   * — every shape the routing rule sends to it — is refused outright: that one is not temporary,
   * and saying "try again later" would be a lie.
   *
   * Answers `undefined` for a selection that stays in the browser — exactly one file. Refusing a
   * single-file delete the plane never sees would take away something the user could do before,
   * which is the one thing this switchover may not do.
   *
   * **This is the refusal a user meets; the services' per-item one is a backstop** for the race
   * `dispatch` describes. This stops the doomed gesture reaching the delete confirm at all — which
   * otherwise asks "delete the folder and everything inside it? This can't be undone", and then
   * deletes nothing.
   */
  spaceBusyReasonFor: (items: SelectableItem[]) => string | undefined;
  /**
   * The same reason, unconditioned by shape — for a control that reaches a control plane whatever
   * the selection looks like.
   *
   * Archive is the one: it enqueues a single file exactly as it enqueues a folder, so asking the
   * file-ops ROUTING predicate on its behalf would leave it enabled for a one-file selection while
   * a run holds the space — and an archive both writes into and deletes from it.
   */
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
 * What a user is told when the file-operations service is not taking work and the browser has no
 * way to perform the shape they picked.
 *
 * It does not say "try again later": while the service is switched off, later is the same. Saying
 * so would be the one false sentence on this surface.
 */
const PLANE_UNAVAILABLE =
  'Folders and multi-item actions are handled by the file operations service, which is not available.';

/**
 * Every dialog and drawer the file browser can raise, the handlers that resolve one into an
 * operation, and **the one place that decides whether an operation runs here or on the plane**.
 *
 * The selection-clearing rules live here because they belong to the dialog's outcome, not to the
 * row: delete, move, rename, a different-folder copy and a started data-quality check all clear
 * it, while a same-folder copy keeps the dialog (and the selection) until its auto-number prompt
 * settles. A dialog that was cancelled never clears it, and one whose request was REFUSED puts it
 * back — the dialogs clear on the way out, before a request resolves, so a refused enqueue would
 * otherwise cost the user every tick they made.
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
 *
 * @example
 * const dialogs = useFileBrowserDialogs({bucket, currentPrefix, space, destinations, del, move, copy});
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
  const toast = useToast();
  const submit = useFileOpSubmit();
  const asyncFileOps = useAsyncFileOperations();

  const [creatingFolder, setCreatingFolder] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [detailsFile, setDetailsFile] = useState<S3FileItem | null>(null);
  const [detailsFolder, setDetailsFolder] = useState<S3FolderItem | null>(null);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [renaming, setRenaming] = useState<RenameTarget | null>(null);
  const [moving, setMoving] = useState<SelectableItem[] | null>(null);
  const [copying, setCopying] = useState<SelectableItem[] | null>(null);
  const [checkingQuality, setCheckingQuality] = useState<SelectableItem | null>(null);

  // WHERE THE USER IS NOW, not where they were when the handler was made. An enqueue resolves long
  // after the dialog closed, and both values below are captured per render — comparing a handler's
  // own `currentPrefix` against itself is a comparison that is true forever. Written from an
  // effect, which runs after every commit.
  const live = useRef({prefix: currentPrefix, selectionCount: selection.count});
  useEffect(() => {
    live.current = {prefix: currentPrefix, selectionCount: selection.count};
  });

  // The chosen destination bucket, as a space. A move or copy across connections names another
  // space entirely, and the plane resolves a bucket from the space rather than the other way
  // round — so a bucket that matches no known target has no answer at all, and the gesture runs
  // here instead. Each file in it is still attempted; a folder is refused per item, because the
  // browser has no recursive primitive left to run it with.
  function destinationSpaceFor(destBucket: string, destPrefix: string): FileOpDestination | undefined {
    const target = (destinations ?? []).find((d) => d.bucket === destBucket && destPrefix.startsWith(d.rootPrefix));
    if (!target) return undefined;
    return {space: {kind: target.kind, name: target.label}, prefix: destPrefix};
  }

  /**
   * Does this selection's SHAPE need the plane, and can the plane take it?
   *
   * **THE ONE PLACE the routing predicate is consulted**, and it answers both questions from that
   * single call because they have different answers and one of them is new. A shape the browser
   * can perform is never refused — a gate that blocked a single-file delete the plane never sees
   * takes away something the user could do before, which is the one thing this switchover may not
   * do. But a shape the browser CANNOT perform is now unavailable when the plane is off, where it
   * used to run slowly in the browser instead; those are different sentences to a user, and asking
   * the predicate twice to tell them apart would make the routing rule two rules that happen to
   * agree today.
   *
   * `dispatch` also runs a gesture here when the chosen destination resolves to no known space, and
   * that is not knowable until the picker has closed — so a gate can be stricter than the dispatch
   * in exactly that case. Accepted: the alternative is a picker whose refusals change as the user
   * browses it.
   *
   * @param items - The current selection. Empty answers `needsPlane: false`.
   * @param targetName - The proposed leaf name, where a gesture has one.
   * @returns Whether the shape needs the plane, and whether the plane is in a position to take it.
   */
  function planeRouting(items: SelectableItem[], targetName?: string): {needsPlane: boolean; reachable: boolean} {
    // The predicate throws on an empty selection rather than answering for one, because the plane
    // refuses an empty source minutes later by notification — so the emptiness guard comes first.
    if (items.length === 0) return {needsPlane: false, reachable: false};
    return {needsPlane: requiresControlPlane(toFileOpItems(items, targetName)), reachable: !!asyncFileOps && !!space};
  }

  /**
   * Would this selection go to the plane, right now?
   *
   * The dispatch question: shape AND availability. `planeRouting` is where both come from.
   */
  function routesToPlane(items: SelectableItem[], targetName?: string): boolean {
    const {needsPlane, reachable} = planeRouting(items, targetName);
    return needsPlane && reachable;
  }

  /**
   * Why a selection cannot be acted on, or `undefined` when it can.
   *
   * Asked through `routesToPlane` so a shape the browser keeps is never refused — and asked in the
   * order the two reasons actually apply: a shape the plane alone can perform is unavailable
   * outright when the plane is off, which is not the same as a plane that is merely busy.
   */
  function planeReasonFor(items: SelectableItem[]): string | undefined {
    const {needsPlane, reachable} = planeRouting(items);
    if (!needsPlane) return undefined;
    return reachable ? submit.busyReason(space ?? undefined) : PLANE_UNAVAILABLE;
  }

  /** What a gesture did, which is not the same question as whether it succeeded. */
  type Dispatched = 'ran-here' | 'enqueued' | 'refused' | 'busy';

  /**
   * The single routing decision, above all five submission points.
   *
   * `runHere` is the synchronous path exactly as it was — the same hook call with the same
   * arguments — so a selection of one file behaves byte for byte as it did before this plane
   * existed, INCLUDING its timing: its promise is returned, so a caller that awaited the delete
   * before still awaits it.
   *
   * A copy or move whose chosen destination resolves to no known space runs here too. The builder
   * would otherwise throw, and the user would get a generic failure for the whole selection. Run
   * here, each file is still attempted and each folder is refused on its own, by name.
   *
   * **The controls decide when they render; this decides at confirm.** A folder or multi-item
   * gesture therefore reaches the browser's hooks only through a race between the two: the flag
   * refetched and switched off while a dialog was open, or a chosen destination dropping out of
   * the spaces list while the picker was. The hooks then loop what arrives: each file is attempted,
   * and each folder is refused per item with `PlaneRequired`.
   */
  async function dispatch(gesture: FileOpGesture, runHere: () => void | Promise<unknown>): Promise<Dispatched> {
    const needsDestination = gesture.operation !== 'delete';
    if (!routesToPlane(gesture.items, gesture.targetName) || (needsDestination && !gesture.destination) || !space) {
      await runHere();
      return 'ran-here';
    }
    const outcome = await submit.submitGesture(gesture, space);
    return outcome === 'sent' ? 'enqueued' : outcome;
  }

  /**
   * Puts a selection back after an enqueue that never happened.
   *
   * The dialogs clear on the way OUT, before the request resolves, because that is the timing the
   * synchronous paths always had. A refused enqueue — a selection over the plane's caps, a queue
   * that is not configured — would otherwise cost the user every tick they made.
   */
  function restoreOnFailure(outcome: Dispatched, items: SelectableItem[], from: string) {
    if (outcome !== 'refused' || items.length === 0) return;
    // Only back into the folder they came from, and only over an empty selection. The enqueue
    // resolves long after the dialog closed, so the user may have navigated — and putting these
    // rows back then is the ghost selection this browser clears on every prefix change to avoid,
    // pointing at objects that are not in the listing. Ticks made in the meantime win outright:
    // `selectAll` replaces, so restoring over them would discard the newer choice.
    if (from !== live.current.prefix || live.current.selectionCount > 0) return;
    selection.selectAll(items);
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
    // Awaited by its dialog where the other three are fire-and-forget, and the dispatch returns
    // the SYNCHRONOUS delete's own promise as well as the enqueue's — so the close-and-clear waits
    // for whichever ran. Closing first would dismiss the dialog before either resolved and lose
    // the busy state the confirm control reads. Because the clear comes AFTER the request, a
    // refused one simply keeps the selection rather than clearing and restoring it — a restore
    // here would read the live count from before this clear and skip itself.
    confirmDelete: async () => {
      const items = [...selection.selected.values()];
      const outcome = await dispatch({operation: 'delete', items}, () => del.runDelete(items));
      if (outcome !== 'refused') selection.clear();
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
      // Nothing to restore here: a rename's item comes from the details panel, not from a
      // selection the user built up tick by tick.
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
      const from = currentPrefix;
      setMoving(null);
      selection.clear();
      void dispatch({operation: 'move', items, destination: destinationSpaceFor(destBucket, destPrefix)}, () =>
        move.moveItems(items, destPrefix, destBucket)
      ).then((outcome) => restoreOnFailure(outcome, items, from));
    },

    copying,
    // The dialog shows the copy error while it is open, so one from an earlier copy is dropped
    // on the way in, and the dialog's own is not left behind on the page on the way out.
    openCopy: () => {
      copy.dismissError();
      setCopying([...selection.selected.values()]);
    },
    cancelCopy: () => {
      copy.cancelCollision();
      copy.dismissError();
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
      const from = currentPrefix;
      setCopying(null);
      selection.clear();
      void dispatch({operation: 'copy', items, destination: destinationSpaceFor(destBucket, destPrefix)}, () =>
        copy.copyItems(items, destPrefix, destBucket)
      ).then((outcome) => restoreOnFailure(outcome, items, from));
    },

    sameFolderPrompt: copy.sameFolderPrompt && {
      ...copy.sameFolderPrompt,
      onConfirm: (name) => {
        const item = copying?.[0];
        const from = currentPrefix;
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
        ).then((outcome) => restoreOnFailure(outcome, [item], from));
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
      if (!request || request.operation === 'delete') {
        // A destructive confirm that quietly does nothing is the worst outcome available here:
        // the user presses Overwrite, the dialog stays exactly as it was, and they press it again.
        toast.push({
          variant: 'danger',
          message: 'That notification no longer carries enough detail to request those items again.'
        });
        return false;
      }
      return (
        (await submit.submitRequest(request, {
          verb: requestVerb(request),
          itemCount: request.source.items.length,
          // The item's own name, as the first submit labelled it — not the name it is going to.
          label: request.source.items.length === 1 ? lastSegment(request.source.items[0].key ?? '') : undefined,
          destinationSpace: request.destination.space
        })) === 'sent'
      );
    },
    submitting: submit.pending,
    spaceBusyReasonFor: (items) => planeReasonFor(items),
    spaceBusyReason: submit.busyReason(space ?? undefined)
  };
}
