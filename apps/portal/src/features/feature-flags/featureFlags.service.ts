import {apiRequest} from '../../lib/apiClient';
import {fromApiFailure} from '../../lib/serviceResult';
import {resolveFeatureFlagDocument} from './resolveFeatureFlags';
import type {FeatureFlags} from './featureFlags.types';
import type {ServiceResult} from '../../types/service.types';

/**
 * Where `.github/workflows/deploy-config.yml` publishes. The portal role may read and list this
 * prefix; the file browser never shows it because the API lists only a space the caller's claims
 * authorize, and this prefix belongs to none.
 *
 * Kept as a declaration although the browser no longer builds a request from it: the key is a
 * contract with the publishing workflow, and it is asserted against the API's own copy so the two
 * cannot drift into naming different objects.
 */
export const FEATURE_FLAGS_KEY = '_config/feature-flags.json';

/**
 * Read the published feature-flag document and resolve it for one environment.
 *
 * **A FLAG IS PRESENTATION, NEVER AUTHORIZATION.** Turning a feature off hides its tab and
 * its entry points; it revokes no IAM grant, no queue permission and no credential scope,
 * and the portal role's policy is identical either way. Anyone reading this document as a
 * security boundary has misread it — the same rule that governs the username
 * directory, and a test pins it: no service and nothing in `lib/` may
 * import this module.
 *
 * **AN UNUSABLE DOCUMENT IS A FAILURE RESULT, NOT AN EMPTY SUCCESS**, and that is the one
 * place this diverges from `getUserDirectory()`. There, absent and corrupt collapse into
 * the empty state because "no suggestions" is a real and honest answer. Here the equivalent
 * answer is the compiled-in all-on defaults, which is indistinguishable from a healthy
 * environment — so the distinction has to survive the return, or `'fallback'` could never
 * be reported and a permanently-blocked read would look like success forever. The hook is
 * what turns a failure into defaults; nothing user-facing ever sees the error.
 *
 * A MISSING object is a failure here for the same reason: it means the publish workflow has
 * never run against this bucket, which is a deploy defect rather than a starting state.
 *
 * **It has a route of its own, and does not ride the document route the other settings documents
 * do.** `_config/` belongs to no user and to no shared space, so the API's space resolver — whose
 * whole job is to refuse a prefix the caller's claims do not authorize — correctly refuses it. The
 * username directory hit the same wall and was solved the same way.
 *
 * @param environment - The runtime document's `environment`. `undefined` (an unwired variable)
 *   and a name the document does not carry both resolve to the document's own `defaults`,
 *   which is a successful read — the document was fetched and understood.
 * @returns Always a `ServiceResult`; never throws.
 */
export async function getFeatureFlags(environment: string | undefined): Promise<ServiceResult<FeatureFlags>> {
  const read = await apiRequest('featureFlags.get');
  if (!read.success) return fromApiFailure(read.error, 'Failed to load the feature flags');
  return resolveFeatureFlagDocument(read.data.body, environment);
}
