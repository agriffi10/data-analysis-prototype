import {readFileSync} from 'node:fs';
import {describe, it, expect, vi, afterEach} from 'vitest';
import {configValue, isPortalConfigured, loadRuntimeConfig} from './runtimeConfig';
import {VITE_NAME} from './env';
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

    expect(fetchMock).toHaveBeenCalledWith('/config.json', {cache: 'no-store'});
  });

  it('serves every key from the document once loaded', async () => {
    respondWith(JSON.stringify({version: 1, ...COMPLETE}));

    await loadRuntimeConfig();

    expect(configValue('userSpaceBucket')).toBe('served-userSpaceBucket');
    expect(configValue('archiveQueueUrl')).toBe('served-archiveQueueUrl');
    expect(isPortalConfigured()).toBe(true);
  });

  it('reads an empty string as unset', () => {
    seedRuntimeConfig({...COMPLETE, sharedSpaceBucket: ''});

    expect(configValue('sharedSpaceBucket')).toBeUndefined();
  });

  it('reads a non-string value as unset', () => {
    // The document's contract is strings. A number that arrived by accident must not
    // reach an SDK as one.
    seedRuntimeConfig({...COMPLETE, maxUploadBytes: 5368709120 as unknown as string});

    expect(configValue('maxUploadBytes')).toBeUndefined();
  });

  it('ignores a key it does not classify', async () => {
    // A task definition ahead of the image must not break the image.
    respondWith(JSON.stringify({version: 1, ...COMPLETE, somethingLater: 'x'}));

    const result = await loadRuntimeConfig();

    expect(result.ok).toBe(true);
    expect(configValue('userSpaceBucket')).toBe('served-userSpaceBucket');
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

  it('reports unparseable for a 200 carrying the app shell', async () => {
    // THE CASE A LOADER KEYED ON `response.ok` GETS WRONG. The static site answers a
    // missing object with its own index.html under a 200, so this is what a deployment
    // that forgot to publish the document actually returns.
    const shell = Object.values(
      import.meta.glob('../../index.html', {query: '?raw', import: 'default', eager: true})
    )[0] as string;
    expect(shell).toContain('<html');

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => JSON.parse(shell) as unknown
      })
    );
    const {loadRuntimeConfig: load} = await productionModule();

    expect(await load()).toEqual({ok: false, reason: 'unparseable'});
  });

  it('reports unparseable for JSON that is not an object', async () => {
    respondWith('[]');
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
    respondWith(JSON.stringify({version: 1, ...withoutKeys('userSpaceBucket', 'athenaWorkgroup')}));
    const {loadRuntimeConfig: load} = await productionModule();

    const result = await load();

    expect(result).toEqual({
      ok: false,
      reason: 'missing-required',
      missing: ['userSpaceBucket', 'athenaWorkgroup']
    });
  });

  it('boots with every optional key absent', async () => {
    const required = Object.fromEntries(REQUIRED_CONFIG.map((key) => [key, `served-${key}`]));
    respondWith(JSON.stringify({version: 1, ...required}));
    const {loadRuntimeConfig: load, configValue: read} = await productionModule();

    expect(await load()).toEqual({ok: true});
    // The flags feature resolves the document's own defaults when this is absent, which
    // is why an unset one must not stop the app booting.
    expect(read('environment')).toBeUndefined();
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
    const paired = [...REQUIRED_CONFIG, ...OPTIONAL_CONFIG].filter((key) => VITE_NAME[key] !== null);
    expect(paired).toHaveLength(19);

    for (const key of paired) vi.stubEnv(VITE_NAME[key] as string, `env-${key}`);

    for (const key of paired) expect(configValue(key)).toBe(`env-${key}`);
  });

  it('has no fallback for a key with no VITE_ variable', () => {
    // Nothing in the browser reads it yet, so a variable for it would be dead weight in
    // every .env file. The document is its only source.
    expect(VITE_NAME.apiBaseUrl).toBeNull();
    expect(configValue('apiBaseUrl')).toBeUndefined();
  });

  it('survives a failed load and keeps answering', async () => {
    vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'local-bucket');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('no server')));

    expect(await loadRuntimeConfig()).toEqual({ok: true});
    expect(configValue('userSpaceBucket')).toBe('local-bucket');
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

describe('runtimeConfig — nothing bakes a document into the image', () => {
  it('has no committed public/config.json', () => {
    // Files in public/ are copied verbatim into dist/, so a committed one would be built
    // into the image and served in preference to the rendered document — a build-time
    // configuration wearing the runtime mechanism's clothes.
    const published = import.meta.glob('../../public/**', {query: '?raw', import: 'default', eager: true});

    // Asserted non-empty first: a glob that matches nothing would pass this by finding
    // nothing, forever.
    expect(Object.keys(published).length).toBeGreaterThan(0);
    expect(Object.keys(published).filter((path) => path.endsWith('/config.json'))).toEqual([]);
  });
});

describe('runtimeConfig — every key has a source in every environment', () => {
  /**
   * Read behind an `import.meta.env.DEV` guard at their own call sites, so they are
   * deliberately absent from the classification.
   */
  const DEV_ONLY = new Set([
    'VITE_S3_DEV_UNAUTH',
    'VITE_S3_BUCKET_NAME',
    'VITE_S3_ROOT_PREFIX',
    'VITE_AWS_ACCESS_KEY_ID',
    'VITE_AWS_SECRET_ACCESS_KEY'
  ]);

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

  const DEPLOY_WORKFLOW = Object.values(
    import.meta.glob('../../../../.github/workflows/deploy-app.yml', {
      query: '?raw',
      import: 'default',
      eager: true
    })
  )[0] as string;

  const ALL_KEYS = [...REQUIRED_CONFIG, ...OPTIONAL_CONFIG];

  /** The step's body, so the two `env:` blocks in this workflow are never confused. */
  function stepBody(name: string): string {
    const start = DEPLOY_WORKFLOW.indexOf(`- name: ${name}`);
    expect(start).toBeGreaterThan(-1);
    const next = DEPLOY_WORKFLOW.indexOf('\n      - name: ', start + 1);
    return DEPLOY_WORKFLOW.slice(start, next === -1 ? undefined : next);
  }

  it('reads both sources', () => {
    // Each leg is a file this test does not own. A moved or renamed one must be a red
    // here rather than a comparison against an empty string.
    expect(ENV_EXAMPLE).toContain('VITE_AWS_REGION=');
    expect(DEPLOY_WORKFLOW).toContain('jobs:');
  });

  it('names every classified key in .env.example, and nothing it does not classify', () => {
    // ASSIGNMENT LINES ONLY. A free-text scrape also finds the variable a comment
    // records as removed, which is history worth keeping and not a variable at all.
    const assigned = new Set([...ENV_EXAMPLE.matchAll(/^(VITE_[A-Z0-9_]+)=/gm)].map(([, name]) => name));
    const classified = new Set<string>(ALL_KEYS.map((key) => VITE_NAME[key]).filter((name) => name !== null));

    expect([...assigned].filter((name) => !classified.has(name) && !DEV_ONLY.has(name))).toEqual([]);
    expect([...classified].filter((name) => !assigned.has(name))).toEqual([]);
  });

  it('passes every classified variable to the build', () => {
    const build = stepBody('Build');
    const passed = new Set([...build.matchAll(/^\s+(VITE_[A-Z0-9_]+):/gm)].map(([, name]) => name));
    const classified = [...ALL_KEYS.map((key) => VITE_NAME[key]).filter((name) => name !== null)];

    expect(classified.filter((name) => !passed.has(name as string))).toEqual([]);
  });

  it('renders every classified key into the document', () => {
    // THE LEG THAT ACTUALLY DECIDES WHAT PRODUCTION READS. After the switchover the
    // build env feeds a fallback no deployment consults; this step is the sole producer
    // of every served value, so a key missing here ships a document without it while
    // every other leg stays green.
    const render = stepBody('Render the runtime configuration document');
    const rendered = new Map(
      [...render.matchAll(/^\s+CONFIG_(\w+):\s*\$\{\{\s*vars\.(\w+)\s*\}\}/gm)].map(([, key, variable]) => [
        key,
        variable
      ])
    );

    expect([...rendered.keys()].sort()).toEqual([...ALL_KEYS].sort());
  });

  it('renders each key from the same repository variable the build reads', () => {
    // Both blocks must name ONE variable per key. Sourcing the document from a different
    // one than the bundle is the drift this whole test exists to catch, and it is
    // invisible in every environment where both happen to be set.
    const build = stepBody('Build');
    const buildSource = new Map(
      [...build.matchAll(/^\s+(VITE_[A-Z0-9_]+):\s*\$\{\{\s*vars\.(\w+)\s*\}\}/gm)].map(([, name, variable]) => [
        name,
        variable
      ])
    );
    const render = stepBody('Render the runtime configuration document');
    const renderSource = new Map(
      [...render.matchAll(/^\s+CONFIG_(\w+):\s*\$\{\{\s*vars\.(\w+)\s*\}\}/gm)].map(([, key, variable]) => [
        key,
        variable
      ])
    );

    for (const key of ALL_KEYS) {
      const viteName = VITE_NAME[key];
      if (viteName === null) {
        // The one key with no browser fallback still needs a source of its own.
        expect(renderSource.get(key)).toBeTruthy();
        continue;
      }
      expect(renderSource.get(key)).toBe(buildSource.get(viteName));
    }
  });

  it('refuses to publish a document missing exactly the keys this build calls required', () => {
    // The workflow cannot import the classification, so it restates the required set —
    // and a restatement that drifts publishes a document every browser then refuses to
    // boot on, which is the failure the check exists to pre-empt.
    const render = stepBody('Render the runtime configuration document');
    const declared = /REQUIRED='([^']+)'/.exec(render)?.[1]?.split(' ') ?? [];

    expect(declared.slice().sort()).toEqual([...REQUIRED_CONFIG].sort());
  });

  it('uploads the document with no-store, outside the passes that own dist/', () => {
    // A cached document is the failure this spec exists to prevent and the one nothing on
    // screen distinguishes, and a file touched by two sync passes silently takes the
    // second one's header.
    expect(DEPLOY_WORKFLOW).toMatch(/aws s3 cp[^\n]*config\.json[\s\S]{0,200}--cache-control 'no-store'/);
    expect(DEPLOY_WORKFLOW).not.toMatch(/dist\/config\.json/);
  });
});
