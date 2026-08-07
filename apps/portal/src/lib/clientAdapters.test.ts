import {beforeEach, describe, expect, it, vi} from 'vitest';
import {SQSClient} from '@aws-sdk/client-sqs';
import {getSessionCredentials} from './awsCredentials';
import {getSqsClient} from './sqsClient';
import {readJsonDocument, writeJsonDocument} from './s3Json';
import {getS3Client} from './s3Client';
import type {ServiceResult} from '../types/service.types';

// ─── from sqsClient.test.ts ───
vi.mock('./awsCredentials', () => ({getSessionCredentials: vi.fn()}));

vi.mock('./s3Client', () => ({getS3Client: vi.fn()}));

describe('sqsClient', () => {
  // The client builder's only real dependency is the shared credential provider —
  // mock that boundary and assert the ServiceResult wiring (success + both failure
  // passthroughs). The AWS SDK client itself is constructed for real (no network).

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
});

// ─── from s3Json.test.ts ───

describe('s3Json', () => {
  const send = vi.fn();
  const mockGetS3Client = vi.mocked(getS3Client);

  /** An S3 GetObject response body, as the SDK hands it to the caller. */
  const body = (text: string) => ({Body: {transformToString: async () => text}});

  const awsError = (name: string, status?: number) =>
    Object.assign(new Error(name), {name, $metadata: status ? {httpStatusCode: status} : {}});

  const ok = <T>(data: T): ServiceResult<T> => ({success: true, data});

  beforeEach(() => {
    vi.clearAllMocks();
    send.mockReset();
    mockGetS3Client.mockResolvedValue({success: true, data: {send} as never});
  });

  describe('readJsonDocument', () => {
    it('hands the raw body to parse and returns what parse decides', async () => {
      send.mockResolvedValue(body('{"a":1}'));

      const result = await readJsonDocument({
        bucket: 'b',
        key: 'k.json',
        parse: (raw) => ok(JSON.parse(raw ?? 'null') as {a: number}),
        fallbackMessage: 'Failed to load'
      });

      expect(result).toEqual({success: true, data: {a: 1}});
      const input = send.mock.calls[0][0].input as {Bucket: string; Key: string};
      expect(input).toEqual({Bucket: 'b', Key: 'k.json'});
    });

    it('passes undefined to parse when the response carries no body', async () => {
      send.mockResolvedValue({});
      const parse = vi.fn(() => ok('empty'));

      await readJsonDocument({bucket: 'b', key: 'k.json', parse, fallbackMessage: 'Failed to load'});

      expect(parse).toHaveBeenCalledWith(undefined);
    });

    it('lets parse return the FAILURE branch — a malformed document is not always empty', async () => {
      // The data-quality report's case, and the reason `parse` returns a result rather
      // than a value: the user followed a link to one specific report.
      send.mockResolvedValue(body('not json at all'));

      const result = await readJsonDocument<{id: string}>({
        bucket: 'b',
        key: 'k.json',
        parse: () => ({success: false, error: {message: 'That report could not be read.', code: 'Unreadable'}}),
        fallbackMessage: 'Failed to load'
      });

      expect(result).toEqual({
        success: false,
        error: {message: 'That report could not be read.', code: 'Unreadable'}
      });
    });

    it.each([
      ['NoSuchKey', undefined],
      ['NotFound', undefined],
      ['SomeOtherName', 404]
    ])('routes a not-found (%s) to onMissing, never to parse', async (name, status) => {
      send.mockRejectedValue(awsError(name, status));
      const parse = vi.fn(() => ok('parsed'));

      const result = await readJsonDocument({
        bucket: 'b',
        key: 'k.json',
        parse,
        onMissing: () => ok('the empty state'),
        fallbackMessage: 'Failed to load'
      });

      expect(result).toEqual({success: true, data: 'the empty state'});
      expect(parse).not.toHaveBeenCalled();
    });

    it('lets onMissing return a failure — absence is the caller`s decision, not always empty', async () => {
      send.mockRejectedValue(awsError('NoSuchKey'));

      const result = await readJsonDocument<string>({
        bucket: 'b',
        key: 'k.json',
        parse: () => ok('parsed'),
        onMissing: () => ({success: false, error: {message: 'That report could not be found.', code: 'NotThere'}}),
        fallbackMessage: 'Failed to load'
      });

      expect(result).toEqual({
        success: false,
        error: {message: 'That report could not be found.', code: 'NotThere'}
      });
    });

    it('falls through to fallbackMessage on a miss when onMissing is omitted', async () => {
      send.mockRejectedValue(awsError('NoSuchKey'));

      const result = await readJsonDocument({
        bucket: 'b',
        key: 'k.json',
        parse: () => ok('parsed'),
        fallbackMessage: 'Failed to load'
      });

      expect(result.success).toBe(false);
      if (!result.success) expect(result.error.code).toBe('NoSuchKey');
    });

    it('wraps any other S3 failure with the caller`s wording and the error name as the code', async () => {
      send.mockRejectedValue(awsError('AccessDenied', 403));

      const result = await readJsonDocument({
        bucket: 'b',
        key: 'k.json',
        parse: () => ok('parsed'),
        onMissing: () => ok('empty'),
        fallbackMessage: 'Failed to load the thing'
      });

      expect(result).toEqual({success: false, error: {message: 'AccessDenied', code: 'AccessDenied'}});
    });

    it('does not throw when parse throws — the contract is result-in, result-out', async () => {
      send.mockResolvedValue(body('{}'));

      const result = await readJsonDocument({
        bucket: 'b',
        key: 'k.json',
        parse: () => {
          throw new Error('parser bug');
        },
        onMissing: () => ok('empty'),
        fallbackMessage: 'Failed to load the thing'
      });

      expect(result).toEqual({success: false, error: {message: 'parser bug', code: 'Error'}});
    });

    it('surfaces a credential failure without ever calling S3', async () => {
      mockGetS3Client.mockResolvedValue({success: false, error: {message: 'Not signed in', code: 'NoCredentials'}});

      const result = await readJsonDocument({
        bucket: 'b',
        key: 'k.json',
        parse: () => ok('parsed'),
        fallbackMessage: 'Failed to load'
      });

      expect(result).toEqual({success: false, error: {message: 'Not signed in', code: 'NoCredentials'}});
      expect(send).not.toHaveBeenCalled();
    });
  });

  describe('writeJsonDocument', () => {
    it('puts the serialized value as application/json', async () => {
      send.mockResolvedValue({});

      const result = await writeJsonDocument({
        bucket: 'b',
        key: 'k.json',
        value: {queries: []},
        fallbackMessage: 'Failed to save'
      });

      expect(result).toEqual({success: true, data: undefined});
      expect(send.mock.calls[0][0].input).toEqual({
        Bucket: 'b',
        Key: 'k.json',
        Body: '{"queries":[]}',
        ContentType: 'application/json'
      });
    });

    it('never issues a delete — the worst race on a user`s own file is last-writer-wins', async () => {
      send.mockResolvedValue({});

      await writeJsonDocument({bucket: 'b', key: 'k.json', value: {}, fallbackMessage: 'Failed to save'});

      expect(send).toHaveBeenCalledTimes(1);
      expect(send.mock.calls[0][0].constructor.name).toBe('PutObjectCommand');
    });

    it('wraps a failure with the caller`s wording', async () => {
      send.mockRejectedValue(awsError('AccessDenied', 403));

      const result = await writeJsonDocument({
        bucket: 'b',
        key: 'k.json',
        value: {},
        fallbackMessage: 'Failed to save the thing'
      });

      expect(result).toEqual({success: false, error: {message: 'AccessDenied', code: 'AccessDenied'}});
    });
  });
});
