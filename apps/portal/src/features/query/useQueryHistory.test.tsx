import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

vi.mock('./queryHistory.service', () => ({
  getQueryHistory: vi.fn(),
  appendQueryHistory: vi.fn(),
  updateQueryHistoryEntry: vi.fn(),
}));

import { getQueryHistory } from './queryHistory.service';
import { useQueryHistory } from './useQueryHistory';
import { queryKeys } from './queryKeys';
import type { QueryHistory } from './query.types';

const mockGet = vi.mocked(getQueryHistory);

function store(n: number): QueryHistory {
  return {
    version: 1,
    entries: Array.from({ length: n }, (_, i) => ({
      queryExecutionId: `q${i}`,
      sql: `SELECT ${i}`,
      database: 'alice',
      submittedAt: new Date(2026, 0, 1, 0, i).toISOString(),
      status: 'SUCCEEDED' as const,
    })),
  };
}

function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('useQueryHistory (SPEC-046 refresh)', () => {
  it('refresh re-reads the store from S3 (refetch of the history key)', async () => {
    mockGet.mockResolvedValueOnce({ success: true, data: store(1) });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(() => useQueryHistory('alice'), {
      wrapper: wrapper(client),
    });

    await waitFor(() => expect(result.current.history).toHaveLength(1));
    expect(mockGet).toHaveBeenCalledTimes(1);

    // A second tab wrote a new entry; Refresh pulls it in.
    mockGet.mockResolvedValueOnce({ success: true, data: store(2) });
    await act(async () => {
      await result.current.refresh();
    });

    expect(mockGet).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(result.current.history).toHaveLength(2));
  });

  it('refresh targets exactly queryKeys.history(username)', async () => {
    mockGet.mockResolvedValue({ success: true, data: store(1) });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const spy = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useQueryHistory('alice'), {
      wrapper: wrapper(client),
    });
    await waitFor(() => expect(result.current.history).toHaveLength(1));

    await act(async () => {
      await result.current.refresh();
    });
    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.history('alice') });
  });

  it('a failed refresh keeps the previously-loaded entries (non-destructive)', async () => {
    mockGet.mockResolvedValueOnce({ success: true, data: store(2) });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(() => useQueryHistory('alice'), {
      wrapper: wrapper(client),
    });
    await waitFor(() => expect(result.current.history).toHaveLength(2));

    mockGet.mockResolvedValueOnce({
      success: false,
      error: { message: 'access denied' },
    });
    await act(async () => {
      await result.current.refresh();
    });

    await waitFor(() => expect(result.current.error).toBe('access denied'));
    // The list is retained despite the failed refetch.
    expect(result.current.history).toHaveLength(2);
  });
});
