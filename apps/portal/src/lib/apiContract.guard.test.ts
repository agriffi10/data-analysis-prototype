import {describe, expect, it} from 'vitest';
import {API_ERROR_CODES} from '../types/apiContract.generated';
import {PASSTHROUGH_CODES, toUserText} from './errorMessages';

/** The two the client mints. Declared here as data so the guards below can reach them. */
const CLIENT_MINTED = ['RequestTimeout', 'NetworkUnavailable'] as const;

/** Read as source, so the assertions are about what the modules DECLARE, not what they do. */
const sources = import.meta.glob('./{apiClient,errorMessages}.ts', {
  query: '?raw',
  import: 'default',
  eager: true
}) as Record<string, string>;

const allAppSources = import.meta.glob('../**/*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true
}) as Record<string, string>;

/**
 * THE WHOLE APP, not just `features/`. Scoped to `features/` the sweeps could not see `src/lib/`,
 * `src/routes/`, `src/components/` or `src/hooks/` — a `fetch` in any of those passed, which was
 * confirmed by planting one in `lib/returnPath.ts`. This is the arc's spine and five specs copy
 * it, so the bound is stated rather than left to be discovered.
 *
 * SHIPPED code only. A test may legitimately stub `fetch`, and a test NAME may say the word — the
 * first offender this sweep found was `'…the DDL fetch (Athena hard cap)'`, which is prose. A
 * sweep that fires on prose is one somebody loosens.
 */
const appSources = Object.fromEntries(
  Object.entries(allAppSources).filter(([path]) => !path.includes('.test.') && !path.includes('/test/'))
);

/**
 * The two modules exempt by EXACT PATH, each for a stated reason:
 *   `runtimeConfig.ts` fetches `/config.json` same-origin, before the app graph is even loaded —
 *     it is what teaches the client where the API is, so it cannot go through the client.
 *   `apiClient.ts` IS the door.
 */
/**
 * The source with its comments removed.
 *
 * Every one of these sweeps is a string match, and every one of them found a COMMENT first: a test
 * name saying "the DDL fetch (Athena hard cap)", and this module's own JSDoc recounting the
 * `retry: 1` incident. A sweep that fires on prose gets loosened rather than heeded, so prose is
 * removed before matching rather than exempted afterwards.
 */
function code(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');
}

const FETCH_EXEMPT = ['/runtimeConfig.ts', '/apiClient.ts', './runtimeConfig.ts', './apiClient.ts'];

describe('the wording boundary', () => {
  it('keeps the API codes and the PASSTHROUGH codes disjoint', () => {
    // THE TRAP THIS EXISTS TO CLOSE. A passthrough rule returns the service's message unchanged.
    // If the API ever returned one of those codes and the client put server text into
    // `error.message`, the single-source-of-wording rule would be reversed through one of its
    // own rules — and it would look fine in every screenshot.
    //
    // TWO DERIVED SETS, never two lists: the left comes from the generated contract, the right is
    // computed from the rules themselves.
    const overlap = API_ERROR_CODES.filter((code) => PASSTHROUGH_CODES.includes(code));

    expect(overlap).toEqual([]);
  });

  it('keeps the CLIENT-MINTED codes out of both other sets', () => {
    expect(CLIENT_MINTED.filter((code) => (API_ERROR_CODES as readonly string[]).includes(code))).toEqual([]);
    expect(CLIENT_MINTED.filter((code) => PASSTHROUGH_CODES.includes(code))).toEqual([]);
  });

  it('gives every API code a rule of its own', () => {
    // A missing rule is not a crash — it is the generic fallback, which is the RIGHT behaviour
    // for an unknown code and the WRONG behaviour for a known one. Only a guard tells them apart.
    const generic = 'Something went wrong. Contact the Administrator.';
    const unruled = [...API_ERROR_CODES, ...CLIENT_MINTED].filter((code) => {
      // A code with no rule resolves to the generic sentence. Two of ours legitimately say that
      // too, so they are named rather than inferred.
      const saysGeneric = toUserText({code}) === generic;
      const deliberatelyGeneric = ['InvalidRequest', 'InternalError', 'UnsupportedMediaType'].includes(code);
      return saysGeneric && !deliberatelyGeneric;
    });

    expect(unruled).toEqual([]);
  });

  it('resolves a code from a NEWER API to the generic sentence', () => {
    // The deploy-skew case: the API deploys before the SPA image, so an old bundle will meet a
    // code it has no rule for. That must be a sentence, not a blank banner.
    expect(toUserText({code: 'SomeCodeFromANewerApi'})).toBe('Something went wrong. Contact the Administrator.');
  });

  it('computes the passthrough set rather than carrying a second list', () => {
    const errorMessages = sources['./errorMessages.ts'];

    expect(errorMessages).toContain('CODE_RULES.filter');
    expect(PASSTHROUGH_CODES.length).toBeGreaterThan(0);
  });
});

describe('the one door', () => {
  it('has no feature calling global fetch', () => {
    // Everything the browser sends to the API goes through `apiClient`. A feature calling `fetch`
    // is outside the contract, the retry rule and the wording boundary at once.
    const offenders = Object.entries(appSources)
      .filter(([path]) => !FETCH_EXEMPT.some((exempt) => path.endsWith(exempt)))
      // `window.fetch(`, `globalThis.fetch(` and `self.fetch(` are the same call. A dotted
      // access walked past the first version of this — confirmed by planting one.
      .filter(([, source]) => /(^|[^\w.])(?:(?:window|globalThis|self)\.)?fetch\(/.test(code(source)))
      .map(([path]) => path);

    expect(offenders).toEqual([]);
  });

  it('has no module outside apiClient building a URL from the API origin', () => {
    const offenders = Object.entries(appSources)
      .filter(([path]) => !path.endsWith('/apiClient.ts') && path !== './apiClient.ts')
      // Quote-agnostic: the repo formats to single quotes, but a sweep that a double quote walks
      // past is one that reports clean for the wrong reason.
      .filter(([, source]) => /configValue\(\s*['"`]apiBaseUrl['"`]\s*\)/.test(code(source)))
      .map(([path]) => path);

    expect(offenders).toEqual([]);
  });

  it('has no feature passing a retry option that is not the contract policy', () => {
    // Idempotency is declared per route. A hook deciding it locally is how a billed, stateful
    // call comes to be retried because it looked like a read.
    const offenders = Object.entries(appSources)
      .filter(([, source]) => code(source).includes('apiRequest'))
      .filter(([, source]) => {
        const retries = [...code(source).matchAll(/retry:\s*([^,\n}]+)/g)].map(([, value]) => value.trim());
        return retries.some((value) => value !== 'false' && !value.startsWith('apiRetryPolicy('));
      })
      .map(([path]) => path);

    expect(offenders).toEqual([]);
  });
});
