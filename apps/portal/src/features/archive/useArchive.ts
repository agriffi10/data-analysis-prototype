import {useRef, useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {toUserText} from '../../lib/errorMessages';
import {unwrap} from '../../lib/serviceResult';
import {enqueueArchive, enqueueRestore, listArchives} from './archive.service';
import type {ArchiveItem, ArchiveSpace} from '../../types/archive.types';

// Only a success is ever pushed: a FAILURE stays in the dialog, beside the selection or the
// pasted id the user would have to reproduce if it closed. The union is the toast host's,
// narrowed here to what these hooks actually send.
type ArchiveToast = {variant: 'success'; message: string};

/**
 * Dialog + enqueue state for Archive.
 *
 * `open(items)` targets a selection or a single item; `submit()` enqueues via `enqueueArchive` —
 * on success the dialog closes and `notify` gets a transient toast, and on failure the dialog
 * stays open with `error` set and the selection intact.
 *
 * THE REQUEST ID IS MINTED PER SUBMIT, not per open, and here it is doing two jobs: it is the
 * queue's `MessageDeduplicationId` and it becomes the archive's permanent identity. Keeping one
 * id across a failed attempt would make the queue swallow the retry — the user sees an error,
 * presses the button again, and nothing at all happens. The trade
 * is a submit whose response was lost being retried as a new request; the plane refuses that as
 * `request_id_reused` only if the first one actually got far enough to write, and otherwise it
 * is simply a second archive.
 */
export function useArchive(space: ArchiveSpace | null, notify: (toast: ArchiveToast) => void) {
  const [items, setItems] = useState<ArchiveItem[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // A ref, not `busy`: a second click in the same tick reads the state before React has
  // re-rendered, so the state read loses the race (the reasoning useDataQualityCheck records).
  const inFlight = useRef(false);

  const open = (selected: ArchiveItem[]) => {
    setError(null);
    setItems(selected);
  };

  const close = () => {
    if (busy) return;
    setItems(null);
    setError(null);
  };

  /**
   * Enqueue, and report whether it worked.
   *
   * THE RETURN VALUE IS LOAD-BEARING: the caller clears the selection and invalidates the
   * listing only after a successful enqueue, and reading `error` from the enclosing render to
   * decide would read the value from BEFORE the submit — clearing the selection under a dialog
   * whose retry then has nothing to archive (the journey test caught exactly that).
   *
   * @param name - What the user called the archive, as typed; the service normalises it and an
   *   empty one sends no name.
   */
  const submit = async (name = ''): Promise<boolean> => {
    if (!items || !space || inFlight.current) return false;
    inFlight.current = true;
    try {
      setBusy(true);
      setError(null);
      const result = await enqueueArchive({requestId: crypto.randomUUID(), space, items, name});
      if (!result.success) {
        setError(toUserText(result.error));
        return false;
      }
      setItems(null);
      notify({
        variant: 'success',
        // "Started", never "archived": the plane copies to Glacier, confirms every object and
        // only then deletes, which takes minutes. Claiming the files are archived here would be
        // wrong for as long as that runs, and simply false for a run that rolls back.
        message: 'Archive started — you’ll get a notification when it finishes.'
      });
      return true;
    } catch (err) {
      // `enqueueArchive` returns a ServiceResult and does not normally throw — but the request
      // is BUILT before that contract starts, and `crypto.randomUUID()` here is undefined outside
      // a secure context. Without this catch its throw escapes the click handler: the `finally`
      // still frees the dialog, but the confirm does nothing and shows no error.
      setError(toUserText(err));
      return false;
    } finally {
      // BOTH cleared on every exit — success, failure and a throw — so one dropped click never
      // wedges the dialog.
      setBusy(false);
      inFlight.current = false;
    }
  };

  return {items, busy, error, open, close, submit};
}

/**
 * Dialog + enqueue state for Restore Archived Data.
 *
 * Beside `useArchive` rather than in its own file because the two are one plane's two modes and
 * share every rule that matters here — the per-submit request id, the in-flight ref, the busy
 * lock, and "success means enqueued". What differs is the shape of what is submitted, and that
 * is the whole of the difference.
 *
 * `requestId` and `archiveId` are DIFFERENT values: this run's id, and the
 * archive it names. A refused restore must be re-submittable, so the run id is minted per submit
 * exactly as the archive's is.
 */
export function useRestoreArchive(space: ArchiveSpace | null, notify: (toast: ArchiveToast) => void) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);

  const submit = async (archiveId: string): Promise<boolean> => {
    if (!space || inFlight.current) return false;
    inFlight.current = true;
    try {
      setBusy(true);
      setError(null);
      const result = await enqueueRestore({
        requestId: crypto.randomUUID(),
        space,
        // Lowercased for the same reason `arcommon.paths` lowercases it: S3 keys are
        // case-sensitive, so a receipt read back in upper case must still resolve one prefix.
        archiveId: archiveId.trim().toLowerCase()
      });
      if (!result.success) {
        setError(toUserText(result.error));
        return false;
      }
      setOpen(false);
      notify({
        variant: 'success',
        message:
          'Restore requested — it takes several hours, and you’ll get a notification when it starts and another when it finishes.'
      });
      return true;
    } catch (err) {
      setError(toUserText(err));
      return false;
    } finally {
      setBusy(false);
      inFlight.current = false;
    }
  };

  return {
    open,
    busy,
    error,
    openDialog: () => {
      setError(null);
      setOpen(true);
    },
    close: () => {
      if (busy) return;
      setOpen(false);
      setError(null);
    },
    submit
  };
}

/** The archive feature's query keys, kept beside the one hook that uses them. */
export const archiveKeys = {
  all: ['archive'] as const,
  list: (space: ArchiveSpace) => [...archiveKeys.all, 'list', space.kind, space.name] as const
};

/**
 * The restore dialog's list of the space's archives.
 *
 * Fetched while the dialog is open and stale at once, so every opening reads the receipt folder
 * afresh — a restore requested a minute ago shows its new status the next time, with no
 * invalidation to remember — while the rows already in the cache show during the refetch. It is
 * not refetched on window focus: a list that reorders under the user's selection is worse than
 * one that is a few minutes old.
 *
 * @param space - The space being restored into, or null before one is known.
 * @param enabled - Whether the dialog is open.
 * @returns The query; its error is the receipt folder failing to list, never the index.
 */
export function useArchiveList(space: ArchiveSpace | null, enabled: boolean) {
  return useQuery({
    queryKey: space ? archiveKeys.list(space) : [...archiveKeys.all, 'list', 'none'],
    enabled: enabled && space !== null,
    queryFn: async () => unwrap(await listArchives(space as ArchiveSpace)),
    staleTime: 0,
    refetchOnWindowFocus: false
  });
}
