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
  return {version: 1, tabs: [], activeTabId: ''};
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

// A stored document is the ONE untrusted input this model has, and "well-formed enough to
// restore" is not the same as "renderable". These check the fields the renderer branches
// on, because a filter with an unrecognised operator renders `"a" undefined 'x'` — invalid
// SQL, sent to StartQueryExecution rather than refused — and a `grouping` of `{}` throws a
// raw TypeError out of the renderer instead of an ExplorationRenderError.
const FILTER_OPERATORS = new Set(['=', '<>', '>', '>=', '<', '<=', 'isNull', 'isNotNull']);
const AGGREGATE_FUNCTIONS = new Set(['COUNT', 'SUM', 'AVG', 'MIN', 'MAX']);

function isValidFilter(value: unknown): boolean {
  if (typeof value !== 'object' || value === null) return false;
  const filter = value as Record<string, unknown>;
  if (typeof filter.column !== 'string') return false;
  if (typeof filter.operator !== 'string' || !FILTER_OPERATORS.has(filter.operator)) return false;
  if (filter.value !== undefined && typeof filter.value !== 'string') return false;
  return filter.valueKind === undefined || filter.valueKind === 'string' || filter.valueKind === 'number';
}

function isValidSortEntry(value: unknown): boolean {
  if (typeof value !== 'object' || value === null) return false;
  const entry = value as Record<string, unknown>;
  return (
    typeof entry.column === 'string' &&
    (entry.direction === 'asc' || entry.direction === 'desc') &&
    typeof entry.priority === 'number' &&
    Number.isFinite(entry.priority)
  );
}

function isValidGrouping(value: unknown): boolean {
  if (value === null) return true;
  if (typeof value !== 'object') return false;
  const grouping = value as Record<string, unknown>;
  if (!Array.isArray(grouping.columns) || !grouping.columns.every((c) => typeof c === 'string')) return false;
  if (!Array.isArray(grouping.aggregates)) return false;
  return grouping.aggregates.every((a) => {
    if (typeof a !== 'object' || a === null) return false;
    const aggregate = a as Record<string, unknown>;
    return (
      typeof aggregate.fn === 'string' && AGGREGATE_FUNCTIONS.has(aggregate.fn) && typeof aggregate.column === 'string'
    );
  });
}

function isValidLedger(value: unknown): boolean {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  // The VALUES matter as much as the shape: `tabBytesScanned` sums them, so one string
  // turns a total into `"0x"` and one NaN turns it into NaN — breaking the never-NaN
  // invariant FR-007 AC4 exists to hold, from the only untrusted input this model has.
  return Object.values(value).every((bytes) => typeof bytes === 'number' && Number.isFinite(bytes));
}

function isValidExploration(value: unknown): boolean {
  if (typeof value !== 'object' || value === null) return false;
  const exploration = value as Record<string, unknown>;
  if (typeof exploration.id !== 'string') return false;
  if (!isValidSource(exploration.source)) return false;

  const query = exploration.query as Record<string, unknown> | undefined;
  if (typeof query !== 'object' || query === null) return false;
  if (!Array.isArray(query.filters) || !query.filters.every(isValidFilter)) return false;
  if (!Array.isArray(query.ordering) || !query.ordering.every(isValidSortEntry)) return false;
  if (query.expression !== null && typeof query.expression !== 'string') return false;
  if (!isValidGrouping(query.grouping)) return false;

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

  const tabsOk = state.tabs.every((t) => {
    if (typeof t !== 'object' || t === null) return false;
    const tab = t as Record<string, unknown>;
    return (
      typeof tab.id === 'string' &&
      typeof tab.label === 'string' &&
      isValidExploration(tab.exploration) &&
      isValidLedger(tab.scannedByExecution)
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
