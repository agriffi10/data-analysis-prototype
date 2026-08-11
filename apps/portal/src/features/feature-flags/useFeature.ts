import {useFeatureFlags} from './useFeatureFlags';
import type {FeatureFlagKey} from './featureFlags.types';

/**
 * Is this feature on for this build?
 *
 * **The only way app code asks.** Everything else — nav, routes, cross-feature entry points,
 * the Help list — goes through this or {@link FeatureGate}, so the answer is computed one way
 * and the registry test has one thing to walk. Reaching for `useFeatureFlags` directly is how
 * a fifth surface ends up gated on a slightly different condition.
 *
 * **A flag is presentation, never authorization** (SPEC-162 FR-006). This hides a control; it
 * revokes nothing, and a user with a feature hidden still holds every IAM grant they did
 * before. Never use it to decide whether a request is allowed — only whether a surface is
 * offered.
 *
 * **`false` while the flags are still loading**, deliberately. A tab that appears and then
 * vanishes under the pointer is worse than one that arrives a tick late, and the load is one
 * cached fetch per session. `'fallback'` resolves every flag `true`, so an unreadable document
 * is indistinguishable from an all-on environment.
 *
 * @example
 * if (!useFeature('query')) return null;
 */
export function useFeature(key: FeatureFlagKey): boolean {
  const {flags, status} = useFeatureFlags();
  return status !== 'loading' && flags[key];
}
