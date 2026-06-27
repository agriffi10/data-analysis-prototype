import {describe, it, expect, vi, beforeEach, type MockedFunction} from 'vitest';
import {S3Client} from '@aws-sdk/client-s3';

vi.mock('aws-amplify/auth', () => ({fetchAuthSession: vi.fn()}));

import {fetchAuthSession} from 'aws-amplify/auth';
import {getS3Client} from './s3Client';

const mockFetch = fetchAuthSession as unknown as MockedFunction<(opts?: {forceRefresh?: boolean}) => Promise<unknown>>;

const credentials = {
  accessKeyId: 'AKIAEXAMPLE',
  secretAccessKey: 'secret',
  sessionToken: 'token'
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('getS3Client', () => {
  it('returns an S3Client built from the session credentials', async () => {
    mockFetch.mockResolvedValueOnce({credentials});

    const result = await getS3Client();

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data).toBeInstanceOf(S3Client);
    expect(mockFetch).toHaveBeenCalledWith({forceRefresh: false});
  });

  it('returns an error (no throw) when there are no credentials', async () => {
    mockFetch.mockResolvedValueOnce({}); // signed out / expired

    const result = await getS3Client();

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.message).toMatch(/sign in/i);
  });

  it('passes forceRefresh through for the credential-expiry retry path', async () => {
    mockFetch.mockResolvedValueOnce({credentials});

    await getS3Client(true);

    expect(mockFetch).toHaveBeenCalledWith({forceRefresh: true});
  });

  it('returns an error result (never throws) when fetchAuthSession rejects', async () => {
    mockFetch.mockRejectedValueOnce(Object.assign(new Error('network down'), {name: 'NetworkError'}));

    const result = await getS3Client();

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.message).toBe('network down');
    expect(result.error.code).toBe('NetworkError');
  });
});
