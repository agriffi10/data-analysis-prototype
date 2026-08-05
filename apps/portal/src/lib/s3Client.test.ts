import {describe, it, expect, vi, beforeEach, type MockedFunction} from 'vitest';
import {S3Client} from '@aws-sdk/client-s3';

vi.mock('aws-amplify/auth', () => ({fetchAuthSession: vi.fn()}));

import {fetchAuthSession} from 'aws-amplify/auth';
import {getS3Client} from './s3Client';
import {toUserMessage} from './errorMessages';

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

  it('codes the no-credentials failure NotAuthenticated, so a lapsed session says "Sign in to continue."', async () => {
    // SPEC-150 FR-005. `getS3Client` used to duplicate `fetchAuthSession` and omit
    // the code, so every S3-backed screen (files, notifications, saved queries,
    // query history, data quality) showed the GENERIC message on an expired session
    // while Athena/Glue/SQS — which route through `getSessionCredentials` — said the
    // right thing. The assertion is on the MAPPED text, not just the code: the code
    // is only a means to it.
    mockFetch.mockResolvedValueOnce({});

    const result = await getS3Client();

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('NotAuthenticated');
    expect(toUserMessage(result.error).message).toBe('Sign in to continue.');
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
