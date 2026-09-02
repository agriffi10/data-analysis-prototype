import type {ReactNode} from 'react';
import {useFeature} from './useFeature';
import type {FeatureFlagKey} from './featureFlags.types';

export type FeatureGateProps = {
  flag: FeatureFlagKey;
  children: ReactNode;
};

/**
 * Renders its children only while `flag` is on.
 *
 * When the flag is off it renders **nothing** — no wrapper element, no placeholder, no
 * `hidden` attribute. A visually-hidden control is still in the accessibility tree and still
 * focusable, so "hidden" that means `display: none` would leave a screen-reader user able to
 * reach a feature the environment says is not there.
 *
 * Same three-state behaviour as {@link useFeature}: nothing while loading, everything under
 * `'fallback'`.
 *
 * Reach for the hook instead when the absence has to change a sibling — a toggle that would
 * otherwise render as a single-option control, a list that needs a different empty state.
 * Wrapping is right when the surface simply goes away.
 *
 * @example
 * <FeatureGate flag="dataQuality">
 *   <Button onClick={check}>Check data quality</Button>
 * </FeatureGate>
 */
export function FeatureGate({flag, children}: FeatureGateProps) {
  return useFeature(flag) ? <>{children}</> : null;
}
