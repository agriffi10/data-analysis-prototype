import {useAuth} from '../auth';
import {useNotifications, type NotificationPayload} from '../notifications';
import {itemResultsFromPayload} from './fileOps.outcomes';
import type {FileOpItemResult} from './fileOps.types';

export type FileOpConflicts = {
  payload: NotificationPayload;
  results: FileOpItemResult[];
};

/**
 * The conflicted items of one run, found by request id.
 *
 * **The notification is the source, and it is the only one that can be.** The conflict view is
 * reachable from a tab that never submitted — which is why the plane puts the request id on
 * every row it writes — and the tab that did submit knows what it SENT, never which items the
 * plane could not place. Reading the submitting tab's own record would give the right answer in
 * the one case that needs it least.
 *
 * A run with no conflicts resolves to nothing, and so does a request id nobody wrote a
 * notification for: both render as no view at all rather than as an empty one, because the id
 * arrives in a URL anyone can type.
 *
 * @param requestId - The `?requestId=` the row's own control minted, or null.
 * @returns The payload and its items, or null.
 */
export function useFileOpConflicts(requestId: string | null): FileOpConflicts | null {
  const {status, user} = useAuth();
  const username = status === 'authenticated' ? (user?.username ?? null) : null;
  // The same query key the header bell already polls, so this costs no extra request.
  const {notifications} = useNotifications(username);
  if (!requestId) return null;

  const row = notifications.find(
    (notification) => notification.payload?.requestId === requestId && (notification.payload.conflicts?.length ?? 0) > 0
  );
  if (!row?.payload) return null;
  return {payload: row.payload, results: itemResultsFromPayload(row.payload)};
}
