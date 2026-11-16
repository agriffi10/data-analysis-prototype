import type {ReactNode} from 'react';
import {RootLayout} from './components/RootLayout';
import {ProtectedLayout} from './components/ProtectedLayout';
import {areaOf, useLocation} from './lib/navigation';

/**
 * The chrome around every page: the header, the skip link and the outer boundary, then the sign-in
 * gate and the signed-in shell for a signed-in page.
 *
 * It decides by the address, through the area records, not by which page matched: the root layout
 * sits above the landing page and the not-found page as well as the signed-in pages. A path no area
 * claims (`/` and every unknown path) is public and renders bare, outside the gate; a path an area
 * claims renders inside the gate. The decision sits ABOVE the gate rather than inside
 * it, so the gate's hooks (the flags read, the notifications prefetch, the exploration eviction and
 * the catalog catch-up) run on signed-in pages only.
 *
 * Nothing between this and the shell may carry a React `key` that changes with the page: a key
 * remounts everything beneath it, and beneath it is the upload queue.
 *
 * @param props.children - The page.
 * @returns The chrome around the page.
 */
export function AppChrome({children}: {children: ReactNode}) {
  const {pathname} = useLocation();
  const signedIn = areaOf(pathname) !== null;
  return <RootLayout>{signedIn ? <ProtectedLayout>{children}</ProtectedLayout> : children}</RootLayout>;
}
