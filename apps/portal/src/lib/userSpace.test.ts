import {describe, it, expect, afterEach, vi} from 'vitest';
import {sharedSpaceBucket, spaceBuckets, userSettingsKey, userSpaceBucket} from './userSpace';

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('the bucket getters', () => {
  it('read at CALL time, so a stub set after import is seen', () => {
    // The rule these getters exist to enforce: a module-level `import.meta.env` const
    // is captured before `vi.stubEnv` runs, and a test would then silently exercise
    // the deployed bucket names instead of its own.
    vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'test-user-space');
    vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'test-shared-space');

    expect(userSpaceBucket()).toBe('test-user-space');
    expect(sharedSpaceBucket()).toBe('test-shared-space');

    vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'a-different-bucket');
    expect(userSpaceBucket()).toBe('a-different-bucket');
  });
});

describe('spaceBuckets', () => {
  it('returns both buckets as a pair', () => {
    vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'test-user-space');
    vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'test-shared-space');

    expect(spaceBuckets()).toEqual({user: 'test-user-space', shared: 'test-shared-space'});
  });

  it('reports an unset bucket as undefined, so a caller can branch on absence', () => {
    // The shape the resolvers need: `undefined`, never the string "undefined" and never
    // the empty string an unset repository variable interpolates to.
    vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'test-user-space');
    vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', '');

    expect(spaceBuckets()).toEqual({user: 'test-user-space', shared: undefined});
  });
});

describe('userSettingsKey', () => {
  it('builds the protected per-user document path', () => {
    expect(userSettingsKey('alice', 'saved-queries.json')).toBe('alice/user_settings/saved-queries.json');
  });
});
