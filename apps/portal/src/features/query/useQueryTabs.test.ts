import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';
import { useQueryTabs } from './useQueryTabs';
import { readTabsState } from './queryTabs';
import { QUERY_TABS_MAX } from './query.constants';

beforeEach(() => sessionStorage.clear());

describe('useQueryTabs', () => {
  it('opens with a single Query 1 on a fresh session', () => {
    const { result } = renderHook(() => useQueryTabs('alice'));
    expect(result.current.tabs).toHaveLength(1);
    expect(result.current.tabs[0].label).toBe('Query 1');
    expect(result.current.activeTab.id).toBe(result.current.tabs[0].id);
  });

  it('hands out monotonic Query N labels, never reusing across a close', () => {
    const { result } = renderHook(() => useQueryTabs('alice'));

    act(() => void result.current.openTab()); // Query 2
    act(() => void result.current.openTab()); // Query 3
    expect(result.current.tabs.map((t) => t.label)).toEqual([
      'Query 1',
      'Query 2',
      'Query 3',
    ]);

    const q2 = result.current.tabs[1].id;
    act(() => result.current.closeTab(q2));
    expect(result.current.tabs.map((t) => t.label)).toEqual([
      'Query 1',
      'Query 3',
    ]);

    act(() => void result.current.openTab()); // must be Query 4, not a reused 2
    expect(result.current.tabs.map((t) => t.label)).toEqual([
      'Query 1',
      'Query 3',
      'Query 4',
    ]);
  });

  it('blank + tab is empty and becomes active', () => {
    const { result } = renderHook(() => useQueryTabs('alice'));
    act(() => void result.current.openTab());
    expect(result.current.activeTab.label).toBe('Query 2');
    expect(result.current.activeTab.sql).toBe('');
  });

  it('opens a named tab verbatim without consuming a Query N number (FR-009)', () => {
    const { result } = renderHook(() => useQueryTabs('alice'));
    act(() =>
      void result.current.openTab({
        label: 'Monthly revenue',
        sql: 'SELECT * FROM rev;',
        savedQueryId: 'sq-1',
      }),
    );
    const active = result.current.activeTab;
    expect(active.label).toBe('Monthly revenue');
    expect(active.sql).toBe('SELECT * FROM rev;');
    expect(active.savedQueryId).toBe('sq-1');

    // The counter was not incremented: the next blank tab is still Query 2.
    act(() => void result.current.openTab());
    expect(result.current.activeTab.label).toBe('Query 2');
  });

  it('isolates edits to the active tab', () => {
    const { result } = renderHook(() => useQueryTabs('alice'));
    act(() => result.current.setActiveSql('SELECT first;'));
    const first = result.current.tabs[0].id;

    act(() => void result.current.openTab());
    act(() => result.current.setActiveSql('SELECT second;'));

    act(() => result.current.setActiveTab(first));
    expect(result.current.activeTab.sql).toBe('SELECT first;');
    expect(result.current.tabs[1].sql).toBe('SELECT second;');
  });

  it('refuses to open past QUERY_TABS_MAX, returning null', () => {
    const { result } = renderHook(() => useQueryTabs('alice'));
    // Start at 1 tab; open up to the cap.
    for (let i = result.current.tabs.length; i < QUERY_TABS_MAX; i++) {
      act(() => void result.current.openTab());
    }
    expect(result.current.tabs).toHaveLength(QUERY_TABS_MAX);

    let returned: string | null = 'sentinel';
    act(() => {
      returned = result.current.openTab();
    });
    expect(returned).toBeNull();
    expect(result.current.tabs).toHaveLength(QUERY_TABS_MAX);
  });

  it('never closes the last remaining tab', () => {
    const { result } = renderHook(() => useQueryTabs('alice'));
    const only = result.current.tabs[0].id;
    act(() => result.current.closeTab(only));
    expect(result.current.tabs).toHaveLength(1);
  });

  it('activates the left neighbor when the active tab is closed', () => {
    const { result } = renderHook(() => useQueryTabs('alice'));
    act(() => void result.current.openTab()); // Query 2 (active)
    act(() => void result.current.openTab()); // Query 3 (active)
    const [q1, q2, q3] = result.current.tabs.map((t) => t.id);
    expect(result.current.activeTabId).toBe(q3);

    act(() => result.current.setActiveTab(q2));
    act(() => result.current.closeTab(q2));
    // Left neighbor (Query 1) becomes active.
    expect(result.current.activeTabId).toBe(q1);
  });

  it('clearActive empties only the active tab', () => {
    const { result } = renderHook(() => useQueryTabs('alice'));
    act(() => result.current.setActiveSql('SELECT keep;'));
    act(() => void result.current.openTab());
    act(() => result.current.setActiveSql('SELECT clearme;'));

    act(() => result.current.clearActive());
    expect(result.current.activeTab.sql).toBe('');
    expect(result.current.tabs[0].sql).toBe('SELECT keep;');
  });

  it('clearActive resets the tab name and unlinks any saved query', () => {
    const { result } = renderHook(() => useQueryTabs('alice'));
    // Open a saved-query tab: named label + saved-query link.
    act(() =>
      void result.current.openTab({
        label: 'Revenue',
        sql: 'SELECT 1',
        savedQueryId: 'sq-1',
      }),
    );
    expect(result.current.activeTab.label).toBe('Revenue');
    expect(result.current.activeTab.savedQueryId).toBe('sq-1');

    act(() => result.current.clearActive());
    // Back to a fresh blank tab: empty SQL, a default "Query N" label, no link.
    expect(result.current.activeTab.sql).toBe('');
    expect(result.current.activeTab.label).toMatch(/^Query \d+$/);
    expect(result.current.activeTab.savedQueryId).toBeUndefined();
  });

  it('persists across remount (restore from sessionStorage)', () => {
    const first = renderHook(() => useQueryTabs('alice'));
    act(() => void first.result.current.openTab({ label: 'Saved', sql: 'X' }));
    expect(readTabsState('alice')?.tabs).toHaveLength(2);
    first.unmount();

    // A fresh mount restores the exact set + active tab.
    const second = renderHook(() => useQueryTabs('alice'));
    expect(second.result.current.tabs.map((t) => t.label)).toEqual([
      'Query 1',
      'Saved',
    ]);
    expect(second.result.current.activeTab.label).toBe('Saved');
  });
});
