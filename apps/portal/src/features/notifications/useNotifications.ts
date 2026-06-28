import {useEffect, useMemo, useRef} from 'react';
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

// FR-004: after a successful enqueue, reconcile the optimistic cache against the
// writer's eventual result by invalidating shortly after (the writer applies the
// SQS message asynchronously). Tunable.
const RECONCILE_DELAY_MS = 2_500;

export type UseNotificationsOptions = {
  // FR-004: surfaced on enqueue failure (after the optimistic change is rolled
  // back) so the SPEC-060 UI can show a toast. Optional — fire-and-forget callers
  // can ignore it.
  onMutationError?: (message: string) => void;
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
    refetchInterval: (q: Query<Notification[]>) => (countUnread(q.state.data) > 0 ? false : POLL_INTERVAL_MS),
    // FR-006: returning to the tab re-checks once regardless of poll state. The
    // interval itself is paused while the tab is hidden (refetchIntervalInBackground
    // defaults to false), so a backgrounded tab does not poll.
    refetchOnWindowFocus: true
  });

  // Track scheduled reconcile timers so they're cleared on unmount (no stray
  // invalidate / test-timer leak).
  const reconcileTimers = useRef<ReturnType<typeof setTimeout>[]>([]);
  useEffect(() => {
    const timers = reconcileTimers.current;
    return () => timers.forEach(clearTimeout);
  }, []);

  const scheduleReconcile = () => {
    const handle = setTimeout(() => {
      void queryClient.invalidateQueries({queryKey: key});
    }, RECONCILE_DELAY_MS);
    reconcileTimers.current.push(handle);
  };

  // Shared optimistic plumbing for both mutations: cancel in-flight reads, snapshot
  // for rollback, apply the transform. Functional setQueryData means concurrent
  // mutations (mark-one then mark-all) compose without losing read state (FR-004).
  const optimistic = (apply: (list: Notification[]) => Notification[]) => async () => {
    await queryClient.cancelQueries({queryKey: key});
    const previous = queryClient.getQueryData<Notification[]>(key);
    queryClient.setQueryData<Notification[]>(key, (old) => apply(old ?? []));
    return {previous};
  };

  const rollback = (_err: unknown, _vars: unknown, ctx: {previous?: Notification[]} | undefined) => {
    if (ctx?.previous !== undefined) queryClient.setQueryData(key, ctx.previous);
    onMutationError?.(_err instanceof Error ? _err.message : 'Failed to update notifications');
  };

  const markReadMutation = useMutation({
    mutationFn: async (id: string): Promise<void> => {
      const result = await enqueueNotificationAction({action: 'markRead', username: username as string, id});
      if (!result.success) throw new Error(result.error.message);
    },
    onMutate: (id: string) => optimistic((list) => list.map((n) => (n.id === id ? {...n, read: true} : n)))(),
    onError: rollback,
    onSuccess: scheduleReconcile
  });

  const markAllReadMutation = useMutation<void, Error, void, {previous?: Notification[]}>({
    mutationFn: async (): Promise<void> => {
      const result = await enqueueNotificationAction({action: 'markAllRead', username: username as string});
      if (!result.success) throw new Error(result.error.message);
    },
    onMutate: optimistic((list) => list.map((n) => (n.read ? n : {...n, read: true}))),
    onError: rollback,
    onSuccess: scheduleReconcile
  });

  const notifications = query.data ?? [];
  const unreadCount = useMemo(() => countUnread(query.data), [query.data]);

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
