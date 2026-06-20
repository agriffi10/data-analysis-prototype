import {
  QUERY_TABS_STORAGE_PREFIX,
  QUERY_DRAFT_STORAGE_PREFIX,
  DEFAULT_SQL,
} from './query.constants';
import type { QueryTab, QueryTabsState } from './query.types';

// SPEC-041: per-user, current-session persistence of the multi-tab editor state.
// Supersedes SPEC-040's single draft (queryDraft.ts). As in SPEC-040 all access
// goes through this wrapper so a disabled/quota-exceeded sessionStorage degrades
// to "not persisted" rather than crashing the editor, and an empty username
// (unauthenticated dev paths) is a no-op.

function tabsKey(username: string): string | null {
  if (!username) return null;
  return `${QUERY_TABS_STORAGE_PREFIX}${username}`;
}

// A fresh, valid id. crypto.randomUUID is available in the browser and in the
// Node test runtime; the catch keeps a single missing-crypto environment from
// throwing (degrades to a timestamp-free pseudo-id).
let fallbackSeq = 0;
function newId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    fallbackSeq += 1;
    return `tab-${fallbackSeq}`;
  }
}

// A brand-new session: one tab "Query 1" (seeded with the boilerplate), with the
// counter pointing at the next blank tab's number.
export function initialTabsState(): QueryTabsState {
  const id = newId();
  return {
    version: 1,
    tabs: [{ id, label: 'Query 1', sql: DEFAULT_SQL }],
    activeTabId: id,
    nextQueryNumber: 2,
  };
}

// Structural validation — a corrupt/old/foreign blob must never crash the editor
// (FR-006). Returns the parsed state only when it is internally consistent.
function isValidTabsState(value: unknown): value is QueryTabsState {
  if (typeof value !== 'object' || value === null) return false;
  const s = value as Record<string, unknown>;
  if (s.version !== 1) return false;
  if (!Array.isArray(s.tabs) || s.tabs.length < 1) return false;
  if (typeof s.activeTabId !== 'string') return false;
  if (typeof s.nextQueryNumber !== 'number') return false;
  const tabsOk = s.tabs.every((t) => {
    if (typeof t !== 'object' || t === null) return false;
    const tab = t as Record<string, unknown>;
    return (
      typeof tab.id === 'string' &&
      typeof tab.label === 'string' &&
      typeof tab.sql === 'string' &&
      (tab.savedQueryId === undefined || typeof tab.savedQueryId === 'string')
    );
  });
  if (!tabsOk) return false;
  const tabs = s.tabs as QueryTab[];
  return tabs.some((t) => t.id === s.activeTabId);
}

// Returns the persisted tabs state, or null if none exists / it is invalid /
// storage is unavailable.
export function readTabsState(username: string): QueryTabsState | null {
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

// Persists the tabs state under the per-user key. No-op on failure / empty user.
export function writeTabsState(username: string, state: QueryTabsState): void {
  const key = tabsKey(username);
  if (!key) return;
  try {
    sessionStorage.setItem(key, JSON.stringify(state));
  } catch {
    // Degrade to not-persisted; never surface a storage error to the editor.
  }
}

// SPEC-040 → 041 one-time migration: if a SPEC-040 single draft exists and no
// tabs state does yet, seed tab 1's SQL from it and remove the old draft key.
// Returns the seeded state, or null when there is nothing to migrate.
export function migrateDraftToTabs(username: string): QueryTabsState | null {
  if (!username) return null;
  if (readTabsState(username)) return null; // tabs already own this user
  const draftKey = `${QUERY_DRAFT_STORAGE_PREFIX}${username}`;
  let draft: string | null;
  try {
    draft = sessionStorage.getItem(draftKey);
  } catch {
    return null;
  }
  if (!draft) return null;

  const state = initialTabsState();
  state.tabs[0].sql = draft;
  try {
    sessionStorage.removeItem(draftKey);
  } catch {
    // Best-effort cleanup; the migration still proceeds.
  }
  return state;
}
