import {readFileSync} from 'node:fs';
import {describe, it, expect, vi, afterEach} from 'vitest';
import {configValue, isPortalConfigured, loadRuntimeConfig} from './runtimeConfig';
import {VITE_NAME} from './env';
import {isAmplifyConfigured} from './amplify';
import {maxUploadBytes} from '../features/file-browser/uploadLimits';
import {clearRuntimeConfig, seedRuntimeConfig} from '../test/seedRuntimeConfig';
import {OPTIONAL_CONFIG, REQUIRED_CONFIG} from '../types/runtimeConfig.types';
import type {RuntimeConfigKey} from '../types/runtimeConfig.types';

/** Every key a complete document carries, with a value that identifies its key. */
const COMPLETE = Object.fromEntries(
  [...REQUIRED_CONFIG, ...OPTIONAL_CONFIG].map((key) => [key, `served-${key}`])
) as Record<RuntimeConfigKey, string>;

/** The complete document minus some keys — what an unset repository variable renders. */
function withoutKeys(...omitted: RuntimeConfigKey[]): Record<string, string> {
  return Object.fromEntries(Object.entries(COMPLETE).filter(([key]) => !omitted.includes(key as RuntimeConfigKey)));
}

/** One `fetch` answering with a body, a status and a content type of the caller's choosing. */
function respondWith(body: string, init: {ok?: boolean; status?: number} = {}): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: init.ok ?? true,
    status: init.status ?? 200,
    json: async () => JSON.parse(body) as unknown
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

/**
 * Re-import the module with `import.meta.env.DEV` stubbed false.
 *
 * The production arm is unreachable any other way: Vitest runs with `DEV` true, so the
 * whole suite — this file included — otherwise exercises the dev fallback, which is the
 * arm that will not exist in a deployed bundle.
 */
async function productionModule() {
  vi.stubEnv('DEV', false);
  vi.resetModules();
  return import('./runtimeConfig');
}

afterEach(() => {
  clearRuntimeConfig();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe('runtimeConfig — the document', () => {
  it('fetches the same-origin document with no-store', async () => {
    const fetchMock = respondWith(JSON.stringify({version: 1, ...COMPLETE}));

    await loadRuntimeConfig();

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/config.json');
    expect(init.cache).toBe('no-store');
    // And a deadline, so an origin that accepts the connection and never answers cannot
    // leave a blank page with an empty console forever.
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it('serves every key from the document once loaded', async () => {
    respondWith(JSON.stringify({version: 1, ...COMPLETE}));

    await loadRuntimeConfig();

    expect(configValue('userSpaceBucket')).toBe('served-userSpaceBucket');
    expect(configValue('sharedSpaceBucket')).toBe('served-sharedSpaceBucket');
    expect(isPortalConfigured()).toBe(true);
  });

  it('reads a non-string value as unset', () => {
    // The document's contract is strings. A number that arrived by accident must not
    // reach an SDK as one.
    seedRuntimeConfig({...COMPLETE, maxUploadBytes: 5368709120 as unknown as string});

    expect(configValue('maxUploadBytes')).toBeUndefined();
  });
});

describe('runtimeConfig — a production load that fails', () => {
  it('reports unreachable when the fetch rejects', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network')));
    const {loadRuntimeConfig: load} = await productionModule();

    expect(await load()).toEqual({ok: false, reason: 'unreachable'});
  });

  it('reports unreachable on a non-2xx', async () => {
    respondWith('{}', {ok: false, status: 500});
    const {loadRuntimeConfig: load} = await productionModule();

    expect(await load()).toEqual({ok: false, reason: 'unreachable'});
  });

  it.each([
    ['an array', '[]'],
    ['a bare number', '42'],
    ['a bare string', '"config"'],
    ['null', 'null']
  ])('reports unparseable for JSON that is %s', async (_shape, payload) => {
    respondWith(payload);
    const {loadRuntimeConfig: load} = await productionModule();

    expect(await load()).toEqual({ok: false, reason: 'unparseable'});
  });

  it('refuses an unsupported version WHOLE, and names what it found', async () => {
    respondWith(JSON.stringify({version: 2, ...COMPLETE}));
    const {loadRuntimeConfig: load, configValue: read} = await productionModule();

    expect(await load()).toEqual({ok: false, reason: 'unsupported-version', found: 2});
    // Not partially read: a complete document at the wrong version yields nothing.
    expect(() => read('userSpaceBucket')).toThrow(/before \/config\.json was loaded/);
  });

  it('names every missing required key', async () => {
    respondWith(JSON.stringify({version: 1, ...withoutKeys('userSpaceBucket', 'cognitoDomain')}));
    const {loadRuntimeConfig: load, configValue: read} = await productionModule();

    const result = await load();

    expect(result).toEqual({
      ok: false,
      reason: 'missing-required',
      missing: ['userSpaceBucket', 'cognitoDomain']
    });
    // AND THE KEYS IT DID CARRY ARE NOT SERVED. Left installed, an incomplete document
    // answers `undefined` for the missing ones — the bucket-named-undefined failure, on
    // the one path where the deployment is already known to be misconfigured.
    expect(() => read('appUrl')).toThrow(/before \/config\.json was loaded/);
  });
});

describe('runtimeConfig — the dev fallback', () => {
  it('answers from import.meta.env with no load having happened at all', () => {
    // What makes the production throw compatible with the existing suite, which imports
    // modules and reads configuration without any bootstrap.
    vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'local-bucket');

    expect(configValue('userSpaceBucket')).toBe('local-bucket');
  });

  it('pairs every key with the right VITE_ variable', () => {
    // The two tables are exhaustive by the compiler; that a key is paired with the RIGHT
    // variable is not a thing a type can say.
    // Against the classification, not a literal. A hard count reddens on any deliberate
    // key retirement, which reads as a defect in the retirement rather than in the test.
    const keys = [...REQUIRED_CONFIG, ...OPTIONAL_CONFIG];
    const paired = keys.filter((key) => VITE_NAME[key] !== null);
    expect(paired).toHaveLength(keys.length);

    for (const key of paired) vi.stubEnv(VITE_NAME[key] as string, `env-${key}`);

    for (const key of paired) expect(configValue(key)).toBe(`env-${key}`);
  });

  it('gives EVERY required key a dev fallback', () => {
    // The dev-boot warning is driven from the classification, so a required key with no
    // variable would warn about nothing: `[null].join(', ')` is the empty string, and the
    // warning fires forever naming no key at all. `apiBaseUrl` gained one the day it became
    // required, and this is the rule that keeps the next one from arriving without it.
    const missing = REQUIRED_CONFIG.filter((key) => VITE_NAME[key] === null);

    expect(missing).toEqual([]);
  });

  it('is NEVER consulted in a production build, not even for an incomplete document', async () => {
    // The variable is set in the process that would have built the bundle, and it must
    // still not answer: a deployment reads its document or it does not boot.
    vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'build-time-bucket');
    respondWith(JSON.stringify({version: 1, ...withoutKeys('userSpaceBucket')}));
    const {loadRuntimeConfig: load} = await productionModule();

    const result = await load();

    expect(result).toEqual({ok: false, reason: 'missing-required', missing: ['userSpaceBucket']});
  });

  it('throws rather than returning undefined when a production build reads before the load', async () => {
    vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'build-time-bucket');
    const {configValue: read} = await productionModule();

    expect(() => read('userSpaceBucket')).toThrow(/before \/config\.json was loaded/);
  });
});

describe('runtimeConfig — the accessor is the only door', () => {
  const SOURCES = import.meta.glob('../**/*.{ts,tsx}', {
    query: '?raw',
    import: 'default',
    eager: true
  }) as Record<string, string>;

  /**
   * The only module that may still name a `VITE_*` variable: `lib/env.ts`, which IS the dev
   * fallback.
   *
   * It used to be five. The other four read the dev-unauth variables behind their own
   * `import.meta.env.DEV` guards, and that path is gone — the browser makes no unsigned AWS call
   * to be unsigned, so the escape hatch had nothing left to open.
   */
  const ALLOWED = ['./env.ts'];

  it('leaves no production module reading import.meta.env.VITE_ outside that one', () => {
    // Fails if the set GROWS. A read added anywhere else works perfectly in dev — the
    // fallback answers — and is baked into the artifact in production, which is the whole
    // property this spec exists to establish.
    const readers = Object.entries(SOURCES)
      .filter(([path]) => !path.includes('.test.') && !path.includes('/test/'))
      .filter(([, source]) => /import\.meta\.env\.VITE_/.test(String(source)))
      .map(([path]) => path);

    expect(Object.keys(SOURCES).length).toBeGreaterThan(0);
    expect(readers.sort()).toEqual([...ALLOWED].sort());
  });

  it('exports the converted reads as functions, not captured values', () => {
    // Each was a module-scope const. As a const the value is captured before the document
    // is in hand — a throw in production, and in a test the deployed name rather than the
    // stubbed one. A later re-collapse is a failing test here rather than a boot failure.
    expect(typeof isAmplifyConfigured).toBe('function');
    expect(typeof maxUploadBytes).toBe('function');
  });
});

describe('runtimeConfig — every key has a source in every environment', () => {
  /**
   * `.env.example` through `node:fs`, where every other source here comes in through
   * Vite's own `?raw`.
   *
   * Vite refuses it: `server.fs.deny` defaults to `.env` and `.env.*`, and the transform
   * pipeline enforces that for a `?raw` id too — measured, as `Denied ID …/.env.example`.
   * Relaxing the deny list to make one test convenient would weaken the guard that keeps
   * a real `.env` out of a served bundle.
   *
   * Two literal paths rather than a constructed one: `security/detect-non-literal-fs-filename`
   * is on, and both are the same file from the two directories a runner starts in.
   */
  function readEnvExample(): string {
    try {
      return readFileSync('.env.example', 'utf8');
    } catch {
      return readFileSync('apps/portal/.env.example', 'utf8');
    }
  }

  const ENV_EXAMPLE = readEnvExample();

  /**
   * The task definition that serves the container's document — and, since `deploy-app.yml`
   * was deleted with the distribution it fed, the ONLY infrastructure statement of the key
   * set. The four tests that compared this classification against that workflow's build env,
   * its render step and its own `KEYS` list went with it: a test asserting the shape of a
   * deleted file is not a guard, it is a parse error waiting for the next run.
   * Two files, because the wiring is split on purpose — root names the keys and their
   * values, and the module renders one environment entry per key without naming any of them.
   *
   * THERE IS A SIXTH, and it is not asserted here: the container's entrypoint, which turns
   * those environment variables into the served document. It is checked in
   * `lambdas/test_spa_image.py`, with the rest of the image's agreements, because nothing
   * in this suite can read a shell script's key list against a Dockerfile's user and a
   * task definition's mounts. A key added to the classification must reach it too.
   *
   * That sentence was FALSE for as long as it stood: no test over there read the entrypoint's
   * `KEYS` against this classification, so the one wiring point whose staleness is silent —
   * a key MISSING there refuses to start, a key LEFT BEHIND publishes quietly — was the one
   * nothing compared. The two tests it names now exist.
   */
  const ROOT_MAIN = Object.values(
    import.meta.glob('../../../../infra/main.tf', {query: '?raw', import: 'default', eager: true})
  )[0] as string;

  /** The keys of root's `spa_runtime_config` map — the infrastructure's whole statement of the set. */
  function runtimeConfigKeys(): string[] {
    const start = ROOT_MAIN.indexOf('spa_runtime_config = {');
    expect(start).toBeGreaterThan(-1);
    const body = ROOT_MAIN.slice(start, ROOT_MAIN.indexOf('\n  }', start));
    return [...body.matchAll(/^\s{4}([A-Za-z][A-Za-z0-9]*)\s*=/gm)].map(([, key]) => key);
  }

  const ALL_KEYS = [...REQUIRED_CONFIG, ...OPTIONAL_CONFIG];

  it('names every classified key in .env.example, and nothing it does not classify', () => {
    // ASSIGNMENT LINES ONLY. A free-text scrape also finds the variable a comment
    // records as removed, which is history worth keeping and not a variable at all.
    const assigned = new Set([...ENV_EXAMPLE.matchAll(/^(VITE_[A-Z0-9_]+)=/gm)].map(([, name]) => name));
    const classified = new Set<string>(ALL_KEYS.map((key) => VITE_NAME[key]).filter((name) => name !== null));

    expect([...assigned].filter((name) => !classified.has(name))).toEqual([]);
    expect([...classified].filter((name) => !assigned.has(name))).toEqual([]);
  });

  it('names every classified key in the ECS task definition\u2019s source map', () => {
    // The container is the fifth wiring point, and it is the one that will serve production
    // after the cutover. A key missing here ships a container whose document lacks it while
    // every other leg stays green \u2014 one feature silently unconfigured, in the environment
    // that matters most.
    const keys = runtimeConfigKeys();

    // Guard-the-guard: a parse that silently found nothing would agree with an empty
    // classification and pass forever. Named rather than counted — a count has to be
    // revised by every key retirement, and revising it is where the guard gets lost.
    expect(keys).toContain('apiBaseUrl');
    expect(keys.slice().sort()).toEqual([...ALL_KEYS].sort());
  });

  it('gives appUrl the container\u2019s own origin, not the CloudFront one', () => {
    // The highest-consequence line in the map, and the one that fails ONLY in a browser:
    // Amplify builds redirectSignIn/redirectSignOut from appUrl, so a container serving
    // var.app_url sends a sign-in started on the container back to CloudFront. The container
    // never receives the ?code=, and the user lands signed-out on a live session.
    const start = ROOT_MAIN.indexOf('spa_runtime_config = {');
    const body = ROOT_MAIN.slice(start, ROOT_MAIN.indexOf('\n  }', start));

    expect(body).toMatch(/^\s+appUrl\s*=\s*local\.spa_origin$/m);
    expect(body).not.toMatch(/^\s+appUrl\s*=\s*var\.app_url$/m);
  });
});
