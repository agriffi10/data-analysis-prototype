import {renderHook, waitFor} from '@testing-library/react';
import {describe, it, expect, vi, beforeEach} from 'vitest';
import {createElement, type ReactNode} from 'react';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {useResultRowCount} from './useResultRowCount';
import {getQueryResults} from './query.service';
import {ROW_COUNT_PAGE_SIZE} from './query.constants';
import type {QueryResultPage} from './query.types';

vi.mock('./query.service');

const mockGetQueryResults = vi.mocked(getQueryResults);

function wrapper() {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}});
  return ({children}: {children: ReactNode}) => createElement(QueryClientProvider, {client}, children);
}

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

    const {result} = renderHook(() => useResultRowCount('q-1'), {wrapper: wrapper()});

    expect(result.current.isCounting).toBe(true);
    await waitFor(() => expect(result.current.isCounting).toBe(false));
    expect(result.current.total).toBe(2384);
    expect(mockGetQueryResults).toHaveBeenCalledWith(
      expect.objectContaining({queryExecutionId: 'q-1', maxRows: ROW_COUNT_PAGE_SIZE})
    );
  });

  it('reports a single-page total immediately (no lingering pending)', async () => {
    mockGetQueryResults.mockResolvedValue(page(7));

    const {result} = renderHook(() => useResultRowCount('q-1'), {wrapper: wrapper()});

    await waitFor(() => expect(result.current.isCounting).toBe(false));
    expect(result.current.total).toBe(7);
    expect(mockGetQueryResults).toHaveBeenCalledTimes(1);
  });

  it('reports 0 for a succeeded query that returned no rows', async () => {
    mockGetQueryResults.mockResolvedValue(page(0));

    const {result} = renderHook(() => useResultRowCount('q-1'), {wrapper: wrapper()});

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

    const {result} = renderHook(() => useResultRowCount('q-1'), {wrapper: wrapper()});

    await waitFor(() => expect(result.current.isCounting).toBe(false));
    expect(result.current.total).toBe(ROW_COUNT_PAGE_SIZE * 5 + 42);
    expect(mockGetQueryResults).toHaveBeenCalledTimes(6);
  });

  it('is disabled (no walk) when the execution id is null', () => {
    const {result} = renderHook(() => useResultRowCount(null), {wrapper: wrapper()});

    expect(result.current.isCounting).toBe(false);
    expect(result.current.total).toBeNull();
    expect(mockGetQueryResults).not.toHaveBeenCalled();
  });

  it('leaves total null (pending) when a page fails — never throws', async () => {
    mockGetQueryResults.mockResolvedValue({
      success: false as const,
      error: {message: 'boom'}
    });

    const {result} = renderHook(() => useResultRowCount('q-1'), {wrapper: wrapper()});

    await waitFor(() => expect(mockGetQueryResults).toHaveBeenCalled());
    expect(result.current.total).toBeNull();
  });

  it('recomputes for a new execution id and abandons the prior count', async () => {
    mockGetQueryResults.mockImplementation(async ({queryExecutionId}) =>
      queryExecutionId === 'q-1' ? page(3) : page(99)
    );

    const {result, rerender} = renderHook(({id}) => useResultRowCount(id), {
      wrapper: wrapper(),
      initialProps: {id: 'q-1' as string | null}
    });
    await waitFor(() => expect(result.current.total).toBe(3));

    rerender({id: 'q-2'});
    await waitFor(() => expect(result.current.total).toBe(99));
  });
});
