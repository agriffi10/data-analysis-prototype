import {createContext, useContext, useEffect, type ReactNode} from 'react';

export type NavRailContextValue = {
  railContent: ReactNode;
  setRailContent: (node: ReactNode) => void;
};

/** The mobile nav drawer's contextual rail slot; provided by `NavRailProvider`. */
export const NavRailContext = createContext<NavRailContextValue | null>(null);

/** Read the current contextual rail content (Header/AppNavDrawer consumer). */
export function useNavRailContent(): ReactNode {
  return useContext(NavRailContext)?.railContent ?? null;
}

/**
 * Register contextual rail content into the mobile `AppNavDrawer`'s contextual
 * slot for as long as the calling page is mounted (cleared on unmount). No-op
 * outside a `NavRailProvider`.
 *
 * Pass a **memoized** node — an inline `<Rail />` recreated every render would
 * re-fire the registration effect on each render.
 *
 * @example
 * const rail = useMemo(() => <Sidebar spaces={spaces} />, [spaces]);
 * useProvideNavRail(rail);
 */
export function useProvideNavRail(node: ReactNode): void {
  const ctx = useContext(NavRailContext);
  const setRailContent = ctx?.setRailContent;
  useEffect(() => {
    if (!setRailContent) return;
    setRailContent(node);
    return () => setRailContent(null);
  }, [setRailContent, node]);
}
