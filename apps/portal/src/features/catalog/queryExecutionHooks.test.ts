import {beforeEach, describe, expect, it, vi} from 'vitest';
import {act, waitFor} from '@testing-library/react';
import {focusManager, onlineManager} from '@tanstack/react-query';
import {createTestQueryClient, renderHookWithProviders} from '../../test/renderWithProviders';
import {getQueryResults, getQueryRowCount, getQueryStatus} from './athena.service';
import {useQueryExecution} from './useQueryExecution';
import {useQueryResults} from './useQueryResults';
import {useResultRowCount} from './useResultRowCount';
import {catalogKeys} from './catalogKeys';
import {MAX_POLL_DURATION_MS, POLL_INTERVAL_MS, ROW_COUNT_PAGE_SIZE} from './catalog.constants';
import type {QueryResultPage, QueryRowCount, QueryStatus} from './catalog.types';

// One boundary for all three hook suites. `isTerminalState` and friends stay real
// (importActual) so the polling/stop logic runs exactly as in production.
vi.mock('./athena.service', async (importActual) => {
  const actual = await importActual<typeof import('./athena.service')>();
  return {...actual, getQueryStatus: vi.fn(), getQueryResults: vi.fn(), getQueryRowCount: vi.fn()};
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
      expect(result.current).toEqual({status: undefined, error: null, stillRunning: null});
      expect(mockGetStatus).not.toHaveBeenCalled();
    });

    it('fetches the execution status for a non-null id and exposes the terminal state', async () => {
      mockGetStatus.mockResolvedValue(ok(status({state: 'SUCCEEDED'})));
      const {result} = renderHookWithProviders(() => useQueryExecution('q-1'));

      await waitFor(() => expect(result.current.status?.state).toBe('SUCCEEDED'));
      expect(mockGetStatus).toHaveBeenCalledWith('q-1');
    });

    it('surfaces a service failure as an error state after its one retry (queryFn throws)', async () => {
      mockGetStatus.mockResolvedValue({success: false, error: {message: 'boom'}});
      const {result} = renderHookWithProviders(() => useQueryExecution('q-1'));

      await waitFor(() => expect(result.current.error).not.toBeNull());
      expect(result.current.error).toEqual(expect.objectContaining({message: 'boom'}));
      // The harness retries nothing, so the second request is the hook's own retry.
      expect(mockGetStatus).toHaveBeenCalledTimes(2);
    });

    it('asks nothing more on the poll interval once a failed request has spent its retry, with stopOnError', async () => {
      vi.useFakeTimers();
      try {
        mockGetStatus.mockResolvedValue({success: false, error: {message: 'refused', code: 'NotFound'}});
        const {result} = renderHookWithProviders(() => useQueryExecution('q-1', {stopOnError: true}));
        await act(async () => {
          await vi.waitFor(() => expect(result.current.error).not.toBeNull());
        });

        await act(async () => {
          await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2);
        });

        expect(mockGetStatus).toHaveBeenCalledTimes(2);
      } finally {
        vi.useRealTimers();
      }
    });

    it('keeps polling after a failed request without stopOnError', async () => {
      vi.useFakeTimers();
      try {
        mockGetStatus.mockResolvedValue({success: false, error: {message: 'refused', code: 'NotFound'}});
        const {result} = renderHookWithProviders(() => useQueryExecution('q-1'));
        await act(async () => {
          await vi.waitFor(() => expect(result.current.error).not.toBeNull());
        });
        // Counted from the error, not the first request, because the retry alone makes a second.
        const atError = mockGetStatus.mock.calls.length;

        await act(async () => {
          await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS + 250);
        });

        // The interval's request, and its own retry.
        expect(mockGetStatus).toHaveBeenCalledTimes(atError + 2);
      } finally {
        vi.useRealTimers();
      }
    });
  });

  describe('the watch’s ceiling', () => {
    const RUNNING = ok(status({state: 'RUNNING'}));
    const requestsFor = (id: string) => mockGetStatus.mock.calls.filter(([requested]) => requested === id).length;

    /**
     * Advances the fake clock inside its own `act`. Crossing the ceiling's mark gets a call of its
     * own: the mark is a state update, and React applies it only when the `act` around it exits.
     */
    async function advance(ms: number) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(ms);
      });
    }
    /** One poll past wherever the clock stands, with room for the read and its notification. */
    const ONE_POLL = POLL_INTERVAL_MS + 10;

    it('ends the watch on the first read after the ceiling that finds it running, and asks nothing more', async () => {
      vi.useFakeTimers();
      try {
        mockGetStatus.mockResolvedValue(RUNNING);
        const {result} = renderHookWithProviders(() => useQueryExecution('q-1'));

        await advance(MAX_POLL_DURATION_MS - 1);
        expect(result.current.stillRunning).toBeNull();
        const beforeTheMark = requestsFor('q-1');
        await advance(1);
        await advance(ONE_POLL);

        expect(requestsFor('q-1')).toBeGreaterThan(beforeTheMark);
        expect(result.current.stillRunning).toMatchObject({
          code: 'QueryStillRunning',
          params: {limit: 30, queryExecutionId: 'q-1'}
        });
        expect(result.current.status?.state).toBe('RUNNING');

        const atVerdict = requestsFor('q-1');
        await advance(POLL_INTERVAL_MS * 2);
        await act(async () => {
          onlineManager.setOnline(false);
          onlineManager.setOnline(true);
          await vi.advanceTimersByTimeAsync(10);
        });
        expect(requestsFor('q-1')).toBe(atVerdict);
      } finally {
        onlineManager.setOnline(true);
        vi.useRealTimers();
      }
    });

    it('re-renders its host on no poll while the status is unchanged', async () => {
      // The reason the hook returns its own shape: reading `dataUpdatedAt` before the ceiling
      // would make TanStack notify on every poll, and the Explorer would re-render with each one.
      vi.useFakeTimers();
      try {
        mockGetStatus.mockResolvedValue(RUNNING);
        let renders = 0;
        renderHookWithProviders(() => {
          renders += 1;
          return useQueryExecution('q-1');
        });
        await advance(POLL_INTERVAL_MS * 2 + POLL_INTERVAL_MS / 3);
        const settled = renders;
        const before = requestsFor('q-1');

        await advance(POLL_INTERVAL_MS * 20);

        expect(requestsFor('q-1')).toBeGreaterThanOrEqual(before + 20);
        expect(renders).toBe(settled);
      } finally {
        vi.useRealTimers();
      }
    });

    it('delivers a terminal status read after the ceiling, and reports no verdict', async () => {
      vi.useFakeTimers();
      try {
        const start = Date.now();
        mockGetStatus.mockImplementation(async () =>
          ok(status({state: Date.now() - start > MAX_POLL_DURATION_MS ? 'SUCCEEDED' : 'RUNNING'}))
        );
        const {result} = renderHookWithProviders(() => useQueryExecution('q-1'));

        await advance(MAX_POLL_DURATION_MS);
        await advance(ONE_POLL);

        expect(result.current.status?.state).toBe('SUCCEEDED');
        expect(result.current.stillRunning).toBeNull();
      } finally {
        vi.useRealTimers();
      }
    });

    it('decides on the first read after a hidden page is shown again, never on the clock alone', async () => {
      vi.useFakeTimers();
      // As production has it: a focus refetch would make the deciding read here, not the interval.
      const queryClient = createTestQueryClient();
      queryClient.setDefaultOptions({
        queries: {...queryClient.getDefaultOptions().queries, refetchOnWindowFocus: false}
      });
      try {
        mockGetStatus.mockResolvedValue(RUNNING);
        const {result} = renderHookWithProviders(() => useQueryExecution('q-1'), {queryClient});
        await advance(MAX_POLL_DURATION_MS - 10_000);

        focusManager.setFocused(false);
        const hidden = requestsFor('q-1');
        await advance(20_000);
        expect(requestsFor('q-1')).toBe(hidden);
        expect(result.current.stillRunning).toBeNull();

        focusManager.setFocused(true);
        await advance(ONE_POLL);
        expect(requestsFor('q-1')).toBe(hidden + 1);
        expect(result.current.stillRunning).not.toBeNull();
      } finally {
        focusManager.setFocused(undefined);
        queryClient.clear();
        vi.useRealTimers();
      }
    });

    it.each([
      ['another execution', 'q-2'],
      ['no execution at all', null]
    ])('looks again when a new watch starts on the same execution, after %s', async (_, between) => {
      vi.useFakeTimers();
      // Keeps the cache: collected on the switch, q-1 would be refetched whatever the hook remembered.
      const queryClient = createTestQueryClient();
      queryClient.setDefaultOptions({queries: {...queryClient.getDefaultOptions().queries, gcTime: Infinity}});
      try {
        mockGetStatus.mockResolvedValue(RUNNING);
        const {result, rerender} = renderHookWithProviders(({id}) => useQueryExecution(id), {
          initialProps: {id: 'q-1' as string | null},
          queryClient
        });
        await advance(MAX_POLL_DURATION_MS);
        await advance(ONE_POLL);
        expect(result.current.stillRunning).not.toBeNull();

        rerender({id: between});
        await advance(ONE_POLL);
        const beforeReturning = requestsFor('q-1');
        rerender({id: 'q-1'});
        await advance(ONE_POLL);

        expect(result.current.stillRunning).toBeNull();
        expect(requestsFor('q-1')).toBeGreaterThanOrEqual(beforeReturning + 2);
      } finally {
        queryClient.clear();
        vi.useRealTimers();
      }
    });

    it('ends the watch on a failed read after the ceiling, even without stopOnError', async () => {
      vi.useFakeTimers();
      try {
        mockGetStatus.mockResolvedValue({success: false, error: {message: 'refused', code: 'NotFound'}});
        const {result} = renderHookWithProviders(() => useQueryExecution('q-1'));

        // Each window ends between two ticks. One that ends ON a tick can leave the timer that tick
        // schedules through its retry for the next window, and the counts would then shift by one poll.
        await advance(POLL_INTERVAL_MS * 4 + POLL_INTERVAL_MS / 3);
        // Before the ceiling a failure keeps polling: each interval is a request and its retry.
        const early = requestsFor('q-1');
        await advance(POLL_INTERVAL_MS);
        expect(requestsFor('q-1')).toBe(early + 2);

        await advance(MAX_POLL_DURATION_MS - POLL_INTERVAL_MS * 5 - POLL_INTERVAL_MS / 3 + 10);
        const atTheMark = requestsFor('q-1');
        await advance(ONE_POLL);
        await advance(POLL_INTERVAL_MS * 2);

        // The deciding read and its retry, and nothing after them.
        expect(requestsFor('q-1')).toBe(atTheMark + 2);
        expect(result.current.error).toEqual(expect.objectContaining({code: 'NotFound'}));
        expect(result.current.stillRunning).toBeNull();
      } finally {
        vi.useRealTimers();
      }
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
  const mockGetRowCount = vi.mocked(getQueryRowCount);

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
  function counted(answer: QueryRowCount) {
    return {success: true as const, data: answer};
  }
  const PENDING = counted({rowCount: null, pending: true});
  const NOT_COUNTED = counted({rowCount: null, pending: false});

  /** Advances fake time inside `act`, so the re-render it causes is flushed before the next assertion. */
  async function advance(ms: number) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  }

  beforeEach(() => {
    vi.clearAllMocks();
    // clearAllMocks keeps implementations, so one test's fake would answer the next test's call.
    mockGetQueryResults.mockReset();
    mockGetRowCount.mockReset();
    // The default is a statement Athena does not count, so the walk tests below keep their subject.
    mockGetRowCount.mockResolvedValue(NOT_COUNTED);
  });

  describe('when Athena counts the result', () => {
    // The test the old hook fails. Its pages never end, and the fake throws on the 101st so a walk
    // fails by assertion here instead of spinning the worker on resolved promises until it dies.
    it.each([10_000_000, 0])('takes Athena’s count of %i and walks no page', async (count) => {
      let served = 0;
      mockGetQueryResults.mockImplementation(async () => {
        served += 1;
        if (served > 100) throw new Error('an unbounded walk reached page 101');
        return page(ROW_COUNT_PAGE_SIZE, `t-${served}`);
      });
      mockGetRowCount.mockResolvedValue(counted({rowCount: count, pending: false}));

      const {result, queryClient} = renderHookWithProviders(() => useResultRowCount('q-1'));

      await waitFor(() => expect(queryClient.getQueryData(catalogKeys.rowCount('q-1'))).toBe(count));
      expect(result.current).toEqual({total: count, isCounting: false});
      expect(mockGetRowCount).toHaveBeenCalledWith('q-1');
      expect(mockGetQueryResults).not.toHaveBeenCalled();
    });

    it('asks again for a pending count on the schedule, and never walks', async () => {
      vi.useFakeTimers();
      try {
        mockGetRowCount
          .mockResolvedValueOnce(PENDING)
          .mockResolvedValueOnce(PENDING)
          .mockResolvedValueOnce(counted({rowCount: 1763, pending: false}));

        const {result} = renderHookWithProviders(() => useResultRowCount('q-1'));

        await advance(0);
        expect(mockGetRowCount).toHaveBeenCalledTimes(1);
        await advance(999);
        expect(mockGetRowCount).toHaveBeenCalledTimes(1);
        await advance(1);
        expect(mockGetRowCount).toHaveBeenCalledTimes(2);
        await advance(1_999);
        expect(mockGetRowCount).toHaveBeenCalledTimes(2);
        await advance(1);
        expect(mockGetRowCount).toHaveBeenCalledTimes(3);

        // TanStack hands the result to its observers on a timer; vi.waitFor advances the fake clock.
        await act(async () => {
          await vi.waitFor(() => expect(result.current.total).toBe(1763));
        });
        expect(mockGetRowCount).toHaveBeenCalledTimes(3);
        expect(mockGetQueryResults).not.toHaveBeenCalled();
      } finally {
        vi.useRealTimers();
      }
    });

    it('walks to the exact total only after the seventh ask still finds nothing', async () => {
      vi.useFakeTimers();
      try {
        mockGetRowCount.mockResolvedValue(PENDING);
        mockGetQueryResults.mockResolvedValue(page(42));

        const {result} = renderHookWithProviders(() => useResultRowCount('q-1'));

        // The six waits sum to 60 s, so the seventh ask is at 60,000 ms.
        await advance(59_999);
        expect(mockGetRowCount).toHaveBeenCalledTimes(6);
        expect(mockGetQueryResults).not.toHaveBeenCalled();

        await advance(1);
        expect(mockGetRowCount).toHaveBeenCalledTimes(7);
        expect(mockGetQueryResults).toHaveBeenCalledTimes(1);
        await act(async () => {
          await vi.waitFor(() => expect(result.current.total).toBe(42));
        });
        expect(mockGetRowCount).toHaveBeenCalledTimes(7);
      } finally {
        vi.useRealTimers();
      }
    });

    it.each(['unmounted', 'pointed at another execution'])(
      'stops asking and never walks the old execution once %s mid-wait',
      async (how) => {
        vi.useFakeTimers();
        try {
          mockGetRowCount.mockImplementation(async (id: string) =>
            id === 'q-1' ? PENDING : counted({rowCount: 5, pending: false})
          );
          mockGetQueryResults.mockResolvedValue(page(42));

          const {unmount, rerender} = renderHookWithProviders(({id}) => useResultRowCount(id), {
            initialProps: {id: 'q-1' as string | null}
          });
          await advance(0);
          expect(mockGetRowCount).toHaveBeenCalledTimes(1);

          if (how === 'unmounted') unmount();
          else rerender({id: 'q-2'});
          await advance(120_000);

          expect(mockGetRowCount.mock.calls.filter(([id]) => id === 'q-1')).toHaveLength(1);
          expect(mockGetQueryResults).not.toHaveBeenCalled();
        } finally {
          vi.useRealTimers();
        }
      }
    );

    it('leaves the total unknown when the request fails, and walks nothing', async () => {
      mockGetRowCount.mockResolvedValue({success: false, error: {message: '', code: 'AccessDenied'}});
      mockGetQueryResults.mockResolvedValue(page(7));

      const {result, queryClient} = renderHookWithProviders(() => useResultRowCount('q-1'));

      // Wait on the error itself: `isCounting` stays true after one, so there is nothing else to
      // wait on — and a walk-on-error hook would reach `success` here instead.
      await waitFor(() => expect(queryClient.getQueryState(catalogKeys.rowCount('q-1'))?.status).toBe('error'));
      expect(result.current.total).toBeNull();
      expect(mockGetQueryResults).not.toHaveBeenCalled();
    });
  });

  describe('where Athena does not count the result', () => {
    it('walks every page to the exact total, with no ceiling', async () => {
      // Five full pages, then a short final page — the walk sums them all.
      mockGetQueryResults.mockImplementation(async ({nextToken}) => {
        const seen = nextToken ? Number(nextToken) : 0;
        if (seen < 5) return page(ROW_COUNT_PAGE_SIZE, String(seen + 1));
        return page(42);
      });

      const {result} = renderHookWithProviders(() => useResultRowCount('q-1'));

      expect(result.current.isCounting).toBe(true);
      await waitFor(() => expect(result.current.isCounting).toBe(false));
      expect(result.current.total).toBe(ROW_COUNT_PAGE_SIZE * 5 + 42);
      expect(mockGetQueryResults).toHaveBeenCalledTimes(6);
      expect(mockGetQueryResults).toHaveBeenCalledWith(
        expect.objectContaining({queryExecutionId: 'q-1', maxRows: ROW_COUNT_PAGE_SIZE})
      );
    });

    it.each([7, 0])('reports a single page of %i rows at once', async (rows) => {
      mockGetQueryResults.mockResolvedValue(page(rows));

      const {result} = renderHookWithProviders(() => useResultRowCount('q-1'));

      await waitFor(() => expect(result.current.isCounting).toBe(false));
      expect(result.current.total).toBe(rows);
      expect(mockGetQueryResults).toHaveBeenCalledTimes(1);
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
  });

  it('is disabled (no request at all) when the execution id is null', () => {
    const {result} = renderHookWithProviders(() => useResultRowCount(null));

    expect(result.current.isCounting).toBe(false);
    expect(result.current.total).toBeNull();
    expect(mockGetRowCount).not.toHaveBeenCalled();
    expect(mockGetQueryResults).not.toHaveBeenCalled();
  });

  it('recomputes for a new execution id and abandons the prior count', async () => {
    mockGetRowCount.mockImplementation(async (id: string) =>
      counted({rowCount: id === 'q-1' ? 3 : 99, pending: false})
    );

    const {result, rerender} = renderHookWithProviders(({id}) => useResultRowCount(id), {
      initialProps: {id: 'q-1' as string | null}
    });
    await waitFor(() => expect(result.current.total).toBe(3));

    rerender({id: 'q-2'});
    await waitFor(() => expect(result.current.total).toBe(99));
  });
});
