import {useCallback, useRef, useState} from 'react';
import {useToast} from '../../components/toastContext';
import {toUserMessage} from '../../lib/errorMessages';
import {enqueueQualityCheck} from './dataQuality.service';
import {locationLabel} from './dataQuality.format';
import type {DataQualitySpace} from './dataQuality.types';

/** One file or one folder to check, in the space that holds it. */
export type DataQualityTarget = {
  space: DataQualitySpace;
  /** The file key or folder prefix, relative to the space's bucket. */
  location: string;
};

export type UseDataQualityCheckResult = {
  start: (target: DataQualityTarget) => Promise<void>;
  isPending: boolean;
};

/**
 * Start a data-quality check: mint the request id, enqueue it, and tell the user.
 *
 * `start` reports the outcome ONLY as a toast — success or, via `toUserMessage`, a friendly
 * failure — and resolves either way. That is deliberate rather than lossy: the confirm
 * dialog has nothing to re-enter, so holding it open on failure would strand the user on a
 * dialog whose only remaining move is Cancel, and the report page's "Re-run check" invokes
 * this with no dialog mounted at all, where the toast is the only channel there is.
 *
 * The check itself is asynchronous and takes minutes; the durable outcome arrives as a
 * notification. Success here means *enqueued*, never *checked*.
 *
 * @example
 * const {start, isPending} = useDataQualityCheck();
 * await start({space, location: 'alice/sales/'});
 */
export function useDataQualityCheck(): UseDataQualityCheckResult {
  const [isPending, setIsPending] = useState(false);
  const toast = useToast();
  // A ref, not the state, guards re-entry: two clicks landing in the same render would both
  // read `isPending === false` and enqueue twice. The disabled button is the visible guard;
  // this is the one that actually holds.
  const inFlight = useRef(false);

  const start = useCallback(
    async (target: DataQualityTarget): Promise<void> => {
      if (inFlight.current) return;
      inFlight.current = true;
      setIsPending(true);
      try {
        const result = await enqueueQualityCheck({
          requestId: crypto.randomUUID(),
          space: target.space,
          location: target.location
        });
        toast.push(
          result.success
            ? {
                variant: 'success',
                message: `Checking “${locationLabel(target.location)}”… you’ll be notified when it’s done.`
              }
            : {variant: 'danger', message: toUserMessage(result.error).message}
        );
      } finally {
        inFlight.current = false;
        setIsPending(false);
      }
    },
    [toast]
  );

  return {start, isPending};
}
