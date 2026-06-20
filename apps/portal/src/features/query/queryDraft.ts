import { QUERY_DRAFT_STORAGE_PREFIX } from './query.constants';

// SPEC-040: per-user, current-session persistence of the un-run query editor
// draft. All access goes through this wrapper so QueryWorkspace stays clean and
// a disabled/quota-exceeded sessionStorage degrades to "not persisted" rather
// than crashing the editor. An empty username (unauthenticated dev paths) is a
// no-op — there is no per-user key to write under.

function draftKey(username: string): string | null {
  if (!username) return null;
  return `${QUERY_DRAFT_STORAGE_PREFIX}${username}`;
}

// Returns the persisted draft, or null if none exists / storage is unavailable.
export function readQueryDraft(username: string): string | null {
  const key = draftKey(username);
  if (!key) return null;
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

// Persists the draft under the per-user key. No-op on failure (storage disabled,
// quota exceeded) or empty username.
export function writeQueryDraft(username: string, sql: string): void {
  const key = draftKey(username);
  if (!key) return;
  try {
    sessionStorage.setItem(key, sql);
  } catch {
    // Degrade to not-persisted; never surface a storage error to the editor.
  }
}

// Removes the persisted draft (e.g. after Clear). No-op on failure / empty user.
export function clearQueryDraft(username: string): void {
  const key = draftKey(username);
  if (!key) return;
  try {
    sessionStorage.removeItem(key);
  } catch {
    // No-op on failure.
  }
}
