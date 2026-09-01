import {useSyncExternalStore} from 'react';
import type {EffectiveTheme, ThemePreference} from './theme.types';

/**
 * Where the preference is kept.
 *
 * `public/theme-init.js` reads the same key with the same vocabulary before the first paint
 * and cannot import it; `useTheme.test.ts` reads that file and asserts the two agree.
 */
export const THEME_STORAGE_KEY = 'portal-theme';

const DARK_QUERY = '(prefers-color-scheme: dark)';

function canMatch(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function';
}

function systemTheme(): EffectiveTheme {
  return canMatch() && window.matchMedia(DARK_QUERY).matches ? 'dark' : 'light';
}

/**
 * The stored preference, or `system` for anything else.
 *
 * Wrapped because `localStorage` throws outright in some privacy modes — reading it is not a
 * safe operation, and an app that will not boot in a private window is a worse outcome than
 * one that forgets a preference.
 *
 * @returns What the user chose, defaulting to `system`.
 */
function readPreference(): ThemePreference {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return stored === 'light' || stored === 'dark' ? stored : 'system';
  } catch {
    return 'system';
  }
}

let preference: ThemePreference = typeof window === 'undefined' ? 'system' : readPreference();
let snapshot = {preference, effective: preference === 'system' ? systemTheme() : preference};
const listeners = new Set<() => void>();

/**
 * Recompute the snapshot, paint the attribute, and wake every subscriber.
 *
 * The snapshot object is rebuilt only when something in it changed, because
 * `useSyncExternalStore` compares by identity and a fresh object per read loops forever.
 *
 * Nothing here re-mounts anything: the theme is an attribute on `<html>` plus a re-render of
 * whoever subscribed, so a switch cannot cost a component its state.
 */
function publish(): void {
  const effective = preference === 'system' ? systemTheme() : preference;
  if (snapshot.preference === preference && snapshot.effective === effective) return;
  snapshot = {preference, effective};
  applyTheme(effective);
  for (const listener of listeners) listener();
}

/**
 * Stamp the effective theme on `<html>`, the same two writes `theme-init.js` makes.
 *
 * @param effective - The theme to paint.
 */
function applyTheme(effective: EffectiveTheme): void {
  if (typeof document === 'undefined') return;
  document.documentElement.setAttribute('data-theme', effective);
  document.documentElement.style.colorScheme = effective;
}

let bound = false;

/**
 * Bind the OS-preference listener and paint the attribute, once per page.
 *
 * The listener is bound for the life of the page rather than per subscriber: one shared
 * `change` handler removed when the FIRST component unmounts would leave every other
 * subscriber deaf to the OS, and `addEventListener` deduplicates the reference anyway.
 *
 * It is bound unconditionally, and `publish` is what makes `light` and `dark` ignore it: an OS
 * change recomputes to the same effective theme and returns without waking anyone.
 */
function bind(): void {
  if (bound) return;
  bound = true;
  applyTheme(snapshot.effective);
  if (canMatch()) window.matchMedia(DARK_QUERY).addEventListener('change', publish);
}

function subscribe(listener: () => void): () => void {
  bind();
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * Choose the theme. Applies immediately and persists, per browser.
 *
 * @param next - Light, Dark, or System.
 */
export function setThemePreference(next: ThemePreference): void {
  preference = next;
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, next);
  } catch {
    // The choice still holds for this session; only its memory is lost.
  }
  publish();
}

/**
 * The current theme preference, what it resolves to, and how to change it.
 *
 * A module store read through `useSyncExternalStore` rather than a Context provider, so that
 * switching the theme re-renders the subscribers and nothing else — a provider whose value
 * changed would re-render its whole subtree, and every component that had to unmount to do it.
 *
 * @returns The chosen preference, the theme actually painted, and the setter.
 *
 * @example
 * const {effective, setPreference} = useTheme();
 */
export function useTheme(): {
  preference: ThemePreference;
  effective: EffectiveTheme;
  setPreference: (next: ThemePreference) => void;
} {
  const current = useSyncExternalStore(
    subscribe,
    () => snapshot,
    () => snapshot
  );
  return {...current, setPreference: setThemePreference};
}

/**
 * Reset the module store. Tests only — a module store outlives a render.
 *
 * @returns Nothing.
 */
export function resetThemeForTest(): void {
  preference = readPreference();
  snapshot = {preference, effective: preference === 'system' ? systemTheme() : preference};
  bound = false;
}
