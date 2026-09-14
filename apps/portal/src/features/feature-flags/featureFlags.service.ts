import {apiRequest} from '../../lib/apiClient';
import {fromApiFailure, ok} from '../../lib/serviceResult';
import {FEATURE_FLAG_DEFAULTS, FEATURE_FLAG_KEYS} from './featureFlagDefaults';
import type {FeatureFlagKey, FeatureFlags} from './featureFlags.types';
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

/** The only document shape this reader understands. A different one is refused, not guessed at. */
const SUPPORTED_VERSION = 1;

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
  // An empty object reads as no document at all, which is what the parser's own "unusable" arm
  // already says about a body it cannot use.
  return parseFlags(read.data.body === '' ? undefined : read.data.body, environment);
}

/** TOTAL: a body that isn't JSON is as unusable as one that is JSON of the wrong shape. */
function parseFlags(body: string | undefined, environment: string | undefined): ServiceResult<FeatureFlags> {
  let parsed: unknown;
  try {
    parsed = body ? JSON.parse(body) : null;
  } catch {
    return unusable('The feature-flag document could not be parsed');
  }
  return resolve(parsed, environment);
}

/**
 * Resolve a parsed document into a complete flag set, or refuse it whole.
 *
 * The two levels of tolerance are deliberate and different. A document whose VERSION or
 * top-level SHAPE is wrong is refused entirely: this build has no reader for it, and
 * guessing at an unknown shape is how a flag ends up meaning something nobody wrote. A
 * single malformed VALUE inside a document that is otherwise fine falls back for that key
 * alone — one bad line must not discard three good ones.
 */
function resolve(parsed: unknown, environment: string | undefined): ServiceResult<FeatureFlags> {
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return unusable('The feature-flag document is not an object');
  }
  const document = parsed as {version?: unknown; defaults?: unknown; environments?: unknown};

  if (document.version !== SUPPORTED_VERSION) {
    return unusable(
      `The feature-flag document has unsupported version ${String(document.version)} — expected ${SUPPORTED_VERSION}`
    );
  }
  if (!isBlock(document.defaults)) {
    return unusable('The feature-flag document has no usable defaults block');
  }

  const overrides = pickEnvironment(document.environments, environment);
  const flags = {} as FeatureFlags;
  // Walks the KEY LIST, not the document — which is what guarantees every key is
  // present and boolean whatever the document happened to name.
  for (const key of FEATURE_FLAG_KEYS) {
    flags[key] = firstBoolean(overrides[key], (document.defaults as Record<string, unknown>)[key], key);
  }
  return ok(flags);
}

/**
 * The named environment's overrides, or none.
 *
 * An environment the document does not name is NOT an error — it resolves to the document's
 * `defaults` and reports ready. The same holds for an unset `environment`, which is
 * what keeps an unwired build from white-screening on a variable it never received.
 */
function pickEnvironment(environments: unknown, environment: string | undefined): Partial<Record<string, unknown>> {
  if (!environment || !isBlock(environments)) return {};
  const block = (environments as Record<string, unknown>)[environment];
  return isBlock(block) ? (block as Record<string, unknown>) : {};
}

/** The first real boolean of override → document default → compiled-in default. */
function firstBoolean(override: unknown, documentDefault: unknown, key: FeatureFlagKey): boolean {
  if (typeof override === 'boolean') return override;
  if (typeof documentDefault === 'boolean') return documentDefault;
  return FEATURE_FLAG_DEFAULTS[key];
}

function isBlock(value: unknown): boolean {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

/**
 * A refusal, in the `ServiceResult` failure shape.
 *
 * The message never reaches a user — the hook swallows it into `'fallback'` — so it is
 * written for whoever is reading a console in dev, not for the render boundary.
 */
function unusable(message: string): ServiceResult<FeatureFlags> {
  return {success: false, error: {message, code: 'FeatureFlagsUnusable'}};
}
