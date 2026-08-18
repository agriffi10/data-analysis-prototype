import {useCallback, useRef, useState} from 'react';
import {useToast} from '../../components/toastContext';
import {toUserText} from '../../lib/errorMessages';
import {enqueueQualityCheck} from './dataQuality.service';
import {locationLabel} from './dataQuality.format';
import type {DataQualitySpace} from './dataQuality.types';

/** One file or one folder to check, in the space that holds it. */
export type DataQualityTarget = {
  space: DataQualitySpace;
  /** The file key or folder prefix, relative to the space's bucket. */
  location: string;
};

/** How the caller wants the outcome announced. */
export type StartQualityCheckOptions = {
  /**
   * Push the success/failure toast. Default true — the Files-browser behaviour, unchanged.
   * The dashboard passes false because it raises its own banner, which says strictly more:
   * one action, one confirmation.
   */
  toast?: boolean;
};

export type UseDataQualityCheckResult = {
  /** Resolves true when the request was enqueued, false when it failed. */
  start: (target: DataQualityTarget, opts?: StartQualityCheckOptions) => Promise<boolean>;
  isPending: boolean;
};

/**
 * Start a data-quality check: mint the request id, enqueue it, and tell the user.
 *
 * `start` reports the outcome two ways, and callers pick. It always RESOLVES to the outcome
 * — the dashboard dialog needs it, because a dialog that closes on failure loses the target
 * the user just browsed to. And unless `opts.toast` is false it also pushes a toast: success,
 * or a friendly failure via `toUserMessage`. The Files-browser confirm dialog leans on that
 * toast and ignores the return: it has nothing to re-enter, so holding it open on failure
 * would strand the user on a dialog whose only remaining move is Cancel — and the report
 * page's "Re-run check" invokes this with no dialog mounted at all, where the toast is the
 * only channel there is.
 *
 * The check itself is asynchronous and takes minutes. Success here means *enqueued*, never
 * *checked* — the outcome arrives as a notification carrying a link to the report,
 * which is what lets this stop at "started" without stranding the user.
 *
 * @example
 * const {start, isPending} = useDataQualityCheck();
 * await start({space, location: 'alice/sales/'});          // toast
 * const ok = await start(target, {toast: false});          // caller announces it
 */
export function useDataQualityCheck(): UseDataQualityCheckResult {
  const [isPending, setIsPending] = useState(false);
  const toast = useToast();
  // A ref, not the state, guards re-entry: two clicks landing in the same render would both
  // read `isPending === false` and enqueue twice. The disabled button is the visible guard;
  // this is the one that actually holds.
  const inFlight = useRef(false);

  const start = useCallback(
    async (target: DataQualityTarget, opts?: StartQualityCheckOptions): Promise<boolean> => {
      // A re-entrant call enqueued nothing, so it reports failure — a caller must never
      // read a dropped click as a started check.
      if (inFlight.current) return false;
      inFlight.current = true;
      setIsPending(true);
      try {
        const result = await enqueueQualityCheck({
          requestId: crypto.randomUUID(),
          space: target.space,
          location: target.location
        });
        if (result.success) {
          // `toast: false` suppresses the SUCCESS toast only. A caller opts out because it
          // has a better receipt of its own (the dashboard's banner), never because it wants
          // a silent failure — and no caller re-implements the failure wording, which is
          // `toUserMessage`'s and lives here.
          if (opts?.toast !== false) {
            toast.push({
              variant: 'success',
              message: `Checking “${locationLabel(target.location)}”… you’ll get a notification when it finishes.`
            });
          }
        } else {
          toast.push({variant: 'danger', message: toUserText(result.error)});
        }
        return result.success;
      } finally {
        inFlight.current = false;
        setIsPending(false);
      }
    },
    [toast]
  );

  return {start, isPending};
}
