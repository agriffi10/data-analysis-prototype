import {describe, it, expect} from 'vitest';
import {renderHook, act} from '@testing-library/react';
import {useColumnWidths} from './useColumnWidths';
import {DEFAULT_COLUMN_WIDTH, MIN_COLUMN_WIDTH} from './query.constants';

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

  it('resets all widths when the execution id (resetKey) changes', () => {
    const {result, rerender} = renderHook(({key, count}) => useColumnWidths(key, count), {
      initialProps: {key: 'exec-1' as string | null, count: 2}
    });
    act(() => result.current.setWidth(0, 320));
    expect(result.current.widths[0]).toBe(320);

    rerender({key: 'exec-2', count: 2});
    expect(result.current.widths).toEqual([DEFAULT_COLUMN_WIDTH, DEFAULT_COLUMN_WIDTH]);
  });

  it('resets when the column count changes (no stale per-index widths bleed across results)', () => {
    const {result, rerender} = renderHook(({key, count}) => useColumnWidths(key, count), {
      initialProps: {key: 'exec-1' as string | null, count: 2}
    });
    act(() => result.current.setWidth(1, 320));

    rerender({key: 'exec-1', count: 4});
    expect(result.current.widths).toEqual([
      DEFAULT_COLUMN_WIDTH,
      DEFAULT_COLUMN_WIDTH,
      DEFAULT_COLUMN_WIDTH,
      DEFAULT_COLUMN_WIDTH
    ]);
  });

  it('ignores out-of-range indices', () => {
    const {result} = renderHook(() => useColumnWidths('exec-1', 2));
    act(() => result.current.setWidth(5, 300));
    act(() => result.current.resetColumn(-1));
    expect(result.current.widths).toEqual([DEFAULT_COLUMN_WIDTH, DEFAULT_COLUMN_WIDTH]);
  });
});
