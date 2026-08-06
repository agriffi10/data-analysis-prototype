import {waitFor, act} from '@testing-library/react';
import {renderHookWithProviders, createTestQueryClient} from '../../test/renderWithProviders';
import {describe, it, expect, vi, beforeEach} from 'vitest';
import {useSavedQueries} from './useSavedQueries';
import {queryKeys} from './queryKeys';
import {getSavedQueries, upsertSavedQuery, removeSavedQuery} from './savedQueries.service';
import type {SavedQueriesStore, SavedQuery} from './query.types';

vi.mock('./savedQueries.service');

const mockGet = vi.mocked(getSavedQueries);
const mockUpsert = vi.mocked(upsertSavedQuery);
const mockRemove = vi.mocked(removeSavedQuery);

function sq(id: string, name = id): SavedQuery {
  return {
    id,
    name,
    sql: 'SELECT 1',
    database: 'alice',
    createdAt: '2026-06-18T10:00:00.000Z',
    updatedAt: '2026-06-18T10:00:00.000Z'
  };
}

function store(queries: SavedQuery[]): SavedQueriesStore {
  return {version: 1, queries};
}

beforeEach(() => {
  vi.clearAllMocks();
  mockGet.mockResolvedValue({success: true, data: store([sq('a')])});
});

describe('useSavedQueries', () => {
  it('is disabled (loading, empty) while username is null', () => {
    const {result} = renderHookWithProviders(() => useSavedQueries(null));
    expect(result.current.queries).toEqual([]);
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('loads the user’s saved queries', async () => {
    const {result} = renderHookWithProviders(() => useSavedQueries('alice'));
    await waitFor(() => expect(result.current.queries.map((q) => q.id)).toEqual(['a']));
  });

  it('upsert seeds the cache with the returned store AND invalidates it', async () => {
    // SPEC-155 FR-001 made a write do both, and both halves matter: the seed is what
    // makes the list update without waiting on S3, the invalidate is what stops the
    // cache diverging from it. Asserted on the client — the same seam
    // `useQueryHistory.test.tsx` uses for its refresh — because the two land in one
    // tick and an assertion on the rendered value alone cannot tell them apart.
    const written = store([sq('b'), sq('a')]);
    mockUpsert.mockResolvedValue({success: true, data: written});
    const client = createTestQueryClient();
    const seed = vi.spyOn(client, 'setQueryData');
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    const {result} = renderHookWithProviders(() => useSavedQueries('alice'), {queryClient: client});
    await waitFor(() => expect(result.current.queries).toHaveLength(1));

    mockGet.mockResolvedValue({success: true, data: written});
    await act(async () => {
      await result.current.upsert(sq('b'));
    });

    expect(seed).toHaveBeenCalledWith(queryKeys.savedQueries('alice'), written);
    expect(invalidate).toHaveBeenCalledWith({queryKey: queryKeys.savedQueries('alice')});
    await waitFor(() => expect(result.current.queries.map((q) => q.id)).toEqual(['b', 'a']));
  });

  it('remove seeds the cache so the entry disappears', async () => {
    const written = store([]);
    mockRemove.mockResolvedValue({success: true, data: written});
    const client = createTestQueryClient();
    const seed = vi.spyOn(client, 'setQueryData');
    const {result} = renderHookWithProviders(() => useSavedQueries('alice'), {queryClient: client});
    await waitFor(() => expect(result.current.queries).toHaveLength(1));

    mockGet.mockResolvedValue({success: true, data: written});
    await act(async () => {
      await result.current.remove('a');
    });

    expect(seed).toHaveBeenCalledWith(queryKeys.savedQueries('alice'), written);
    await waitFor(() => expect(result.current.queries).toEqual([]));
    expect(mockRemove).toHaveBeenCalledWith('alice', 'a');
  });

  it('reconciles against S3 after a write, so another tab’s query is not dropped', async () => {
    // SPEC-155 FR-001 resolved the asymmetry with `useQueryHistory` in favour of
    // invalidating: the seeded store is the WRITER'S view of a read-modify-write, so
    // without the refetch a concurrent write would sit unnoticed until something else
    // refetched. `c` was saved in another tab between this tab's read and its write.
    mockUpsert.mockResolvedValue({success: true, data: store([sq('b'), sq('a')])});
    const {result} = renderHookWithProviders(() => useSavedQueries('alice'));
    await waitFor(() => expect(result.current.queries).toHaveLength(1));

    mockGet.mockResolvedValue({success: true, data: store([sq('b'), sq('a'), sq('c')])});
    await act(async () => {
      await result.current.upsert(sq('b'));
    });

    await waitFor(() => expect(result.current.queries.map((q) => q.id)).toEqual(['b', 'a', 'c']));
  });

  it('surfaces a load error', async () => {
    mockGet.mockResolvedValue({
      success: false,
      error: {message: 'access denied'}
    });
    const {result} = renderHookWithProviders(() => useSavedQueries('alice'));
    await waitFor(() => expect(result.current.error).toEqual(expect.objectContaining({message: 'access denied'})));
  });
});
