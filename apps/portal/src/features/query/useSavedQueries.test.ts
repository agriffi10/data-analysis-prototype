import { renderHook, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { createElement, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useSavedQueries } from './useSavedQueries';
import { getSavedQueries, upsertSavedQuery, removeSavedQuery } from './savedQueries.service';
import type { SavedQueriesStore, SavedQuery } from './query.types';

vi.mock('./savedQueries.service');

const mockGet = vi.mocked(getSavedQueries);
const mockUpsert = vi.mocked(upsertSavedQuery);
const mockRemove = vi.mocked(removeSavedQuery);

function wrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
}

function sq(id: string, name = id): SavedQuery {
  return {
    id,
    name,
    sql: 'SELECT 1',
    database: 'alice',
    createdAt: '2026-06-18T10:00:00.000Z',
    updatedAt: '2026-06-18T10:00:00.000Z',
  };
}

function store(queries: SavedQuery[]): SavedQueriesStore {
  return { version: 1, queries };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockGet.mockResolvedValue({ success: true, data: store([sq('a')]) });
});

describe('useSavedQueries', () => {
  it('is disabled (loading, empty) while username is null', () => {
    const { result } = renderHook(() => useSavedQueries(null), {
      wrapper: wrapper(),
    });
    expect(result.current.queries).toEqual([]);
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('loads the user’s saved queries', async () => {
    const { result } = renderHook(() => useSavedQueries('alice'), {
      wrapper: wrapper(),
    });
    await waitFor(() => expect(result.current.queries.map((q) => q.id)).toEqual(['a']));
  });

  it('upsert seeds the cache so the list reflects the change', async () => {
    mockUpsert.mockResolvedValue({
      success: true,
      data: store([sq('b'), sq('a')]),
    });
    const { result } = renderHook(() => useSavedQueries('alice'), {
      wrapper: wrapper(),
    });
    await waitFor(() => expect(result.current.queries).toHaveLength(1));

    await act(async () => {
      await result.current.upsert(sq('b'));
    });
    await waitFor(() => expect(result.current.queries.map((q) => q.id)).toEqual(['b', 'a']));
  });

  it('remove seeds the cache so the entry disappears', async () => {
    mockRemove.mockResolvedValue({ success: true, data: store([]) });
    const { result } = renderHook(() => useSavedQueries('alice'), {
      wrapper: wrapper(),
    });
    await waitFor(() => expect(result.current.queries).toHaveLength(1));

    await act(async () => {
      await result.current.remove('a');
    });
    await waitFor(() => expect(result.current.queries).toEqual([]));
    expect(mockRemove).toHaveBeenCalledWith('alice', 'a');
  });

  it('surfaces a load error', async () => {
    mockGet.mockResolvedValue({
      success: false,
      error: { message: 'access denied' },
    });
    const { result } = renderHook(() => useSavedQueries('alice'), {
      wrapper: wrapper(),
    });
    await waitFor(() => expect(result.current.error).toBe('access denied'));
  });
});
