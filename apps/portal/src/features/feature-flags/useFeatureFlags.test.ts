import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {waitFor} from '@testing-library/react';
import {renderHookWithProviders} from '../../test/renderWithProviders';
import {unauthenticated} from '../../test/authFixtures';
import {useFeatureFlags} from './useFeatureFlags';
import {getFeatureFlags} from './featureFlags.service';
import {FEATURE_FLAG_DEFAULTS} from './featureFlagDefaults';

vi.mock('./featureFlags.service', () => ({getFeatureFlags: vi.fn()}));

const allOn = {files: true, query: true, sharedWorkspaces: true, dataQuality: true};

const resolved = (flags: Partial<typeof allOn> = {}) => ({success: true as const, data: {...allOn, ...flags}});

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv('VITE_ENVIRONMENT', 'prod');
  vi.mocked(getFeatureFlags).mockResolvedValue(resolved());
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('useFeatureFlags — status', () => {
  it('is loading before the document arrives and ready after', async () => {
    const {result} = renderHookWithProviders(() => useFeatureFlags(), {seedFeatureFlags: false});
    expect(result.current.status).toBe('loading');

    await waitFor(() => expect(result.current.status).toBe('ready'));
  });

  it('reports fallback when the document could not be used', async () => {
    vi.mocked(getFeatureFlags).mockResolvedValue({success: false, error: {message: 'unparseable'}});
    const {result} = renderHookWithProviders(() => useFeatureFlags(), {seedFeatureFlags: false});

    await waitFor(() => expect(result.current.status).toBe('fallback'));
    expect(result.current.flags).toEqual(FEATURE_FLAG_DEFAULTS);
  });

  it('does not fetch at all when there is no signed-in user', () => {
    const {result} = renderHookWithProviders(() => useFeatureFlags(), {
      auth: unauthenticated(),
      seedFeatureFlags: false
    });

    // 'fallback', not 'loading': a session with no user has nothing to read the document
    // WITH, so the compiled-in defaults really are in force. Reporting 'loading' there left
    // the dev-unauth path rendering a permanent spinner behind every gated route.
    expect(result.current.status).toBe('fallback');
    expect(result.current.flags).toEqual(FEATURE_FLAG_DEFAULTS);
    expect(getFeatureFlags).not.toHaveBeenCalled();
  });

  it('passes the build environment to the service', async () => {
    vi.stubEnv('VITE_ENVIRONMENT', 'staging');
    renderHookWithProviders(() => useFeatureFlags(), {seedFeatureFlags: false});

    await waitFor(() => expect(getFeatureFlags).toHaveBeenCalledWith('staging'));
  });

  it('passes undefined through when the variable is unwired', async () => {
    // FR-007: the app must not white-screen on a variable the deploy forgot.
    vi.stubEnv('VITE_ENVIRONMENT', '');
    const {result} = renderHookWithProviders(() => useFeatureFlags(), {seedFeatureFlags: false});

    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(getFeatureFlags).toHaveBeenCalledWith(undefined);
  });
});

describe('useFeatureFlags — flags', () => {
  it('holds the compiled-in defaults while the fetch is in flight', () => {
    // Everything visible, then something may go away. The other direction would hide a
    // feature the user has permission to use on the strength of a read that had not finished.
    const {result} = renderHookWithProviders(() => useFeatureFlags(), {seedFeatureFlags: false});

    expect(result.current.flags).toEqual(FEATURE_FLAG_DEFAULTS);
  });

  it('exposes the resolved set once ready', async () => {
    vi.mocked(getFeatureFlags).mockResolvedValue(resolved({query: false}));
    const {result} = renderHookWithProviders(() => useFeatureFlags(), {seedFeatureFlags: false});

    await waitFor(() => expect(result.current.flags.query).toBe(false));
    expect(result.current.flags).toEqual({...allOn, query: false});
  });

  it('never retries a failed read', async () => {
    vi.mocked(getFeatureFlags).mockResolvedValue({success: false, error: {message: 'boom'}});
    const {result} = renderHookWithProviders(() => useFeatureFlags(), {seedFeatureFlags: false});

    await waitFor(() => expect(result.current.status).toBe('fallback'));
    expect(getFeatureFlags).toHaveBeenCalledTimes(1);
  });
});

describe('useFeatureFlags — the dev diagnostic (FR-009)', () => {
  it('says which way the read went, and warns that an "off" is not applied', async () => {
    // The silent fallback means a working-looking app proves nothing. This is the only
    // channel that distinguishes the two, and it exists for the developer, not the user.
    const debug = vi.spyOn(console, 'debug').mockImplementation(() => {});
    vi.mocked(getFeatureFlags).mockResolvedValue({success: false, error: {message: 'boom'}});
    const {result} = renderHookWithProviders(() => useFeatureFlags(), {seedFeatureFlags: false});

    await waitFor(() => expect(result.current.status).toBe('fallback'));
    const lines = debug.mock.calls.map((call) => String(call[0]));
    expect(lines.some((line) => line.includes('[feature-flags] fallback'))).toBe(true);
    expect(lines.some((line) => line.includes('NOT applied'))).toBe(true);
  });

  it('says nothing at all while the read is still in flight', () => {
    const debug = vi.spyOn(console, 'debug').mockImplementation(() => {});
    renderHookWithProviders(() => useFeatureFlags(), {seedFeatureFlags: false});

    expect(debug).not.toHaveBeenCalled();
  });

  it('is never a user-facing surface', async () => {
    // FR-005: no banner, no toast. Nothing about the failure reaches the render tree, so the
    // only assertion available is that the hook's own contract has no place to put one.
    vi.spyOn(console, 'debug').mockImplementation(() => {});
    vi.mocked(getFeatureFlags).mockResolvedValue({success: false, error: {message: 'boom'}});
    const {result} = renderHookWithProviders(() => useFeatureFlags(), {seedFeatureFlags: false});

    await waitFor(() => expect(result.current.status).toBe('fallback'));
    expect(Object.keys(result.current).sort()).toEqual(['flags', 'status']);
  });
});
