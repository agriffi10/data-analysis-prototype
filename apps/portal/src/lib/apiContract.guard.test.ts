import {describe, expect, it} from 'vitest';
import {API_ERROR_CODES} from '../types/apiContract.generated';
import {PASSTHROUGH_CODES, USER_FIXABLE_CODES, toUserText} from './errorMessages';

/** The two the client mints. Declared here as data so the guards below can reach them. */
const CLIENT_MINTED = ['RequestTimeout', 'NetworkUnavailable', 'UnsendableParameter'] as const;

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

const packageJson = Object.values(
  import.meta.glob('../../package.json', {query: '?raw', import: 'default', eager: true}) as Record<string, string>
)[0];

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

/**
 * One glob key as a path under `src/`.
 *
 * The globs run from `src/lib/`, so a sibling arrives as `./queryClient.ts` and everything else
 * as `../features/…`. Two spellings for the same idea is how an exemption list comes to miss the
 * file it names, so exemptions compare against this.
 */
function srcPath(key: string): string {
  return key.startsWith('./') ? `lib/${key.slice(2)}` : key.replace(/^\.\.\//, '');
}

/**
 * The AWS packages the API surfaces retired, read by the source sweep AND the manifest check.
 *
 * NAMED, not "any `@aws-sdk` import": SQS is still called from the browser and its package stays.
 * A sweep phrased as the dependency CLASS would go red on work no spec has done yet, and would be
 * loosened rather than heeded.
 *
 * ONE list for both checks. They were two, and had already diverged by the time anyone looked —
 * the source sweep named five packages and the manifest check three.
 */
const RETIRED = [
  '@aws-sdk/client-s3',
  '@aws-sdk/lib-storage',
  '@aws-sdk/s3-request-presigner',
  '@aws-sdk/client-athena',
  '@aws-sdk/client-glue'
];

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
    //
    // THE RULE THE LIST BELOW ENFORCES: the generic sentence is for a failure the user cannot act
    // on. Every code on it is an app or deploy fault — a body that failed validation, a fault with
    // no mapping, a content type the client should not have sent. A code a user CAN do something
    // about does not belong here, and adding one is how "Contact the Administrator" comes to be
    // shown to somebody looking at their own typo. `QuerySyntaxError` exists because it was.
    const generic = 'Something went wrong. Contact the Administrator.';
    const deliberatelyGeneric = ['InvalidRequest', 'InternalError', 'UnsupportedMediaType'];
    const unruled = [...API_ERROR_CODES, ...CLIENT_MINTED].filter(
      (code) => toUserText({code}) === generic && !deliberatelyGeneric.includes(code)
    );

    expect(unruled).toEqual([]);
  });

  it('keeps the generic sentence out of the reach of anything a user can fix', () => {
    // The other direction, and the one the list above cannot police: a code marked `userFixable`
    // must never resolve to the sentence that tells its reader there is nothing to do. Derived
    // from the rules rather than listed, so a new user-fixable code joins by existing.
    const generic = 'Something went wrong. Contact the Administrator.';
    const contradictions = USER_FIXABLE_CODES.filter((code) => toUserText({code}) === generic);

    expect(contradictions).toEqual([]);
    expect(USER_FIXABLE_CODES.length).toBeGreaterThan(0);
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

  it('names XMLHttpRequest in exactly one module, the upload path', () => {
    // Widening the fetch sweep, and it has to be widened together with it: a rule that forbids
    // `fetch` and says nothing about `XMLHttpRequest` permits the same escape hatch under another
    // name. One module may use it, and only because `fetch` fires no upload-progress event — a
    // `fetch` upload works perfectly and leaves the progress bar at 0% until it jumps to 100%.
    const offenders = Object.entries(appSources)
      .filter(([, source]) => code(source).includes('XMLHttpRequest'))
      .map(([path]) => path)
      .filter((path) => !path.endsWith('/fileBrowser.service.ts'));

    expect(offenders).toEqual([]);
  });

  it('still has that one module — the exemption is not a dead entry', () => {
    // The half a sweep cannot state on its own: an exemption for a module that stopped using the
    // thing reads exactly like an exemption for a module that still does. If the upload path ever
    // moves back to `fetch`, the progress bar dies silently and this is what says so.
    const uploader = Object.entries(appSources).find(([path]) => path.endsWith('/fileBrowser.service.ts'));

    expect(uploader?.[1]).toContain('XMLHttpRequest');
  });

  it('has no module importing the AWS packages these surfaces retired', () => {
    // Athena and Glue joined `RETIRED` when the catalog moved behind the API. The comment there
    // used to say those two were staying — which is the failure a named list invites: it is only
    // true on the day it is written, and it reads as a decision rather than a snapshot.
    const offenders = Object.entries(appSources)
      .filter(([, source]) => RETIRED.some((pkg) => code(source).includes(pkg)))
      .map(([path]) => path);

    expect(offenders).toEqual([]);
  });

  it('has no retired package left in the manifest either', () => {
    // ONE list, read by both halves. Two hand-kept copies had already diverged by three entries
    // before this was written — the source sweep named five and the manifest check named three.
    // The source sweep above only sees imports. A package nothing imports still ships in the
    // lockfile, still resolves, and is still something a later feature can reach for by
    // accident — which is the whole reason the spec removes them rather than leaving them unused.
    const manifest = JSON.parse(packageJson) as {
      dependencies?: Record<string, string>;
      devDependencies?: Record<string, string>;
    };
    // BOTH dependency maps: a retired package moved to `devDependencies` still resolves from
    // `src`, so checking only the one it used to live in is a hole with the shape of a fix.
    const declared = {...manifest.devDependencies, ...manifest.dependencies};

    expect(RETIRED.filter((pkg) => declared[pkg] !== undefined)).toEqual([]);
    expect(declared['@aws-sdk/client-sqs']).toBeDefined();
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
    //
    // THE POPULATION IS EVERY MODULE THAT SETS A RETRY, not every module naming `apiRequest`.
    // Filtered on that substring, the sweep could not see the one hook whose retry this rule
    // exists for: `useExploration` reaches the API through a service and mentions `apiRequest`
    // nowhere, so the exact call the incident was about sat outside the guard named after it.
    //
    // **A CALLBACK IS THE MOST DANGEROUS VALUE HERE, NOT AN EXEMPT ONE.** A first version of this
    // widening excused any value starting with `(`, to get past two domain properties that happen
    // to be spelled `retry`. That let `retry: (failureCount, error) => …` — TanStack's documented
    // way to write a custom policy, and a deliberate decision rather than a typo — pass unseen,
    // while a literal `retry: 3` was caught. The value shape says nothing about intent, so the
    // three modules whose `retry` is not a transport policy are named by path instead.
    const NOT_A_TRANSPORT_POLICY = [
      // The composition root's own default. A default is the thing a route policy overrides
      // rather than an instance of one — and it is what makes this rule matter, since a hook
      // that writes no `retry` at all silently inherits it.
      'lib/queryClient.ts',
      // A domain property that shares the key's name: "the upload collided, here is my decision,
      // run it again". It takes a `CollisionDecision` and re-runs a gesture.
      'features/file-browser/useFileUpload.ts',
      // The same, one layer up: the type of the exploration region's "run it again" affordance.
      'features/data-explorer/useExplorationQuery.ts'
    ];
    const offenders = Object.entries(appSources)
      // EXACT paths, not suffixes: `endsWith('/queryClient.ts')` would exempt a future
      // `features/anything/queryClient.ts` as well, which is how a named exemption quietly
      // becomes a pattern one. `srcPath` normalises the glob's own `./` and `../` prefixes so
      // there is one spelling to compare against.
      .filter(([path]) => !NOT_A_TRANSPORT_POLICY.includes(srcPath(path)))
      .filter(([, source]) => {
        const retries = [...code(source).matchAll(/retry:\s*([^,\n}]+)/g)].map(([, value]) => value.trim());
        return retries.some((value) => value !== 'false' && !value.startsWith('apiRetryPolicy('));
      })
      .map(([path]) => path);

    expect(offenders).toEqual([]);
  });

  it('catches a retry CALLBACK, which is the shape a decision takes', () => {
    // The regression the exemption-by-value-shape introduced, pinned so it cannot come back: a
    // custom policy written as a function is the case this rule most needs to see, and it is the
    // one an "it starts with a paren, it must be a domain handler" filter waves through.
    const offends = (value: string) => value !== 'false' && !value.startsWith('apiRetryPolicy(');

    expect(offends('(failureCount, error) => failureCount < 3')).toBe(true);
    expect(offends('3')).toBe(true);
    expect(offends('false')).toBe(false);
    expect(offends("apiRetryPolicy('athena.start')")).toBe(false);
  });

  it('sees the module whose retry this rule was written for', () => {
    // Guard-the-guard, and it is not hypothetical: filtered on modules naming `apiRequest`, the
    // sweep above resolved onto a population that excluded `useExploration` — the one hook whose
    // retry the incident was about. A population that misses its own subject passes forever.
    const population = Object.entries(appSources).filter(([, source]) => /retry:\s*/.test(code(source)));

    expect(population.map(([path]) => path)).toContain('../features/data-explorer/useExploration.ts');
  });
});
