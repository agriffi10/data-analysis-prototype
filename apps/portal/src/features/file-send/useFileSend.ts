import {useRef, useState} from 'react';
import {toUserText} from '../../lib/errorMessages';
import {enqueueFileSend} from './fileSend.service';
import type {SendItem, SendRecipient, SendSourceSpace} from './fileSend.types';

// Only a success is ever pushed: a FAILURE stays in the dialog, next to the recipients the user
// would have to retype if it closed. The union is the toast host's, narrowed here to what this
// hook actually sends.
type SendToast = {variant: 'success'; message: string};

/**
 * Dialog + enqueue state for "Send to…".
 *
 * `open(items)` targets the current selection; `submit` enqueues via `enqueueFileSend` — on
 * success the dialog closes and `notify` gets a transient toast, and on failure the dialog stays
 * open with `error` set and the recipients the user typed still there.
 *
 * THE REQUEST ID IS MINTED PER SUBMIT, not per open — which means the queue's
 * `MessageDeduplicationId` is NOT the double-submit guard on this plane; the in-flight ref below
 * and the busy lock are. Keeping one id across a failed attempt would make the queue swallow the
 * retry: the user sees an error, presses the button again, and nothing at all happens. The trade
 * is a send whose response was lost being retried as a new request, which the control plane's
 * conflict guard then refuses per recipient and tells the sender about.
 */
export function useFileSend(space: SendSourceSpace | null, notify: (toast: SendToast) => void) {
  const [items, setItems] = useState<SendItem[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // A ref, not `busy`: a second click in the same tick reads the state before React has
  // re-rendered, so the state read loses the race (the reasoning useDataQualityCheck records).
  const inFlight = useRef(false);

  const open = (selected: SendItem[]) => {
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
   * THE RETURN VALUE IS LOAD-BEARING, not a convenience: the caller clears the selection after a
   * successful send, and reading `error` from the enclosing render to decide would read the
   * value from BEFORE the submit — clearing the selection under a dialog whose retry then has
   * nothing to send.
   */
  const submit = async (recipients: SendRecipient[]): Promise<boolean> => {
    if (!items || !space || inFlight.current) return false;
    inFlight.current = true;
    try {
      setBusy(true);
      setError(null);
      const result = await enqueueFileSend({
        requestId: crypto.randomUUID(),
        space,
        items,
        recipients
      });
      if (!result.success) {
        setError(toUserText(result.error));
        return false;
      }
      setItems(null);
      notify({
        variant: 'success',
        // "Requested", never "sent": the plane copies in the background, and the outcome per
        // recipient arrives as a notification. Claiming delivery here would be a lie for the
        // several minutes a large send takes, and simply wrong for one that conflicts.
        message: `Send requested to ${recipients.length === 1 ? '1 recipient' : `${recipients.length} recipients`} — you'll get a notification for each one.`
      });
      return true;
    } catch (err) {
      // `enqueueFileSend` returns a ServiceResult and does not normally throw — but the request
      // is BUILT before that contract starts, and `crypto.randomUUID()` here is undefined outside
      // a secure context, which is the documented dev-preview shape. A throw here used to leave
      // `busy` true forever: the submit control reads "Sending…", Cancel is disabled, the modal
      // refuses to dismiss and swallows Escape, and `close()` refuses because it is busy — an
      // unrecoverable dialog, with no error shown.
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
