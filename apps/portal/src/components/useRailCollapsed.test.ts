import {beforeEach, describe, expect, it, vi} from 'vitest';
import {act, renderHook} from '@testing-library/react';
import {useRailCollapsed} from './useRailCollapsed';
import {memoryStorage} from '../test/storage';

describe('useRailCollapsed', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal('localStorage', memoryStorage());
  });

  describe('useRailCollapsed', () => {
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
});
