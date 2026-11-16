import {decodePath} from '../address';
import {matchPath} from '../matchPath';
import type {AreaRecord} from './area.types';
import {filesArea} from './files';
import {notificationsArea} from './notifications';
import {helpArea} from './help';
import {queryArea} from './query';
import {exploreArea} from './explore';
import {connectionsArea} from './connections';
import {dataQualityArea} from './data-quality';

export type {AreaName, AreaRecord} from './area.types';

/**
 * Every signed-in area and the paths it serves, each served by its pages under
 * `src/app/(signed-in)/`. A path one of them claims is signed in; every other path is public.
 */
export const AREAS: readonly AreaRecord[] = [
  filesArea,
  notificationsArea,
  helpArea,
  queryArea,
  exploreArea,
  connectionsArea,
  dataQualityArea
];

/**
 * The area that claims a path, matched whole and case-sensitively on the path decoded segment by
 * segment.
 *
 * Decoded, so an encoded spelling of an area's path (`/fil%65s`) is claimed as that area and a
 * signed-out user is sent to `/`. Next does not decode a static segment and answers such a spelling
 * with the not-found page, so claiming it costs a not-found inside the shell for an address nobody
 * builds; matching undecoded instead would leave the gate claiming less than a page might serve.
 *
 * @param pathname - The path to look up.
 * @param records - The records to read; {@link AREAS} unless a test passes a fixture.
 * @returns The record, or null for a public path: `/`, or one no area claims.
 */
export function areaOf(pathname: string, records: readonly AreaRecord[] = AREAS): AreaRecord | null {
  const decoded = decodePath(pathname);
  return records.find((record) => record.paths.some((pattern) => matchPath(pattern, decoded))) ?? null;
}
