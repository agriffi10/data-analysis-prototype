import type {ReactNode} from 'react';
import {LoadingState} from '../components/LoadingState';
import {FEATURE_FLAG_KEYS, navDestination, useFeatureSet} from '../features/feature-flags';
import type {FeatureFlagKey} from '../features/feature-flags';
import {FeatureUnavailablePage} from './FeatureUnavailablePage';

export type FeatureRouteProps = {
  flag: FeatureFlagKey;
  children: ReactNode;
};

/**
 * Route-level gate: the page, or {@link FeatureUnavailablePage}.
 *
 * **THE PAGE MUST NOT MOUNT WHILE THE ANSWER IS UNKNOWN.** Every gated page fetches on mount,
 * so rendering it first and swapping to the unavailable state a tick later would issue the
 * very requests FR-004 forbids — and on `/data-quality/:space/:requestId` that request is an
 * existence oracle for someone else's report (SPEC-113). Hence a neutral `LoadingState` while
 * the flags resolve, rather than the optimistic render a nav item can afford.
 *
 * It is `LoadingState` and not `null` because a route is the whole viewport: an empty frame
 * for a beat reads as a broken page, where an absent tab reads as a tab that was never there.
 * That difference is why FR-007's "render nothing while loading" applies to the nav and the
 * controls and not here.
 *
 * The offered fallback is the first ENABLED feature in flag order, so the link never points
 * at another unavailable page; with every feature off it is omitted entirely.
 *
 * @example
 * <Route path="/query" element={<FeatureRoute flag="query"><QueryPage /></FeatureRoute>} />
 */
export function FeatureRoute({flag, children}: FeatureRouteProps) {
  const {isEnabled, status} = useFeatureSet();

  if (status === 'loading') return <LoadingState />;
  if (isEnabled(flag)) return <>{children}</>;

  const fallbackKey = FEATURE_FLAG_KEYS.find((key) => isEnabled(key) && navDestination(key));
  return (
    <FeatureUnavailablePage
      feature={navDestination(flag)?.label}
      fallback={fallbackKey ? navDestination(fallbackKey) : undefined}
    />
  );
}
