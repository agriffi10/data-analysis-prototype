/**
 * The portal's configuration, read at runtime from a same-origin document.
 *
 * A `VITE_*` variable is inlined into the bundle when it is built, so a bundle carries
 * one environment's bucket names, queue URLs and Cognito ids everywhere it is promoted.
 * This module reads them from `/config.json` instead, fetched once before the app
 * renders, which is what lets one artifact be promoted rather than rebuilt.
 *
 * EVERY READ IS AT CALL TIME, never at module load. A module-level const captures the
 * value before the document is in hand — in production that is a throw, and in a test
 * it silently exercises the deployed names instead of the stubbed ones.
 *
 * A DEV BUILD FALLS BACK TO `import.meta.env`, and a production build must not. A
 * laptop has no container to render the document, and the whole test suite runs on that
 * fallback arm; production reads the document or fails to boot, so a missing value can
 * never reach a caller as `undefined`.
 */
import {devFallbackValue} from './env';
import {REQUIRED_CONFIG} from '../types/runtimeConfig.types';
import type {
  RequiredConfigKey,
  RuntimeConfigDocument,
  RuntimeConfigKey,
  RuntimeConfigLoad
} from '../types/runtimeConfig.types';

/** Where the document is served from. Same-origin, and never proxied to the API. */
const CONFIG_URL = '/config.json';

/** The only document shape this build understands. A different one is refused, not guessed at. */
const SUPPORTED_VERSION = 1;

/**
 * Thrown when a production build reads configuration before the document is loaded.
 *
 * The alternative is returning `undefined`, which surfaces far from its cause as a
 * generic SDK error about a bucket named "undefined" — the failure this whole module
 * exists to prevent. A throw names the defect at the line that caused it.
 */
export class RuntimeConfigNotLoadedError extends Error {
  constructor(key: RuntimeConfigKey) {
    super(`Runtime configuration read (${key}) before /config.json was loaded`);
    this.name = 'RuntimeConfigNotLoadedError';
  }
}

let loaded: RuntimeConfigDocument | undefined;

/**
 * Install a document directly, bypassing the fetch.
 *
 * The loader's own writer, and the seam `src/test/seedRuntimeConfig.ts` uses to put a
 * test on the document path rather than the fallback. Passing nothing resets to
 * unloaded, which is the state a production build throws from.
 *
 * @param next - The document to serve reads from, or `undefined` to reset.
 * @returns None.
 */
export function setRuntimeConfigDocument(next?: RuntimeConfigDocument): void {
  loaded = next;
}

/**
 * Fetch and validate `/config.json`. Called once, from the bootstrap, before render.
 *
 * Never throws: every failure is a reason on the returned result, because the caller's
 * job is to render a boot failure rather than to catch.
 *
 * In a DEV build a failed load still resolves `{ok: true}` with no document installed,
 * so every read falls through to `import.meta.env`. That is what makes local
 * development work with no server able to render the document, and what lets the test
 * suite read configuration with no bootstrap at all.
 *
 * @returns `{ok: true}`, or the machine reason the document is unusable.
 */
export async function loadRuntimeConfig(): Promise<RuntimeConfigLoad> {
  const result = await readDocument();
  // A dev build has no container to render the document, so a failed load is the
  // ordinary local case rather than a defect: report success with nothing installed and
  // let every read fall through to `import.meta.env`.
  if (!result.ok && import.meta.env.DEV) return {ok: true};
  return result;
}

/** Fetch, parse, version-gate and completeness-check, in that order. */
async function readDocument(): Promise<RuntimeConfigLoad> {
  let response: Response;
  try {
    // `no-store` on the request as well as the response: a promoted image whose
    // configuration is answered from a cache populated in the previous environment
    // renders a working, fully-functional portal pointed at the wrong account, and
    // nothing on screen distinguishes it.
    response = await fetch(CONFIG_URL, {cache: 'no-store'});
  } catch {
    return {ok: false, reason: 'unreachable'};
  }
  if (!response.ok) return {ok: false, reason: 'unreachable'};

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    // WHERE A MISSING DOCUMENT ACTUALLY ARRIVES. The static site answers a missing
    // object with its own index.html under a 200, so the response is `ok` and full of
    // markup; only parsing it tells the two apart. A loader keyed on the status reads
    // an app shell as configuration and boots with everything undefined.
    return {ok: false, reason: 'unparseable'};
  }
  return install(body);
}

/** Refuse a document whole, or install it. */
function install(body: unknown): RuntimeConfigLoad {
  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    return {ok: false, reason: 'unparseable'};
  }
  const candidate = body as RuntimeConfigDocument;
  if (candidate.version !== SUPPORTED_VERSION) {
    // Refused WHOLE — not partially read, not merged with defaults. This build has no
    // reader for another shape, and guessing at one is how a value ends up meaning
    // something nobody wrote.
    return {ok: false, reason: 'unsupported-version', found: candidate.version};
  }
  loaded = candidate;
  const missing = missingRequiredConfig();
  if (missing.length > 0) {
    // Uninstalled again, so an incomplete document serves NOTHING. Left in place, the
    // keys it did carry would answer while the missing ones read `undefined` — a
    // half-configured app, on the one path already known to be misconfigured.
    loaded = undefined;
    return {ok: false, reason: 'missing-required', missing};
  }
  return {ok: true};
}

/**
 * One typed read of one configuration key, at call time.
 *
 * An empty string reads as unset: an unset repository variable and an unset task
 * variable both interpolate to `""`, which is the deploy mistake this module names. A
 * non-string value reads as unset for the same reason — the document's contract is
 * strings, and a number that arrived by accident must not reach an SDK.
 *
 * @param name - The key to read.
 * @returns The configured value, or `undefined` when it is unset.
 * @throws RuntimeConfigNotLoadedError - In a production build, before the load resolves.
 */
export function configValue(name: RuntimeConfigKey): string | undefined {
  if (loaded === undefined) {
    // Gated at the READ so the bundler can delete the fallback, its key table and every
    // VITE_ name from a production build.
    if (import.meta.env.DEV) return devFallbackValue(name);
    throw new RuntimeConfigNotLoadedError(name);
  }
  const value = loaded[name];
  if (typeof value !== 'string' || value === '') return undefined;
  return value;
}

/** Which required keys are missing right now — empty when the portal is configured. */
export function missingRequiredConfig(): RequiredConfigKey[] {
  return REQUIRED_CONFIG.filter((name) => configValue(name) === undefined);
}

/** True when every required key is set. */
export function isPortalConfigured(): boolean {
  return missingRequiredConfig().length === 0;
}
