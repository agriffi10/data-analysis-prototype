import { describe, it, expect, vi, beforeEach, type MockedFunction } from 'vitest';
import { AthenaClient } from '@aws-sdk/client-athena';

vi.mock('aws-amplify/auth', () => ({ fetchAuthSession: vi.fn() }));

import { fetchAuthSession } from 'aws-amplify/auth';
import { getAthenaClient } from './athenaClient';

const mockFetch = fetchAuthSession as unknown as MockedFunction<
  (opts?: { forceRefresh?: boolean }) => Promise<unknown>
>;

const credentials = {
  accessKeyId: 'AKIAEXAMPLE',
  secretAccessKey: 'secret',
  sessionToken: 'token',
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('getAthenaClient', () => {
  it('returns an AthenaClient built from the session credentials', async () => {
    mockFetch.mockResolvedValueOnce({ credentials });

    const result = await getAthenaClient();

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data).toBeInstanceOf(AthenaClient);
    expect(mockFetch).toHaveBeenCalledWith({ forceRefresh: false });
  });

  it('returns an error (no throw) when there are no credentials', async () => {
    mockFetch.mockResolvedValueOnce({}); // signed out / expired

    const result = await getAthenaClient();

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.message).toMatch(/sign in/i);
  });

  it('passes forceRefresh through for the credential-expiry retry path', async () => {
    mockFetch.mockResolvedValueOnce({ credentials });

    await getAthenaClient(true);

    expect(mockFetch).toHaveBeenCalledWith({ forceRefresh: true });
  });

  it('returns an error result (never throws) when fetchAuthSession rejects', async () => {
    mockFetch.mockRejectedValueOnce(Object.assign(new Error('network down'), { name: 'NetworkError' }));

    const result = await getAthenaClient();

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.message).toBe('network down');
    expect(result.error.code).toBe('NetworkError');
  });
});
