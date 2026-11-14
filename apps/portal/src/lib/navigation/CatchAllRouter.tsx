'use client';
import {useMemo, type ReactNode} from 'react';
import {Router, createPath, type NavigationType as RouterNavigationType, type Navigator} from 'react-router';
import {InCatchAllContext, useSeam} from './seamContext';

/**
 * react-router inside the catch-all, as a matcher the seam feeds.
 *
 * Its location and navigation type are the seam's, and its navigator sends every push and replace
 * back through the seam. It cannot own its own history, as the migration guide's `BrowserRouter`
 * does: measured on Next 16.4.6, once the catch-all's chunk is cached, every navigation from an App
 * Router page back to a catch-all page rendered the 404, because a `BrowserRouter` reads
 * `window.location` as it mounts, before Next has written the new address.
 *
 * @param props.children - The route table.
 * @returns The router.
 */
export function CatchAllRouter({children}: {children: ReactNode}) {
  const {location, navigationType, navigate} = useSeam();
  const navigator = useMemo<Navigator>(
    () => ({
      createHref: (to) => (typeof to === 'string' ? to : createPath(to)),
      go: (delta) => window.history.go(delta),
      push: (to, state) => navigate(typeof to === 'string' ? to : createPath(to), {state}),
      replace: (to, state) => navigate(typeof to === 'string' ? to : createPath(to), {replace: true, state})
    }),
    [navigate]
  );
  return (
    <InCatchAllContext.Provider value={true}>
      <Router
        location={location}
        navigationType={navigationType as RouterNavigationType}
        navigator={navigator}>
        {children}
      </Router>
    </InCatchAllContext.Provider>
  );
}
