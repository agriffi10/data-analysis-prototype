import {useUploadQueue} from './uploadQueueContext';
import {TERMINAL_STATUSES} from './upload.types';

/**
 * What reloading the page would cost the upload queue, said only while there is a cost.
 *
 * Shown in the app shell's crash panel. That panel's one button reloads the page, and a reload
 * ends every upload the session is still sending — where opening another page keeps them, because
 * the queue lives in the shell rather than the page that crashed. Counts every upload not yet
 * finished — running, waiting to start, or waiting on a name decision — since a reload loses all
 * three; renders nothing when none is left.
 *
 * @example
 * <ErrorBoundary notice={<UploadsAtRiskNotice />}>{children}</ErrorBoundary>
 */
export function UploadsAtRiskNotice() {
  const {items} = useUploadQueue();
  const pending = items.filter((item) => !TERMINAL_STATUSES.has(item.status)).length;
  if (pending === 0) return null;

  return (
    <p className="max-w-prose font-medium text-text">
      {pending === 1
        ? 'Reloading cancels the upload still in progress — to keep it, open another page instead.'
        : `Reloading cancels the ${pending} uploads still in progress — to keep them, open another page instead.`}
    </p>
  );
}
