import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {FEATURE_FLAGS_KEY, getFeatureFlags} from './featureFlags.service';
import {FEATURE_FLAG_DEFAULTS, FEATURE_FLAG_KEYS} from './featureFlagDefaults';
import {getS3Client} from '../../lib/s3Client';

vi.mock('../../lib/s3Client', () => ({getS3Client: vi.fn()}));

const send = vi.fn();

const awsError = (name: string, status?: number) =>
  Object.assign(new Error(name), {name, $metadata: status ? {httpStatusCode: status} : {}});

const body = (value: unknown) => ({
  Body: {transformToString: async () => (typeof value === 'string' ? value : JSON.stringify(value))}
});

const document = (over: Record<string, unknown> = {}) => ({
  version: 1,
  defaults: {files: true, query: true, sharedWorkspaces: true, dataQuality: true, dataExplorer: true},
  environments: {prod: {}},
  ...over
});

const allOn = {files: true, query: true, sharedWorkspaces: true, dataQuality: true, dataExplorer: true};

beforeEach(() => {
  vi.clearAllMocks();
  send.mockReset();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.mocked(getS3Client).mockResolvedValue({success: true, data: {send} as never});
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('getFeatureFlags — where it reads', () => {
  it('reads the key deploy-config.yml publishes, from the user-space bucket', async () => {
    send.mockResolvedValue(body(document()));

    const result = await getFeatureFlags('prod');

    expect(FEATURE_FLAGS_KEY).toBe('_config/feature-flags.json');
    expect(send.mock.calls[0][0].input).toMatchObject({Bucket: 'user-space', Key: '_config/feature-flags.json'});
    expect(result).toEqual({success: true, data: allOn});
  });

  it('reads the bucket name at call time, not module load', async () => {
    // A module-level `import.meta.env` const would have been captured before `stubEnv` ran.
    vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'a-different-bucket');
    send.mockResolvedValue(body(document()));

    await getFeatureFlags('prod');

    expect(send.mock.calls[0][0].input.Bucket).toBe('a-different-bucket');
  });
});

describe('getFeatureFlags — resolution', () => {
  it('merges the named environment over the defaults', async () => {
    send.mockResolvedValue(body(document({environments: {prod: {query: false, dataQuality: false}}})));

    expect(await getFeatureFlags('prod')).toEqual({
      success: true,
      data: {files: true, query: false, sharedWorkspaces: true, dataQuality: false, dataExplorer: true}
    });
  });

  it('honours a partial environment block, inheriting the rest', async () => {
    send.mockResolvedValue(body(document({defaults: {...allOn, files: false}, environments: {prod: {query: false}}})));

    expect(await getFeatureFlags('prod')).toMatchObject({data: {files: false, query: false, sharedWorkspaces: true}});
  });

  it('resolves an environment the document does not name to the defaults, and calls it a success', async () => {
    // Not an error: the document was fetched and understood. FR-004 is explicit that this
    // reports 'ready' — an environment with no block has simply overridden nothing.
    send.mockResolvedValue(body(document({defaults: {...allOn, query: false}})));

    expect(await getFeatureFlags('staging')).toEqual({success: true, data: {...allOn, query: false}});
  });

  it('resolves an UNSET environment to the defaults rather than crashing', async () => {
    // FR-007: an unwired VITE_ENVIRONMENT must never white-screen the app.
    send.mockResolvedValue(body(document({defaults: {...allOn, query: false}})));

    expect(await getFeatureFlags(undefined)).toEqual({success: true, data: {...allOn, query: false}});
  });

  it('always returns all five keys as booleans, whatever the document named', async () => {
    // The resolver walks the KEY LIST, not the document, so no consumer ever sees undefined.
    send.mockResolvedValue(body(document({defaults: {}, environments: {}})));

    const result = await getFeatureFlags('prod');

    expect(result).toMatchObject({success: true});
    const flags = (result as {data: Record<string, unknown>}).data;
    expect(Object.keys(flags).sort()).toEqual([...FEATURE_FLAG_KEYS].sort());
    expect(Object.values(flags).every((value) => typeof value === 'boolean')).toBe(true);
  });
});

describe('getFeatureFlags — one bad value is not a bad document', () => {
  it('falls back for that KEY ONLY when a default is malformed', async () => {
    // FR-005: one string where a boolean belonged must not discard three good values.
    send.mockResolvedValue(body(document({defaults: {...allOn, query: 'false', sharedWorkspaces: false}})));

    expect(await getFeatureFlags('prod')).toEqual({
      success: true,
      // `query` takes the compiled-in default (true), NOT the string's truthiness — which
      // would happen to agree here and disagree for `"false"` in a document whose default
      // was off, so the assertion below pins the source rather than the value.
      data: {
        files: true,
        query: FEATURE_FLAG_DEFAULTS.query,
        sharedWorkspaces: false,
        dataQuality: true,
        dataExplorer: true
      }
    });
  });

  it('falls back for that key only when an ENVIRONMENT override is malformed', async () => {
    send.mockResolvedValue(
      body(document({defaults: {...allOn, files: false, query: false}, environments: {prod: {query: 'true'}}}))
    );

    // The malformed override is skipped and the document's own default takes over — the
    // compiled-in default is the LAST resort, not the first.
    expect(await getFeatureFlags('prod')).toMatchObject({data: {files: false, query: false}});
  });

  it('ignores an unknown flag key rather than carrying it through', async () => {
    send.mockResolvedValue(body(document({defaults: {...allOn, quries: false}})));

    const result = await getFeatureFlags('prod');

    expect(result).toEqual({success: true, data: allOn});
  });

  it('ignores an environment block that is not an object', async () => {
    send.mockResolvedValue(body(document({environments: {prod: 'off'}})));

    expect(await getFeatureFlags('prod')).toEqual({success: true, data: allOn});
  });
});

describe('getFeatureFlags — an unusable document is a FAILURE, not an empty success', () => {
  // This is the one place this service diverges from getUserDirectory(), and it is
  // load-bearing: the compiled-in fallback is all-on, which is indistinguishable from a
  // healthy environment, so the distinction has to survive the return or 'fallback' could
  // never be reported.

  it('refuses an unparseable body', async () => {
    send.mockResolvedValue(body('{not json'));

    expect(await getFeatureFlags('prod')).toMatchObject({success: false, error: {code: 'FeatureFlagsUnusable'}});
  });

  it('refuses a version it does not understand, and names it', async () => {
    send.mockResolvedValue(body(document({version: 2})));

    const result = await getFeatureFlags('prod');

    expect(result).toMatchObject({success: false});
    expect((result as {error: {message: string}}).error.message).toContain('2');
  });

  it('refuses a document with no usable defaults block', async () => {
    send.mockResolvedValue(body(document({defaults: 'all-on'})));

    expect(await getFeatureFlags('prod')).toMatchObject({success: false});
  });

  it('refuses a body that is a JSON array', async () => {
    send.mockResolvedValue(body([{files: true}]));

    expect(await getFeatureFlags('prod')).toMatchObject({success: false});
  });

  it('refuses an empty body', async () => {
    send.mockResolvedValue(body(''));

    expect(await getFeatureFlags('prod')).toMatchObject({success: false});
  });

  it('refuses a MISSING document rather than treating it as a starting state', async () => {
    // Unlike the username directory, absence here is not "the builder has not run yet" — it
    // means the publish workflow has never reached this bucket, which is a deploy defect.
    send.mockRejectedValue(awsError('NoSuchKey', 404));

    expect(await getFeatureFlags('prod')).toMatchObject({success: false});
  });

  it('reports a blocked read as a failure, and never throws', async () => {
    send.mockRejectedValue(awsError('AccessDenied', 403));

    await expect(getFeatureFlags('prod')).resolves.toMatchObject({success: false});
  });

  it('reports a client that could not be built as a failure', async () => {
    vi.mocked(getS3Client).mockResolvedValue({success: false, error: {message: 'no credentials'}});

    expect(await getFeatureFlags('prod')).toMatchObject({success: false});
  });
});

// Sources are pulled in through Vite's own glob rather than `node:fs`, so the app's
// tsconfig keeps its browser-only `types` list — adding `"node"` to it would let ordinary
// app code import a Node builtin and still typecheck, which is a far bigger hole than these
// three sweeps are worth.
// The options object must be an inline literal — Vite parses this call statically and
// refuses a shared constant.
const FLAG_DOCUMENT = import.meta.glob('../../../../../config/feature-flags.json', {
  query: '?raw',
  import: 'default',
  eager: true
}) as Record<string, string>;
const SERVICE_SOURCES = import.meta.glob('../**/*.service.ts', {
  query: '?raw',
  import: 'default',
  eager: true
}) as Record<string, string>;
const LIB_SOURCES = import.meta.glob('../../lib/**/*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true
}) as Record<string, string>;

describe('the compiled-in defaults and the checked-in document', () => {
  it('cannot drift apart', () => {
    // FR-005: the file and the fallback are two statements of the same answer. If a flag is
    // ever born OFF, this test is what forces both to say so.
    const source = Object.values(FLAG_DOCUMENT)[0];
    expect(source, 'config/feature-flags.json was not readable from the test').toBeTypeOf('string');
    const onDisk = JSON.parse(source) as {defaults: Record<string, boolean>};

    expect(onDisk.defaults).toEqual(FEATURE_FLAG_DEFAULTS);
  });

  it('names every flag key exactly once', () => {
    expect([...FEATURE_FLAG_KEYS].sort()).toEqual(Object.keys(FEATURE_FLAG_DEFAULTS).sort());
    expect(new Set(FEATURE_FLAG_KEYS).size).toBe(FEATURE_FLAG_KEYS.length);
  });
});

describe('a flag is never an authorization input (FR-006)', () => {
  // THE BOUNDARY THAT KEEPS THIS FEATURE HONEST. A flag hides a tab; it must never decide
  // whether a request is made, which bucket it targets, or what a credential may do — those
  // answers belong to IAM, which a presentation document cannot reach. The failure mode is
  // not subtle in hindsight and is very easy to reach in a hurry: `if (flags.query) return`
  // inside a service reads like a guard and is actually a client-side access control, which
  // is no control at all.
  //
  // Enforced by reading the source rather than by convention, because the convention is
  // exactly what an urgent change forgets.
  const notATest = ([path]: [string, string]) => !path.includes('.test.');
  const notTheFlagsFeature = ([path]: [string, string]) => !path.includes('/feature-flags/');

  const SERVICES = Object.entries(SERVICE_SOURCES).filter(notATest).filter(notTheFlagsFeature);
  const LIB = Object.entries(LIB_SOURCES).filter(notATest);

  it('found the files it claims to check', () => {
    // Guards the guard: a sweep that matches nothing passes silently forever.
    expect(SERVICES.length).toBeGreaterThan(10);
    expect(LIB.length).toBeGreaterThan(20);
  });

  it.each([
    ['services', () => SERVICES],
    ['lib', () => LIB]
  ])('no file under %s imports the feature-flags module', (_label, get) => {
    const offenders = get()
      .filter(([, source]) => /from '[^']*feature-flags/.test(source))
      .map(([path]) => path);

    expect(offenders).toEqual([]);
  });

  it('the flags module itself reaches no authorization surface', () => {
    // The other direction: the resolver must not grow a branch on who the user is. Its only
    // inputs are the document and the environment name.
    const [, source] = Object.entries(SERVICE_SOURCES).find(([path]) => path.endsWith('featureFlags.service.ts'))!;

    expect(source).not.toMatch(/PrincipalTag|fetchAuthSession|assumeRole|IamPolicy/i);
  });
});
