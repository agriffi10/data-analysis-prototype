import {describe, it, expect, vi, beforeEach} from 'vitest';
import {SQSClient} from '@aws-sdk/client-sqs';

// The client builder's only real dependency is the shared credential provider —
// mock that boundary and assert the ServiceResult wiring (success + both failure
// passthroughs). The AWS SDK client itself is constructed for real (no network).
vi.mock('./awsCredentials', () => ({getSessionCredentials: vi.fn()}));

import {getSessionCredentials} from './awsCredentials';
import {getSqsClient} from './sqsClient';

const mockCreds = vi.mocked(getSessionCredentials);

const credentials = {
  accessKeyId: 'AKIAEXAMPLE',
  secretAccessKey: 'secret',
  sessionToken: 'token'
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('getSqsClient', () => {
  it('returns an SQSClient built from the session credentials', async () => {
    mockCreds.mockResolvedValueOnce({success: true, data: credentials as never});

    const result = await getSqsClient();

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data).toBeInstanceOf(SQSClient);
    expect(mockCreds).toHaveBeenCalledWith(false);
  });

  it('passes forceRefresh through for the credential-expiry retry path', async () => {
    mockCreds.mockResolvedValueOnce({success: true, data: credentials as never});

    await getSqsClient(true);

    expect(mockCreds).toHaveBeenCalledWith(true);
  });

  it('returns the credential error (no throw) when there are no credentials', async () => {
    mockCreds.mockResolvedValueOnce({
      success: false,
      error: {message: 'No AWS credentials — sign in required'}
    });

    const result = await getSqsClient();

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.message).toMatch(/sign in/i);
  });

  it('surfaces a credential-provider failure as a ServiceResult error', async () => {
    mockCreds.mockResolvedValueOnce({
      success: false,
      error: {message: 'network down', code: 'NetworkError'}
    });

    const result = await getSqsClient();

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('NetworkError');
  });
});
