import {useEffect} from 'react';
import {useQuery} from '@tanstack/react-query';
import {envVar} from '../../lib/env';
import {unwrap} from '../../lib/serviceResult';
import {useAuth} from '../auth';
import {featureFlagKeys} from './featureFlagKeys';
import {FEATURE_FLAG_DEFAULTS} from './featureFlagDefaults';
import {getFeatureFlags} from './featureFlags.service';
import type {FeatureFlags, FeatureFlagsStatus} from './featureFlags.types';

/** The document changes when someone publishes one, which is a deploy — an hour costs nothing. */
const STALE_TIME_MS = 60 * 60 * 1000;
const GC_TIME_MS = 4 * STALE_TIME_MS;

export type UseFeatureFlagsResult = {
  /** Always holds all four keys as booleans, whatever the document said. */
  flags: FeatureFlags;
  status: FeatureFlagsStatus;
};

/**
 * The resolved feature flags for this build's environment.
 *
 * **A FLAG IS PRESENTATION, NEVER AUTHORIZATION** — see `featureFlags.service.ts` for the
 * rule in full. Consumers hide things with it; nothing branches an AWS call on it.
 *
 * `flags` is never partial and never pending: while the fetch is in flight it holds the
 * compiled-in defaults, so a consumer that ignores `status` renders the all-on app rather
 * than flashing an empty one. Everything is visible, then something may go away — which is
 * the right direction for a presentation flag, because the alternative hides a feature the
 * user has permission to use on the strength of a read that had not finished.
 *
 * @example
 * const {flags} = useFeatureFlags();
 * if (!flags.query) return null;
 */
export function useFeatureFlags(): UseFeatureFlagsResult {
  const {user} = useAuth();
  const environment = envVar('VITE_ENVIRONMENT');
  // The document is bucket-wide, so nothing about the session changes what is fetched — but
  // reading it still needs credentials, and a fetch issued before there are any is a
  // guaranteed failure that would land the flags in 'fallback' for the session.
  const enabled = !!user;

  const query = useQuery({
    queryKey: featureFlagKeys.resolved(environment),
    enabled,
    staleTime: STALE_TIME_MS,
    gcTime: GC_TIME_MS,
    // A retry only delays the fallback: the service already treats every recoverable shape
    // as a resolved answer, so anything reaching here is a real fault.
    retry: false,
    queryFn: async (): Promise<FeatureFlags> => unwrap(await getFeatureFlags(environment))
  });

  const status: FeatureFlagsStatus = !enabled
    ? 'loading'
    : query.isPending
      ? 'loading'
      : query.isError
        ? 'fallback'
        : 'ready';
  const flags = query.data ?? FEATURE_FLAG_DEFAULTS;

  useDevDiagnostic(status, environment);

  return {flags, status};
}

/**
 * Say out loud, in dev only, which way the read went (SPEC-162 FR-009).
 *
 * FR-005 is deliberately silent, which means a permanently-blocked fetch is
 * indistinguishable from a healthy all-on environment — there is no banner and no toast,
 * because the user is not the audience for that failure. This is the audience. Stripped
 * from production builds by the `DEV` guard, exactly as `warnIfMisconfigured` is, and for
 * the same reason: a deployed app must not narrate its own configuration to a user's
 * console.
 */
function useDevDiagnostic(status: FeatureFlagsStatus, environment: string | undefined): void {
  useEffect(() => {
    if (!import.meta.env.DEV || status === 'loading') return;
    console.debug(
      `[feature-flags] ${status} — environment ${environment ?? '(unset)'}` +
        (status === 'fallback' ? '; the compiled-in defaults are in force, so a deliberate "off" is NOT applied' : '')
    );
  }, [status, environment]);
}
