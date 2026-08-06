import {waitFor, act} from '@testing-library/react';
import {renderHookWithProviders} from '../../test/renderWithProviders';
import {describe, it, expect, vi, beforeEach} from 'vitest';
import {useQueryResults} from './useQueryResults';
import {getQueryResults} from './query.service';
import type {QueryResultPage} from './query.types';

vi.mock('./query.service');

const mockGetQueryResults = vi.mocked(getQueryResults);

const cols = [{name: 'v', type: 'integer'}];
function ok(rows: string[][], nextToken?: string) {
  return {
    success: true as const,
    data: {columns: cols, rows, nextToken} satisfies QueryResultPage
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  // Two pages: page 1 (rows 1–2, more available) → page 2 (row 3, last).
  mockGetQueryResults.mockImplementation(async ({nextToken}) => {
    if (!nextToken) return ok([['1'], ['2']], 'T2');
    if (nextToken === 'T2') return ok([['3']]);
    throw new Error(`unexpected token ${nextToken}`);
  });
});

// pageSize = 2 in these tests so the range math is easy to assert.
describe('useQueryResults', () => {
  it('loads the first page and reports that more is available', async () => {
    const {result} = renderHookWithProviders(() => useQueryResults('q-1', 2));

    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(result.current.rows).toEqual([['1'], ['2']]);
    expect(result.current.pageIndex).toBe(0);
    expect(result.current.hasPrev).toBe(false);
    expect(result.current.hasNext).toBe(true);
    expect(result.current.rangeStart).toBe(1);
    expect(result.current.rangeEnd).toBe(2);
    expect(result.current.totalRowCount).toBeNull(); // unknown until last page
  });

  it('Next fetches the next page forward and replaces the visible rows', async () => {
    const {result} = renderHookWithProviders(() => useQueryResults('q-1', 2));
    await waitFor(() => expect(result.current.isPending).toBe(false));

    await act(async () => {
      result.current.goNext();
    });
    await waitFor(() => expect(result.current.pageIndex).toBe(1));

    expect(result.current.rows).toEqual([['3']]); // replaced, not appended
    expect(result.current.hasPrev).toBe(true);
    expect(result.current.hasNext).toBe(false); // last page
    expect(result.current.rangeStart).toBe(3);
    expect(result.current.totalRowCount).toBe(3); // 2 + 1, now that all loaded
    expect(mockGetQueryResults).toHaveBeenCalledTimes(2);
  });

  it('Prev returns to the previous page from cache, with no refetch', async () => {
    const {result} = renderHookWithProviders(() => useQueryResults('q-1', 2));
    await waitFor(() => expect(result.current.isPending).toBe(false));
    await act(async () => {
      result.current.goNext();
    });
    await waitFor(() => expect(result.current.pageIndex).toBe(1));

    const callsAfterNext = mockGetQueryResults.mock.calls.length;
    act(() => {
      result.current.goPrev();
    });

    await waitFor(() => expect(result.current.pageIndex).toBe(0));
    expect(result.current.rows).toEqual([['1'], ['2']]);
    expect(mockGetQueryResults).toHaveBeenCalledTimes(callsAfterNext);
  });

  it('resets to page 1 when the execution id changes', async () => {
    const {result, rerender} = renderHookWithProviders(({id}) => useQueryResults(id, 2), {
      initialProps: {id: 'q-1' as string | null}
    });
    await waitFor(() => expect(result.current.isPending).toBe(false));
    await act(async () => {
      result.current.goNext();
    });
    await waitFor(() => expect(result.current.pageIndex).toBe(1));

    rerender({id: 'q-2'});

    await waitFor(() => expect(result.current.pageIndex).toBe(0));
  });

  it('re-pages to page 1 and refetches at the new size when the page size changes (SPEC-087)', async () => {
    const {result, rerender} = renderHookWithProviders(({size}) => useQueryResults('q-1', size), {
      initialProps: {size: 2}
    });
    await waitFor(() => expect(result.current.isPending).toBe(false));
    await act(async () => {
      result.current.goNext();
    });
    await waitFor(() => expect(result.current.pageIndex).toBe(1));

    rerender({size: 3});

    // Back on page 1, fetched fresh at the new size (the old-size pages are
    // keyed separately and never mixed in).
    await waitFor(() => expect(result.current.pageIndex).toBe(0));
    await waitFor(() =>
      expect(mockGetQueryResults).toHaveBeenLastCalledWith(expect.objectContaining({maxRows: 3, nextToken: undefined}))
    );
  });

  it('numbers rows from the actual loaded page lengths, not an assumed uniform size', async () => {
    // A short first page (like the 1000-cap case, where page 1 nets one fewer
    // row): rows must continue 1 → 2,3 — not skip to pageIndex*pageSize+1.
    mockGetQueryResults.mockImplementation(async ({nextToken}) => {
      if (!nextToken) return ok([['1']], 'T2');
      if (nextToken === 'T2') return ok([['2'], ['3']]);
      throw new Error(`unexpected token ${nextToken}`);
    });
    const {result} = renderHookWithProviders(() => useQueryResults('q-1', 2));
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(result.current.rangeStart).toBe(1);
    expect(result.current.rangeEnd).toBe(1);

    await act(async () => {
      result.current.goNext();
    });
    await waitFor(() => expect(result.current.pageIndex).toBe(1));
    expect(result.current.rangeStart).toBe(2);
    expect(result.current.rangeEnd).toBe(3);
  });

  it('remembers each execution’s page when switching back (SPEC-078 result tabs)', async () => {
    const {result, rerender} = renderHookWithProviders(({id}) => useQueryResults(id, 2), {
      initialProps: {id: 'q-1' as string | null}
    });
    await waitFor(() => expect(result.current.isPending).toBe(false));
    await act(async () => {
      result.current.goNext();
    });
    await waitFor(() => expect(result.current.pageIndex).toBe(1));

    // Another result tab starts on ITS page 1…
    rerender({id: 'q-2'});
    await waitFor(() => expect(result.current.pageIndex).toBe(0));

    // …and switching back restores q-1's page position.
    rerender({id: 'q-1'});
    await waitFor(() => expect(result.current.pageIndex).toBe(1));
  });
});
