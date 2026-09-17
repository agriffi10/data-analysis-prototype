import {useMemo} from 'react';
import {useQuery} from '@tanstack/react-query';
import {useAuth} from '../auth';
import {useConnections} from '../connections/useConnections';
import {useSpaceLinkPending} from '../connections/useSpaceLinkPending';
import {isConnectionUsable} from '../connections/connection.types';
import {toUserText} from '../../lib/errorMessages';
import {unwrap} from '../../lib/serviceResult';
import {spaceBuckets} from '../../lib/userSpace';
import type {ApiClientCode} from '../../lib/apiClient';
import type {ApiErrorCode} from '../../types/apiContract.generated';
import {dataQualityKeys} from './dataQualityKeys';
import {getQualityReport} from './dataQualityReport.service';
import type {DataQualityReport, DataQualitySpace} from './dataQuality.types';

export type UseDataQualityReportResult = {
  /**
   * Only while the space resolves. A report cached before the connections list withdrew its space is
   * not returned, so it cannot show beside that space's refusal or while a link back to it waits.
   * Nor is one a later read refused; a later read that did not get through leaves it, beside `refreshError`.
   */
  report: DataQualityReport | undefined;
  /** The resolved space, for the page's "Re-run check" and "Open folder" actions. */
  space: DataQualitySpace | undefined;
  isLoading: boolean;
  /** Why no report can be shown. Already passed through `toUserMessage` — render it directly. */
  error: string | undefined;
  /** Why a later read of the report on screen did not get through. Set only beside `report`. */
  refreshError: string | undefined;
  /** The `:space` segment named no space this user can reach. */
  isInaccessible: boolean;
};

/**
 * The failures that say a read never got through, and so say nothing about the report itself.
 *
 * A report is written once per check, so a copy already on screen stays right through any of these.
 * The list is closed so that everything else — a report deleted or unreadable, a refusal, a code
 * added later — takes the report off the page rather than leaving one the server may no longer serve.
 */
const UNDELIVERED_CODES: ReadonlySet<unknown> = new Set<ApiErrorCode | ApiClientCode>([
  'NetworkUnavailable',
  'RequestTimeout',
  'RateLimited',
  'InternalError',
  'ApiUnavailable'
]);

function isUndelivered(error: unknown): boolean {
  return UNDELIVERED_CODES.has((error as {code?: unknown} | null)?.code);
}

/**
 * Resolve a `:space` route segment to the space that holds the report.
 *
 * PRECEDENCE IS LOAD-BEARING: the actor's own username always resolves personal, and
 * shared names are consulted only when the segment differs from it. A user whose
 * username happens to match a shared space they belong to would otherwise resolve to
 * the shared bucket and read a stranger's report — or, more likely, 403 on their own.
 * the link builder pins the same rule from the producer side.
 *
 * Returns `undefined` for a space the user cannot reach, which is what keeps this
 * function from becoming an existence oracle: the caller does not fetch, so an
 * inaccessible name and a nonexistent one are indistinguishable from the outside.
 */
export function resolveSpace(
  spaceName: string,
  username: string | null,
  sharedSpaceNames: readonly string[],
  buckets: {user?: string; shared?: string} = spaceBuckets()
): DataQualitySpace | undefined {
  if (!spaceName) return undefined;
  if (username && spaceName === username) {
    return buckets.user ? {kind: 'personal', bucket: buckets.user, prefix: `${username}/`} : undefined;
  }
  if (!sharedSpaceNames.includes(spaceName)) return undefined;
  return buckets.shared ? {kind: 'shared', bucket: buckets.shared, prefix: `${spaceName}/`} : undefined;
}

/**
 * Fetch one data-quality report by space + request id.
 *
 * It does NOT fetch until the space resolves, and never fetches at all for a space the
 * user has no access to — no probing S3 on a guess, and no leaking whether a
 * space exists via the difference between a 403 and a 404.
 */
export function useDataQualityReport(spaceName: string, requestId: string): UseDataQualityReportResult {
  const {user} = useAuth();
  const username = user?.username ?? null;
  const {connections, isLoading: connectionsLoading, listReadsSettled, rereadList} = useConnections(username);

  const sharedSpaceNames = useMemo(
    () => connections.filter((c) => c.kind === 'shared' && isConnectionUsable(c)).map((c) => c.database),
    [connections]
  );

  const space = useMemo(
    () => resolveSpace(spaceName, username, sharedSpaceNames),
    [spaceName, username, sharedSpaceNames]
  );

  // Resolving a shared space needs the connections list, so "inaccessible" is only meaningful on a
  // read of it after the link was followed — before that, the list is not there yet or may predate
  // a space the user has just joined, and the denied state would show to a user who can read the
  // report.
  const pending = useSpaceLinkPending({
    username,
    space: spaceName,
    missing: !space,
    listReadsSettled,
    rereadList
  });
  const isInaccessible = !pending && !space;

  const query = useQuery({
    queryKey: dataQualityKeys.report(spaceName, requestId),
    // Not held for the connections list. The list can add or withdraw a shared space, but it
    // never moves a segment to the other bucket, because the username wins over shared names,
    // so a personal report — the one space that resolves without the list — starts at once.
    enabled: !!space && !!requestId,
    // A missing report is a terminal answer ("still running, or deleted"), not a
    // transient fault worth three more round trips.
    retry: false,
    queryFn: async ({client, queryKey}): Promise<DataQualityReport> => {
      const read = await getQualityReport((space as DataQualitySpace).bucket, spaceName, requestId);
      // A failed read keeps the report beneath a refusal, so a read that says nothing new must not
      // replace that refusal: the report would show again beside it.
      const held = client.getQueryState(queryKey)?.error;
      if (!read.success && isUndelivered(read.error) && held && !isUndelivered(held)) throw held;
      return unwrap(read);
    }
  });

  const report = space && (!query.error || isUndelivered(query.error)) ? query.data : undefined;
  const error = query.error ? toUserText(query.error) : undefined;

  return {
    report,
    space,
    isLoading: space ? query.isPending : connectionsLoading || pending,
    error: report ? undefined : error,
    refreshError: report ? error : undefined,
    isInaccessible
  };
}
