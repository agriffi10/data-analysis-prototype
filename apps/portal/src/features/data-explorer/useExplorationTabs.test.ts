import {act, renderHook} from '@testing-library/react';
import {beforeEach, describe, expect, it} from 'vitest';
import {useExplorationTabs} from './useExplorationTabs';
import {EXPLORATION_TABS_MAX, EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import type {ExplorationSource} from './dataExplorer.types';

const TABLE: ExplorationSource = {kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'};
const OTHER: ExplorationSource = {kind: 'table', spaceId: 'personal', database: 'alice', table: 'customers'};
const KEY = `${EXPLORATION_TABS_STORAGE_PREFIX}alice`;

const setup = (username = 'alice') => renderHook(() => useExplorationTabs(username));

beforeEach(() => {
  sessionStorage.clear();
});

describe('useExplorationTabs — opening and the cap (FR-008)', () => {
  it('starts with no tabs — an exploration needs a source and there is none to guess', () => {
    const {result} = setup();
    expect(result.current.tabs).toEqual([]);
    expect(result.current.activeTab).toBeNull();
    expect(result.current.activeTabId).toBe('');
  });

  it('opens a tab over a source, labels it from the source and activates it', () => {
    const {result} = setup();
    let id: string | null = null;
    act(() => {
      id = result.current.openTab(TABLE);
    });

    expect(id).toBeTruthy();
    expect(result.current.tabs).toHaveLength(1);
    expect(result.current.activeTabId).toBe(id);
    expect(result.current.activeTab?.label).toBe('orders');
    expect(result.current.activeTab?.exploration.source).toEqual(TABLE);
    // FR-001 AC4: an empty query description.
    expect(result.current.activeTab?.exploration.query).toEqual({
      filters: [],
      expression: null,
      ordering: [],
      grouping: null
    });
  });

  it('takes an explicit label over the source’s own name', () => {
    const {result} = setup();
    act(() => {
      result.current.openTab(TABLE, {label: 'Q3 orders'});
    });
    expect(result.current.activeTab?.label).toBe('Q3 orders');
  });

  it('returns NULL at the cap rather than throwing or silently dropping', () => {
    // The caller needs a value it can branch on to raise the cap dialog (SPEC-179).
    const {result} = setup();
    act(() => {
      for (let i = 0; i < EXPLORATION_TABS_MAX; i += 1) result.current.openTab(TABLE);
    });
    expect(result.current.tabs).toHaveLength(EXPLORATION_TABS_MAX);

    let refused: string | null = 'not-null';
    act(() => {
      refused = result.current.openTab(TABLE);
    });
    expect(refused).toBeNull();
    expect(result.current.tabs).toHaveLength(EXPLORATION_TABS_MAX);
  });
});

describe('useExplorationTabs — closing keeps the invariant (FR-008 AC4)', () => {
  it('activates the tab to the LEFT when the active one closes', () => {
    const {result} = setup();
    let first: string | null = null;
    let second: string | null = null;
    act(() => {
      first = result.current.openTab(TABLE);
      second = result.current.openTab(OTHER);
    });
    expect(result.current.activeTabId).toBe(second);

    act(() => result.current.closeTab(second as unknown as string));
    expect(result.current.activeTabId).toBe(first);
    expect(result.current.tabs).toHaveLength(1);
  });

  it('leaves a VALID state when the last tab closes', () => {
    // `activeTabId` must never dangle. Unlike the Query workspace this surface has a
    // legitimate zero-tab state, so the answer is '' rather than a kept-alive tab.
    const {result} = setup();
    let id: string | null = null;
    act(() => {
      id = result.current.openTab(TABLE);
    });
    act(() => result.current.closeTab(id as unknown as string));

    expect(result.current.tabs).toEqual([]);
    expect(result.current.activeTabId).toBe('');
    expect(result.current.activeTab).toBeNull();
  });

  it('ignores a close for an id that is not open', () => {
    const {result} = setup();
    act(() => {
      result.current.openTab(TABLE);
    });
    act(() => result.current.closeTab('nope'));
    expect(result.current.tabs).toHaveLength(1);
  });

  it('keeps the active tab when a DIFFERENT tab closes', () => {
    const {result} = setup();
    let first: string | null = null;
    act(() => {
      first = result.current.openTab(TABLE);
      result.current.openTab(OTHER);
    });
    const active = result.current.activeTabId;
    act(() => result.current.closeTab(first as unknown as string));
    expect(result.current.activeTabId).toBe(active);
  });
});

describe('useExplorationTabs — persistence (FR-008 AC2/AC3)', () => {
  it('persists under a prefix + username key and survives a reload', () => {
    const first = setup();
    act(() => {
      first.result.current.openTab(TABLE, {label: 'Q3 orders'});
    });
    expect(sessionStorage.getItem(KEY)).toBeTruthy();

    // A fresh hook is what a reload looks like to this module.
    const second = setup();
    expect(second.result.current.tabs).toHaveLength(1);
    expect(second.result.current.activeTab?.label).toBe('Q3 orders');
    expect(second.result.current.activeTab?.exploration.source).toEqual(TABLE);
  });

  it('keeps each user’s tabs separate', () => {
    const alice = setup('alice');
    act(() => {
      alice.result.current.openTab(TABLE);
    });
    expect(setup('bob').result.current.tabs).toEqual([]);
  });

  it('persists NOTHING for an empty username (the dev-unauth path)', () => {
    const {result} = setup('');
    act(() => {
      result.current.openTab(TABLE);
    });
    expect(result.current.tabs).toHaveLength(1);
    expect(sessionStorage.length).toBe(0);
  });

  it('discards a malformed document entirely rather than applying it partially', () => {
    // A half-restored exploration is worse than none: it renders SQL from a description
    // the user never built.
    const cases = [
      'not json at all',
      JSON.stringify({version: 2, tabs: [], activeTabId: '', nextExplorationNumber: 1}),
      JSON.stringify({version: 1, tabs: 'nope', activeTabId: '', nextExplorationNumber: 1}),
      // A tab whose exploration has no source.
      JSON.stringify({
        version: 1,
        tabs: [{id: 'a', label: 'x', exploration: {id: 'e'}, scannedByExecution: {}}],
        activeTabId: 'a',
        nextExplorationNumber: 2
      }),
      // A tab whose source has an unknown kind.
      JSON.stringify({
        version: 1,
        tabs: [
          {
            id: 'a',
            label: 'x',
            exploration: {
              id: 'e',
              source: {kind: 'elsewhere'},
              query: {filters: [], expression: null, ordering: [], grouping: null},
              presentation: {hiddenColumns: [], columnOrder: [], pinnedColumns: [], columnWidths: {}}
            },
            scannedByExecution: {}
          }
        ],
        activeTabId: 'a',
        nextExplorationNumber: 2
      }),
      // activeTabId referencing a tab that is not there — the invariant, violated.
      JSON.stringify({version: 1, tabs: [], activeTabId: 'ghost', nextExplorationNumber: 1})
    ];

    for (const raw of cases) {
      sessionStorage.setItem(KEY, raw);
      const {result} = setup();
      expect(result.current.tabs).toEqual([]);
      expect(result.current.activeTabId).toBe('');
    }
  });

  it('restores a well-formed document, so the discard test above is not vacuous', () => {
    // Without this pair, a validator that rejected EVERYTHING would pass every case above.
    const first = setup();
    act(() => {
      first.result.current.openTab(TABLE);
    });
    const stored = sessionStorage.getItem(KEY) as string;

    sessionStorage.clear();
    sessionStorage.setItem(KEY, stored);
    expect(setup().result.current.tabs).toHaveLength(1);
  });
});

describe('useExplorationTabs — cumulative cost (FR-007 AC2/AC3)', () => {
  it('accumulates bytes across distinct executions', () => {
    const {result} = setup();
    let id: string | null = null;
    act(() => {
      id = result.current.openTab(TABLE);
    });

    act(() => result.current.recordScan(id as unknown as string, 'exec-1', 1024));
    expect(result.current.activeTabBytesScanned).toBe(1024);

    act(() => result.current.recordScan(id as unknown as string, 'exec-2', 2048));
    expect(result.current.activeTabBytesScanned).toBe(3072);
  });

  it('adds NOTHING for a cache hit — the same execution recorded twice', () => {
    // FR-007 AC3, true by construction: the ledger is keyed by execution id, so a
    // re-rendered identical statement resolves to an id already present. A running total
    // would have to DETECT a cache hit, and a detector can be wrong in the direction that
    // overcharges the user.
    const {result} = setup();
    let id: string | null = null;
    act(() => {
      id = result.current.openTab(TABLE);
    });

    act(() => result.current.recordScan(id as unknown as string, 'exec-1', 1024));
    act(() => result.current.recordScan(id as unknown as string, 'exec-1', 1024));
    act(() => result.current.recordScan(id as unknown as string, 'exec-1', 1024));

    expect(result.current.activeTabBytesScanned).toBe(1024);
  });

  it('counts a zero-byte execution without turning the total into NaN', () => {
    const {result} = setup();
    let id: string | null = null;
    act(() => {
      id = result.current.openTab(TABLE);
    });
    act(() => result.current.recordScan(id as unknown as string, 'exec-1', 0));
    expect(result.current.activeTabBytesScanned).toBe(0);
  });

  it('keeps each tab’s ledger to itself', () => {
    const {result} = setup();
    let first: string | null = null;
    act(() => {
      first = result.current.openTab(TABLE);
      result.current.openTab(OTHER);
    });

    act(() => result.current.recordScan(first as unknown as string, 'exec-1', 500));
    // The second tab is the active one and has run nothing.
    expect(result.current.activeTabBytesScanned).toBe(0);

    act(() => result.current.setActiveTab(first as unknown as string));
    expect(result.current.activeTabBytesScanned).toBe(500);
  });
});

describe('useExplorationTabs — editing the active exploration', () => {
  it('replaces only the active tab’s exploration', () => {
    const {result} = setup();
    let first: string | null = null;
    act(() => {
      first = result.current.openTab(TABLE);
      result.current.openTab(OTHER);
    });

    act(() =>
      result.current.updateActiveExploration((exploration) => ({
        ...exploration,
        query: {...exploration.query, expression: 'qty > 0'}
      }))
    );

    expect(result.current.activeTab?.exploration.query.expression).toBe('qty > 0');
    const untouched = result.current.tabs.find((t) => t.id === first);
    expect(untouched?.exploration.query.expression).toBeNull();
  });

  it('is a no-op with no tabs open', () => {
    const {result} = setup();
    act(() => result.current.updateActiveExploration((e) => e));
    expect(result.current.tabs).toEqual([]);
  });
});
