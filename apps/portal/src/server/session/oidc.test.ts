import {afterEach, describe, expect, it, vi} from 'vitest';
import {TOKEN_ENDPOINT_TIMEOUT_MS, refreshTokens} from './oidc';
import {NOW, testConfig} from './testSupport';

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('the token endpoint', () => {
  it('answers unavailable when the endpoint has not answered after five seconds, and not before', async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => init.signal?.addEventListener('abort', () => reject(init.signal?.reason)))
      )
    );
    let settled = false;

    const refreshed = refreshTokens(testConfig(), 'refresh', NOW).finally(() => {
      settled = true;
    });
    await vi.advanceTimersByTimeAsync(TOKEN_ENDPOINT_TIMEOUT_MS - 1);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1);

    expect(await refreshed).toEqual({ok: false, failure: 'unavailable'});
    expect(TOKEN_ENDPOINT_TIMEOUT_MS).toBe(5_000);
  });
});
