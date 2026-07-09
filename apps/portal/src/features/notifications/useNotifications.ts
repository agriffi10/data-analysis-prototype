import {useEffect, useMemo, useRef, useState} from 'react';
import {useMutation, useQuery, useQueryClient, type QueryClient} from '@tanstack/react-query';
import {getNotifications, enqueueNotificationAction} from './notifications.service';
import {notificationsKeys} from './notificationsKeys';
import type {Notification} from './notifications.types';

// Background poll cadence for the unread indicator. Runs continuously (not just
// until something is unread) so the bell count stays live as further notifications
// arrive; paused only via `pausePoll`.
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
  /**
   * Suspend the 60s background poll (the /notifications page sets this so a poll
   * doesn't fight in-page mark-read actions — the writer is the async source of
   * truth and may lag). Post-action reconcile refetches still run.
   */
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

/**
 * Notifications list + unread indicator for one user.
 *
 * Reads via TanStack Query (keyed per user, 60s poll). Mutations only enqueue onto
 * the notifications queue — the browser never writes the inbox — so mark-read state
 * is held as an optimistic overlay on top of server truth and cleared per-entry once
 * a delayed reconcile refetch confirms the writer applied it. Disabled when signed out.
 */
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
    refetchInterval: () => (pausePoll ? false : POLL_INTERVAL_MS),
    // Returning to the tab re-checks once regardless of poll state; the interval
    // itself is paused while the tab is hidden (refetchIntervalInBackground is false).
    refetchOnWindowFocus: true
  });

  // The writer applies mark-read/all asynchronously and can lag. Rather than mutate
  // the read cache (which a refetch racing ahead of the writer would revert), hold
  // optimistic reads as an overlay on server truth and clear each only once the
  // server confirms it — that's what makes a mark-read stick instead of snapping back.
  const [pendingRead, setPendingRead] = useState<Set<string>>(() => new Set());
  const [pendingAll, setPendingAll] = useState(false);

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

  // Clear overlay entries the writer has confirmed (server reports read, or the row
  // aged out of the capped inbox) so the overlay never grows unbounded. Done during
  // render — the "adjust state when a value changes" pattern, guarded to only set on
  // an actual change — rather than in an effect, which would cascade a re-render.
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
      if (!result.success) throw Object.assign(new Error(result.error.message), {code: result.error.code});
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
      onMutationError?.(err);
    },
    onSuccess: scheduleReconcile
  });

  const markAllReadMutation = useMutation<void, Error, void>({
    mutationFn: async (): Promise<void> => {
      const result = await enqueueNotificationAction({action: 'markAllRead', username: username as string});
      if (!result.success) throw Object.assign(new Error(result.error.message), {code: result.error.code});
    },
    onMutate: () => setPendingAll(true),
    onError: (err) => {
      setPendingAll(false);
      onMutationError?.(err);
    },
    onSuccess: scheduleReconcile
  });

  // Server truth with the optimistic read overlay applied.
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
      if (!result.success) throw new Error(result.error.message);
      return result.data;
    }
  });
}
