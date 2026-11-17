import {ok, type ServiceResult} from '../../lib/serviceResult';
import {FEATURE_FLAG_DEFAULTS, FEATURE_FLAG_KEYS} from './featureFlagDefaults';
import type {FeatureFlagKey, FeatureFlags} from './featureFlags.types';

/** The only document shape this reader understands. A different one is refused, not guessed at. */
const SUPPORTED_VERSION = 1;

/**
 * Resolve the published feature-flag document's text for one environment, or refuse it whole.
 *
 * The one resolver, called by the browser's service on the body the API returned and by the
 * Next.js server on the body its own read returned, so a document can never resolve one way in
 * the browser and another way on the server. It reaches nothing but the flag types, the defaults
 * and the result helpers: no network, no React and no configuration, which is what lets the
 * server import it.
 *
 * TOTAL: a body that isn't JSON is as unusable as one that is JSON of the wrong shape, and an
 * empty body reads as no document at all.
 *
 * @param body - The document's text, as the API returned it.
 * @param environment - The runtime document's `environment`. `undefined` and a name the document
 *   does not carry both resolve to the document's own `defaults`, which is a successful read.
 * @returns The complete flag set, or a `FeatureFlagsUnusable` failure; never throws.
 */
export function resolveFeatureFlagDocument(
  body: string | undefined,
  environment: string | undefined
): ServiceResult<FeatureFlags> {
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
 * The message never reaches a user — the hook swallows it into `'fallback'` and the server logs
 * only its code — so it is written for whoever is reading a console in dev.
 */
function unusable(message: string): ServiceResult<FeatureFlags> {
  return {success: false, error: {message, code: 'FeatureFlagsUnusable'}};
}
