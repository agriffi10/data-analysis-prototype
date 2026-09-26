import {useRef, useState} from 'react';
import {toUserText} from '../../lib/errorMessages';
import {enqueueArchive, enqueueRestore} from './archive.service';
import type {ArchiveItem, ArchiveSpace} from '../../types/archive.types';

// Only a success is ever pushed: a FAILURE stays in the dialog, beside the selection or the
// pasted id the user would have to reproduce if it closed. The union is the toast host's,
// narrowed here to what these hooks actually send.
type ArchiveToast = {variant: 'success'; message: string};

/**
 * The archive id's shape, checked before enqueue.
 *
 * The SERVER validates it again — `arcommon.paths.validated_archive_id`, before the value is
 * concatenated into any key — and that is the boundary. This copy exists so a typo costs the
 * user a sentence now rather than a notification hours later, which on this plane is the whole
 * difference: a restore that fails at the front door still spent none of the 3-5 hours.
 */
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/**
 * Is this a well-formed archive id? Held to the SAME pattern the control plane uses, rather than
 * a laxer "looks like a uuid" — a second, looser rule in the browser would report a value as
 * valid that the plane then refuses, which is the failure this check exists to prevent.
 */
export function isArchiveId(value: string): boolean {
  return UUID_V4.test(value.trim());
}

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
   */
  const submit = async (): Promise<boolean> => {
    if (!items || !space || inFlight.current) return false;
    inFlight.current = true;
    try {
      setBusy(true);
      setError(null);
      const result = await enqueueArchive({requestId: crypto.randomUUID(), space, items});
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
