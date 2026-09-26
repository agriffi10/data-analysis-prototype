// Persists the protected URL a signed-out user tried to reach, so they can be
// returned to it after the Hosted UI login round-trip. sessionStorage is used
// because the OAuth redirect is a full-page navigation — in-memory router state
// would not survive it. All access is guarded: if sessionStorage is unavailable
// (e.g. private browsing), callers fall back to the default route.

const RETURN_PATH_KEY = 'portal.returnPath';

/** Stores the path to return to after the auth round-trip. */
export function setReturnPath(path: string): void {
  try {
    sessionStorage.setItem(RETURN_PATH_KEY, path);
  } catch {
    // Non-fatal — login simply lands on the default route.
  }
}

/**
 * Sets the return path only when none is already stored. Used when starting
 * sign-in/sign-up so a fresh auth round-trip lands on a default route (e.g.
 * /files) without clobbering a specific protected path captured by the auth gate.
 */
export function setReturnPathIfAbsent(path: string): void {
  try {
    if (!sessionStorage.getItem(RETURN_PATH_KEY)) {
      sessionStorage.setItem(RETURN_PATH_KEY, path);
    }
  } catch {
    // Non-fatal — login simply lands on the default route.
  }
}

/**
 * Reads the stored return path without clearing it. Returns null when none is set.
 *
 * Separate from {@link clearReturnPath} so a render can read it: StrictMode renders twice and
 * keeps the second render, so a read that cleared would leave that render with nothing.
 */
export function peekReturnPath(): string | null {
  try {
    return sessionStorage.getItem(RETURN_PATH_KEY) || null;
  } catch {
    return null;
  }
}

/** Clears the stored return path once it has been used — from an effect, not a render. */
export function clearReturnPath(): void {
  try {
    sessionStorage.removeItem(RETURN_PATH_KEY);
  } catch {
    // Non-fatal — the path is simply offered again.
  }
}
