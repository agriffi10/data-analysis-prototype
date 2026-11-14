import {createContext, useContext} from 'react';
import {matchPath} from '../matchPath';
import type {AreaRecord, AreaRouter} from './area.types';
import {filesArea} from './files';
import {notificationsArea} from './notifications';
import {helpArea} from './help';
import {queryArea} from './query';
import {exploreArea} from './explore';
import {connectionsArea} from './connections';
import {dataQualityArea} from './data-quality';

export type {AreaName, AreaRecord, AreaRouter} from './area.types';

/**
 * Every signed-in area, and which router serves it. An area move flips its own record to `'app'`
 * and adds its pages; nothing else names which router serves what.
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
 * The records as the seam, the chrome and the table read them. Nothing in production provides
 * it; the test App Router does, so a test can serve an area from either router whatever is on disk.
 */
export const AreaRecordsContext = createContext<readonly AreaRecord[]>(AREAS);

/** The records in force here: the context's, which in production are {@link AREAS}. */
export function useAreaRecords(): readonly AreaRecord[] {
  return useContext(AreaRecordsContext);
}

/**
 * The area that claims a path, matched whole and case-sensitively.
 *
 * @param pathname - The path to look up.
 * @param records - The records to read; {@link AREAS} unless a test overrides them.
 * @returns The record, or null for a public path: `/`, or one no area claims.
 */
export function areaOf(pathname: string, records: readonly AreaRecord[] = AREAS): AreaRecord | null {
  return records.find((record) => record.paths.some((pattern) => matchPath(pattern, pathname))) ?? null;
}

/**
 * Which router serves a path. A public path is the catch-all's until the last spec moves it.
 *
 * @param pathname - The path to look up.
 * @param records - The records to read; {@link AREAS} unless a test overrides them.
 * @returns `'app'` or `'catch-all'`.
 */
export function routerFor(pathname: string, records: readonly AreaRecord[] = AREAS): AreaRouter {
  return areaOf(pathname, records)?.router ?? 'catch-all';
}
