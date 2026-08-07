import {beforeEach, describe, expect, it, vi} from 'vitest';
import type {MockedFunction} from 'vitest';
import {AthenaClient} from '@aws-sdk/client-athena';
import {fetchAuthSession} from 'aws-amplify/auth';
import {getAthenaClient} from './athenaClient';
import {GlueClient} from '@aws-sdk/client-glue';
import {getGlueClient} from './glueClient';
import {S3Client} from '@aws-sdk/client-s3';
import {getS3Client} from './s3Client';
import {toUserMessage} from './errorMessages';
import {getIdToken, getSessionCredentials} from './awsCredentials';

// ─── from athenaClient.test.ts ───
vi.mock('aws-amplify/auth', () => ({fetchAuthSession: vi.fn()}));

describe('athenaClient', () => {
  const mockFetch = fetchAuthSession as unknown as MockedFunction<
    (opts?: {forceRefresh?: boolean}) => Promise<unknown>
  >;

  const credentials = {
    accessKeyId: 'AKIAEXAMPLE',
    secretAccessKey: 'secret',
    sessionToken: 'token'
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('getAthenaClient', () => {
    it('returns an AthenaClient built from the session credentials', async () => {
      mockFetch.mockResolvedValueOnce({credentials});

      const result = await getAthenaClient();

      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.data).toBeInstanceOf(AthenaClient);
      expect(mockFetch).toHaveBeenCalledWith({forceRefresh: false});
    });

    it('returns an error (no throw) when there are no credentials', async () => {
      mockFetch.mockResolvedValueOnce({}); // signed out / expired

      const result = await getAthenaClient();

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.error.message).toMatch(/sign in/i);
    });

    it('passes forceRefresh through for the credential-expiry retry path', async () => {
      mockFetch.mockResolvedValueOnce({credentials});

      await getAthenaClient(true);

      expect(mockFetch).toHaveBeenCalledWith({forceRefresh: true});
    });

    it('returns an error result (never throws) when fetchAuthSession rejects', async () => {
      mockFetch.mockRejectedValueOnce(Object.assign(new Error('network down'), {name: 'NetworkError'}));

      const result = await getAthenaClient();

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.error.message).toBe('network down');
      expect(result.error.code).toBe('NetworkError');
    });
  });
});

// ─── from glueClient.test.ts ───

describe('glueClient', () => {
  const mockFetch = fetchAuthSession as unknown as MockedFunction<
    (opts?: {forceRefresh?: boolean}) => Promise<unknown>
  >;

  const credentials = {
    accessKeyId: 'AKIAEXAMPLE',
    secretAccessKey: 'secret',
    sessionToken: 'token'
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('getGlueClient', () => {
    it('returns a GlueClient built from the session credentials', async () => {
      mockFetch.mockResolvedValueOnce({credentials});

      const result = await getGlueClient();

      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.data).toBeInstanceOf(GlueClient);
      expect(mockFetch).toHaveBeenCalledWith({forceRefresh: false});
    });

    it('returns an error (no throw) when there are no credentials', async () => {
      mockFetch.mockResolvedValueOnce({});

      const result = await getGlueClient();

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.error.message).toMatch(/sign in/i);
    });

    it('passes forceRefresh through for the credential-expiry retry path', async () => {
      mockFetch.mockResolvedValueOnce({credentials});

      await getGlueClient(true);

      expect(mockFetch).toHaveBeenCalledWith({forceRefresh: true});
    });

    it('returns an error result (never throws) when fetchAuthSession rejects', async () => {
      mockFetch.mockRejectedValueOnce(Object.assign(new Error('network down'), {name: 'NetworkError'}));

      const result = await getGlueClient();

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.error.code).toBe('NetworkError');
    });
  });
});

// ─── from s3Client.test.ts ───

describe('s3Client', () => {
  const mockFetch = fetchAuthSession as unknown as MockedFunction<
    (opts?: {forceRefresh?: boolean}) => Promise<unknown>
  >;

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
});

// ─── from awsCredentials.test.ts ───

describe('awsCredentials', () => {
  const mockSession = vi.mocked(fetchAuthSession);

  beforeEach(() => vi.clearAllMocks());

  describe('getSessionCredentials', () => {
    it('returns the session credentials on success', async () => {
      const credentials = {accessKeyId: 'AKIA', secretAccessKey: 's', sessionToken: 't'};
      mockSession.mockResolvedValue({credentials} as never);
      const result = await getSessionCredentials();
      expect(result).toEqual({success: true, data: credentials});
    });

    it('fails when the session has no credentials', async () => {
      mockSession.mockResolvedValue({} as never);
      const result = await getSessionCredentials();
      expect(result.success).toBe(false);
    });

    it('passes forceRefresh through to Amplify', async () => {
      mockSession.mockResolvedValue({credentials: {accessKeyId: 'AKIA'}} as never);
      await getSessionCredentials(true);
      expect(mockSession).toHaveBeenCalledWith({forceRefresh: true});
    });
  });

  describe('getIdToken', () => {
    it('returns the ID token string on success', async () => {
      mockSession.mockResolvedValue({tokens: {idToken: {toString: () => 'jwt-abc'}}} as never);
      const result = await getIdToken();
      expect(result).toEqual({success: true, data: 'jwt-abc'});
    });

    it('fails when no ID token is present', async () => {
      mockSession.mockResolvedValue({tokens: {}} as never);
      const result = await getIdToken();
      expect(result.success).toBe(false);
    });

    it('maps a thrown error to a ServiceResult with its name as code', async () => {
      mockSession.mockRejectedValue(Object.assign(new Error('network down'), {name: 'NetworkError'}));
      const result = await getIdToken();
      expect(result).toEqual({success: false, error: {message: 'network down', code: 'NetworkError'}});
    });
  });
});
