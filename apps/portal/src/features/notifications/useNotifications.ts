import {useEffect, useMemo, useRef} from 'react';
import {useMutation, useQuery, useQueryClient, type QueryClient} from '@tanstack/react-query';
import {getNotifications, enqueueNotificationAction} from './notifications.service';
import {unwrap} from '../../lib/serviceResult';
import {notificationsKeys} from './notificationsKeys';
import {NO_KEY} from '../../lib/queryKeys';
import type {Notification} from './notifications.types';

// Background poll cadence for the unread indicator. Runs continuously (not just
// until something is unread) so the bell count stays live as further notifications
// arrive. Not pausable per caller: TanStack runs `refetchInterval` per observer, and the
// header bell observes this key on every page, so one caller's pause would stop nothing.
const POLL_INTERVAL_MS = 60_000;

// After a successful enqueue, refetch a few times to pick up the writer's eventual
// (async) write. Staggered to cover writer cold-start latency; the pending-read
// overlay holds optimistic state until a refetch confirms it, so a reconcile that
// races ahead of the writer can't revert the UI back to unread.
const RECONCILE_DELAYS_MS = [2_500, 9_000, 18_000];

export type UseNotificationsOptions = {
  /** Called on enqueue failure, after the optimistic change is rolled back (e.g. to show a toast). */
  /** Receives the failed mutation's error (mapped to friendly text by the caller). */
  onMutationError?: (error: unknown) => void;
};

export type UseNotificationsResult = {
  notifications: Notification[];
  unreadCount: number;
  hasUnread: boolean;
  isLoading: boolean;
  isError: boolean;
  refresh: () => Promise<unknown>;
  markRead: (id: string) => void;
  markAllRead: () => void;
};

function countUnread(list: Notification[] | undefined): number {
  return (list ?? []).reduce((n, item) => (item.read ? n : n + 1), 0);
}

/**
 * Reads the user has asked for that the writer has not yet confirmed, by id.
 *
 * Mark-all goes through the same ids, recording the rows unread when it was pressed: an
 * "everything" flag would also cover rows that arrived after it, and it cleared only once
 * every row read as read — so a notification landing before the writer caught up showed as
 * read, and so did every one after it, for as long as the overlay lived.
 */
type PendingReads = {ids: readonly string[]};

const NO_PENDING_READS: PendingReads = {ids: []};

/**
 * Drop every pending read the server has confirmed, or whose row aged out of the capped inbox,
 * so the overlay never grows without bound.
 *
 * @param current - The overlay as it stands.
 * @param list - The server's latest list.
 * @returns `current` itself when nothing changed, so a caller can skip the write.
 */
function prunePendingReads(current: PendingReads, list: Notification[]): PendingReads {
  const ids = current.ids.filter((id) => list.some((n) => n.id === id && !n.read));
  return ids.length === current.ids.length ? current : {ids};
}

/**
 * Notifications list + unread indicator for one user.
 *
 * Reads via TanStack Query (keyed per user, 60s poll). Mutations only enqueue onto
 * the notifications queue — the browser never writes the inbox — so mark-read state
 * is held as an optimistic overlay on top of server truth and cleared per-entry once
 * a delayed reconcile refetch confirms the writer applied it. Disabled when signed out.
 *
 * The overlay lives in the query cache rather than in this hook's own state, because the
 * header bell and the Notifications page are two instances: held per instance, a read marked
 * on the page left the bell's count unchanged until a refetch caught the writer up.
 */
export function useNotifications(
  username: string | null,
  options: UseNotificationsOptions = {}
): UseNotificationsResult {
  const queryClient = useQueryClient();
  const key = notificationsKeys.list(username ?? NO_KEY);
  const onMutationError = options.onMutationError;

  const query = useQuery({
    queryKey: key,
    enabled: username !== null,
    queryFn: async (): Promise<Notification[]> => {
      const result = await getNotifications(username as string);
      return unwrap(result);
    },
    refetchInterval: POLL_INTERVAL_MS,
    // Returning to the tab re-checks once regardless of poll state; the interval
    // itself is paused while the tab is hidden (refetchIntervalInBackground is false).
    refetchOnWindowFocus: true
  });

  // The writer applies mark-read/all asynchronously and can lag. Rather than mutate
  // the read cache (which a refetch racing ahead of the writer would revert), hold
  // optimistic reads as an overlay on server truth and clear each only once the
  // server confirms it — that's what makes a mark-read stick instead of snapping back.
  // Never fetched: the entry exists only to be shared, so its queryFn returns what is there.
  const pendingKey = notificationsKeys.pendingReads(username ?? NO_KEY);
  const {data: pending} = useQuery({
    queryKey: pendingKey,
    queryFn: () => queryClient.getQueryData<PendingReads>(pendingKey) ?? NO_PENDING_READS,
    initialData: NO_PENDING_READS,
    enabled: false,
    staleTime: Infinity,
    gcTime: Infinity
  });
  const updatePending = (update: (current: PendingReads) => PendingReads) =>
    queryClient.setQueryData<PendingReads>(pendingKey, (current) => update(current ?? NO_PENDING_READS));

  // Reconcile timers are cleared on unmount so no stray invalidate fires. Capture the
  // ref OBJECT (stable) and read its `.current` array at teardown — so it clears
  // whatever is pending even if the array is later reassigned, rather than a snapshot
  // taken at mount (the fragile pattern this replaces).
  const reconcileTimers = useRef<ReturnType<typeof setTimeout>[]>([]);
  useEffect(() => {
    const timersRef = reconcileTimers;
    return () => timersRef.current.forEach(clearTimeout);
  }, []);

  const scheduleReconcile = () => {
    for (const delay of RECONCILE_DELAYS_MS) {
      const handle = setTimeout(() => {
        void queryClient.invalidateQueries({queryKey: key});
      }, delay);
      reconcileTimers.current.push(handle);
    }
  };

  // Clear overlay entries the writer has confirmed. In an effect rather than during render:
  // the overlay is shared, and writing it while rendering would update the other instance
  // mid-render.
  useEffect(() => {
    const list = query.data;
    if (!list) return;
    const sharedKey = notificationsKeys.pendingReads(username ?? NO_KEY);
    const current = queryClient.getQueryData<PendingReads>(sharedKey) ?? NO_PENDING_READS;
    const pruned = prunePendingReads(current, list);
    if (pruned !== current) queryClient.setQueryData(sharedKey, pruned);
  }, [query.data, queryClient, username]);

  const markReadMutation = useMutation<void, Error, string>({
    mutationFn: async (id: string): Promise<void> => {
      const result = await enqueueNotificationAction({action: 'markRead', username: username as string, id});
      unwrap(result);
    },
    onMutate: (id: string) => updatePending((p) => (p.ids.includes(id) ? p : {...p, ids: [...p.ids, id]})),
    onError: (err, id) => {
      updatePending((p) => ({...p, ids: p.ids.filter((pendingId) => pendingId !== id)}));
      onMutationError?.(err);
    },
    onSuccess: scheduleReconcile
  });

  // The context is the ids THIS mark-all added, so a failure takes back exactly those and
  // leaves a separate, still-pending mark-read alone.
  const markAllReadMutation = useMutation<void, Error, void, string[]>({
    mutationFn: async (): Promise<void> => {
      const result = await enqueueNotificationAction({action: 'markAllRead', username: username as string});
      unwrap(result);
    },
    onMutate: () => {
      const unread = (queryClient.getQueryData<Notification[]>(key) ?? []).filter((n) => !n.read).map((n) => n.id);
      const current = queryClient.getQueryData<PendingReads>(pendingKey) ?? NO_PENDING_READS;
      const added = unread.filter((id) => !current.ids.includes(id));
      updatePending((p) => ({ids: [...p.ids, ...added.filter((id) => !p.ids.includes(id))]}));
      return added;
    },
    onError: (err, _vars, added) => {
      updatePending((p) => ({ids: p.ids.filter((id) => !(added ?? []).includes(id))}));
      onMutationError?.(err);
    },
    onSuccess: scheduleReconcile
  });

  // Server truth with the optimistic read overlay applied.
  const notifications = useMemo<Notification[]>(() => {
    const list = query.data ?? [];
    if (pending.ids.length === 0) return list;
    return list.map((n) => (!n.read && pending.ids.includes(n.id) ? {...n, read: true} : n));
  }, [query.data, pending]);

  const unreadCount = useMemo(() => countUnread(notifications), [notifications]);

  return {
    notifications,
    unreadCount,
    hasUnread: unreadCount > 0,
    isLoading: query.isPending && username !== null,
    isError: query.isError,
    refresh: () => queryClient.invalidateQueries({queryKey: key}),
    markRead: (id: string) => {
      if (username === null) return;
      markReadMutation.mutate(id);
    },
    markAllRead: () => {
      if (username === null) return;
      markAllReadMutation.mutate();
    }
  };
}

/**
 * Prefetch the notifications inbox once on authenticated app load so the header
 * indicator is accurate before first interaction. prefetchQuery swallows fetch
 * errors, so a failed prefetch never blocks the shell; no-op when signed out.
 */
export async function prefetchNotifications(queryClient: QueryClient, username: string | null): Promise<void> {
  if (!username) return;
  await queryClient.prefetchQuery({
    queryKey: notificationsKeys.list(username),
    queryFn: async (): Promise<Notification[]> => {
      const result = await getNotifications(username);
      return unwrap(result);
    }
  });
}
