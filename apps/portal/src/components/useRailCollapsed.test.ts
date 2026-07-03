import {renderHook, act} from '@testing-library/react';
import {beforeEach, describe, it, expect, vi} from 'vitest';
import {useRailCollapsed, RAIL_COLLAPSED_STORAGE_KEY} from './useRailCollapsed';
import {memoryStorage} from '../test/storage';

beforeEach(() => {
  vi.restoreAllMocks();
  vi.stubGlobal('localStorage', memoryStorage());
});

describe('useRailCollapsed', () => {
  it('defaults to expanded when nothing is stored', () => {
    const {result} = renderHook(() => useRailCollapsed());
    expect(result.current.collapsed).toBe(false);
  });

  it('reads a persisted collapsed=true on mount', () => {
    localStorage.setItem(RAIL_COLLAPSED_STORAGE_KEY, 'true');
    const {result} = renderHook(() => useRailCollapsed());
    expect(result.current.collapsed).toBe(true);
  });

  it('toggle flips the state and persists it under the shared key', () => {
    const {result} = renderHook(() => useRailCollapsed());
    act(() => result.current.toggle());
    expect(result.current.collapsed).toBe(true);
    expect(localStorage.getItem(RAIL_COLLAPSED_STORAGE_KEY)).toBe('true');
    act(() => result.current.toggle());
    expect(result.current.collapsed).toBe(false);
    expect(localStorage.getItem(RAIL_COLLAPSED_STORAGE_KEY)).toBe('false');
  });

  it('setCollapsed writes through to storage', () => {
    const {result} = renderHook(() => useRailCollapsed());
    act(() => result.current.setCollapsed(true));
    expect(result.current.collapsed).toBe(true);
    expect(localStorage.getItem(RAIL_COLLAPSED_STORAGE_KEY)).toBe('true');
  });

  it('is shared across rails: a fresh instance reads the persisted value', () => {
    const a = renderHook(() => useRailCollapsed());
    act(() => a.result.current.setCollapsed(true));
    const b = renderHook(() => useRailCollapsed());
    expect(b.result.current.collapsed).toBe(true);
  });

  it('degrades to not-persisted (default expanded, no throw) when localStorage is unavailable', () => {
    vi.spyOn(localStorage, 'getItem').mockImplementation(() => {
      throw new Error('storage denied');
    });
    vi.spyOn(localStorage, 'setItem').mockImplementation(() => {
      throw new Error('storage denied');
    });
    const {result} = renderHook(() => useRailCollapsed());
    expect(result.current.collapsed).toBe(false); // default, not a throw
    act(() => result.current.toggle()); // must not throw despite setItem throwing
    expect(result.current.collapsed).toBe(true); // in-memory state still works
  });
});
