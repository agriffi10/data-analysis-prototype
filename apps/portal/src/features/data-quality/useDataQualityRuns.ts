import {useMemo} from 'react';
import {useQuery, useQueryClient} from '@tanstack/react-query';
import {useAuth} from '../auth';
import {useConnections} from '../connections/useConnections';
import {isConnectionUsable} from '../connections/connection.types';
import {logBackgroundFailure, toUserText} from '../../lib/errorMessages';
import {spaceBuckets} from '../../lib/userSpace';
import {dataQualityKeys} from './dataQualityKeys';
import {getRunsIndex} from './dataQualityRuns.service';
import type {DataQualityRunSummary} from './dataQuality.types';

/** A space to read an index from: its name and the bucket that holds it. */
export type RunsSource = {space: string; bucket: string};

/**
 * Every space whose runs this user can see: their personal space plus each usable shared
 * space they belong to.
 *
 * Exported pure so the aggregation can be tested without mounting the auth/connections
 * providers.
 */
export function runsSources(
  username: string | null,
  sharedSpaceNames: readonly string[],
  buckets: {user?: string; shared?: string} = spaceBuckets()
): RunsSource[] {
  const sources: RunsSource[] = [];
  if (username && buckets.user) sources.push({space: username, bucket: buckets.user});
  if (buckets.shared) {
    for (const name of sharedSpaceNames) {
      // A shared space named like the user would resolve PERSONAL at the report route
      //, so its rows would link somewhere that 404s. Skipping it here
      // matches what the link builder does on the producer side.
      if (name !== username) sources.push({space: name, bucket: buckets.shared});
    }
  }
  return sources;
}

export type UseDataQualityRunsResult = {
  /** Merged across spaces, newest first. */
  runs: DataQualityRunSummary[];
  isLoading: boolean;
  /** Already passed through `toUserMessage` — render it directly. */
  error: string | undefined;
  refresh: () => Promise<void>;
};

/**
 * Every completed check this user can see, newest first.
 *
 * IT AGGREGATES RATHER THAN MAKING THE USER PICK A SPACE. This page answers "what have I
 * checked", not "what has been checked in this folder" — and forcing a space selection
 * before showing anything makes the common case (one personal space, no shared ones)
 * strictly worse for no gain.
 *
 * ONE UNREADABLE SPACE NEVER BLANKS THE PAGE. Indexes are fetched in parallel and settled
 * independently: a space that was deleted, or whose membership changed since the
 * connections list was cached, is skipped with a warning. The query only fails when EVERY
 * source failed — i.e. when there is genuinely nothing to show and silence would be a lie.
 */
export function useDataQualityRuns(): UseDataQualityRunsResult {
  const {user} = useAuth();
  const username = user?.username ?? null;
  const {connections, isLoading: connectionsLoading} = useConnections(username);
  const queryClient = useQueryClient();

  const sharedSpaceNames = useMemo(
    () => connections.filter((c) => c.kind === 'shared' && isConnectionUsable(c)).map((c) => c.database),
    [connections]
  );

  const sources = useMemo(() => runsSources(username, sharedSpaceNames), [username, sharedSpaceNames]);
  // The key carries the space NAMES so gaining or losing a shared space refetches rather
  // than serving a merged list that silently still contains a space the user just left.
  const spaceKey = sources.map((s) => s.space).join(',');

  const query = useQuery({
    queryKey: dataQualityKeys.runs(spaceKey),
    // WAIT FOR THE CONNECTIONS LIST, not merely for a username: until it settles
    // `sharedSpaceNames` is empty, so a user with shared spaces would otherwise cache a
    // personal-only list under a key that never refetches when the real answer arrives.
    enabled: !connectionsLoading && sources.length > 0,
    queryFn: async (): Promise<DataQualityRunSummary[]> => {
      const settled = await Promise.all(
        sources.map(async (source) => ({source, result: await getRunsIndex(source.bucket, source.space)}))
      );

      const failed = settled.filter(({result}) => !result.success);
      for (const {source, result} of failed) {
        // A skipped space is operator information, not a user-facing error: the page still
        // renders every space that did load.
        logBackgroundFailure(
          'data-quality',
          `skipping runs for space "${source.space}": ${result.success ? '' : result.error.message}`
        );
      }
      if (failed.length === settled.length) {
        // Everything failed, so there is no partial list to show. Throwing here is what
        // puts the banner up; resolving with [] would render "no checks yet", which
        // would tell the user their history is empty when it is merely unreachable.
        throw failed[0].result.success ? new Error('unreachable') : failed[0].result.error;
      }

      return settled
        .flatMap(({result}) => (result.success ? result.data : []))
        .sort((a, b) => b.timestamp.localeCompare(a.timestamp));
    }
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({queryKey: dataQualityKeys.runs(spaceKey)});
  };

  return {
    runs: query.data ?? [],
    isLoading: connectionsLoading || (sources.length > 0 && query.isPending),
    error: query.error ? toUserText(query.error) : undefined,
    refresh
  };
}
