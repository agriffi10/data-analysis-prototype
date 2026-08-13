import {EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import type {ExplorationTab, ExplorationTabsState} from './dataExplorer.types';

// Per-user, current-session persistence of the Data Explorer's tabs. All access goes
// through this wrapper so a disabled or quota-exceeded sessionStorage degrades to "not
// persisted" rather than crashing the page, and an empty username (the dev-unauth path)
// is a no-op. The split mirrors `features/query/queryTabs.ts`, which is the precedent
// this whole model follows.

function tabsKey(username: string): string | null {
  if (!username) return null;
  return `${EXPLORATION_TABS_STORAGE_PREFIX}${username}`;
}

/**
 * A brand-new session: no tabs at all.
 *
 * Deliberately unlike `initialTabsState()` in the Query workspace, which seeds "Query 1"
 * with boilerplate SQL. An exploration cannot exist without a source, and there is no
 * table to guess — SPEC-179's empty state asks the user to pick one.
 *
 * @returns An empty, valid tabs state.
 */
export function initialExplorationTabsState(): ExplorationTabsState {
  return {version: 1, tabs: [], activeTabId: '', nextExplorationNumber: 1};
}

function isValidSource(value: unknown): boolean {
  if (typeof value !== 'object' || value === null) return false;
  const source = value as Record<string, unknown>;
  if (source.kind === 'table') {
    return (
      typeof source.spaceId === 'string' && typeof source.database === 'string' && typeof source.table === 'string'
    );
  }
  if (source.kind === 'sql') {
    return typeof source.body === 'string' && typeof source.label === 'string';
  }
  return false;
}

function isValidExploration(value: unknown): boolean {
  if (typeof value !== 'object' || value === null) return false;
  const exploration = value as Record<string, unknown>;
  if (typeof exploration.id !== 'string') return false;
  if (!isValidSource(exploration.source)) return false;

  const query = exploration.query as Record<string, unknown> | undefined;
  if (typeof query !== 'object' || query === null) return false;
  if (!Array.isArray(query.filters) || !Array.isArray(query.ordering)) return false;
  if (query.expression !== null && typeof query.expression !== 'string') return false;
  if (query.grouping !== null && typeof query.grouping !== 'object') return false;

  const presentation = exploration.presentation as Record<string, unknown> | undefined;
  if (typeof presentation !== 'object' || presentation === null) return false;
  return (
    Array.isArray(presentation.hiddenColumns) &&
    Array.isArray(presentation.columnOrder) &&
    Array.isArray(presentation.pinnedColumns) &&
    typeof presentation.columnWidths === 'object' &&
    presentation.columnWidths !== null
  );
}

// Structural validation — a corrupt, old or foreign blob must never crash the page, and
// must never be PARTIALLY applied. A half-restored exploration is worse than none: it
// renders SQL from a description the user never built.
function isValidTabsState(value: unknown): value is ExplorationTabsState {
  if (typeof value !== 'object' || value === null) return false;
  const state = value as Record<string, unknown>;
  if (state.version !== 1) return false;
  if (!Array.isArray(state.tabs)) return false;
  if (typeof state.activeTabId !== 'string') return false;
  if (typeof state.nextExplorationNumber !== 'number') return false;

  const tabsOk = state.tabs.every((t) => {
    if (typeof t !== 'object' || t === null) return false;
    const tab = t as Record<string, unknown>;
    return (
      typeof tab.id === 'string' &&
      typeof tab.label === 'string' &&
      isValidExploration(tab.exploration) &&
      typeof tab.scannedByExecution === 'object' &&
      tab.scannedByExecution !== null &&
      !Array.isArray(tab.scannedByExecution)
    );
  });
  if (!tabsOk) return false;

  // The invariant `activeTabId` always references an existing tab — with the empty state
  // as the one legal exception, since there is nothing for it to reference.
  const tabs = state.tabs as ExplorationTab[];
  if (tabs.length === 0) return state.activeTabId === '';
  return tabs.some((t) => t.id === state.activeTabId);
}

/** Returns the persisted tabs state, or null if none exists / it is invalid / storage is unavailable. */
export function readExplorationTabsState(username: string): ExplorationTabsState | null {
  const key = tabsKey(username);
  if (!key) return null;
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isValidTabsState(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/** Persists the tabs state under the per-user key. No-op on failure / empty user. */
export function writeExplorationTabsState(username: string, state: ExplorationTabsState): void {
  const key = tabsKey(username);
  if (!key) return;
  try {
    sessionStorage.setItem(key, JSON.stringify(state));
  } catch {
    // Degrade to not-persisted; never surface a storage error to the page.
  }
}

/**
 * Total bytes this tab has scanned, across every DISTINCT execution it has run.
 *
 * Summed from a map keyed by execution id rather than accumulated as a running total,
 * which is what makes FR-007's "a cache hit adds nothing" true by construction: a
 * re-rendered identical statement resolves to an id already in the map, so recording it
 * again changes no total. A running sum would have to DETECT a cache hit, and a detector
 * can be wrong in the direction that overcharges.
 *
 * @param tab - The tab to total.
 * @returns Bytes scanned; 0 for a tab that has run nothing.
 */
export function tabBytesScanned(tab: ExplorationTab): number {
  return Object.values(tab.scannedByExecution).reduce((total, bytes) => total + bytes, 0);
}
