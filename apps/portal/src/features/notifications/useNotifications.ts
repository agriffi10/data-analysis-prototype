import {useEffect, useMemo, useRef, useState} from 'react';
import {useMutation, useQuery, useQueryClient, type QueryClient, type Query} from '@tanstack/react-query';
import {getNotifications, enqueueNotificationAction} from './notifications.service';
import {notificationsKeys} from './notificationsKeys';
import type {Notification} from './notifications.types';

// FR-006: background poll cadence for the unread indicator — newly delivered
// notifications flip `hasUnread` within ~1 minute. Self-limiting: the interval is a
// function of the cached data and returns `false` once there's anything unread (the
// bell already conveys it), resuming after the set is marked read / a manual
// refresh / reload.
const POLL_INTERVAL_MS = 60_000;

// FR-004: after a successful enqueue, refetch a few times to pick up the writer's
// eventual write (it applies the SQS action asynchronously). Staggered to cover the
// writer's cold-start latency (a cold invocation fetches the Cognito JWKS and can run
// several seconds); the pending-read overlay holds the optimistic state until one of
// these refetches confirms it, so a reconcile that races ahead of the writer can't
// revert the UI back to unread.
const RECONCILE_DELAYS_MS = [2_500, 9_000, 18_000];

export type UseNotificationsOptions = {
  // FR-004: surfaced on enqueue failure (after the optimistic change is rolled
  // back) so the SPEC-060 UI can show a toast. Optional — fire-and-forget callers
  // can ignore it.
  onMutationError?: (message: string) => void;
  // Suspend the 60s background poll for this hook instance. The /notifications page
  // passes this so viewing the list doesn't re-pull the inbox and fight the user's
  // in-page mark-read actions (the writer is the async source of truth and may lag).
  // Reconcile refetches after an action still run regardless.
  pausePoll?: boolean;
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

// SPEC-059: the single hook the SPEC-060 UI consumes for the notifications list and
// the unread indicator. Reads via TanStack Query (keyed per user); mutations enqueue
// onto the SPEC-058 queue and update the cache optimistically (the browser never
// writes the inbox), reconciling on a delayed refetch. Disabled when signed out.
export function useNotifications(
  username: string | null,
  options: UseNotificationsOptions = {}
): UseNotificationsResult {
  const queryClient = useQueryClient();
  const key = notificationsKeys.list(username ?? '__none__');
  const onMutationError = options.onMutationError;
  const pausePoll = options.pausePoll === true;

  const query = useQuery({
    queryKey: key,
    enabled: username !== null,
    queryFn: async (): Promise<Notification[]> => {
      const result = await getNotifications(username as string);
      if (!result.success) throw new Error(result.error.message);
      return result.data;
    },
    // FR-006: poll while there's nothing unread; suspend once unread is showing
    // (returning false stops the interval), and resume when the set is marked read.
    // `pausePoll` (the /notifications page) suspends it outright.
    refetchInterval: (q: Query<Notification[]>) =>
      pausePoll || countUnread(q.state.data) > 0 ? false : POLL_INTERVAL_MS,
    // FR-006: returning to the tab re-checks once regardless of poll state. The
    // interval itself is paused while the tab is hidden (refetchIntervalInBackground
    // defaults to false), so a backgrounded tab does not poll.
    refetchOnWindowFocus: true
  });

  // FR-004: the browser never writes the inbox — the writer applies mark-read/all
  // asynchronously and can lag (cold start). Rather than mutate the read cache (which
  // a refetch racing ahead of the writer would then revert), we hold the optimistic
  // reads as an OVERLAY on top of server truth and clear each one only once the server
  // confirms it. This is what makes a mark-read stick instead of snapping back.
  const [pendingRead, setPendingRead] = useState<Set<string>>(() => new Set());
  const [pendingAll, setPendingAll] = useState(false);

  // Track scheduled reconcile timers so they're cleared on unmount (no stray
  // invalidate / test-timer leak).
  const reconcileTimers = useRef<ReturnType<typeof setTimeout>[]>([]);
  useEffect(() => {
    const timers = reconcileTimers.current;
    return () => timers.forEach(clearTimeout);
  }, []);

  const scheduleReconcile = () => {
    for (const delay of RECONCILE_DELAYS_MS) {
      const handle = setTimeout(() => {
        void queryClient.invalidateQueries({queryKey: key});
      }, delay);
      reconcileTimers.current.push(handle);
    }
  };

  // Clear overlay entries the writer has now confirmed (server reports read, or the
  // row aged out of the capped inbox) so the overlay self-heals and never grows
  // unbounded. Done during render — React's "adjust state when a value changes"
  // pattern (guarded so it only sets on an actual change, and thus converges) —
  // rather than in an effect, which would trigger a cascading re-render.
  if (query.data) {
    if (pendingRead.size > 0) {
      const stillPending = [...pendingRead].filter((id) => {
        const row = query.data.find((n) => n.id === id);
        return row !== undefined && !row.read;
      });
      if (stillPending.length !== pendingRead.size) setPendingRead(new Set(stillPending));
    }
    if (pendingAll && query.data.every((n) => n.read)) setPendingAll(false);
  }

  const markReadMutation = useMutation<void, Error, string>({
    mutationFn: async (id: string): Promise<void> => {
      const result = await enqueueNotificationAction({action: 'markRead', username: username as string, id});
      if (!result.success) throw new Error(result.error.message);
    },
    onMutate: (id: string) =>
      setPendingRead((p) => {
        const next = new Set(p);
        next.add(id);
        return next;
      }),
    onError: (err, id) => {
      setPendingRead((p) => {
        const next = new Set(p);
        next.delete(id);
        return next;
      });
      onMutationError?.(err instanceof Error ? err.message : 'Failed to update notifications');
    },
    onSuccess: scheduleReconcile
  });

  const markAllReadMutation = useMutation<void, Error, void>({
    mutationFn: async (): Promise<void> => {
      const result = await enqueueNotificationAction({action: 'markAllRead', username: username as string});
      if (!result.success) throw new Error(result.error.message);
    },
    onMutate: () => setPendingAll(true),
    onError: (err) => {
      setPendingAll(false);
      onMutationError?.(err instanceof Error ? err.message : 'Failed to update notifications');
    },
    onSuccess: scheduleReconcile
  });

  // Server truth with the optimistic read overlay applied (FR-004).
  const notifications = useMemo<Notification[]>(() => {
    const list = query.data ?? [];
    if (!pendingAll && pendingRead.size === 0) return list;
    return list.map((n) => (!n.read && (pendingAll || pendingRead.has(n.id)) ? {...n, read: true} : n));
  }, [query.data, pendingAll, pendingRead]);

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

// FR-005: prefetch the notifications read once on authenticated app load so the
// header indicator is accurate before the user interacts and the first
// notifications-page render has data. Graceful: prefetchQuery swallows the fetch
// error, so a failed prefetch never crashes or blocks the shell. No-op when signed
// out.
export async function prefetchNotifications(queryClient: QueryClient, username: string | null): Promise<void> {
  if (!username) return;
  await queryClient.prefetchQuery({
    queryKey: notificationsKeys.list(username),
    queryFn: async (): Promise<Notification[]> => {
      const result = await getNotifications(username);
      if (!result.success) throw new Error(result.error.message);
      return result.data;
    }
  });
}
