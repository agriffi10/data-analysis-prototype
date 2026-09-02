import {act, render, renderHook, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import {useClientPager} from './useClientPager';

// ─── from useClientPager.test.tsx ───
describe('useClientPager', () => {
  const items = (n: number) => Array.from({length: n}, (_, i) => `item-${i + 1}`);

  describe('useClientPager', () => {
    it('slices the current page and reports what the pager can do', () => {
      const {result} = renderHook(() => useClientPager(items(25), 10));

      expect(result.current.pageItems).toHaveLength(10);
      expect(result.current.pageItems[0]).toBe('item-1');
      expect(result.current.pagerProps.hasPrev).toBe(false);
      expect(result.current.pagerProps.hasNext).toBe(true);
    });

    it('walks forward and back, and stops at both ends', () => {
      const {result} = renderHook(() => useClientPager(items(25), 10));

      act(() => result.current.pagerProps.onNext());
      act(() => result.current.pagerProps.onNext());
      expect(result.current.pageItems).toEqual(['item-21', 'item-22', 'item-23', 'item-24', 'item-25']);
      expect(result.current.pagerProps.hasNext).toBe(false);

      act(() => result.current.pagerProps.onNext()); // no-op at the end
      expect(result.current.pageItems[0]).toBe('item-21');

      act(() => result.current.pagerProps.onPrev());
      expect(result.current.pageItems[0]).toBe('item-11');
    });

    it('CLAMPS when the list shrinks under the user rather than stranding them on a blank page', () => {
      // The reason the index is derived every render instead of stored: a filter, a
      // refresh or a mark-read can drop the list out from under page 3 with nothing
      // having remembered to reset it.
      const {result, rerender} = renderHook(({list}) => useClientPager(list, 10), {
        initialProps: {list: items(25)}
      });

      act(() => result.current.pagerProps.onNext());
      act(() => result.current.pagerProps.onNext());
      expect(result.current.pageItems[0]).toBe('item-21');

      rerender({list: items(8)});
      expect(result.current.pageItems).toHaveLength(8);
      expect(result.current.pagerProps.hasPrev).toBe(false);
      expect(result.current.pagerProps.hasNext).toBe(false);
    });

    it('labels the range AND announces the page number to screen readers', () => {
      // The reason the label lives in the hook rather than at two call sites: a page
      // count announced to sighted users only is exactly the divergence two copies make.
      const {result} = renderHook(() => useClientPager(items(25), 10));

      const {container} = render(<>{result.current.pagerProps.label}</>);
      expect(container).toHaveTextContent('1–10 of 25');
      expect(screen.getByText('(page 1)')).toHaveClass('sr-only');

      act(() => result.current.pagerProps.onNext());
      const second = render(<>{result.current.pagerProps.label}</>);
      expect(second.container).toHaveTextContent('11–20 of 25');
      expect(second.getByText('(page 2)')).toBeInTheDocument();
    });

    it('labels an empty list without a negative range', () => {
      const {result} = renderHook(() => useClientPager([], 10));
      const {container} = render(<>{result.current.pagerProps.label}</>);
      expect(container).toHaveTextContent('1–0 of 0');
    });

    it('resetToFirst jumps back to page 1', () => {
      const {result} = renderHook(() => useClientPager(items(25), 10));

      act(() => result.current.pagerProps.onNext());
      act(() => result.current.resetToFirst());
      expect(result.current.pageItems[0]).toBe('item-1');
    });

    it('handles an empty list without a negative range or a second page', () => {
      const {result} = renderHook(() => useClientPager([], 10));

      expect(result.current.pageItems).toEqual([]);
      expect(result.current.pagerProps.hasPrev).toBe(false);
      expect(result.current.pagerProps.hasNext).toBe(false);
    });
  });
});
