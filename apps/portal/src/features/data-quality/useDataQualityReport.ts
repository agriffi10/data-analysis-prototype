import {useMemo} from 'react';
import {useQuery} from '@tanstack/react-query';
import {useAuth} from '../auth';
import {useConnections} from '../query/useConnections';
import {isConnectionUsable} from '../query/query.types';
import {toUserMessage} from '../../lib/errorMessages';
import {unwrap} from '../../lib/serviceResult';
import {spaceBuckets} from '../../lib/userSpace';
import {dataQualityKeys} from './dataQualityKeys';
import {getQualityReport} from './dataQualityReport.service';
import type {DataQualityReport, DataQualitySpace} from './dataQuality.types';

export type UseDataQualityReportResult = {
  report: DataQualityReport | undefined;
  /** The resolved space, for the page's "Re-run check" and "Open folder" actions. */
  space: DataQualitySpace | undefined;
  isLoading: boolean;
  /** Already passed through `toUserMessage` — render it directly. */
  error: string | undefined;
  /** The `:space` segment named no space this user can reach. */
  isInaccessible: boolean;
};

/**
 * Resolve a `:space` route segment to the space that holds the report.
 *
 * PRECEDENCE IS LOAD-BEARING: the actor's own username always resolves personal, and
 * shared names are consulted only when the segment differs from it. A user whose
 * username happens to match a shared space they belong to would otherwise resolve to
 * the shared bucket and read a stranger's report — or, more likely, 403 on their own.
 * SPEC-114's link builder pins the same rule from the producer side.
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
 * user has no access to (FR-005) — no probing S3 on a guess, and no leaking whether a
 * space exists via the difference between a 403 and a 404.
 */
export function useDataQualityReport(spaceName: string, requestId: string): UseDataQualityReportResult {
  const {user} = useAuth();
  const username = user?.username ?? null;
  const {connections, isLoading: connectionsLoading} = useConnections(username);

  const sharedSpaceNames = useMemo(
    () => connections.filter((c) => c.kind === 'shared' && isConnectionUsable(c)).map((c) => c.database),
    [connections]
  );

  const space = useMemo(
    () => resolveSpace(spaceName, username, sharedSpaceNames),
    [spaceName, username, sharedSpaceNames]
  );

  // Resolution needs the connections list, so "inaccessible" is only meaningful once
  // that has settled — otherwise every shared-space deep link would flash the denied
  // state before its own space had loaded.
  const isInaccessible = !connectionsLoading && !space;

  const query = useQuery({
    queryKey: dataQualityKeys.report(spaceName, requestId),
    // WAIT FOR THE CONNECTIONS LIST before fetching, not merely for a space to resolve.
    // Until it loads, `sharedSpaceNames` is empty, so a shared space whose name equals
    // the username would resolve PERSONAL on the first pass — and since the query key
    // is (space name, requestId) and carries no bucket, the wrong-bucket result would
    // then be cached and never refetched when the real answer arrived.
    enabled: !!space && !!requestId && !connectionsLoading,
    // A missing report is a terminal answer ("still running, or deleted"), not a
    // transient fault worth three more round trips.
    retry: false,
    queryFn: async (): Promise<DataQualityReport> =>
      unwrap(await getQualityReport((space as DataQualitySpace).bucket, spaceName, requestId))
  });

  return {
    report: query.data,
    space,
    isLoading: connectionsLoading || (!!space && query.isPending),
    error: query.error ? toUserMessage(query.error).message : undefined,
    isInaccessible
  };
}
