import {waitFor, act} from '@testing-library/react';
import {renderHookWithProviders, createTestQueryClient} from '../../test/renderWithProviders';
import {describe, it, expect, vi, beforeEach} from 'vitest';
import {useSavedQueries} from './useSavedQueries';
import {queryKeys} from './queryKeys';
import {deleteSavedQuery, listSavedQueries} from './savedQueries.service';
import type {QuerySpace, SavedQuery} from './query.types';

vi.mock('./savedQueries.service');

const mockList = vi.mocked(listSavedQueries);
const mockDelete = vi.mocked(deleteSavedQuery);

const PERSONAL: QuerySpace = {
  id: 'personal',
  label: 'My files',
  bucket: 'user-space',
  rootPrefix: 'alice/',
  rootLabel: 'My Files'
};

function sq(name: string, space: QuerySpace = PERSONAL): SavedQuery {
  return {
    spaceId: space.id,
    bucket: space.bucket,
    key: `${space.rootPrefix}saved_queries/${name}.sql`,
    name,
    updatedAt: '2026-08-11T10:00:00.000Z',
    size: 12
  };
}

const page = (queries: SavedQuery[], next?: string) => ({
  success: true as const,
  data: {queries, isTruncated: next !== undefined, nextContinuationToken: next}
});

beforeEach(() => {
  vi.clearAllMocks();
  mockList.mockResolvedValue(page([sq('a')]));
  mockDelete.mockResolvedValue({success: true, data: undefined});
});

describe('useSavedQueries', () => {
  it('is disabled (loading, empty) while the space is null', () => {
    const {result} = renderHookWithProviders(() => useSavedQueries(null));
    expect(result.current.queries).toEqual([]);
    expect(mockList).not.toHaveBeenCalled();
  });

  it('lists the space’s saved queries', async () => {
    const {result} = renderHookWithProviders(() => useSavedQueries(PERSONAL));
    await waitFor(() => expect(result.current.queries.map((q) => q.name)).toEqual(['a']));
    expect(mockList).toHaveBeenCalledWith(expect.objectContaining({space: PERSONAL}));
  });

  it('keys on the SPACE, so two spaces are two lists', async () => {
    const shared: QuerySpace = {
      id: 'project_alpha',
      label: 'project_alpha',
      bucket: 'shared-space',
      rootPrefix: 'project_alpha/',
      rootLabel: 'project_alpha'
    };
    const client = createTestQueryClient();
    mockList.mockResolvedValueOnce(page([sq('mine')])).mockResolvedValueOnce(page([sq('theirs', shared)]));

    const personal = renderHookWithProviders(() => useSavedQueries(PERSONAL), {queryClient: client});
    await waitFor(() => expect(personal.result.current.queries).toHaveLength(1));
    const other = renderHookWithProviders(() => useSavedQueries(shared), {queryClient: client});
    await waitFor(() => expect(other.result.current.queries.map((q) => q.name)).toEqual(['theirs']));

    expect(client.getQueryData(queryKeys.savedQueries('personal'))).toBeDefined();
    expect(client.getQueryData(queryKeys.savedQueries('project_alpha'))).toBeDefined();
  });

  it('accumulates pages on loadMore and reports hasMore from the listing', async () => {
    mockList.mockResolvedValueOnce(page([sq('a')], 'page-2')).mockResolvedValueOnce(page([sq('b')]));

    const {result} = renderHookWithProviders(() => useSavedQueries(PERSONAL));
    await waitFor(() => expect(result.current.hasMore).toBe(true));

    act(() => result.current.loadMore());

    await waitFor(() => expect(result.current.queries.map((q) => q.name)).toEqual(['a', 'b']));
    expect(result.current.hasMore).toBe(false);
    expect(mockList).toHaveBeenLastCalledWith(expect.objectContaining({continuationToken: 'page-2'}));
  });

  it('remove deletes the object and refreshes the list', async () => {
    const client = createTestQueryClient();
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    const {result} = renderHookWithProviders(() => useSavedQueries(PERSONAL), {queryClient: client});
    await waitFor(() => expect(result.current.queries).toHaveLength(1));

    mockList.mockResolvedValue(page([]));
    await act(async () => {
      await result.current.remove(sq('a'));
    });

    expect(mockDelete).toHaveBeenCalledWith({
      bucket: 'user-space',
      key: 'alice/saved_queries/a.sql',
      username: 'alice'
    });
    expect(invalidate).toHaveBeenCalledWith({queryKey: queryKeys.savedQueries('personal')});
    await waitFor(() => expect(result.current.queries).toEqual([]));
  });

  it('takes the marker-guard owner from the KEY, so a shared space is guarded by its own root', async () => {
    const shared: QuerySpace = {
      id: 'project_alpha',
      label: 'project_alpha',
      bucket: 'shared-space',
      rootPrefix: 'project_alpha/',
      rootLabel: 'project_alpha'
    };
    const {result} = renderHookWithProviders(() => useSavedQueries(shared));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.remove(sq('a', shared));
    });

    expect(mockDelete).toHaveBeenCalledWith(expect.objectContaining({username: 'project_alpha'}));
  });

  it('surfaces a load error', async () => {
    mockList.mockResolvedValue({success: false, error: {message: 'access denied'}});
    const {result} = renderHookWithProviders(() => useSavedQueries(PERSONAL));
    await waitFor(() => expect(result.current.error).toEqual(expect.objectContaining({message: 'access denied'})));
  });
});
