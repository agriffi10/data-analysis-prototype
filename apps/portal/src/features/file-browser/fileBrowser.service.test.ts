import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  HeadObjectCommand,
  PutObjectCommand,
  DeleteObjectCommand,
  GetObjectCommand,
} from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';
import {
  listFiles,
  ensurePrefixMarker,
  deleteObject,
  isPrefixMarkerKey,
  getDownloadUrl,
  __resetPrefixMarkerCache,
} from './fileBrowser.service';
import { PREFIX_MARKER_BODY } from './fileBrowser.constants';

vi.mock('@aws-sdk/s3-request-presigner', () => ({ getSignedUrl: vi.fn() }));
const mockGetSignedUrl = vi.mocked(getSignedUrl);

// The service now obtains an authenticated client via getS3Client() (SPEC-013).
// Mock that + the client's send. vi.hoisted lets the mock factory reference these.
const { mockSend, mockGetS3Client, mockStaticSend } = vi.hoisted(() => ({
  mockSend: vi.fn(),
  mockGetS3Client: vi.fn(),
  mockStaticSend: vi.fn(),
}));

vi.mock('../../lib/s3Client', () => ({
  s3Client: { send: mockStaticSend }, // dev-only fallback; unused on the auth path
  getS3Client: mockGetS3Client,
}));

beforeEach(() => {
  vi.clearAllMocks();
  // Default: an authenticated client whose send is mockSend.
  mockGetS3Client.mockResolvedValue({ success: true, data: { send: mockSend } });
  // Reset the once-per-session marker guard so each case starts clean.
  __resetPrefixMarkerCache();
});

// A NotFound error as the v3 SDK surfaces it for HeadObject on a missing key.
function notFoundError() {
  return Object.assign(new Error('Not Found'), {
    name: 'NotFound',
    $metadata: { httpStatusCode: 404 },
  });
}

describe('listFiles', () => {
  it('returns files and folders from a successful S3 response', async () => {
    mockSend.mockResolvedValueOnce({
      Contents: [
        {
          Key: 'documents/report.pdf',
          Size: 1024,
          LastModified: new Date('2024-01-15T10:00:00Z'),
        },
        {
          Key: 'documents/notes.txt',
          Size: 512,
          LastModified: new Date('2024-01-10T08:00:00Z'),
        },
      ],
      CommonPrefixes: [{ Prefix: 'documents/archive/' }],
    });

    const result = await listFiles('my-bucket', 'documents/');

    expect(result.success).toBe(true);
    if (!result.success) return;

    expect(result.data.folders).toHaveLength(1);
    expect(result.data.folders[0]).toEqual({
      type: 'folder',
      prefix: 'documents/archive/',
      name: 'archive',
    });

    expect(result.data.files).toHaveLength(2);
    expect(result.data.files[0]).toEqual({
      type: 'file',
      key: 'documents/notes.txt',
      name: 'notes.txt',
      size: 512,
      lastModified: new Date('2024-01-10T08:00:00Z'),
    });
    expect(result.data.files[1]).toEqual({
      type: 'file',
      key: 'documents/report.pdf',
      name: 'report.pdf',
      size: 1024,
      lastModified: new Date('2024-01-15T10:00:00Z'),
    });
  });

  it('sorts folders before files, both alphabetically', async () => {
    mockSend.mockResolvedValueOnce({
      Contents: [
        { Key: 'zebra.txt', Size: 10, LastModified: new Date() },
        { Key: 'apple.txt', Size: 10, LastModified: new Date() },
      ],
      CommonPrefixes: [{ Prefix: 'monkeys/' }, { Prefix: 'ants/' }],
    });

    const result = await listFiles('my-bucket');

    expect(result.success).toBe(true);
    if (!result.success) return;

    expect(result.data.folders.map((f) => f.name)).toEqual(['ants', 'monkeys']);
    expect(result.data.files.map((f) => f.name)).toEqual(['apple.txt', 'zebra.txt']);
  });

  it('excludes the prefix key itself from files (S3 folder placeholder)', async () => {
    mockSend.mockResolvedValueOnce({
      Contents: [
        { Key: 'documents/', Size: 0, LastModified: new Date() },
        { Key: 'documents/file.txt', Size: 100, LastModified: new Date() },
      ],
      CommonPrefixes: [],
    });

    const result = await listFiles('my-bucket', 'documents/');

    expect(result.success).toBe(true);
    if (!result.success) return;

    expect(result.data.files).toHaveLength(1);
    expect(result.data.files[0].name).toBe('file.txt');
  });

  it('returns empty lists when bucket/prefix is empty', async () => {
    mockSend.mockResolvedValueOnce({ Contents: [], CommonPrefixes: [] });

    const result = await listFiles('my-bucket');

    expect(result.success).toBe(true);
    if (!result.success) return;

    expect(result.data.files).toHaveLength(0);
    expect(result.data.folders).toHaveLength(0);
  });

  it('handles undefined Contents and CommonPrefixes gracefully', async () => {
    mockSend.mockResolvedValueOnce({});

    const result = await listFiles('my-bucket');

    expect(result.success).toBe(true);
    if (!result.success) return;

    expect(result.data.files).toHaveLength(0);
    expect(result.data.folders).toHaveLength(0);
  });

  it('returns success: false on SDK error without throwing', async () => {
    const sdkError = Object.assign(new Error('Access Denied'), {
      name: 'AccessDenied',
    });
    mockSend.mockRejectedValueOnce(sdkError);

    const result = await listFiles('my-bucket');

    expect(result.success).toBe(false);
    if (result.success) return;

    expect(result.error.message).toBe('Access Denied');
    expect(result.error.code).toBe('AccessDenied');
    // A non-expiry error must NOT trigger a credential refresh/retry.
    expect(mockGetS3Client).toHaveBeenCalledTimes(1);
  });

  it('sends a ListObjectsV2Command with the correct bucket and prefix', async () => {
    mockSend.mockResolvedValueOnce({ Contents: [], CommonPrefixes: [] });

    await listFiles('test-bucket', 'some/prefix/');

    expect(mockSend).toHaveBeenCalledOnce();
    expect(mockSend).toHaveBeenCalledWith(
      expect.objectContaining({
        input: {
          Bucket: 'test-bucket',
          Prefix: 'some/prefix/',
          Delimiter: '/',
          MaxKeys: 1000,
          ContinuationToken: undefined,
        },
      }),
    );
  });

  it('threads the continuation token and surfaces pagination fields', async () => {
    mockSend.mockResolvedValueOnce({
      Contents: [],
      CommonPrefixes: [],
      IsTruncated: true,
      NextContinuationToken: 'TOKEN-2',
    });

    const result = await listFiles('my-bucket', 'alice/', 'TOKEN-1');

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.isTruncated).toBe(true);
    expect(result.data.nextContinuationToken).toBe('TOKEN-2');
    expect(mockSend).toHaveBeenCalledWith(
      expect.objectContaining({
        input: expect.objectContaining({ ContinuationToken: 'TOKEN-1', MaxKeys: 1000 }),
      }),
    );
  });

  it('defaults isTruncated to false when S3 omits it', async () => {
    mockSend.mockResolvedValueOnce({ Contents: [], CommonPrefixes: [] });

    const result = await listFiles('my-bucket');

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.isTruncated).toBe(false);
    expect(result.data.nextContinuationToken).toBeUndefined();
  });

  it('retries once with refreshed credentials on an expired-token error', async () => {
    mockSend
      .mockRejectedValueOnce(
        Object.assign(new Error('token expired'), { name: 'ExpiredToken' }),
      )
      .mockResolvedValueOnce({ Contents: [], CommonPrefixes: [] });

    const result = await listFiles('my-bucket', 'alice/');

    expect(result.success).toBe(true);
    // Two client acquisitions: the normal one, then a forced refresh.
    expect(mockGetS3Client).toHaveBeenCalledTimes(2);
    expect(mockGetS3Client).toHaveBeenNthCalledWith(1);
    expect(mockGetS3Client).toHaveBeenNthCalledWith(2, true);
    expect(mockSend).toHaveBeenCalledTimes(2);
  });

  it('surfaces the credential error when getS3Client fails (not signed in)', async () => {
    mockGetS3Client.mockResolvedValueOnce({
      success: false,
      error: { message: 'No AWS credentials — sign in required' },
    });

    const result = await listFiles('my-bucket', 'alice/');

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.message).toBe('No AWS credentials — sign in required');
    expect(mockSend).not.toHaveBeenCalled();
  });
});

describe('ensurePrefixMarker', () => {
  it('creates the marker with HEAD-then-PUT when it does not exist', async () => {
    mockSend
      .mockRejectedValueOnce(notFoundError()) // HEAD → 404
      .mockResolvedValueOnce({}); // PUT → ok

    const result = await ensurePrefixMarker({ bucket: 'us', username: 'alice' });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.created).toBe(true);

    expect(mockSend).toHaveBeenCalledTimes(2);
    expect(mockSend.mock.calls[0][0]).toBeInstanceOf(HeadObjectCommand);
    const put = mockSend.mock.calls[1][0];
    expect(put).toBeInstanceOf(PutObjectCommand);
    expect(put.input).toEqual({
      Bucket: 'us',
      Key: 'alice/DO_NOT_DELETE.txt',
      Body: PREFIX_MARKER_BODY,
      ContentType: 'text/plain',
    });
  });

  it('does not overwrite an existing marker (HEAD succeeds → no PUT)', async () => {
    mockSend.mockResolvedValueOnce({}); // HEAD → exists

    const result = await ensurePrefixMarker({ bucket: 'us', username: 'alice' });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.created).toBe(false);
    expect(mockSend).toHaveBeenCalledTimes(1);
    expect(mockSend.mock.calls[0][0]).toBeInstanceOf(HeadObjectCommand);
  });

  it('runs at most once per session — repeat calls issue no further HEADs', async () => {
    mockSend.mockResolvedValueOnce({}); // HEAD → exists (first call only)

    const first = await ensurePrefixMarker({ bucket: 'us', username: 'alice' });
    const second = await ensurePrefixMarker({ bucket: 'us', username: 'alice' });

    expect(first.success && second.success).toBe(true);
    expect(mockSend).toHaveBeenCalledTimes(1);
  });

  it('returns failure (never throws) when PUT fails', async () => {
    mockSend
      .mockRejectedValueOnce(notFoundError()) // HEAD → 404
      .mockRejectedValueOnce(
        Object.assign(new Error('Access Denied'), { name: 'AccessDenied' }),
      ); // PUT → fail

    const result = await ensurePrefixMarker({ bucket: 'us', username: 'alice' });

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('AccessDenied');
  });

  it('retries once with refreshed credentials when HEAD hits an expired token', async () => {
    mockSend
      .mockRejectedValueOnce(
        Object.assign(new Error('token expired'), { name: 'ExpiredToken' }),
      ) // HEAD → expiry
      .mockResolvedValueOnce({}); // HEAD (retry) → exists

    const result = await ensurePrefixMarker({ bucket: 'us', username: 'alice' });

    expect(result.success).toBe(true);
    expect(mockGetS3Client).toHaveBeenCalledTimes(2);
    expect(mockGetS3Client).toHaveBeenNthCalledWith(2, true);
  });
});

describe('isPrefixMarkerKey', () => {
  it('matches only the exact root marker key', () => {
    expect(isPrefixMarkerKey('alice/DO_NOT_DELETE.txt', 'alice')).toBe(true);
    expect(isPrefixMarkerKey('alice/docs/DO_NOT_DELETE.txt', 'alice')).toBe(
      false,
    );
    expect(isPrefixMarkerKey('alice/report.pdf', 'alice')).toBe(false);
  });
});

describe('deleteObject', () => {
  // FR-003: UI-layer defense in depth only — the authoritative protection is the
  // IAM deny on */DO_NOT_DELETE.txt in SPEC-013 FR-001's role policy.
  it('rejects deletion of the prefix marker without calling S3', async () => {
    const result = await deleteObject({
      bucket: 'us',
      key: 'alice/DO_NOT_DELETE.txt',
      username: 'alice',
    });

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('ProtectedObject');
    expect(mockSend).not.toHaveBeenCalled();
  });

  it('deletes a normal object', async () => {
    mockSend.mockResolvedValueOnce({});

    const result = await deleteObject({
      bucket: 'us',
      key: 'alice/report.pdf',
      username: 'alice',
    });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.key).toBe('alice/report.pdf');
    expect(mockSend).toHaveBeenCalledOnce();
    expect(mockSend.mock.calls[0][0]).toBeInstanceOf(DeleteObjectCommand);
  });
});

describe('getDownloadUrl', () => {
  // A mock client exposing a credentials provider with the given remaining TTL.
  function clientWithExpiry(secondsFromNow: number) {
    return {
      send: mockSend,
      config: {
        credentials: vi.fn().mockResolvedValue({
          accessKeyId: 'AKIA',
          secretAccessKey: 'secret',
          expiration: new Date(Date.now() + secondsFromNow * 1000),
        }),
      },
    };
  }

  it('builds a presigned GetObject URL with attachment disposition + default expiry', async () => {
    mockGetS3Client.mockResolvedValue({
      success: true,
      data: clientWithExpiry(3600),
    });
    mockGetSignedUrl.mockResolvedValue('https://signed.example/report.pdf');

    const result = await getDownloadUrl({ bucket: 'us', key: 'alice/report.pdf' });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.url).toBe('https://signed.example/report.pdf');
    expect(typeof result.data.expiresAt).toBe('string');

    const [, command, options] = mockGetSignedUrl.mock.calls[0];
    expect(command).toBeInstanceOf(GetObjectCommand);
    expect((command as GetObjectCommand).input).toMatchObject({
      Bucket: 'us',
      Key: 'alice/report.pdf',
      ResponseContentDisposition: 'attachment; filename="report.pdf"',
    });
    // Far-future credentials → uncapped default of 900s.
    expect(options).toEqual({ expiresIn: 900 });
  });

  it('defaults the filename to the last path segment', async () => {
    mockGetS3Client.mockResolvedValue({ success: true, data: clientWithExpiry(3600) });
    mockGetSignedUrl.mockResolvedValue('https://signed');

    await getDownloadUrl({ bucket: 'us', key: 'alice/docs/2024/q1.csv' });

    const [, command] = mockGetSignedUrl.mock.calls[0];
    expect((command as GetObjectCommand).input.ResponseContentDisposition).toBe(
      'attachment; filename="q1.csv"',
    );
  });

  it('caps the expiry to the remaining credential lifetime', async () => {
    mockGetS3Client.mockResolvedValue({ success: true, data: clientWithExpiry(120) });
    mockGetSignedUrl.mockResolvedValue('https://signed');

    await getDownloadUrl({ bucket: 'us', key: 'alice/f.txt', expiresInSeconds: 900 });

    const options = mockGetSignedUrl.mock.calls[0][2];
    expect(options?.expiresIn).toBeGreaterThan(0);
    expect(options?.expiresIn).toBeLessThan(900); // capped below the requested 900
  });

  it('surfaces a no-credentials error after one forced-refresh retry, without signing', async () => {
    mockGetS3Client
      .mockResolvedValueOnce({
        success: false,
        error: { message: 'No AWS credentials — sign in required' },
      })
      .mockResolvedValueOnce({
        success: false,
        error: { message: 'No AWS credentials — sign in required' },
      });

    const result = await getDownloadUrl({ bucket: 'us', key: 'alice/f.txt' });

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.message).toBe('No AWS credentials — sign in required');
    expect(mockGetS3Client).toHaveBeenCalledTimes(2);
    expect(mockGetS3Client).toHaveBeenNthCalledWith(2, true);
    expect(mockGetSignedUrl).not.toHaveBeenCalled();
  });
});
