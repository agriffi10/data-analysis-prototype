import {createContext, useContext} from 'react';
import type {NavigateOptions, NavigationType, NavLocation, To} from './navigation.types';

/** What the seam provides: where the user is, how they got there, and the way to move. */
export type Seam = {
  location: NavLocation;
  navigationType: NavigationType;
  navigate: (to: To, options?: NavigateOptions) => void;
  /** `navigate` for a user's click on a link, which a page that is leaving never drops. */
  follow: (to: To, options?: NavigateOptions) => void;
};

/** The seam, provided by `NavigationProvider`. */
export const SeamContext = createContext<Seam | null>(null);

/**
 * The seam, from inside a `NavigationProvider`.
 *
 * @returns The seam.
 * @throws Error when no `NavigationProvider` is above the caller.
 */
export function useSeam(): Seam {
  const seam = useContext(SeamContext);
  if (!seam) throw new Error('navigation was used outside the NavigationProvider');
  return seam;
}
