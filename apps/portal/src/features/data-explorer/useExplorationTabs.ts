import {useEffect, useMemo, useRef, useState} from 'react';
import {EXPLORATION_TABS_MAX} from './dataExplorer.constants';
import {emptyQueryHistory, explorationSourceLabel, newExploration, newExplorationId} from './exploration';
import {
  initialExplorationTabsState,
  readExplorationTabsState,
  tabBytesScanned,
  writeExplorationTabsState
} from './explorationTabs';
import type {
  AwaitingRun,
  Exploration,
  ExplorationSource,
  ExplorationTab,
  ExplorationTabsState
} from './dataExplorer.types';
import type {QueryColumn} from '../catalog/catalog.types';
import type {SavedQueryLink} from '../saved-queries/savedQueries.types';

export type OpenExplorationOpts = {
  /** Verbatim label; omit to take the source's own name. */
  label?: string;
  /** A query and presentation to open with — a reopened saved view's — instead of empty ones. */
  seed?: Pick<Exploration, 'query' | 'presentation'>;
  /** Opens the tab held: its statement renders but does not run until asked. */
  awaitingRun?: AwaitingRun;
  /** The saved query the tab was opened from, so a re-save replaces it. */
  savedQuery?: SavedQueryLink;
};

export type UseExplorationTabsResult = {
  tabs: ExplorationTab[];
  /** '' when there are no tabs. */
  activeTabId: string;
  /** Null when there are no tabs — the shell renders the empty state. */
  activeTab: ExplorationTab | null;
  /** Opens a tab over a source and returns its id, or null at the cap (caller shows the dialog). */
  openTab: (source: ExplorationSource, opts?: OpenExplorationOpts) => string | null;
  closeTab: (id: string) => void;
  setActiveTab: (id: string) => void;
  /** Replaces the active tab's exploration — how every query and presentation edit lands. */
  updateActiveExploration: (update: (exploration: Exploration) => Exploration) => void;
  /**
   * Replaces ONE tab, by id — how a query edit and its history entry land together.
   *
   * Named rather than active because a description and the history it pushes have to move
   * in the same update: written through two calls, a tab switch between them would file
   * the entry against whichever tab is active by then.
   */
  updateTab: (tabId: string, update: (tab: ExplorationTab) => ExplorationTab) => void;
  /** Records what one execution scanned, keyed by execution id so a repeat is free. */
  recordScan: (tabId: string, queryExecutionId: string, bytesScanned: number) => void;
  /**
   * Links a tab to the `.sql` file a save just wrote.
   *
   * By id rather than "the active tab", for the reason `updateTab` is: the write is async
   * and the user may have switched tabs while it was in flight, and linking the wrong tab
   * would make its next re-save replace a file it has nothing to do with.
   */
  setTabSavedQuery: (tabId: string, link: SavedQueryLink) => void;
  /** Ends a held tab's hold, dropping the field rather than blanking it: a blank reads back as held. */
  releaseHold: (tabId: string) => void;
  /**
   * Remembers a `sql` tab's source columns, from an execution with no grouping.
   *
   * By id, for `updateTab`'s reason. A table tab is left alone — its columns are Glue's — and an
   * equal list changes nothing, so the effect that reports every such execution cannot loop.
   */
  setTabSourceColumns: (tabId: string, columns: QueryColumn[]) => void;
  /** Bytes scanned by the active tab across its lifetime; 0 with no tabs. */
  activeTabBytesScanned: number;
};

function sameColumns(stored: QueryColumn[] | undefined, columns: QueryColumn[]): boolean {
  return (
    stored !== undefined &&
    stored.length === columns.length &&
    stored.every((column, index) => column.name === columns[index].name && column.type === columns[index].type)
  );
}

/**
 * Owns the Data Explorer's tabs and their sessionStorage persistence.
 *
 * Mirrors `useQueryTabs` — an ordered list, one active tab, a soft cap enforced by
 * refusal — with two deliberate differences. There is no seeded first tab, because an
 * exploration needs a source and there is no table to guess; and a tab carries its own
 * cost ledger, because cost is this feature's through-line.
 *
 * No component is delivered here; the shell mounts the first one.
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

  // How many tabs are open, readable SYNCHRONOUSLY. `openTab` has to decide its return
  // value before the updater runs, and this render's `state` is stale the moment a second
  // open happens in the same tick — three rapid opens two below the cap would each see
  // room, each return an id, and only two tabs would appear, so the caller would believe
  // it opened three and raise no cap dialog. A plausible shape for a multi-select "open
  // these tables".
  const openCount = useRef(state.tabs.length);
  useEffect(() => {
    openCount.current = state.tabs.length;
  }, [state.tabs.length]);

  const openTab = (source: ExplorationSource, opts: OpenExplorationOpts = {}): string | null => {
    if (openCount.current >= EXPLORATION_TABS_MAX) return null;
    openCount.current += 1;
    const id = newExplorationId();
    // The updater re-checks anyway: the ref is the synchronous view, the state is the
    // authority, and only the state can be trusted to have applied every prior open.
    setState((s) => {
      if (s.tabs.length >= EXPLORATION_TABS_MAX) return s;
      const named = opts.label !== undefined;
      const fresh = newExploration(source);
      const tab: ExplorationTab = {
        id,
        label: named ? (opts.label as string) : explorationSourceLabel(source),
        exploration: opts.seed ? {...fresh, query: opts.seed.query, presentation: opts.seed.presentation} : fresh,
        scannedByExecution: {},
        history: emptyQueryHistory(),
        ...(opts.awaitingRun && {awaitingRun: opts.awaitingRun}),
        ...(opts.savedQuery && {savedQuery: opts.savedQuery})
      };
      return {
        ...s,
        tabs: [...s.tabs, tab],
        activeTabId: id
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

  const updateTab = (tabId: string, update: (tab: ExplorationTab) => ExplorationTab) =>
    setState((s) => ({...s, tabs: s.tabs.map((t) => (t.id === tabId ? update(t) : t))}));

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

  const releaseHold = (tabId: string) =>
    setState((s) => ({
      ...s,
      tabs: s.tabs.map((t) => {
        if (t.id !== tabId || !t.awaitingRun) return t;
        const released = {...t};
        delete released.awaitingRun;
        return released;
      })
    }));

  const setTabSavedQuery = (tabId: string, link: SavedQueryLink) =>
    setState((s) => ({...s, tabs: s.tabs.map((t) => (t.id === tabId ? {...t, savedQuery: link} : t))}));

  const setTabSourceColumns = (tabId: string, columns: QueryColumn[]) =>
    setState((s) => {
      const tab = s.tabs.find((t) => t.id === tabId);
      if (!tab || tab.exploration.source.kind !== 'sql' || sameColumns(tab.sqlSourceColumns, columns)) return s;
      const recorded = columns.map(({name, type}) => ({name, type}));
      return {...s, tabs: s.tabs.map((t) => (t.id === tabId ? {...t, sqlSourceColumns: recorded} : t))};
    });

  return {
    tabs: state.tabs,
    activeTabId: state.activeTabId,
    activeTab,
    openTab,
    closeTab,
    setActiveTab,
    updateActiveExploration,
    updateTab,
    recordScan,
    setTabSavedQuery,
    releaseHold,
    setTabSourceColumns,
    activeTabBytesScanned: activeTab ? tabBytesScanned(activeTab) : 0
  };
}
