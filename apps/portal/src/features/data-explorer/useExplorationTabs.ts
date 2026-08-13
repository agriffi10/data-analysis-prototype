import {useEffect, useMemo, useState} from 'react';
import {EXPLORATION_TABS_MAX} from './dataExplorer.constants';
import {explorationSourceLabel, newExploration, newExplorationId} from './exploration';
import {
  initialExplorationTabsState,
  readExplorationTabsState,
  tabBytesScanned,
  writeExplorationTabsState
} from './explorationTabs';
import type {Exploration, ExplorationSource, ExplorationTab, ExplorationTabsState} from './dataExplorer.types';

export type OpenExplorationOpts = {
  /** Verbatim label; omit to take the source's own name. */
  label?: string;
};

export type UseExplorationTabsResult = {
  tabs: ExplorationTab[];
  /** '' when there are no tabs. */
  activeTabId: string;
  /** Null when there are no tabs — SPEC-179 renders the empty state. */
  activeTab: ExplorationTab | null;
  /** Opens a tab over a source and returns its id, or null at the cap (caller shows the dialog). */
  openTab: (source: ExplorationSource, opts?: OpenExplorationOpts) => string | null;
  closeTab: (id: string) => void;
  setActiveTab: (id: string) => void;
  /** Replaces the active tab's exploration — how every query and presentation edit lands. */
  updateActiveExploration: (update: (exploration: Exploration) => Exploration) => void;
  /** Records what one execution scanned, keyed by execution id so a repeat is free. */
  recordScan: (tabId: string, queryExecutionId: string, bytesScanned: number) => void;
  /** Bytes scanned by the active tab across its lifetime; 0 with no tabs. */
  activeTabBytesScanned: number;
};

/**
 * Owns the Data Explorer's tabs and their sessionStorage persistence (SPEC-178 FR-008).
 *
 * Mirrors `useQueryTabs` — an ordered list, one active tab, a soft cap enforced by
 * refusal — with two deliberate differences. There is no seeded first tab, because an
 * exploration needs a source and there is no table to guess; and a tab carries its own
 * cost ledger, because cost is this feature's through-line.
 *
 * No component is delivered here (SPEC-179 mounts the first one).
 *
 * @param username - Whose tabs these are; '' persists nothing (the dev-unauth path).
 * @returns The tabs, the active one, and the actions over them.
 */
export function useExplorationTabs(username: string): UseExplorationTabsResult {
  const [state, setState] = useState<ExplorationTabsState>(
    () => readExplorationTabsState(username) ?? initialExplorationTabsState()
  );

  useEffect(() => {
    writeExplorationTabsState(username, state);
  }, [username, state]);

  const activeTab = useMemo(
    () => state.tabs.find((t) => t.id === state.activeTabId) ?? null,
    [state.tabs, state.activeTabId]
  );

  const openTab = (source: ExplorationSource, opts: OpenExplorationOpts = {}): string | null => {
    // Checked against this render's state so the caller can raise the cap dialog; the
    // updater re-checks so a double-open can never exceed the cap.
    if (state.tabs.length >= EXPLORATION_TABS_MAX) return null;
    const id = newExplorationId();
    setState((s) => {
      if (s.tabs.length >= EXPLORATION_TABS_MAX) return s;
      const named = opts.label !== undefined;
      const tab: ExplorationTab = {
        id,
        label: named ? (opts.label as string) : explorationSourceLabel(source),
        exploration: newExploration(source),
        scannedByExecution: {}
      };
      return {
        ...s,
        tabs: [...s.tabs, tab],
        activeTabId: id,
        nextExplorationNumber: s.nextExplorationNumber + 1
      };
    });
    return id;
  };

  const closeTab = (id: string) =>
    setState((s) => {
      const index = s.tabs.findIndex((t) => t.id === id);
      if (index === -1) return s;
      const tabs = s.tabs.filter((t) => t.id !== id);
      // The invariant: `activeTabId` always references an existing tab. Closing the last
      // one leaves '' rather than a dangling id — unlike the Query workspace, this
      // surface has a legitimate zero-tab state.
      if (tabs.length === 0) return {...s, tabs, activeTabId: ''};
      let activeTabId = s.activeTabId;
      if (id === s.activeTabId) {
        // Prefer the tab to the left, else the one that slid into its place.
        const neighbor = index > 0 ? index - 1 : 0;
        activeTabId = tabs[Math.min(neighbor, tabs.length - 1)].id;
      }
      return {...s, tabs, activeTabId};
    });

  const setActiveTab = (id: string) => setState((s) => (s.tabs.some((t) => t.id === id) ? {...s, activeTabId: id} : s));

  const updateActiveExploration = (update: (exploration: Exploration) => Exploration) =>
    setState((s) => ({
      ...s,
      tabs: s.tabs.map((t) => (t.id === s.activeTabId ? {...t, exploration: update(t.exploration)} : t))
    }));

  const recordScan = (tabId: string, queryExecutionId: string, bytesScanned: number) =>
    setState((s) => {
      const tab = s.tabs.find((t) => t.id === tabId);
      // Already recorded: this is the cache hit, and it must change nothing. Returning the
      // same state also keeps the effect that calls this from looping.
      if (!tab || tab.scannedByExecution[queryExecutionId] === bytesScanned) return s;
      return {
        ...s,
        tabs: s.tabs.map((t) =>
          t.id === tabId ? {...t, scannedByExecution: {...t.scannedByExecution, [queryExecutionId]: bytesScanned}} : t
        )
      };
    });

  return {
    tabs: state.tabs,
    activeTabId: state.activeTabId,
    activeTab,
    openTab,
    closeTab,
    setActiveTab,
    updateActiveExploration,
    recordScan,
    activeTabBytesScanned: activeTab ? tabBytesScanned(activeTab) : 0
  };
}
