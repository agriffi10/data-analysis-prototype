import {useRef, useState} from 'react';
import {toUserText} from '../../lib/errorMessages';
import {enqueueFileSend} from './fileSend.service';
import type {SendItem, SendRecipient, SendSourceSpace} from './fileSend.types';

type SendToast = {variant: 'success' | 'danger'; message: string};

/**
 * Dialog + enqueue state for "Send to…" (SPEC-167).
 *
 * `open(items)` targets the current selection; `submit` enqueues via `enqueueFileSend` — on
 * success the dialog closes and `notify` gets a transient toast, and on failure the dialog stays
 * open with `error` set and the recipients the user typed still there (FR-003).
 *
 * THE REQUEST ID IS MINTED PER SUBMIT, not per open. It is the queue's `MessageDeduplicationId`
 * and the only double-submit guard there is, so a dialog that kept one across a failed attempt
 * would have its retry silently swallowed by the queue — the user would see an error, press the
 * button again, and nothing at all would happen.
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
      setBusy(false);
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
        message: `Sending ${recipients.length === 1 ? 'to 1 recipient' : `to ${recipients.length} recipients`} — you'll get a notification for each one.`
      });
      return true;
    } finally {
      // Cleared on every exit — success, failure and a throw — so one dropped click never
      // wedges the dialog.
      inFlight.current = false;
    }
  };

  return {items, busy, error, open, close, submit};
}
