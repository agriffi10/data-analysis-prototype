// Persists the protected URL a signed-out user tried to reach, so they can be
// returned to it after the Hosted UI login round-trip. sessionStorage is used
// because the OAuth redirect is a full-page navigation — in-memory router state
// would not survive it (FR-004). All access is guarded: if sessionStorage is
// unavailable (e.g. private browsing), callers fall back to the default route.

const RETURN_PATH_KEY = 'portal.returnPath';

export function setReturnPath(path: string): void {
  try {
    sessionStorage.setItem(RETURN_PATH_KEY, path);
  } catch {
    // Non-fatal — login simply lands on the default route.
  }
}

/** Reads and clears the stored return path. Returns null when none is set. */
export function takeReturnPath(): string | null {
  try {
    const path = sessionStorage.getItem(RETURN_PATH_KEY);
    if (path) sessionStorage.removeItem(RETURN_PATH_KEY);
    return path;
  } catch {
    return null;
  }
}
