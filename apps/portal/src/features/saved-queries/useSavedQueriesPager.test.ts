import {act, renderHook} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';
import {useSavedQueriesPager} from './useSavedQueriesPager';
import {SAVED_QUERIES_PAGE_SIZE} from './savedQueries.constants';
import type {SavedQuery} from './savedQueries.types';

function sq(name: string, updatedAt = '2026-07-01T10:00:00.000Z'): SavedQuery {
  return {
    spaceId: 'personal',
    bucket: 'user-space',
    key: `alice/saved_queries/${name}.sql`,
    name,
    updatedAt,
    size: 24
  };
}

const many = (n: number) => Array.from({length: n}, (_, i) => sq(`q${String(i).padStart(3, '0')}`));

function setup(over: Partial<Parameters<typeof useSavedQueriesPager>[0]> = {}) {
  const loadMore = over.loadMore ?? vi.fn();
  // `loadMore` is resolved above so the spy is returned even when the caller supplies one.
  const args = {
    queries: many(24),
    hasMore: false,
    isLoadingMore: false,
    error: null as unknown,
    resetKey: 'open:personal',
    ...over,
    loadMore
  };
  const hook = renderHook((props: typeof args) => useSavedQueriesPager(props), {initialProps: args});
  return {...hook, loadMore, args};
}

describe('useSavedQueriesPager (SPEC-174 FR-002)', () => {
  it('pages 24 rows ten at a time and reports an honest range', () => {
    const {result} = setup();
    expect(result.current.page).toHaveLength(SAVED_QUERIES_PAGE_SIZE);
    expect(result.current.label).toBe('1–10 of 24');
    expect(result.current.hasPrev).toBe(false);
    expect(result.current.hasNext).toBe(true);

    act(() => result.current.onNext());
    expect(result.current.label).toBe('11–20 of 24');
    act(() => result.current.onNext());
    expect(result.current.label).toBe('21–24 of 24');
    expect(result.current.hasNext).toBe(false);
    expect(result.current.hasPrev).toBe(true);

    act(() => result.current.onPrev());
    expect(result.current.label).toBe('11–20 of 24');
  });

  it('marks the total with a `+` while listing pages remain, and drops it when they don’t', () => {
    // S3 reports no total. The `+` is the difference between "there are 25" and "there
    // are at least 25".
    const {result, rerender, args} = setup({queries: many(25), hasMore: true});
    expect(result.current.label).toBe('1–10 of 25+');
    rerender({...args, queries: many(25), hasMore: false});
    expect(result.current.label).toBe('1–10 of 25');
  });

  it('keeps fetching while a listing page yields fewer rows than one display page', () => {
    // A listing page and a display page are different things: 25 keys can hold no `.sql`
    // file at all, so a folder of CSVs must not render as empty.
    const loadMore = vi.fn();
    const {result} = setup({queries: [], hasMore: true, loadMore});
    expect(loadMore).toHaveBeenCalledTimes(1);
    expect(result.current.isFilling).toBe(true);
    expect(result.current.isEmpty).toBe(false);
  });

  it('stops at the end of the listing rather than looping', () => {
    // The bound is the listing's own end: one row and nothing truncated asks for nothing.
    const loadMore = vi.fn();
    const {result, rerender, args} = setup({queries: [sq('only')], hasMore: false, loadMore});
    rerender({...args, queries: [sq('only')], hasMore: false, loadMore});
    expect(loadMore).not.toHaveBeenCalled();
    expect(result.current.label).toBe('1–1 of 1');
    expect(result.current.isEmpty).toBe(false);
  });

  it('walks SEVERAL yield-nothing listing pages and then stops — the bound, not the guard', () => {
    // The `hasMore: false` case above is stopped by the guard alone and would pass with the
    // row-count condition deleted. This is the case the rule exists for: page after page of
    // keys the `.sql` filter empties, then a page with rows, then silence.
    const loadMore = vi.fn();
    const {result, rerender, args} = setup({queries: [], hasMore: true, loadMore});
    expect(loadMore).toHaveBeenCalledTimes(1);

    // Each round trip is a fetch flipping in and out of flight, yielding no `.sql` row.
    const round = () => {
      rerender({...args, queries: [], hasMore: true, isLoadingMore: true, loadMore});
      rerender({...args, queries: [], hasMore: true, isLoadingMore: false, loadMore});
    };
    round();
    expect(loadMore).toHaveBeenCalledTimes(2);
    round();
    expect(loadMore).toHaveBeenCalledTimes(3);

    // Rows arrive and the listing ends: it asks for nothing further.
    rerender({...args, queries: many(2), hasMore: false, loadMore});
    expect(loadMore).toHaveBeenCalledTimes(3);
    expect(result.current.label).toBe('1–2 of 2');
    expect(result.current.isFilling).toBe(false);
  });

  it('asks for nothing at all while the surface is not on screen', () => {
    // A closed drawer still runs its hooks. A folder of two hundred CSVs must not walk its
    // whole listing on every visit to /query for a list nobody opened.
    const loadMore = vi.fn();
    const {result} = setup({queries: [], hasMore: true, loadMore, enabled: false});
    expect(loadMore).not.toHaveBeenCalled();
    expect(result.current.isFilling).toBe(false);
  });

  it('keeps the loaded rows and Prev after a failed page, and stops offering Next', () => {
    // FR-002 AC5. The fill is stopped by the error, so a Next that could never advance is
    // not offered — but nothing the user already had is taken away.
    const {result} = setup({queries: many(12), hasMore: true, error: new Error('nope')});
    act(() => result.current.onNext());
    expect(result.current.page).toHaveLength(2);
    expect(result.current.hasPrev).toBe(true);
    expect(result.current.hasNext).toBe(false);
  });

  it('asks for no more while a fetch is in flight, or after one has failed', () => {
    const inFlight = vi.fn();
    setup({queries: [], hasMore: true, isLoadingMore: true, loadMore: inFlight});
    expect(inFlight).not.toHaveBeenCalled();

    // A failure that left `hasMore` true must not spin: the list keeps its rows and the
    // host renders the message.
    const failed = vi.fn();
    setup({queries: many(3), hasMore: true, error: new Error('nope'), loadMore: failed});
    expect(failed).not.toHaveBeenCalled();
  });

  it('is empty only once the listing is exhausted', () => {
    expect(setup({queries: [], hasMore: true}).result.current.isEmpty).toBe(false);
    expect(setup({queries: [], hasMore: false}).result.current.isEmpty).toBe(true);
  });

  it('fetches when Next runs off the loaded rows, and lands on the new page when they arrive', () => {
    const loadMore = vi.fn();
    const {result, rerender, args} = setup({queries: many(10), hasMore: true, loadMore});
    loadMore.mockClear();

    act(() => result.current.onNext());
    expect(loadMore).toHaveBeenCalledTimes(1);
    // Clamped here until the rows land — never a blank page.
    expect(result.current.page).toHaveLength(10);

    rerender({...args, queries: many(14), hasMore: false, loadMore});
    expect(result.current.label).toBe('11–14 of 14');
  });

  it('resets to page 1 when the reset key changes (another space, or a reopen)', () => {
    const {result, rerender, args} = setup();
    act(() => result.current.onNext());
    expect(result.current.label).toBe('11–20 of 24');

    rerender({...args, resetKey: 'open:teamspace', queries: many(24)});
    expect(result.current.label).toBe('1–10 of 24');
  });

  it('clamps rather than showing a blank page when the list shrinks under it', () => {
    // FR-005: deleting the only row on the last page moves the view to the new last page.
    const {result, rerender, args} = setup({queries: many(11)});
    act(() => result.current.onNext());
    expect(result.current.label).toBe('11–11 of 11');

    rerender({...args, queries: many(10)});
    expect(result.current.label).toBe('1–10 of 10');
  });

  it('applies no sort of its own — key order wins over `updatedAt` order (FR-003)', () => {
    const contradictory = [
      sq('alpha', '2026-01-03T00:00:00.000Z'),
      sq('beta', '2026-01-01T00:00:00.000Z'),
      sq('gamma', '2026-01-02T00:00:00.000Z')
    ];
    const {result} = setup({queries: contradictory});
    expect(result.current.page.map((q) => q.name)).toEqual(['alpha', 'beta', 'gamma']);
  });
});
