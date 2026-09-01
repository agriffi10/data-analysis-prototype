type Listener = (event: MediaQueryListEvent) => void;

let prefersDark = false;
const listeners = new Set<Listener>();

/** What `(prefers-color-scheme: dark)` currently answers in this test. */
export function prefersDarkScheme(): boolean {
  return prefersDark;
}

/**
 * Register a `change` listener against the emulated OS preference.
 *
 * @param listener - Called when {@link setPrefersDark} flips the preference.
 * @returns Nothing.
 */
export function addSchemeListener(listener: Listener): void {
  listeners.add(listener);
}

/**
 * Drop a `change` listener.
 *
 * @param listener - The listener to remove.
 * @returns Nothing.
 */
export function removeSchemeListener(listener: Listener): void {
  listeners.delete(listener);
}

/**
 * Change the OS colour-scheme preference and fire `change`, as a real browser would.
 *
 * jsdom has no OS preference of its own, so a test that needs one drives it through here
 * rather than re-stubbing `matchMedia` — which is how a stub that answers one query correctly
 * and every other one by accident gets written.
 *
 * @param next - Whether `(prefers-color-scheme: dark)` should now match.
 * @returns Nothing.
 */
export function setPrefersDark(next: boolean): void {
  if (prefersDark === next) return;
  prefersDark = next;
  for (const listener of listeners) listener({matches: next} as MediaQueryListEvent);
}

/**
 * Restore the suite's default: the light scheme, with nothing listening.
 *
 * @returns Nothing.
 */
export function resetColorScheme(): void {
  prefersDark = false;
  listeners.clear();
}
