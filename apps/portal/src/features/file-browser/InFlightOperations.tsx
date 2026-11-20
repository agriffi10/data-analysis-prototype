import {Link} from '../../lib/navigation';
import {formatRelativeTime} from '../../lib/format';
import {useAsyncFileOperations} from './useAsyncFileOperations';
import {useFileOpsInFlight} from './fileOpsInFlightContext';
import type {InFlightOperation} from './fileOps.types';

/** What this run is doing, in the words the user's own gesture used. */
function describe(operation: InFlightOperation): string {
  const what = operation.label ?? `${operation.itemCount} ${operation.itemCount === 1 ? 'item' : 'items'}`;
  const verb = {Copy: 'Copying', Move: 'Moving', Rename: 'Renaming', Delete: 'Deleting'}[operation.verb];
  return `${verb} ${what}`;
}

/** The one line that says where this run got to, or that it has not got there yet. */
function status(operation: InFlightOperation): string {
  switch (operation.state) {
    case 'settled':
      return 'Finished — see your notifications for what happened.';
    case 'refused':
      return 'Didn’t finish — see your notifications for what happened.';
    case 'expired':
      return 'No result arrived. Check your notifications, or refresh the folder to see where things stand.';
    default:
      return 'Running in the background. You’ll get a notification when it finishes.';
  }
}

/**
 * What this session has handed to the file-operations plane, and how far each one got.
 *
 * **A persistent in-flight surface has no precedent in this repo, and it is justified on its
 * merits rather than by citation.** The upload queue is not one: its provider is session-scoped
 * at the shell so uploads survive navigation, but its list renders inside a drawer that only
 * exists while it is open. The three async planes already in the file browser — send, archive,
 * restore — have no in-flight surface at all; they toast and hand off to notifications. That is
 * survivable for an action the user chose to fire and forget. It is not survivable here, because
 * these gestures replaced synchronous ones: a user who copies a folder and watches nothing happen
 * has no way to tell "accepted, running" from "the click missed".
 *
 * **There is no progress percentage.** `onProgress` went with the browser's own copy loop, and
 * the plane reports outcomes only at the end. This says what is running and since when.
 *
 * **Every entry is dismissible**, and that is load-bearing rather than tidy: an entry settles
 * when a notification carrying its `requestId` arrives, and a request whose notification never
 * reaches the inbox has nothing to match. Dismiss is what releases the per-space submit gate
 * when correlation never comes.
 */
export function InFlightOperations() {
  const {operations, dismiss} = useFileOpsInFlight();
  // Gated with the switchover it belongs to, not with `files`: with the routing off nothing can
  // ever be added here, and a permanently empty region is not something to keep mounted. Through
  // the SHARED reading of the flag, so a gesture can never enqueue into a store whose only surface
  // is hidden — the dismiss here is what frees a space whose run never correlates.
  const enabled = useAsyncFileOperations();
  if (!enabled || operations.length === 0) return null;

  return (
    <section
      aria-label="File operations in progress"
      className="fixed inset-x-3 bottom-24 z-30 ml-auto max-w-sm space-y-2 tablet:inset-x-auto tablet:bottom-4 tablet:right-4">
      {operations.map((operation) => (
        <div
          key={operation.requestId}
          className="flex items-start gap-3 rounded-lg border border-border bg-surface p-3 shadow-lg">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-text">{describe(operation)}</p>
            <p className="mt-0.5 text-xs text-text-3">Started {formatRelativeTime(operation.submittedAt)}</p>
            <p className="mt-1 text-xs text-text-2">{status(operation)}</p>
            {operation.state !== 'submitted' && (
              <p className="mt-1">
                <Link
                  to="/notifications"
                  className="text-xs font-medium underline underline-offset-2 hover:text-accent-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
                  Open notifications
                </Link>
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={() => dismiss(operation.requestId)}
            className="flex-none rounded-md px-2 py-1 text-xs font-medium text-text-2 hover:bg-surface-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            aria-label={`Dismiss ${describe(operation).toLowerCase()}`}>
            Dismiss
          </button>
        </div>
      ))}
    </section>
  );
}
