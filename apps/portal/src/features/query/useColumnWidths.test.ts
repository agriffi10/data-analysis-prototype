import {describe, it, expect} from 'vitest';
import {renderHook, act} from '@testing-library/react';
import {useColumnWidths} from './useColumnWidths';
import {DEFAULT_COLUMN_WIDTH, MIN_COLUMN_WIDTH} from './query.constants';

type Props = {id: string | null; count: number};

function renderWidths(initial: Props) {
  return renderHook(({id, count}: Props) => useColumnWidths(id, count), {initialProps: initial});
}

describe('useColumnWidths', () => {
  it('defaults every column to DEFAULT_COLUMN_WIDTH', () => {
    const {result} = renderHook(() => useColumnWidths('exec-1', 3));
    expect(result.current.widths).toEqual([DEFAULT_COLUMN_WIDTH, DEFAULT_COLUMN_WIDTH, DEFAULT_COLUMN_WIDTH]);
  });

  it('setWidth updates one column without touching the others', () => {
    const {result} = renderHook(() => useColumnWidths('exec-1', 3));
    act(() => result.current.setWidth(1, 300));
    expect(result.current.widths).toEqual([DEFAULT_COLUMN_WIDTH, 300, DEFAULT_COLUMN_WIDTH]);
  });

  it('clamps setWidth at MIN_COLUMN_WIDTH', () => {
    const {result} = renderHook(() => useColumnWidths('exec-1', 2));
    act(() => result.current.setWidth(0, 10));
    expect(result.current.widths[0]).toBe(MIN_COLUMN_WIDTH);
  });

  it('resetColumn returns a single column to the default', () => {
    const {result} = renderHook(() => useColumnWidths('exec-1', 2));
    act(() => result.current.setWidth(0, 320));
    expect(result.current.widths[0]).toBe(320);
    act(() => result.current.resetColumn(0));
    expect(result.current.widths[0]).toBe(DEFAULT_COLUMN_WIDTH);
  });

  it('keeps widths across a re-render of the same execution (paging)', () => {
    const {result, rerender} = renderWidths({id: 'exec-1', count: 2});
    act(() => result.current.setWidth(0, 320));
    rerender({id: 'exec-1', count: 2}); // same execution, e.g. Prev/Next
    expect(result.current.widths[0]).toBe(320);
  });

  it('resets to defaults for a new execution id (a new query)', () => {
    const {result, rerender} = renderWidths({id: 'exec-1', count: 2});
    act(() => result.current.setWidth(0, 320));

    rerender({id: 'exec-2', count: 2});
    expect(result.current.widths).toEqual([DEFAULT_COLUMN_WIDTH, DEFAULT_COLUMN_WIDTH]);
  });

  it('restores a prior execution’s widths when navigating back to it (tab switch)', () => {
    const {result, rerender} = renderWidths({id: 'exec-1', count: 2});
    act(() => result.current.setWidth(0, 320));

    // Switch to another tab's query (defaults), then back to exec-1.
    rerender({id: 'exec-2', count: 3});
    expect(result.current.widths).toEqual([DEFAULT_COLUMN_WIDTH, DEFAULT_COLUMN_WIDTH, DEFAULT_COLUMN_WIDTH]);

    rerender({id: 'exec-1', count: 2});
    expect(result.current.widths).toEqual([320, DEFAULT_COLUMN_WIDTH]); // exec-1's widths survived
  });

  it('re-defaults when the same id reappears with a different column count', () => {
    const {result, rerender} = renderWidths({id: 'exec-1', count: 2});
    act(() => result.current.setWidth(1, 320));

    rerender({id: 'exec-1', count: 4});
    expect(result.current.widths).toEqual([
      DEFAULT_COLUMN_WIDTH,
      DEFAULT_COLUMN_WIDTH,
      DEFAULT_COLUMN_WIDTH,
      DEFAULT_COLUMN_WIDTH
    ]);
  });

  it('returns defaults and ignores setters when the execution id is null', () => {
    const {result} = renderHook(() => useColumnWidths(null, 2));
    expect(result.current.widths).toEqual([DEFAULT_COLUMN_WIDTH, DEFAULT_COLUMN_WIDTH]);
    act(() => result.current.setWidth(0, 320));
    expect(result.current.widths).toEqual([DEFAULT_COLUMN_WIDTH, DEFAULT_COLUMN_WIDTH]);
  });

  it('ignores out-of-range indices', () => {
    const {result} = renderHook(() => useColumnWidths('exec-1', 2));
    act(() => result.current.setWidth(5, 300));
    act(() => result.current.resetColumn(-1));
    expect(result.current.widths).toEqual([DEFAULT_COLUMN_WIDTH, DEFAULT_COLUMN_WIDTH]);
  });
});
