import {useCallback, useState} from 'react';

// One shared preference for BOTH left rails (Files Sidebar + Query
// SchemaBrowser), persisted per browser so the choice survives reloads and carries
// across the two pages.
export const RAIL_COLLAPSED_STORAGE_KEY = 'portal.rail.collapsed';

export type UseRailCollapsedResult = {
  collapsed: boolean;
  toggle: () => void;
  setCollapsed: (value: boolean) => void;
};

// All localStorage access is guarded: a disabled / quota-exceeded / unavailable
// store degrades to not-persisted (default = expanded) rather than throwing —
// mirroring the app's other guarded-storage helpers (e.g. lib/returnPath).
function readCollapsed(): boolean {
  try {
    return localStorage.getItem(RAIL_COLLAPSED_STORAGE_KEY) === 'true';
  } catch {
    return false;
  }
}

function writeCollapsed(value: boolean): void {
  try {
    localStorage.setItem(RAIL_COLLAPSED_STORAGE_KEY, value ? 'true' : 'false');
  } catch {
    // Non-fatal — the choice simply isn't persisted this session.
  }
}

/**
 * The collapsed/expanded state of the authenticated left rail, backed by a single
 * shared `localStorage` key so it is remembered per browser and applies to whichever
 * rail (Files or Query) the user is looking at. Defaults to expanded when nothing is
 * stored or storage is unavailable.
 */
export function useRailCollapsed(): UseRailCollapsedResult {
  const [collapsed, setCollapsedState] = useState<boolean>(readCollapsed);

  const setCollapsed = useCallback((value: boolean) => {
    setCollapsedState(value);
    writeCollapsed(value);
  }, []);

  const toggle = useCallback(() => {
    setCollapsedState((prev) => {
      const next = !prev;
      writeCollapsed(next);
      return next;
    });
  }, []);

  return {collapsed, toggle, setCollapsed};
}
