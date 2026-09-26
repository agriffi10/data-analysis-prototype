import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {QUERY_TABS_MAX} from './query.constants';
import type {QueryTab, QueryTabsState} from './query.types';
import type {SavedQueryLink} from '../saved-queries/savedQueries.types';
import {readTabsState, writeTabsState, migrateDraftToTabs, initialTabsState} from './queryTabs';

export type OpenTabOpts = {
  /** Verbatim label (saved query / table action); omit for a blank "Query N". */
  label?: string;
  /** Pre-filled editor text; omit for an empty tab. */
  sql?: string;
  /** Links the tab to the saved query it was opened from; inert here. */
  savedQuery?: SavedQueryLink;
};

export type UseQueryTabsResult = {
  tabs: QueryTab[];
  activeTabId: string;
  activeTab: QueryTab;
  setActiveSql: (sql: string) => void;
  setActiveTab: (id: string) => void;
  setActiveSavedQuery: (link: SavedQueryLink | undefined) => void;
  /** Patches the active tab's label/link together (a save links + relabels in one step). */
  setActiveTabMeta: (meta: {label?: string; savedQuery?: SavedQueryLink}) => void;
  /** Clears the link on every tab pointing at a deleted saved query (tabs keep their label/SQL). */
  unlinkSavedQuery: (key: string) => void;
  /** Opens a tab and returns its id, or null when already at QUERY_TABS_MAX (caller shows the tab-limit dialog). */
  openTab: (opts?: OpenTabOpts) => string | null;
  closeTab: (id: string) => void;
  clearActive: () => void;
};

/**
 * Owns the QueryTabsState + sessionStorage persistence. Seed order: restore
 * persisted tabs → else migrate a legacy single draft → else a fresh single
 * "Query 1". State is read once at mount and persisted on every change.
 *
 * `stateRef` is the synchronous source of truth — every write goes through `update`, from event
 * handlers and effects only, never render — so an open that lands after an await, from a closure
 * a later render has replaced, still counts the tabs opened since.
 */
export function useQueryTabs(username: string): UseQueryTabsResult {
  const [state, setState] = useState<QueryTabsState>(
    () => readTabsState(username) ?? migrateDraftToTabs(username) ?? initialTabsState()
  );
  const stateRef = useRef(state);
  const update = useCallback((updater: (prev: QueryTabsState) => QueryTabsState) => {
    stateRef.current = updater(stateRef.current);
    setState(stateRef.current);
  }, []);

  // Persist on change (writeTabsState no-ops for an empty/dev-unauth username).
  useEffect(() => {
    writeTabsState(username, state);
  }, [username, state]);

  const activeTab = useMemo(
    () => state.tabs.find((t) => t.id === state.activeTabId) ?? state.tabs[0],
    [state.tabs, state.activeTabId]
  );

  const setActiveSql = (sql: string) =>
    update((s) => ({
      ...s,
      tabs: s.tabs.map((t) => (t.id === s.activeTabId ? {...t, sql} : t))
    }));

  const setActiveTab = (id: string) => update((s) => (s.tabs.some((t) => t.id === id) ? {...s, activeTabId: id} : s));

  const setActiveSavedQuery = (link: SavedQueryLink | undefined) =>
    update((s) => ({
      ...s,
      tabs: s.tabs.map((t) => (t.id === s.activeTabId ? {...t, savedQuery: link} : t))
    }));

  const setActiveTabMeta = (meta: {label?: string; savedQuery?: SavedQueryLink}) =>
    update((s) => ({
      ...s,
      tabs: s.tabs.map((t) => (t.id === s.activeTabId ? {...t, ...meta} : t))
    }));

  // Keyed by the OBJECT KEY, which is a saved query's identity now that there is no id.
  const unlinkSavedQuery = (key: string) =>
    update((s) => ({
      ...s,
      tabs: s.tabs.map((t) => (t.savedQuery?.key === key ? {...t, savedQuery: undefined} : t))
    }));

  const openTab = (opts: OpenTabOpts = {}): string | null => {
    const current = stateRef.current;
    if (current.tabs.length >= QUERY_TABS_MAX) return null;
    const id =
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID()
        : `tab-${current.nextQueryNumber}-${current.tabs.length}`;
    update((s) => {
      const named = opts.label !== undefined;
      const tab: QueryTab = {
        id,
        label: named ? opts.label! : `Query ${s.nextQueryNumber}`,
        sql: opts.sql ?? '',
        savedQuery: opts.savedQuery
      };
      return {
        ...s,
        tabs: [...s.tabs, tab],
        activeTabId: id,
        // Only blank "Query N" tabs consume a number; named tabs do not.
        nextQueryNumber: named ? s.nextQueryNumber : s.nextQueryNumber + 1
      };
    });
    return id;
  };

  const closeTab = (id: string) =>
    update((s) => {
      if (s.tabs.length <= 1) return s; // always >= 1 tab
      const idx = s.tabs.findIndex((t) => t.id === id);
      if (idx === -1) return s;
      const tabs = s.tabs.filter((t) => t.id !== id);
      let activeTabId = s.activeTabId;
      if (id === s.activeTabId) {
        // Prefer the tab to the left, else the right (now at index 0).
        const neighbor = idx > 0 ? idx - 1 : 0;
        activeTabId = tabs[Math.min(neighbor, tabs.length - 1)].id;
      }
      return {...s, tabs, activeTabId};
    });

  // Clear, scoped to the active tab: empty its SQL and reset the tab back to
  // a fresh blank "Query N" — drop any saved-query link and relabel
  // (consuming a query number, like a brand-new tab). Other tabs untouched.
  const clearActive = () =>
    update((s) => ({
      ...s,
      tabs: s.tabs.map((t) =>
        t.id === s.activeTabId
          ? {
              ...t,
              sql: '',
              label: `Query ${s.nextQueryNumber}`,
              savedQuery: undefined
            }
          : t
      ),
      nextQueryNumber: s.nextQueryNumber + 1
    }));

  return {
    tabs: state.tabs,
    activeTabId: state.activeTabId,
    activeTab,
    setActiveSql,
    setActiveTab,
    setActiveSavedQuery,
    setActiveTabMeta,
    unlinkSavedQuery,
    openTab,
    closeTab,
    clearActive
  };
}
