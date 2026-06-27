import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { readTabsState, writeTabsState, migrateDraftToTabs, initialTabsState } from './queryTabs';
import { QUERY_TABS_STORAGE_PREFIX, QUERY_DRAFT_STORAGE_PREFIX, DEFAULT_SQL } from './query.constants';
import type { QueryTabsState } from './query.types';

const KEY = `${QUERY_TABS_STORAGE_PREFIX}alice`;

function sample(): QueryTabsState {
  return {
    version: 1,
    tabs: [
      { id: 'a', label: 'Query 1', sql: 'SELECT 1;' },
      { id: 'b', label: 'Monthly revenue', sql: 'SELECT 2;', savedQueryId: 'sq-1' },
    ],
    activeTabId: 'b',
    nextQueryNumber: 2,
  };
}

describe('queryTabs', () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('initialTabsState is a single Query 1 seeded with the boilerplate', () => {
    const s = initialTabsState();
    expect(s.tabs).toHaveLength(1);
    expect(s.tabs[0].label).toBe('Query 1');
    expect(s.tabs[0].sql).toBe(DEFAULT_SQL);
    expect(s.activeTabId).toBe(s.tabs[0].id);
    expect(s.nextQueryNumber).toBe(2);
  });

  it('round-trips a valid state through sessionStorage', () => {
    writeTabsState('alice', sample());
    expect(readTabsState('alice')).toEqual(sample());
  });

  it('returns null when no state exists', () => {
    expect(readTabsState('alice')).toBeNull();
  });

  it('returns null (does not throw) on corrupt JSON', () => {
    sessionStorage.setItem(KEY, '{not json');
    expect(readTabsState('alice')).toBeNull();
  });

  it('rejects structurally invalid state (activeTabId references no tab)', () => {
    sessionStorage.setItem(
      KEY,
      JSON.stringify({
        version: 1,
        tabs: [{ id: 'a', label: 'Query 1', sql: '' }],
        activeTabId: 'missing',
        nextQueryNumber: 2,
      })
    );
    expect(readTabsState('alice')).toBeNull();
  });

  it('rejects an empty tabs array and a wrong version', () => {
    sessionStorage.setItem(KEY, JSON.stringify({ version: 1, tabs: [], activeTabId: 'a', nextQueryNumber: 2 }));
    expect(readTabsState('alice')).toBeNull();
    sessionStorage.setItem(KEY, JSON.stringify({ ...sample(), version: 2 }));
    expect(readTabsState('alice')).toBeNull();
  });

  it('is a no-op for an empty username', () => {
    writeTabsState('', sample());
    expect(sessionStorage.length).toBe(0);
    expect(readTabsState('')).toBeNull();
  });

  it('swallows storage failures rather than throwing', () => {
    const setItem = vi.fn(() => {
      throw new Error('QuotaExceededError');
    });
    const getItem = vi.fn(() => {
      throw new Error('SecurityError');
    });
    vi.stubGlobal('sessionStorage', {
      setItem,
      getItem,
      removeItem: vi.fn(),
    });

    expect(() => writeTabsState('alice', sample())).not.toThrow();
    expect(readTabsState('alice')).toBeNull();
    expect(setItem).toHaveBeenCalled();
    expect(getItem).toHaveBeenCalled();
  });

  describe('migrateDraftToTabs', () => {
    it('seeds tab 1 from a SPEC-040 draft and removes the old key', () => {
      sessionStorage.setItem(`${QUERY_DRAFT_STORAGE_PREFIX}alice`, 'SELECT migrated;');
      const state = migrateDraftToTabs('alice');
      expect(state).not.toBeNull();
      expect(state!.tabs).toHaveLength(1);
      expect(state!.tabs[0].sql).toBe('SELECT migrated;');
      // Old draft key is cleaned up.
      expect(sessionStorage.getItem(`${QUERY_DRAFT_STORAGE_PREFIX}alice`)).toBeNull();
    });

    it('returns null when there is no draft', () => {
      expect(migrateDraftToTabs('alice')).toBeNull();
    });

    it('returns null when a tabs state already exists (does not clobber)', () => {
      writeTabsState('alice', sample());
      sessionStorage.setItem(`${QUERY_DRAFT_STORAGE_PREFIX}alice`, 'stale');
      expect(migrateDraftToTabs('alice')).toBeNull();
      // The stale draft is left alone (only migrated when tabs are absent).
      expect(sessionStorage.getItem(`${QUERY_DRAFT_STORAGE_PREFIX}alice`)).toBe('stale');
    });
  });
});
