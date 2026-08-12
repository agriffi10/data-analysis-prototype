import {QUERY_SAVED_QUERY_SPACE_STORAGE_PREFIX} from './query.constants';

// The last space the user loaded saved queries from, remembered for the session only.
// Degrade-safe on the same pattern as `useResultsPageSize` and `useEditorLayout`: a
// sessionStorage that is disabled, full or throwing degrades to "not remembered" rather
// than breaking the drawer. Nothing here validates the id against the current space
// list — that is `useSavedQuerySpace`'s job, because a stored space the user has since
// left is a fallback and not a corrupt value.

function storageKey(username: string | null): string | null {
  if (!username) return null;
  return `${QUERY_SAVED_QUERY_SPACE_STORAGE_PREFIX}${username}`;
}

/**
 * Reads the space id last chosen in this session.
 *
 * @param username - The signed-in user; a falsy one has no key and no stored value.
 * @returns The stored id, or null when absent, empty or unreadable.
 */
export function readSavedQuerySpaceId(username: string | null): string | null {
  const key = storageKey(username);
  if (!key) return null;
  try {
    const raw = sessionStorage.getItem(key);
    return raw === null || raw === '' ? null : raw;
  } catch {
    return null;
  }
}

/**
 * Remembers the chosen space id for this session, best effort.
 *
 * @param username - The signed-in user; a falsy one is a no-op.
 * @param spaceId - The `QuerySpace.id` to remember.
 * @returns Nothing; a storage failure is swallowed and the choice still applies in-tree.
 */
export function writeSavedQuerySpaceId(username: string | null, spaceId: string): void {
  const key = storageKey(username);
  if (!key) return;
  try {
    sessionStorage.setItem(key, spaceId);
  } catch {
    // Storage unavailable — the choice still applies for this render tree.
  }
}
