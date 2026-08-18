import {useMemo, useState, type ReactNode} from 'react';
import {NavRailContext} from './navRailContext';

/**
 * Bridges a page's contextual rail (Files → Spaces list, Query → schema rail)
 * to the Header-owned mobile `AppNavDrawer`, which renders in a different part
 * of the tree. Wrap the app shell (Header + routed page) so a page can register
 * its rail via `useProvideNavRail` and the drawer can read it.
 *
 * @example
 * <NavRailProvider>
 *   <Header />
 *   <Outlet />
 * </NavRailProvider>
 */
export function NavRailProvider({children}: {children: ReactNode}) {
  const [railContent, setRailContent] = useState<ReactNode>(null);
  const value = useMemo(() => ({railContent, setRailContent}), [railContent]);
  return <NavRailContext.Provider value={value}>{children}</NavRailContext.Provider>;
}
