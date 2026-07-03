import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {renderHook, waitFor, act} from '@testing-library/react';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import type {ReactNode} from 'react';

vi.mock('./notifications.service', () => ({
  getNotifications: vi.fn(),
  enqueueNotificationAction: vi.fn()
}));

import {getNotifications, enqueueNotificationAction} from './notifications.service';
import {useNotifications, prefetchNotifications} from './useNotifications';
import {notificationsKeys} from './notificationsKeys';
import type {Notification} from './notifications.types';

const mockGet = vi.mocked(getNotifications);
const mockEnqueue = vi.mocked(enqueueNotificationAction);

const note = (id: string, read = false): Notification => ({
  id,
  message: `m-${id}`,
  read,
  timestamp: `2026-06-${id.padStart(2, '0')}T00:00:00.000Z`
});

function wrapper(client: QueryClient) {
  return ({children}: {children: ReactNode}) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function newClient() {
  return new QueryClient({defaultOptions: {queries: {retry: false}}});
}

beforeEach(() => {
  vi.clearAllMocks();
  mockEnqueue.mockResolvedValue({success: true, data: undefined});
});

describe('useNotifications — read + derived state', () => {
  it('is disabled and not loading when signed out', () => {
    const {result} = renderHook(() => useNotifications(null), {wrapper: wrapper(newClient())});
    expect(result.current.isLoading).toBe(false);
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('derives unreadCount / hasUnread from the list', async () => {
    mockGet.mockResolvedValue({success: true, data: [note('05'), note('04', true), note('03')]});
    const {result} = renderHook(() => useNotifications('alice'), {wrapper: wrapper(newClient())});
    await waitFor(() => expect(result.current.notifications).toHaveLength(3));
    expect(result.current.unreadCount).toBe(2);
    expect(result.current.hasUnread).toBe(true);
  });

  it('surfaces a read error via isError', async () => {
    mockGet.mockResolvedValue({success: false, error: {message: 'boom'}});
    const {result} = renderHook(() => useNotifications('alice'), {wrapper: wrapper(newClient())});
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe('useNotifications — optimistic mutations', () => {
  it('markRead optimistically flips read and enqueues', async () => {
    mockGet.mockResolvedValue({success: true, data: [note('05'), note('04')]});
    const {result} = renderHook(() => useNotifications('alice'), {wrapper: wrapper(newClient())});
    await waitFor(() => expect(result.current.unreadCount).toBe(2));

    act(() => result.current.markRead('05'));

    await waitFor(() => expect(result.current.unreadCount).toBe(1));
    expect(mockEnqueue).toHaveBeenCalledWith({action: 'markRead', username: 'alice', id: '05'});
    expect(result.current.notifications.find((n) => n.id === '05')?.read).toBe(true);
  });

  it('markAllRead optimistically clears unread', async () => {
    mockGet.mockResolvedValue({success: true, data: [note('05'), note('04')]});
    const {result} = renderHook(() => useNotifications('alice'), {wrapper: wrapper(newClient())});
    await waitFor(() => expect(result.current.unreadCount).toBe(2));

    act(() => result.current.markAllRead());

    await waitFor(() => expect(result.current.unreadCount).toBe(0));
    expect(mockEnqueue).toHaveBeenCalledWith({action: 'markAllRead', username: 'alice'});
  });

  it('rolls back and reports the error on enqueue failure', async () => {
    mockGet.mockResolvedValue({success: true, data: [note('05')]});
    mockEnqueue.mockResolvedValue({success: false, error: {message: 'queue down'}});
    const onMutationError = vi.fn();
    const {result} = renderHook(() => useNotifications('alice', {onMutationError}), {wrapper: wrapper(newClient())});
    await waitFor(() => expect(result.current.unreadCount).toBe(1));

    act(() => result.current.markRead('05'));

    // optimistic flip, then rollback once the enqueue rejects.
    await waitFor(() => expect(result.current.unreadCount).toBe(1));
    expect(result.current.notifications[0].read).toBe(false);
    expect(onMutationError).toHaveBeenCalledWith('queue down');
  });

  it('composes mark-one-read then mark-all-read', async () => {
    mockGet.mockResolvedValue({success: true, data: [note('05'), note('04'), note('03')]});
    const {result} = renderHook(() => useNotifications('alice'), {wrapper: wrapper(newClient())});
    await waitFor(() => expect(result.current.unreadCount).toBe(3));

    act(() => result.current.markRead('05'));
    act(() => result.current.markAllRead());

    await waitFor(() => expect(result.current.unreadCount).toBe(0));
    expect(result.current.notifications.every((n) => n.read)).toBe(true);
  });

  it('schedules a delayed reconcile refetch after a successful enqueue', async () => {
    vi.useFakeTimers();
    try {
      mockGet.mockResolvedValue({success: true, data: [note('05')]});
      const {result} = renderHook(() => useNotifications('alice'), {wrapper: wrapper(newClient())});
      await vi.waitFor(() => expect(result.current.unreadCount).toBe(1));
      expect(mockGet).toHaveBeenCalledTimes(1);

      act(() => result.current.markRead('05'));
      await vi.waitFor(() => expect(mockEnqueue).toHaveBeenCalledTimes(1));

      // The reconcile invalidate fires ~2.5s after enqueue → a second read.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_500);
      });
      expect(mockGet).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('clears pending reconcile timers on unmount — no stray refetch fires [SPEC-083 FR-008]', async () => {
    vi.useFakeTimers();
    try {
      mockGet.mockResolvedValue({success: true, data: [note('05')]});
      const client = newClient();
      const invalidateSpy = vi.spyOn(client, 'invalidateQueries');
      const {result, unmount} = renderHook(() => useNotifications('alice'), {wrapper: wrapper(client)});
      await vi.waitFor(() => expect(result.current.unreadCount).toBe(1));

      act(() => result.current.markRead('05'));
      // Let the enqueue resolve so onSuccess schedules the reconcile timers.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      const invalidatesBeforeUnmount = invalidateSpy.mock.calls.length;

      unmount();
      // Advance past every reconcile delay (2.5s / 9s / 18s). A cleared timer must not
      // fire its invalidate; without the cleanup this would refetch after unmount.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(20_000);
      });
      expect(invalidateSpy.mock.calls.length).toBe(invalidatesBeforeUnmount);
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps a mark-read applied even when a reconcile refetch still shows it unread', async () => {
    vi.useFakeTimers();
    try {
      // The writer hasn't caught up yet: every server read still returns it unread.
      mockGet.mockResolvedValue({success: true, data: [note('05')]});
      const {result} = renderHook(() => useNotifications('alice'), {wrapper: wrapper(newClient())});
      await vi.waitFor(() => expect(result.current.unreadCount).toBe(1));

      act(() => result.current.markRead('05'));
      await vi.waitFor(() => expect(result.current.unreadCount).toBe(0));

      // A reconcile refetch lands while the server still reports unread — the overlay
      // must hold the optimistic read instead of snapping back to unread.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_500);
      });
      expect(mockGet).toHaveBeenCalledTimes(2);
      expect(result.current.unreadCount).toBe(0);
      expect(result.current.notifications[0].read).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it('clears the overlay once the server confirms the read (self-heal)', async () => {
    vi.useFakeTimers();
    try {
      mockGet.mockResolvedValueOnce({success: true, data: [note('05')]});
      mockGet.mockResolvedValue({success: true, data: [note('05', true)]}); // writer caught up
      const {result} = renderHook(() => useNotifications('alice'), {wrapper: wrapper(newClient())});
      await vi.waitFor(() => expect(result.current.unreadCount).toBe(1));

      act(() => result.current.markRead('05'));
      await vi.waitFor(() => expect(result.current.unreadCount).toBe(0));

      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_500);
      });
      // Server now reports read=true; overlay pruned, row stays read.
      expect(result.current.notifications[0].read).toBe(true);
      expect(result.current.unreadCount).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('useNotifications — background poll (FR-006)', () => {
  it('polls on the 60s interval while there is no unread', async () => {
    vi.useFakeTimers();
    try {
      mockGet.mockResolvedValue({success: true, data: [note('05', true)]});
      const {result} = renderHook(() => useNotifications('alice'), {wrapper: wrapper(newClient())});
      await vi.waitFor(() => expect(result.current.notifications).toHaveLength(1));
      expect(mockGet).toHaveBeenCalledTimes(1);
      expect(result.current.hasUnread).toBe(false);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });
      expect(mockGet).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps polling while unread so a later notification bumps the count', async () => {
    vi.useFakeTimers();
    try {
      // First read delivers one unread item; a later read adds a second unread one.
      mockGet.mockResolvedValueOnce({success: true, data: [note('05')]});
      mockGet.mockResolvedValue({success: true, data: [note('06'), note('05')]});
      const {result} = renderHook(() => useNotifications('alice'), {wrapper: wrapper(newClient())});
      await vi.waitFor(() => expect(result.current.unreadCount).toBe(1));
      const callsAfterFirst = mockGet.mock.calls.length;

      // The poll does NOT suspend on unread — a later poll picks up the 2nd item and
      // the count climbs (a presence-only dot would have hidden it).
      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });
      expect(mockGet.mock.calls.length).toBeGreaterThan(callsAfterFirst);
      await vi.waitFor(() => expect(result.current.unreadCount).toBe(2));
    } finally {
      vi.useRealTimers();
    }
  });

  it('pausePoll suspends the 60s poll (the /notifications page)', async () => {
    vi.useFakeTimers();
    try {
      // All read → the interval would normally poll; pausePoll must stop it.
      mockGet.mockResolvedValue({success: true, data: [note('05', true)]});
      const {result} = renderHook(() => useNotifications('alice', {pausePoll: true}), {
        wrapper: wrapper(newClient())
      });
      await vi.waitFor(() => expect(result.current.notifications).toHaveLength(1));
      expect(mockGet).toHaveBeenCalledTimes(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(180_000);
      });
      expect(mockGet).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('prefetchNotifications (FR-005)', () => {
  it('seeds the cache for the user', async () => {
    mockGet.mockResolvedValue({success: true, data: [note('05')]});
    const client = newClient();
    await prefetchNotifications(client, 'alice');
    expect(client.getQueryData(notificationsKeys.list('alice'))).toHaveLength(1);
  });

  it('is a no-op when signed out', async () => {
    await prefetchNotifications(newClient(), null);
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('degrades gracefully on read failure (no throw)', async () => {
    mockGet.mockResolvedValue({success: false, error: {message: 'nope'}});
    await expect(prefetchNotifications(newClient(), 'alice')).resolves.toBeUndefined();
  });
});

afterEach(() => {
  vi.useRealTimers();
});
