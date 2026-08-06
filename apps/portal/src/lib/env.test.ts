import {describe, it, expect, afterEach, vi} from 'vitest';
import {REQUIRED_ENV, envVar, isPortalConfigured, missingRequiredEnv, warnIfMisconfigured} from './env';

/** Set every required variable, so a test can then unset exactly the one it cares about. */
function stubAllRequired(): void {
  for (const name of REQUIRED_ENV) vi.stubEnv(name, `value-for-${name}`);
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('envVar', () => {
  it('reads at CALL time, so a stub set after import is seen', () => {
    vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'test-bucket');
    expect(envVar('VITE_S3_USER_SPACE_BUCKET')).toBe('test-bucket');
  });

  it('treats the empty string as unset — an unset repo variable interpolates to ""', () => {
    vi.stubEnv('VITE_ATHENA_WORKGROUP', '');
    expect(envVar('VITE_ATHENA_WORKGROUP')).toBeUndefined();
  });
});

describe('missingRequiredEnv', () => {
  it('is empty when every required variable is set', () => {
    stubAllRequired();
    expect(missingRequiredEnv()).toEqual([]);
    expect(isPortalConfigured()).toBe(true);
  });

  it('names the variable that is missing', () => {
    stubAllRequired();
    vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', '');
    expect(missingRequiredEnv()).toEqual(['VITE_S3_USER_SPACE_BUCKET']);
    expect(isPortalConfigured()).toBe(false);
  });

  it('does not require the variables with their own degraded path', () => {
    // Each queue URL degrades through `enqueueFifo`'s notConfiguredMessage, the
    // shared bucket through "no shared spaces", the identity pool through
    // "signed in but no credentials" — one feature each, not the app.
    stubAllRequired();
    vi.stubEnv('VITE_TABLE_BUILD_QUEUE_URL', '');
    vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', '');
    vi.stubEnv('VITE_COGNITO_IDENTITY_POOL_ID', '');
    expect(isPortalConfigured()).toBe(true);
  });
});

describe('warnIfMisconfigured', () => {
  it('names every missing variable in dev', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    stubAllRequired();
    vi.stubEnv('VITE_AWS_REGION', '');
    vi.stubEnv('DEV', true);

    warnIfMisconfigured();

    expect(warn).toHaveBeenCalledOnce();
    expect(warn.mock.calls[0][0]).toContain('VITE_AWS_REGION');
  });

  it('says nothing when the portal is configured', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    stubAllRequired();
    vi.stubEnv('DEV', true);

    warnIfMisconfigured();

    expect(warn).not.toHaveBeenCalled();
  });

  it('stays silent in a production build even when a variable is missing', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    stubAllRequired();
    vi.stubEnv('VITE_AWS_REGION', ''); // genuinely missing, not merely absent from the ambient env
    vi.stubEnv('DEV', false);

    warnIfMisconfigured();

    expect(warn).not.toHaveBeenCalled();
  });
});
