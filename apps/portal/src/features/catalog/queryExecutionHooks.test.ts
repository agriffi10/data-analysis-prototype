import {beforeEach, describe, expect, it, vi} from 'vitest';
import {act, waitFor} from '@testing-library/react';
import {renderHookWithProviders} from '../../test/renderWithProviders';
import {getQueryResults, getQueryStatus} from './athena.service';
import {useQueryExecution} from './useQueryExecution';
import {useQueryResults} from './useQueryResults';
import {useResultRowCount} from './useResultRowCount';
import {ROW_COUNT_PAGE_SIZE} from './catalog.constants';
import type {QueryResultPage, QueryStatus} from './catalog.types';

// One boundary for all three hook suites. `isTerminalState` and friends stay real
// (importActual) so the polling/stop logic runs exactly as in production.
vi.mock('./athena.service', async (importActual) => {
  const actual = await importActual<typeof import('./athena.service')>();
  return {...actual, getQueryStatus: vi.fn(), getQueryResults: vi.fn()};
});

// ─── from useQueryExecution.test.ts ───
describe('useQueryExecution', () => {
  // Integration style: exercise the real polling hook over a mocked Athena
  // service boundary. `isTerminalState` stays real (importActual) so the
  // refetch-stop logic runs exactly as in production.
  const mockGetStatus = vi.mocked(getQueryStatus);

  const status = (over: Partial<QueryStatus> = {}): QueryStatus => ({
    queryExecutionId: 'q-1',
    state: 'SUCCEEDED',
    ...over
  });
  const ok = (data: QueryStatus) => ({success: true as const, data});

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('useQueryExecution', () => {
    it('is disabled and does not poll while the id is null', () => {
      const {result} = renderHookWithProviders(() => useQueryExecution(null));
      expect(result.current.fetchStatus).toBe('idle');
      expect(mockGetStatus).not.toHaveBeenCalled();
    });

    it('fetches the execution status for a non-null id and exposes the terminal state', async () => {
      mockGetStatus.mockResolvedValue(ok(status({state: 'SUCCEEDED'})));
      const {result} = renderHookWithProviders(() => useQueryExecution('q-1'));

      await waitFor(() => expect(result.current.data?.state).toBe('SUCCEEDED'));
      expect(mockGetStatus).toHaveBeenCalledWith('q-1');
    });

    it('surfaces a service failure as an error state (queryFn throws)', async () => {
      mockGetStatus.mockResolvedValue({success: false, error: {message: 'boom'}});
      const {result} = renderHookWithProviders(() => useQueryExecution('q-1'));

      await waitFor(() => expect(result.current.isError).toBe(true));
      expect(result.current.error).toEqual(expect.objectContaining({message: 'boom'}));
    });
  });
});

// ─── from useQueryResults.test.ts ───
describe('useQueryResults', () => {
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
  /*
   * SCOPE NOTE (SPEC-154 FR-005 AC6). Two of the cases below — Next fetching forward, and Prev
   * returning from cache — are now ALSO driven through the UI in `QueryWorkspace.test.tsx`,
   * which is where a broken pager button or an unwired token would actually surface. They are
   * kept here rather than deleted because this file asserts the STATE DERIVATION the workspace
   * cannot see: `pageIndex`, `hasPrev`/`hasNext`, the row NUMBERING across pages of unequal
   * length, the reset on a new execution id, and the per-execution page memory. §21 forbids
   * testing the same LOGIC at two levels; the same FLOW at two levels, with each asserting what
   * only it can, is the split the rulebook asks for.
   */
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
        expect(mockGetQueryResults).toHaveBeenLastCalledWith(
          expect.objectContaining({maxRows: 3, nextToken: undefined})
        )
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
      // A second, permanent observer on q-1 keeps its pages in cache while the first hook
      // looks elsewhere. Without it the test client's `gcTime: 0` collects them the moment
      // nobody is watching, and this would be measuring the clamp below instead of the
      // page memory it is named for.
      const {result, rerender} = renderHookWithProviders(
        ({id}) => ({active: useQueryResults(id, 2), warm: useQueryResults('q-1', 2)}),
        {initialProps: {id: 'q-1' as string | null}}
      );
      await waitFor(() => expect(result.current.active.isPending).toBe(false));
      await act(async () => {
        result.current.active.goNext();
      });
      await waitFor(() => expect(result.current.active.pageIndex).toBe(1));

      // Another result tab starts on ITS page 1…
      rerender({id: 'q-2'});
      await waitFor(() => expect(result.current.active.pageIndex).toBe(0));

      // …and switching back restores q-1's page position.
      rerender({id: 'q-1'});
      await waitFor(() => expect(result.current.active.pageIndex).toBe(1));
      expect(result.current.active.rows).toEqual([['3']]);
    });

    it('clamps a remembered page the cache no longer holds, rather than showing nothing', async () => {
      // The pages of an execution nobody is observing are collected once `gcTime` elapses
      // — switch tabs in the Data Explorer, come back later — and the refetch starts again
      // from page 1. The remembered index then points past the end, and an absent page is
      // indistinguishable from an empty one: the grid would render "No rows returned" over
      // a result that has rows.
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
      rerender({id: 'q-1'});

      await waitFor(() => expect(result.current.rows).toEqual([['1'], ['2']]));
      expect(result.current.pageIndex).toBe(0);
      expect(result.current.rangeStart).toBe(1);
      expect(result.current.hasNext).toBe(true);
    });
  });
});

// ─── from useResultRowCount.test.ts ───

describe('useResultRowCount', () => {
  const mockGetQueryResults = vi.mocked(getQueryResults);

  const cols = [{name: 'v', type: 'integer'}];
  function ok(rows: string[][], nextToken?: string) {
    return {success: true as const, data: {columns: cols, rows, nextToken} satisfies QueryResultPage};
  }
  function page(rowCount: number, nextToken?: string) {
    return ok(
      Array.from({length: rowCount}, (_, i) => [String(i)]),
      nextToken
    );
  }

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('useResultRowCount', () => {
    it('sums rows across every page for the exact total', async () => {
      mockGetQueryResults.mockImplementation(async ({nextToken}) => {
        if (!nextToken) return page(1000, 'T2');
        if (nextToken === 'T2') return page(1000, 'T3');
        if (nextToken === 'T3') return page(384);
        throw new Error(`unexpected token ${nextToken}`);
      });

      const {result} = renderHookWithProviders(() => useResultRowCount('q-1'));

      expect(result.current.isCounting).toBe(true);
      await waitFor(() => expect(result.current.isCounting).toBe(false));
      expect(result.current.total).toBe(2384);
      expect(mockGetQueryResults).toHaveBeenCalledWith(
        expect.objectContaining({queryExecutionId: 'q-1', maxRows: ROW_COUNT_PAGE_SIZE})
      );
    });

    it('reports a single-page total immediately (no lingering pending)', async () => {
      mockGetQueryResults.mockResolvedValue(page(7));

      const {result} = renderHookWithProviders(() => useResultRowCount('q-1'));

      await waitFor(() => expect(result.current.isCounting).toBe(false));
      expect(result.current.total).toBe(7);
      expect(mockGetQueryResults).toHaveBeenCalledTimes(1);
    });

    it('reports 0 for a succeeded query that returned no rows', async () => {
      mockGetQueryResults.mockResolvedValue(page(0));

      const {result} = renderHookWithProviders(() => useResultRowCount('q-1'));

      await waitFor(() => expect(result.current.isCounting).toBe(false));
      expect(result.current.total).toBe(0);
    });

    it('walks every page to the exact total with no ceiling', async () => {
      // Five full pages, then a short final page — the walk sums them all.
      mockGetQueryResults.mockImplementation(async ({nextToken}) => {
        const seen = nextToken ? Number(nextToken) : 0;
        if (seen < 5) return page(ROW_COUNT_PAGE_SIZE, String(seen + 1));
        return page(42);
      });

      const {result} = renderHookWithProviders(() => useResultRowCount('q-1'));

      await waitFor(() => expect(result.current.isCounting).toBe(false));
      expect(result.current.total).toBe(ROW_COUNT_PAGE_SIZE * 5 + 42);
      expect(mockGetQueryResults).toHaveBeenCalledTimes(6);
    });

    it('is disabled (no walk) when the execution id is null', () => {
      const {result} = renderHookWithProviders(() => useResultRowCount(null));

      expect(result.current.isCounting).toBe(false);
      expect(result.current.total).toBeNull();
      expect(mockGetQueryResults).not.toHaveBeenCalled();
    });

    it('leaves total null (pending) when a page fails — never throws', async () => {
      mockGetQueryResults.mockResolvedValue({
        success: false as const,
        error: {message: 'boom'}
      });

      const {result} = renderHookWithProviders(() => useResultRowCount('q-1'));

      await waitFor(() =>
        expect(mockGetQueryResults).toHaveBeenCalledWith(expect.objectContaining({queryExecutionId: 'q-1'}))
      );
      expect(result.current.total).toBeNull();
    });

    it('recomputes for a new execution id and abandons the prior count', async () => {
      mockGetQueryResults.mockImplementation(async ({queryExecutionId}) =>
        queryExecutionId === 'q-1' ? page(3) : page(99)
      );

      const {result, rerender} = renderHookWithProviders(({id}) => useResultRowCount(id), {
        initialProps: {id: 'q-1' as string | null}
      });
      await waitFor(() => expect(result.current.total).toBe(3));

      rerender({id: 'q-2'});
      await waitFor(() => expect(result.current.total).toBe(99));
    });
  });
});
