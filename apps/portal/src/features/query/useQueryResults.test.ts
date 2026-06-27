import { renderHook, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { createElement, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useQueryResults } from './useQueryResults';
import { getQueryResults } from './query.service';
import type { QueryResultPage } from './query.types';

vi.mock('./query.service');

const mockGetQueryResults = vi.mocked(getQueryResults);

// Fresh client per render, retries off so an errored query fails fast.
function wrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
}

const cols = [{ name: 'v', type: 'integer' }];
function ok(rows: string[][], nextToken?: string) {
  return {
    success: true as const,
    data: { columns: cols, rows, nextToken } satisfies QueryResultPage,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  // Two pages: page 1 (rows 1–2, more available) → page 2 (row 3, last).
  mockGetQueryResults.mockImplementation(async ({ nextToken }) => {
    if (!nextToken) return ok([['1'], ['2']], 'T2');
    if (nextToken === 'T2') return ok([['3']]);
    throw new Error(`unexpected token ${nextToken}`);
  });
});

// pageSize = 2 in these tests so the range math is easy to assert.
describe('useQueryResults', () => {
  it('loads the first page and reports that more is available', async () => {
    const { result } = renderHook(() => useQueryResults('q-1', 2), {
      wrapper: wrapper(),
    });

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
    const { result } = renderHook(() => useQueryResults('q-1', 2), {
      wrapper: wrapper(),
    });
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
    const { result } = renderHook(() => useQueryResults('q-1', 2), {
      wrapper: wrapper(),
    });
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
    const { result, rerender } = renderHook(({ id }) => useQueryResults(id, 2), {
      wrapper: wrapper(),
      initialProps: { id: 'q-1' as string | null },
    });
    await waitFor(() => expect(result.current.isPending).toBe(false));
    await act(async () => {
      result.current.goNext();
    });
    await waitFor(() => expect(result.current.pageIndex).toBe(1));

    rerender({ id: 'q-2' });

    await waitFor(() => expect(result.current.pageIndex).toBe(0));
  });
});
