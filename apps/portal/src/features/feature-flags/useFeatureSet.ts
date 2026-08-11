import {useCallback} from 'react';
import {useFeatureFlags} from './useFeatureFlags';
import type {FeatureFlagKey, FeatureFlagsStatus} from './featureFlags.types';

export type UseFeatureSetResult = {
  /** Is this feature on? `false` while the flags are still loading, exactly as `useFeature`. */
  isEnabled: (key: FeatureFlagKey) => boolean;
  status: FeatureFlagsStatus;
};

/**
 * The whole flag set at once, for the few consumers that cannot ask one question.
 *
 * {@link useFeature} answers "is this on?" and is what nearly everything should use. Three
 * places genuinely need more and would otherwise reach past it into `useFeatureFlags`:
 *
 *   * `Header` builds one path→enabled predicate for two nav components at once.
 *   * `FeatureRoute` must tell "off" from "not known yet" — a page that mounts before the
 *     answer arrives has already fetched — and then name the first OTHER enabled feature.
 *   * `LandingPage` picks the first enabled destination for its signed-in call to action.
 *
 * Exposing this deliberately keeps `useFeatureFlags` internal to the feature, which is what
 * FR-001 asks for: one sanctioned surface, so a fifth consumer cannot quietly gate on a
 * slightly different condition. A tripwire test enforces it.
 *
 * `isEnabled` is stable across renders and reports `false` while loading, so a caller that
 * ignores `status` gets the same conservative answer `useFeature` gives.
 *
 * @example
 * const {isEnabled, status} = useFeatureSet();
 * if (status === 'loading') return <LoadingState />;
 */
export function useFeatureSet(): UseFeatureSetResult {
  const {flags, status} = useFeatureFlags();
  const isEnabled = useCallback((key: FeatureFlagKey) => status !== 'loading' && flags[key], [flags, status]);
  return {isEnabled, status};
}
