import type {ReactNode} from 'react';
import {serverRouteGate} from '../../../server/featureFlags';
import {UnavailableMount} from '../UnavailableMount';

/**
 * The server's gate for `/explore`: the "not available" page when the server holds a flag
 * set with this area's flag off, and the page otherwise, which then decides in the browser as it
 * always has.
 *
 * It reads no session and no `params`, does no I/O and never throws, and it carries no `key`, so
 * moving between areas never remounts the shell above it.
 *
 * @param props.children - The area's page.
 * @returns The page, or the unavailable page in its place.
 */
export default function ExploreLayout({children}: {children: ReactNode}) {
  const gate = serverRouteGate('/explore');
  return gate.kind === 'unavailable' ? (
    <UnavailableMount
      flag={gate.flag}
      fallback={gate.fallback}
    />
  ) : (
    children
  );
}
