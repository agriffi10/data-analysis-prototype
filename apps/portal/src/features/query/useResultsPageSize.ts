import {useCallback, useState} from 'react';
import {
  DEFAULT_RESULTS_PAGE_SIZE,
  MAX_RESULTS_PAGE_SIZE,
  MIN_RESULTS_PAGE_SIZE,
  QUERY_RESULTS_PAGE_SIZE_STORAGE_PREFIX
} from './query.constants';

export type UseResultsPageSizeResult = {
  /** Effective page size — always an integer in [MIN, MAX]. */
  pageSize: number;
  /** Clamps to [MIN, MAX], applies, and persists (best-effort) for the session. */
  setPageSize: (value: number) => void;
};

/** Coerce any candidate into a valid page size; null when it isn't a finite integer. */
export function clampPageSize(value: number): number | null {
  if (!Number.isInteger(value)) return null;
  return Math.min(MAX_RESULTS_PAGE_SIZE, Math.max(MIN_RESULTS_PAGE_SIZE, value));
}

function storageKey(username: string | null): string | null {
  if (!username) return null;
  return `${QUERY_RESULTS_PAGE_SIZE_STORAGE_PREFIX}${username}`;
}

// Storage access is wrapped so a disabled/quota-exceeded sessionStorage
// degrades to "not persisted" rather than crashing the workspace (FR-005).
function readStoredPageSize(username: string | null): number | null {
  const key = storageKey(username);
  if (!key) return null;
  try {
    const raw = sessionStorage.getItem(key);
    if (raw === null) return null;
    const parsed = Number(raw);
    // A stored value is only trusted verbatim — out-of-range/malformed falls
    // back to the default rather than being silently clamped (FR-005).
    return Number.isInteger(parsed) && parsed >= MIN_RESULTS_PAGE_SIZE && parsed <= MAX_RESULTS_PAGE_SIZE
      ? parsed
      : null;
  } catch {
    return null;
  }
}

function writeStoredPageSize(username: string | null, pageSize: number): void {
  const key = storageKey(username);
  if (!key) return;
  try {
    sessionStorage.setItem(key, String(pageSize));
  } catch {
    // Storage unavailable — the choice still applies for this render tree.
  }
}

/**
 * the workspace-global "Rows per page" value — one shared value for
 * every result tab, session-persisted per user (sessionStorage, defensive
 * read), defaulting to DEFAULT_RESULTS_PAGE_SIZE. Owned once at the workspace
 * level so all result tabs re-page together when it changes (FR-004).
 */
export function useResultsPageSize(username: string | null): UseResultsPageSizeResult {
  const [pageSize, setPageSizeState] = useState<number>(
    () => readStoredPageSize(username) ?? DEFAULT_RESULTS_PAGE_SIZE
  );

  const setPageSize = useCallback(
    (value: number) => {
      // Non-integer input is rejected outright (the control reverts to the
      // last valid value, FR-003); out-of-range integers are clamped.
      const next = clampPageSize(value);
      if (next === null) return;
      setPageSizeState((current) => {
        if (next === current) return current;
        writeStoredPageSize(username, next);
        return next;
      });
    },
    [username]
  );

  return {pageSize, setPageSize};
}
