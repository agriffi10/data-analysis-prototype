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

  it('suspends polling once unread is showing', async () => {
    vi.useFakeTimers();
    try {
      // First read = all read (poll active); next read delivers an unread item.
      mockGet.mockResolvedValueOnce({success: true, data: [note('05', true)]});
      mockGet.mockResolvedValue({success: true, data: [note('06'), note('05', true)]});
      const {result} = renderHook(() => useNotifications('alice'), {wrapper: wrapper(newClient())});
      await vi.waitFor(() => expect(result.current.hasUnread).toBe(false));

      // One poll delivers the unread item...
      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });
      await vi.waitFor(() => expect(result.current.hasUnread).toBe(true));
      const callsAfterUnread = mockGet.mock.calls.length;

      // ...and the interval then stops — further time does not trigger more reads.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(180_000);
      });
      expect(mockGet).toHaveBeenCalledTimes(callsAfterUnread);
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
