import {areaOf, type AreaRecord} from '../../lib/navigation';

/**
 * The name a path the catch-all serves is titled by as it mounts, as the route table decides what
 * it shows: the product's alone for the landing page, none for an area the catch-all serves, whose
 * view titles itself a commit late on a first visit as before, and "Not Found" for every other path.
 *
 * @param pathname - The committed path.
 * @param records - The area records in force.
 * @returns The name for `usePageTitleOnMount`, or null to leave the title to the view.
 */
export function catchAllPageName(pathname: string, records: readonly AreaRecord[]): string | null {
  if (pathname === '/') return '';
  return areaOf(pathname, records)?.router === 'catch-all' ? null : 'Not Found';
}
