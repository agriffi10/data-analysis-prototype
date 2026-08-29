import {beforeEach, describe, expect, it, vi} from 'vitest';
import {SQSClient} from '@aws-sdk/client-sqs';
import {getSessionCredentials} from './awsCredentials';
import {getSqsClient} from './sqsClient';
import {classifyDocument, quarantineDocument, readJsonDocument, writeJsonDocument} from './s3Json';
import {apiRequest} from './apiClient';
import type {ServiceResult} from '../types/service.types';

// ─── from sqsClient.test.ts ───
vi.mock('./awsCredentials', () => ({getSessionCredentials: vi.fn()}));

vi.mock('./apiClient', () => ({apiRequest: vi.fn()}));

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
  const send = vi.mocked(apiRequest);

  /** What the document route answers: the object's bytes as text, NEVER parsed. */
  const body = (text: string) => ({success: true as const, data: {body: text, etag: 'e'}});

  /** A failure arrives as a machine code now, not as a thrown AWS error. */
  const awsError = (name: string) =>
    ({
      success: false as const,
      error: {message: '', code: name === 'NoSuchKey' ? 'NotFound' : name}
    });

  const ok = <T>(data: T): ServiceResult<T> => ({success: true, data});

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('readJsonDocument', () => {
    it('hands the raw body to parse and returns what parse decides', async () => {
      send.mockResolvedValue(body('{"a":1}'));

      const result = await readJsonDocument({
        bucket: 'b',
        key: 'alice/user_settings/k.json',
        parse: (raw) => ok(JSON.parse(raw ?? 'null') as {a: number}),
        fallbackMessage: 'Failed to load'
      });

      expect(result).toEqual({success: true, data: {a: 1}});
      // The bucket no longer travels — the API resolves the space from the caller's verified
      // claims — so what is observable is the route, the derived space and the key.
      expect(send.mock.calls[0][0]).toBe('objects.readContent');
      expect(send.mock.calls[0][1]).toMatchObject({
        query: {spaceKind: 'personal', spaceName: 'alice', key: 'alice/user_settings/k.json'}
      });
    });

    it('passes undefined to parse when the response carries no body', async () => {
      // An EMPTY object, which is what the SDK path reported as "no body". The mapping is
      // deliberate: every caller's parser reads `raw ?? 'null'`, so handing it `''` instead would
      // make `JSON.parse` throw and turn an empty file into a failure — a change that only shows
      // up on an object nobody has written to yet.
      send.mockResolvedValue(body(''));
      const parse = vi.fn(() => ok('empty'));

      await readJsonDocument({bucket: 'b', key: 'alice/user_settings/k.json', parse, fallbackMessage: 'Failed to load'});

      expect(parse).toHaveBeenCalledWith(undefined);
    });

    it('lets parse return the FAILURE branch — a malformed document is not always empty', async () => {
      // The data-quality report's case, and the reason `parse` returns a result rather
      // than a value: the user followed a link to one specific report.
      send.mockResolvedValue(body('not json at all'));

      const result = await readJsonDocument<{id: string}>({
        bucket: 'b',
        key: 'alice/user_settings/k.json',
        parse: () => ({success: false, error: {message: 'That report could not be read.', code: 'Unreadable'}}),
        fallbackMessage: 'Failed to load'
      });

      expect(result).toEqual({
        success: false,
        error: {message: 'That report could not be read.', code: 'Unreadable'}
      });
    });

    it.each([['NoSuchKey'], ['NotFound']])(
      'routes a not-found (%s) to onMissing, never to parse',
      async (name) => {
        send.mockResolvedValue(awsError(name));
        const parse = vi.fn(() => ok('parsed'));

        const result = await readJsonDocument({
          bucket: 'b',
          key: 'alice/user_settings/k.json',
          parse,
          onMissing: () => ok('the empty state'),
          fallbackMessage: 'Failed to load'
        });

        expect(result).toEqual({success: true, data: 'the empty state'});
        expect(parse).not.toHaveBeenCalled();
      }
    );

    it('lets onMissing return a failure — absence is the caller`s decision, not always empty', async () => {
      send.mockResolvedValue(awsError('NoSuchKey'));

      const result = await readJsonDocument<string>({
        bucket: 'b',
        key: 'alice/user_settings/k.json',
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
      send.mockResolvedValue(awsError('NoSuchKey'));

      const result = await readJsonDocument({
        bucket: 'b',
        key: 'alice/user_settings/k.json',
        parse: () => ok('parsed'),
        fallbackMessage: 'Failed to load'
      });

      expect(result.success).toBe(false);
      // The route reports absence as `NotFound`; there is one spelling now, where the SDK had
      // three.
      if (!result.success) expect(result.error.code).toBe('NotFound');
    });

    it('wraps any other S3 failure with the caller`s wording and the error name as the code', async () => {
      send.mockResolvedValue(awsError('AccessDenied'));

      const result = await readJsonDocument({
        bucket: 'b',
        key: 'alice/user_settings/k.json',
        parse: () => ok('parsed'),
        onMissing: () => ok('empty'),
        fallbackMessage: 'Failed to load the thing'
      });

      // The MESSAGE is the caller's own wording now, never the service's. The API returns a
      // machine code and operator text the browser renders nowhere, so the sentence a user sees is
      // chosen client-side from the code — which is what `fallbackMessage` has always been for.
      expect(result).toEqual({
        success: false,
        error: {message: 'Failed to load the thing', code: 'AccessDenied'}
      });
    });

    it('does not throw when parse throws — the contract is result-in, result-out', async () => {
      send.mockResolvedValue(body('{}'));

      const result = await readJsonDocument({
        bucket: 'b',
        key: 'alice/user_settings/k.json',
        parse: () => {
          throw new Error('parser bug');
        },
        onMissing: () => ok('empty'),
        fallbackMessage: 'Failed to load the thing'
      });

      expect(result).toEqual({success: false, error: {message: 'parser bug', code: 'Error'}});
    });

    it('surfaces an identity the API could not assume as a failure', async () => {
      send.mockResolvedValue({success: false, error: {message: '', code: 'IdentityUnavailable'}});

      const result = await readJsonDocument({
        bucket: 'b',
        key: 'alice/user_settings/k.json',
        parse: () => ok('parsed'),
        fallbackMessage: 'Failed to load'
      });

      // The browser holds no credentials to fail on any more; the equivalent is the API being
      // unable to assume the caller's session, which it reports as its own machine code. The
      // request IS made now — there is no client to fail to build before it — so what this asserts
      // is that the failure surfaces rather than that nothing was attempted.
      expect(result).toEqual({success: false, error: {message: 'Failed to load', code: 'IdentityUnavailable'}});
      expect(send).toHaveBeenCalledTimes(1);
    });
  });

  describe('writeJsonDocument', () => {
    it('puts the serialized value as application/json', async () => {
      send.mockResolvedValue({success: true, data: {key: 'k', etag: 'e'}});

      const result = await writeJsonDocument({
        bucket: 'b',
        key: 'alice/user_settings/k.json',
        value: {queries: []},
        fallbackMessage: 'Failed to save'
      });

      expect(result).toEqual({success: true, data: undefined});
      expect(send.mock.calls[0][0]).toBe('objects.writeContent');
      expect((send.mock.calls[0][1] as {body: Record<string, unknown>}).body).toMatchObject({
        key: 'alice/user_settings/k.json',
        // The SAME serialisation the browser always did. Moving `JSON.stringify` server-side would
        // have changed key order and whitespace for every document in the app — invisible, and not
        // byte-identical.
        body: '{"queries":[]}',
        contentType: 'application/json'
      });
    });

    it('never issues a delete — the worst race on a user`s own file is last-writer-wins', async () => {
      send.mockResolvedValue({success: true, data: {key: 'k', etag: 'e'}});

      await writeJsonDocument({bucket: 'b', key: 'alice/user_settings/k.json', value: {}, fallbackMessage: 'Failed to save'});

      expect(send).toHaveBeenCalledTimes(1);
      expect(send.mock.calls[0][0]).toBe('objects.writeContent');
    });

    it('wraps a failure with the caller`s wording', async () => {
      send.mockResolvedValue(awsError('AccessDenied'));

      const result = await writeJsonDocument({
        bucket: 'b',
        key: 'alice/user_settings/k.json',
        value: {},
        fallbackMessage: 'Failed to save the thing'
      });

      expect(result).toEqual({success: false, error: {message: 'Failed to save the thing', code: 'AccessDenied'}});
    });
  });

  // ── SPEC-159: the three-way classification and the quarantine copy ──────────
  describe('classifyDocument', () => {
    const classify = (raw: string | undefined) =>
      classifyDocument<{version: number; queries: unknown[]}>({
        body: raw,
        version: 1,
        empty: () => ({version: 1, queries: []}),
        isReadable: (document) => Array.isArray(document.queries)
      });

    it.each([
      ['absent', undefined],
      ['zero-byte', '']
    ])('reads a %s body as the empty document — absence has nothing to lose', (_label, raw) => {
      expect(classify(raw)).toEqual({readable: true, value: {version: 1, queries: []}});
    });

    it('freshly allocates each empty document', () => {
      const first = classify(undefined);
      const second = classify(undefined);

      expect(first.readable && second.readable && first.value).not.toBe(second.readable && second.value);
    });

    it('reads a current, well-shaped document', () => {
      const document = {version: 1, queries: [{id: 'a'}]};

      expect(classify(JSON.stringify(document))).toEqual({readable: true, value: document});
    });

    it.each([
      ['not JSON at all', 'not json{'],
      ['valid JSON that is not an object', '"a string"'],
      ['an array', '["queries"]'],
      ['null', 'null'],
      ['an object with no version', '{"queries":[]}'],
      ['a non-numeric version', '{"version":"1","queries":[]}'],
      ['a current version with the wrong shape', '{"version":1,"queries":{}}'],
      ['a version BELOW the current one — no reader for it either', '{"version":0,"queries":[]}']
    ])('classifies %s as unparseable', (_label, raw) => {
      expect(classify(raw)).toEqual({readable: false, reason: 'unparseable'});
    });

    it.each([
      ['carrying a valid array', '{"version":2,"queries":[]}'],
      ['with the array field missing', '{"version":2}'],
      ['with the array field malformed', '{"version":2,"queries":"nope"}'],
      ['several versions ahead', '{"version":97}']
    ])('classifies a newer document %s as newer, not corrupt', (_label, raw) => {
      // The distinction the whole spec turns on: quarantining one of these would
      // downgrade a document a newer client wrote — the loss the spec prevents.
      expect(classify(raw)).toEqual({readable: false, reason: 'newer'});
    });
  });

  describe('quarantineDocument', () => {
    const at = new Date('2026-08-10T13:15:00.123Z');

    it('copies the document aside, server-side, under the same prefix', async () => {
      send.mockResolvedValue({success: true, data: {key: 'k', etag: 'e'}});

      const result = await quarantineDocument({
        bucket: 'user-bucket',
        key: 'alice/user_settings/query-history.json',
        now: at
      });

      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.data.quarantineKey).toMatch(
        /^alice\/user_settings\/query-history\.json\.unreadable-20260810T131500Z-[0-9a-f]{8}\.json$/
      );
      // A CopyObject, never a read-then-write: the unreadable bytes never enter the
      // browser, so an arbitrarily large document costs no memory.
      expect(send).toHaveBeenCalledTimes(1);
      expect(send.mock.calls[0][0]).toBe('objects.copy');
      expect((send.mock.calls[0][1] as {body: Record<string, unknown>}).body).toMatchObject({
        destinationKey: result.data.quarantineKey,
        // Source and destination travel as spaces and KEYS, never as a hand-built
        // `${bucket}/${key}`. That string needed the key percent-encoded, and a key carrying a
        // space or a `+` produced a silently wrong source rather than a failure. The route hands
        // boto3 a dict and boto3 does the encoding.
        sourceKey: 'alice/user_settings/query-history.json'
      });
    });

    it('keeps the quarantine object in the SOURCE`s own folder — the boundary the grants are scoped to', async () => {
      // The reason this needs no IAM change: GetObject + PutObject inside the user's
      // own prefix, both already granted. Derived from the source key rather than
      // asserted against a literal, so moving quarantines to a sibling folder — the
      // change that would need IAM — fails here instead of passing by construction.
      send.mockResolvedValue({success: true, data: {key: 'k', etag: 'e'}});
      const key = 'alice/user_settings/query-history.json';

      const result = await quarantineDocument({bucket: 'user-bucket', key, now: at});

      expect(result.success).toBe(true);
      if (!result.success) return;
      const folder = (k: string) => k.slice(0, k.lastIndexOf('/'));
      expect(folder(result.data.quarantineKey)).toBe(folder(key));
      expect(result.data.quarantineKey).not.toContain('..');
    });

    it('is unique per event even WITHIN a second, so a racing quarantine cannot overwrite evidence', async () => {
      // The scenario the clock alone does not cover: two tabs find the same corrupt
      // document in the same second. `CopyObject` copies whatever is live, so the
      // loser would copy the already-REPAIRED document over the winner's quarantine
      // object — destroying the only surviving copy of what the user had.
      send.mockResolvedValue({success: true, data: {key: 'k', etag: 'e'}});
      const key = 'alice/user_settings/query-history.json';

      const first = await quarantineDocument({bucket: 'b', key, now: at});
      const second = await quarantineDocument({bucket: 'b', key, now: at});

      expect(first.success && second.success).toBe(true);
      if (!first.success || !second.success) return;
      expect(first.data.quarantineKey).not.toBe(second.data.quarantineKey);
    });

    it('returns a failure the caller must treat as fatal, and never throws', async () => {
      send.mockResolvedValue(awsError('AccessDenied'));

      const result = await quarantineDocument({bucket: 'b', key: 'alice/user_settings/x.json', now: at});

      expect(result).toEqual({
        success: false,
        error: {message: 'Failed to set the unreadable file aside', code: 'AccessDenied'}
      });
    });
  });
});
