import {useSyncExternalStore} from 'react';

/** Project breakpoint thresholds; mirror `src/index.css` `@theme`. */
export const TABLET_MIN = 900;
export const DESKTOP_MIN = 1300;

export type BreakpointState = {isMobile: boolean; isTablet: boolean; isDesktop: boolean};

// Shared, stable snapshots — `useSyncExternalStore` requires getSnapshot to
// return a referentially-stable value while the tier is unchanged (a fresh
// object every call would loop). Window state is global, so one module cache
// serves every hook instance.
const DESKTOP: BreakpointState = {isMobile: false, isTablet: false, isDesktop: true};
const TABLET: BreakpointState = {isMobile: false, isTablet: true, isDesktop: false};
const MOBILE: BreakpointState = {isMobile: true, isTablet: false, isDesktop: false};

function canMatch(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function';
}

function subscribe(callback: () => void): () => void {
  if (!canMatch()) return () => {};
  const tablet = window.matchMedia(`(min-width: ${TABLET_MIN}px)`);
  const desktop = window.matchMedia(`(min-width: ${DESKTOP_MIN}px)`);
  tablet.addEventListener('change', callback);
  desktop.addEventListener('change', callback);
  return () => {
    tablet.removeEventListener('change', callback);
    desktop.removeEventListener('change', callback);
  };
}

function getSnapshot(): BreakpointState {
  if (!canMatch()) return DESKTOP;
  if (window.matchMedia(`(min-width: ${DESKTOP_MIN}px)`).matches) return DESKTOP;
  if (window.matchMedia(`(min-width: ${TABLET_MIN}px)`).matches) return TABLET;
  return MOBILE;
}

/**
 * Current viewport tier as booleans, kept live via `matchMedia`. **For
 * mount-gating decisions only** (e.g. not instantiating Monaco on phones,
 * mounting the mobile nav drawer) — never for styling, which is Tailwind's
 * `tablet:` / `desktop:` variants. SSR-safe (defaults to
 * desktop when `matchMedia` is unavailable).
 *
 * @example
 * const {isMobile} = useBreakpoint();
 * return isMobile ? <MobileNav /> : <DesktopRail />;
 */
export function useBreakpoint(): BreakpointState {
  return useSyncExternalStore(subscribe, getSnapshot, () => DESKTOP);
}

/**
 * Convenience: `true` when the viewport is below the tablet breakpoint (<900px).
 *
 * @example
 * const isMobile = useIsMobile();
 */
export function useIsMobile(): boolean {
  return useBreakpoint().isMobile;
}
