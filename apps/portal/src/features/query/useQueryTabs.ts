import { useEffect, useMemo, useState } from 'react';
import { QUERY_TABS_MAX } from './query.constants';
import type { QueryTab, QueryTabsState } from './query.types';
import {
  readTabsState,
  writeTabsState,
  migrateDraftToTabs,
  initialTabsState,
} from './queryTabs';

export type OpenTabOpts = {
  label?: string; // verbatim label (saved query / table action); omit for a blank "Query N"
  sql?: string; // pre-filled editor text; omit for an empty tab
  savedQueryId?: string; // links the tab to a saved query (SPEC-043); inert here
};

export type UseQueryTabsResult = {
  tabs: QueryTab[];
  activeTabId: string;
  activeTab: QueryTab;
  setActiveSql: (sql: string) => void;
  setActiveTab: (id: string) => void;
  setActiveSavedQueryId: (id: string | undefined) => void;
  // SPEC-043: patch the active tab's label/savedQueryId together (used when a
  // save links + relabels the active tab in one step).
  setActiveTabMeta: (meta: { label?: string; savedQueryId?: string }) => void;
  // SPEC-043 FR-007: clear the link on every tab pointing at a deleted saved
  // query (the tabs keep their label/SQL; a later Save creates a new record).
  unlinkSavedQuery: (savedQueryId: string) => void;
  // Opens a tab and returns its id, or null when already at QUERY_TABS_MAX
  // (the caller surfaces the FR-008 "close a tab first" dialog).
  openTab: (opts?: OpenTabOpts) => string | null;
  closeTab: (id: string) => void;
  clearActive: () => void;
};

// SPEC-041: owns the QueryTabsState + sessionStorage persistence. The seed order
// is: restore persisted tabs → else migrate a SPEC-040 draft → else a fresh
// single "Query 1". State is read once at mount and persisted on every change.
export function useQueryTabs(username: string): UseQueryTabsResult {
  const [state, setState] = useState<QueryTabsState>(
    () =>
      readTabsState(username) ?? migrateDraftToTabs(username) ?? initialTabsState(),
  );

  // Persist on change (writeTabsState no-ops for an empty/dev-unauth username).
  useEffect(() => {
    writeTabsState(username, state);
  }, [username, state]);

  const activeTab = useMemo(
    () => state.tabs.find((t) => t.id === state.activeTabId) ?? state.tabs[0],
    [state.tabs, state.activeTabId],
  );

  const setActiveSql = (sql: string) =>
    setState((s) => ({
      ...s,
      tabs: s.tabs.map((t) => (t.id === s.activeTabId ? { ...t, sql } : t)),
    }));

  const setActiveTab = (id: string) =>
    setState((s) =>
      s.tabs.some((t) => t.id === id) ? { ...s, activeTabId: id } : s,
    );

  const setActiveSavedQueryId = (id: string | undefined) =>
    setState((s) => ({
      ...s,
      tabs: s.tabs.map((t) =>
        t.id === s.activeTabId ? { ...t, savedQueryId: id } : t,
      ),
    }));

  const setActiveTabMeta = (meta: { label?: string; savedQueryId?: string }) =>
    setState((s) => ({
      ...s,
      tabs: s.tabs.map((t) =>
        t.id === s.activeTabId ? { ...t, ...meta } : t,
      ),
    }));

  const unlinkSavedQuery = (savedQueryId: string) =>
    setState((s) => ({
      ...s,
      tabs: s.tabs.map((t) =>
        t.savedQueryId === savedQueryId ? { ...t, savedQueryId: undefined } : t,
      ),
    }));

  const openTab = (opts: OpenTabOpts = {}): string | null => {
    // Cap guard against the current render's state; the updater re-checks so a
    // double-open can never exceed the cap.
    if (state.tabs.length >= QUERY_TABS_MAX) return null;
    const id =
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID()
        : `tab-${state.nextQueryNumber}-${state.tabs.length}`;
    setState((s) => {
      if (s.tabs.length >= QUERY_TABS_MAX) return s;
      const named = opts.label !== undefined;
      const tab: QueryTab = {
        id,
        label: named ? opts.label! : `Query ${s.nextQueryNumber}`,
        sql: opts.sql ?? '',
        savedQueryId: opts.savedQueryId,
      };
      return {
        ...s,
        tabs: [...s.tabs, tab],
        activeTabId: id,
        // Only blank "Query N" tabs consume a number; named tabs do not.
        nextQueryNumber: named ? s.nextQueryNumber : s.nextQueryNumber + 1,
      };
    });
    return id;
  };

  const closeTab = (id: string) =>
    setState((s) => {
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
      return { ...s, tabs, activeTabId };
    });

  // SPEC-040 Clear, scoped to the active tab: empty its SQL and reset the tab back
  // to a fresh blank "Query N" — drop any saved-query link and relabel (consuming a
  // query number, like a brand-new tab). Other tabs are untouched.
  const clearActive = () =>
    setState((s) => ({
      ...s,
      tabs: s.tabs.map((t) =>
        t.id === s.activeTabId
          ? {
              ...t,
              sql: '',
              label: `Query ${s.nextQueryNumber}`,
              savedQueryId: undefined,
            }
          : t,
      ),
      nextQueryNumber: s.nextQueryNumber + 1,
    }));

  return {
    tabs: state.tabs,
    activeTabId: state.activeTabId,
    activeTab,
    setActiveSql,
    setActiveTab,
    setActiveSavedQueryId,
    setActiveTabMeta,
    unlinkSavedQuery,
    openTab,
    closeTab,
    clearActive,
  };
}
