import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {headers} from 'next/headers';
import {heldFeatureFlags, resetServerFeatureFlagsForTests, serverFeatureFlags} from './featureFlags';
import {resolveFeatureFlagDocument} from '../features/feature-flags/resolveFeatureFlags';
import {FEATURE_FLAG_DEFAULTS} from '../features/feature-flags/featureFlagDefaults';
import {envelope, flagDocument, settle, signedInRequest} from './featureFlagsTestSupport';
import {environmentDeps} from './session/handlers';

vi.mock('next/headers', () => ({headers: vi.fn()}));
vi.mock('./session/handlers', () => ({environmentDeps: vi.fn()}));
vi.mock('../features/feature-flags/resolveFeatureFlags', () => ({resolveFeatureFlagDocument: vi.fn()}));

/** A set no real document resolves to from the body the API answers below. */
const SENTINEL = {...FEATURE_FLAG_DEFAULTS, files: false, archive: false};

beforeEach(async () => {
  resetServerFeatureFlagsForTests();
  await signedInRequest();
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => envelope(flagDocument()))
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  vi.mocked(headers).mockReset();
  vi.mocked(environmentDeps).mockReset();
});

describe('the server resolves a body only through the shared resolver', () => {
  it('holds what the resolver returned for the body the API answered and the server’s environment', async () => {
    vi.stubEnv('CONFIG_environment', 'staging');
    vi.mocked(resolveFeatureFlagDocument).mockReturnValue({success: true, data: SENTINEL});

    await serverFeatureFlags();
    await settle();

    expect(vi.mocked(resolveFeatureFlagDocument).mock.calls[0]).toEqual([JSON.stringify(flagDocument()), 'staging']);
    expect(heldFeatureFlags()?.flags).toEqual(SENTINEL);
  });

  it('holds nothing when the resolver refuses the body', async () => {
    vi.mocked(resolveFeatureFlagDocument).mockReturnValue({
      success: false,
      error: {message: 'refused', code: 'FeatureFlagsUnusable'}
    });
    vi.spyOn(console, 'error').mockImplementation(() => undefined);

    await serverFeatureFlags();
    await settle();

    expect(heldFeatureFlags()).toBeUndefined();
  });
});
