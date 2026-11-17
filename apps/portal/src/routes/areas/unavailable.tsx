import {navDestination} from '../../features/feature-flags';
import type {FeatureFlagKey} from '../../features/feature-flags';
import {FeatureUnavailablePage} from '../FeatureUnavailablePage';

export type UnavailableViewProps = {
  /** The flag that is off for the area the address names. */
  flag: FeatureFlagKey;
  /** The first enabled flag with a destination, which the server chose, or none. */
  fallback: FeatureFlagKey | undefined;
};

/**
 * The "not available" page the server chose for an area whose flag is off, in place of the area's
 * page, so the area's own view is never loaded.
 *
 * The names it shows are read from the registry's nav rows here, in the browser, so the server sends
 * only two flag keys.
 *
 * @returns The unavailable page for `flag`, offering `fallback`'s destination.
 */
export function UnavailableView({flag, fallback}: UnavailableViewProps) {
  return (
    <FeatureUnavailablePage
      feature={navDestination(flag)?.label}
      fallback={fallback ? navDestination(fallback) : undefined}
    />
  );
}
