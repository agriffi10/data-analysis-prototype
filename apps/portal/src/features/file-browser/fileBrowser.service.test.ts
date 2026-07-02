import {describe, it, expect, vi, beforeEach} from 'vitest';
import {
  HeadObjectCommand,
  PutObjectCommand,
  DeleteObjectCommand,
  DeleteObjectsCommand,
  CopyObjectCommand,
  ListObjectsV2Command,
  GetObjectCommand
} from '@aws-sdk/client-s3';
import {getSignedUrl} from '@aws-sdk/s3-request-presigner';
import {
  listFiles,
  ensurePrefixMarker,
  deleteObject,
  deleteObjects,
  deleteFolder,
  copyObject,
  copyFolder,
  moveObject,
  moveFolder,
  isPrefixMarkerKey,
  getDownloadUrl,
  objectExists,
  uploadFile,
  createFolder,
  validateFolderName,
  uploadPercent,
  getObjectMetadata,
  __resetPrefixMarkerCache
} from './fileBrowser.service';
import {LISTING_PAGE_SIZE} from './fileBrowser.constants';
import {PREFIX_MARKER_BODY} from './fileBrowser.constants';
import {MAX_UPLOAD_BYTES} from './fileBrowser.types';

vi.mock('@aws-sdk/s3-request-presigner', () => ({getSignedUrl: vi.fn()}));
const mockGetSignedUrl = vi.mocked(getSignedUrl);

// Mock the managed lib-storage Upload. `uploadState` captures the constructor
// args + the httpUploadProgress callback so tests can fire progress and control
// how done() resolves/rejects.
const uploadState = vi.hoisted(() => ({
  ctorArgs: null as unknown,
  progressCb: null as null | ((p: {loaded?: number; total?: number}) => void),
  doneImpl: null as null | (() => Promise<unknown>),
  aborted: false
}));

vi.mock('@aws-sdk/lib-storage', () => ({
  Upload: class {
    constructor(args: unknown) {
      uploadState.ctorArgs = args;
    }
    on(_event: string, cb: (p: {loaded?: number; total?: number}) => void) {
      uploadState.progressCb = cb;
    }
    async done() {
      return uploadState.doneImpl ? uploadState.doneImpl() : {};
    }
    async abort() {
      uploadState.aborted = true;
    }
  }
}));

// The service obtains an authenticated client via getS3Client(). Mock that +
// the client's send; vi.hoisted lets the mock factory reference these.
const {mockSend, mockGetS3Client, mockStaticSend} = vi.hoisted(() => ({
  mockSend: vi.fn(),
  mockGetS3Client: vi.fn(),
  mockStaticSend: vi.fn()
}));

vi.mock('../../lib/s3Client', () => ({
  s3Client: {send: mockStaticSend}, // dev-only fallback; unused on the auth path
  getS3Client: mockGetS3Client
}));

beforeEach(() => {
  vi.clearAllMocks();
  mockGetS3Client.mockResolvedValue({success: true, data: {send: mockSend}});
  // Reset the once-per-session marker guard so each case starts clean.
  __resetPrefixMarkerCache();
  uploadState.ctorArgs = null;
  uploadState.progressCb = null;
  uploadState.doneImpl = null;
  uploadState.aborted = false;
});

// A NotFound error as the v3 SDK surfaces it for HeadObject on a missing key.
function notFoundError() {
  return Object.assign(new Error('Not Found'), {
    name: 'NotFound',
    $metadata: {httpStatusCode: 404}
  });
}

describe('listFiles', () => {
  it('returns files and folders from a successful S3 response', async () => {
    mockSend.mockResolvedValueOnce({
      Contents: [
        {
          Key: 'documents/report.pdf',
          Size: 1024,
          LastModified: new Date('2024-01-15T10:00:00Z')
        },
        {
          Key: 'documents/notes.txt',
          Size: 512,
          LastModified: new Date('2024-01-10T08:00:00Z')
        }
      ],
      CommonPrefixes: [{Prefix: 'documents/archive/'}]
    });

    const result = await listFiles('my-bucket', 'documents/');

    expect(result.success).toBe(true);
    if (!result.success) return;

    expect(result.data.folders).toHaveLength(1);
    expect(result.data.folders[0]).toEqual({
      type: 'folder',
      prefix: 'documents/archive/',
      name: 'archive'
    });

    expect(result.data.files).toHaveLength(2);
    expect(result.data.files[0]).toEqual({
      type: 'file',
      key: 'documents/notes.txt',
      name: 'notes.txt',
      size: 512,
      lastModified: new Date('2024-01-10T08:00:00Z')
    });
    expect(result.data.files[1]).toEqual({
      type: 'file',
      key: 'documents/report.pdf',
      name: 'report.pdf',
      size: 1024,
      lastModified: new Date('2024-01-15T10:00:00Z')
    });
  });

  it('sorts folders before files, both alphabetically', async () => {
    mockSend.mockResolvedValueOnce({
      Contents: [
        {Key: 'zebra.txt', Size: 10, LastModified: new Date()},
        {Key: 'apple.txt', Size: 10, LastModified: new Date()}
      ],
      CommonPrefixes: [{Prefix: 'monkeys/'}, {Prefix: 'ants/'}]
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
        {Key: 'documents/', Size: 0, LastModified: new Date()},
        {Key: 'documents/file.txt', Size: 100, LastModified: new Date()}
      ],
      CommonPrefixes: []
    });

    const result = await listFiles('my-bucket', 'documents/');

    expect(result.success).toBe(true);
    if (!result.success) return;

    expect(result.data.files).toHaveLength(1);
    expect(result.data.files[0].name).toBe('file.txt');
  });

  it('returns empty lists when bucket/prefix is empty', async () => {
    mockSend.mockResolvedValueOnce({Contents: [], CommonPrefixes: []});

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
      name: 'AccessDenied'
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
    mockSend.mockResolvedValueOnce({Contents: [], CommonPrefixes: []});

    await listFiles('test-bucket', 'some/prefix/');

    expect(mockSend).toHaveBeenCalledOnce();
    expect(mockSend).toHaveBeenCalledWith(
      expect.objectContaining({
        input: {
          Bucket: 'test-bucket',
          Prefix: 'some/prefix/',
          Delimiter: '/',
          MaxKeys: LISTING_PAGE_SIZE,
          ContinuationToken: undefined
        }
      })
    );
  });

  it('threads the continuation token and surfaces pagination fields', async () => {
    mockSend.mockResolvedValueOnce({
      Contents: [],
      CommonPrefixes: [],
      IsTruncated: true,
      NextContinuationToken: 'TOKEN-2'
    });

    const result = await listFiles('my-bucket', 'alice/', 'TOKEN-1');

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.isTruncated).toBe(true);
    expect(result.data.nextContinuationToken).toBe('TOKEN-2');
    expect(mockSend).toHaveBeenCalledWith(
      expect.objectContaining({
        input: expect.objectContaining({
          ContinuationToken: 'TOKEN-1',
          MaxKeys: LISTING_PAGE_SIZE
        })
      })
    );
  });

  it('defaults isTruncated to false when S3 omits it', async () => {
    mockSend.mockResolvedValueOnce({Contents: [], CommonPrefixes: []});

    const result = await listFiles('my-bucket');

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.isTruncated).toBe(false);
    expect(result.data.nextContinuationToken).toBeUndefined();
  });

  it('retries once with refreshed credentials on an expired-token error', async () => {
    mockSend
      .mockRejectedValueOnce(Object.assign(new Error('token expired'), {name: 'ExpiredToken'}))
      .mockResolvedValueOnce({Contents: [], CommonPrefixes: []});

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
      error: {message: 'No AWS credentials — sign in required'}
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

    const result = await ensurePrefixMarker({bucket: 'us', username: 'alice'});

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
      ContentType: 'text/plain'
    });
  });

  it('does not overwrite an existing marker (HEAD succeeds → no PUT)', async () => {
    mockSend.mockResolvedValueOnce({}); // HEAD → exists

    const result = await ensurePrefixMarker({bucket: 'us', username: 'alice'});

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.created).toBe(false);
    expect(mockSend).toHaveBeenCalledTimes(1);
    expect(mockSend.mock.calls[0][0]).toBeInstanceOf(HeadObjectCommand);
  });

  it('runs at most once per session — repeat calls issue no further HEADs', async () => {
    mockSend.mockResolvedValueOnce({}); // HEAD → exists (first call only)

    const first = await ensurePrefixMarker({bucket: 'us', username: 'alice'});
    const second = await ensurePrefixMarker({bucket: 'us', username: 'alice'});

    expect(first.success && second.success).toBe(true);
    expect(mockSend).toHaveBeenCalledTimes(1);
  });

  it('returns failure (never throws) when PUT fails', async () => {
    mockSend
      .mockRejectedValueOnce(notFoundError()) // HEAD → 404
      .mockRejectedValueOnce(Object.assign(new Error('Access Denied'), {name: 'AccessDenied'})); // PUT → fail

    const result = await ensurePrefixMarker({bucket: 'us', username: 'alice'});

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('AccessDenied');
  });

  it('retries once with refreshed credentials when HEAD hits an expired token', async () => {
    mockSend
      .mockRejectedValueOnce(Object.assign(new Error('token expired'), {name: 'ExpiredToken'})) // HEAD → expiry
      .mockResolvedValueOnce({}); // HEAD (retry) → exists

    const result = await ensurePrefixMarker({bucket: 'us', username: 'alice'});

    expect(result.success).toBe(true);
    expect(mockGetS3Client).toHaveBeenCalledTimes(2);
    expect(mockGetS3Client).toHaveBeenNthCalledWith(2, true);
  });
});

describe('isPrefixMarkerKey', () => {
  it('matches only the exact root marker key', () => {
    expect(isPrefixMarkerKey('alice/DO_NOT_DELETE.txt', 'alice')).toBe(true);
    expect(isPrefixMarkerKey('alice/docs/DO_NOT_DELETE.txt', 'alice')).toBe(false);
    expect(isPrefixMarkerKey('alice/report.pdf', 'alice')).toBe(false);
  });
});

describe('deleteObject', () => {
  // UI-layer defense in depth only — the authoritative protection is the IAM
  // deny on */DO_NOT_DELETE.txt in the role policy.
  it('rejects deletion of the prefix marker without calling S3', async () => {
    const result = await deleteObject({
      bucket: 'us',
      key: 'alice/DO_NOT_DELETE.txt',
      username: 'alice'
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
      username: 'alice'
    });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.key).toBe('alice/report.pdf');
    expect(mockSend).toHaveBeenCalledOnce();
    expect(mockSend.mock.calls[0][0]).toBeInstanceOf(DeleteObjectCommand);
  });
});

describe('deleteObjects', () => {
  // Echo each batch's keys back as Deleted, so chunking can be asserted by the
  // number of requests and the per-request object counts.
  function echoDeleted() {
    mockSend.mockImplementation((cmd: DeleteObjectsCommand) =>
      Promise.resolve({
        Deleted: (cmd.input.Delete?.Objects ?? []).map((o) => ({Key: o.Key})),
        Errors: []
      })
    );
  }

  it('deletes a single key via DeleteObjects and returns it', async () => {
    mockSend.mockResolvedValueOnce({Deleted: [{Key: 'alice/a.txt'}], Errors: []});

    const result = await deleteObjects({
      bucket: 'us',
      keys: ['alice/a.txt'],
      username: 'alice'
    });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.deleted).toEqual(['alice/a.txt']);
    expect(result.data.errors).toEqual([]);

    const cmd = mockSend.mock.calls[0][0];
    expect(cmd).toBeInstanceOf(DeleteObjectsCommand);
    expect(cmd.input).toEqual({
      Bucket: 'us',
      Delete: {Objects: [{Key: 'alice/a.txt'}], Quiet: false}
    });
  });

  it('returns an empty result and makes no S3 call for an empty key list', async () => {
    const result = await deleteObjects({bucket: 'us', keys: [], username: 'alice'});
    expect(result).toEqual({success: true, data: {deleted: [], errors: []}});
    expect(mockSend).not.toHaveBeenCalled();
  });

  it('chunks more than 1000 keys into separate DeleteObjects requests', async () => {
    echoDeleted();
    const keys = Array.from({length: 1500}, (_, i) => `alice/f${i}.txt`);

    const result = await deleteObjects({bucket: 'us', keys, username: 'alice'});

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.deleted).toHaveLength(1500);
    expect(mockSend).toHaveBeenCalledTimes(2);
    expect(mockSend.mock.calls[0][0].input.Delete.Objects).toHaveLength(1000);
    expect(mockSend.mock.calls[1][0].input.Delete.Objects).toHaveLength(500);
  });

  it('refuses the prefix marker without sending it, but deletes the rest', async () => {
    mockSend.mockResolvedValueOnce({Deleted: [{Key: 'alice/a.txt'}], Errors: []});

    const result = await deleteObjects({
      bucket: 'us',
      keys: ['alice/DO_NOT_DELETE.txt', 'alice/a.txt'],
      username: 'alice'
    });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.deleted).toEqual(['alice/a.txt']);
    expect(result.data.errors).toEqual([
      {
        key: 'alice/DO_NOT_DELETE.txt',
        message: expect.stringMatching(/cannot be deleted/i)
      }
    ]);
    // The marker was never part of the DeleteObjects request.
    expect(mockSend.mock.calls[0][0].input.Delete.Objects).toEqual([{Key: 'alice/a.txt'}]);
  });

  it('makes no S3 call when the only key is the protected marker', async () => {
    const result = await deleteObjects({
      bucket: 'us',
      keys: ['alice/DO_NOT_DELETE.txt'],
      username: 'alice'
    });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.deleted).toEqual([]);
    expect(result.data.errors).toHaveLength(1);
    expect(mockSend).not.toHaveBeenCalled();
  });

  it('aggregates per-key S3 errors without throwing (partial failure)', async () => {
    mockSend.mockResolvedValueOnce({
      Deleted: [{Key: 'alice/a.txt'}],
      Errors: [{Key: 'alice/locked.txt', Code: 'AccessDenied', Message: 'Access Denied'}]
    });

    const result = await deleteObjects({
      bucket: 'us',
      keys: ['alice/a.txt', 'alice/locked.txt'],
      username: 'alice'
    });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.deleted).toEqual(['alice/a.txt']);
    expect(result.data.errors).toEqual([{key: 'alice/locked.txt', message: 'Access Denied'}]);
  });

  it('records a non-expiry whole-batch failure as per-key errors, no retry', async () => {
    mockSend.mockRejectedValueOnce(Object.assign(new Error('Service Unavailable'), {name: 'ServiceUnavailable'}));

    const result = await deleteObjects({
      bucket: 'us',
      keys: ['alice/a.txt', 'alice/b.txt'],
      username: 'alice'
    });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.deleted).toEqual([]);
    expect(result.data.errors).toEqual([
      {key: 'alice/a.txt', message: 'Service Unavailable'},
      {key: 'alice/b.txt', message: 'Service Unavailable'}
    ]);
    expect(mockGetS3Client).toHaveBeenCalledTimes(1); // no credential refresh
  });

  it('retries once with refreshed credentials on an expired-token error', async () => {
    mockSend
      .mockRejectedValueOnce(Object.assign(new Error('token expired'), {name: 'ExpiredToken'}))
      .mockResolvedValueOnce({Deleted: [{Key: 'alice/a.txt'}], Errors: []});

    const result = await deleteObjects({
      bucket: 'us',
      keys: ['alice/a.txt'],
      username: 'alice'
    });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.deleted).toEqual(['alice/a.txt']);
    expect(mockGetS3Client).toHaveBeenCalledTimes(2);
    expect(mockGetS3Client).toHaveBeenNthCalledWith(2, true);
  });
});

describe('deleteFolder', () => {
  it('lists all keys recursively across pages, then batch-deletes them', async () => {
    mockSend
      // page 1 of the recursive listing (truncated)
      .mockResolvedValueOnce({
        Contents: [{Key: 'alice/photos/'}, {Key: 'alice/photos/a.jpg'}],
        IsTruncated: true,
        NextContinuationToken: 'TOKEN-2'
      })
      // page 2 (final)
      .mockResolvedValueOnce({
        Contents: [{Key: 'alice/photos/b.jpg'}],
        IsTruncated: false
      })
      // the DeleteObjects batch
      .mockResolvedValueOnce({
        Deleted: [{Key: 'alice/photos/'}, {Key: 'alice/photos/a.jpg'}, {Key: 'alice/photos/b.jpg'}],
        Errors: []
      });

    const result = await deleteFolder({
      bucket: 'us',
      prefix: 'alice/photos/',
      username: 'alice'
    });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.deleted).toEqual(['alice/photos/', 'alice/photos/a.jpg', 'alice/photos/b.jpg']);

    const listCmds = mockSend.mock.calls.filter((c) => c[0] instanceof ListObjectsV2Command);
    expect(listCmds).toHaveLength(2);
    expect(listCmds[0][0].input).toMatchObject({
      Bucket: 'us',
      Prefix: 'alice/photos/',
      MaxKeys: 1000
    });
    // Recursive: no Delimiter, so nested keys are returned, not collapsed.
    expect(listCmds[0][0].input.Delimiter).toBeUndefined();
    expect(listCmds[1][0].input.ContinuationToken).toBe('TOKEN-2');

    const delCmd = mockSend.mock.calls.find((c) => c[0] instanceof DeleteObjectsCommand);
    expect(delCmd?.[0].input.Delete.Objects).toHaveLength(3);
  });

  it('deletes the lone folder marker when the folder is otherwise empty', async () => {
    mockSend
      .mockResolvedValueOnce({Contents: [{Key: 'alice/empty/'}], IsTruncated: false})
      .mockResolvedValueOnce({Deleted: [{Key: 'alice/empty/'}], Errors: []});

    const result = await deleteFolder({
      bucket: 'us',
      prefix: 'alice/empty/',
      username: 'alice'
    });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.deleted).toEqual(['alice/empty/']);
  });

  it('returns an empty result and issues no delete when the prefix has no objects', async () => {
    mockSend.mockResolvedValueOnce({Contents: [], IsTruncated: false});

    const result = await deleteFolder({
      bucket: 'us',
      prefix: 'alice/ghost/',
      username: 'alice'
    });

    expect(result).toEqual({success: true, data: {deleted: [], errors: []}});
    const delCmds = mockSend.mock.calls.filter((c) => c[0] instanceof DeleteObjectsCommand);
    expect(delCmds).toHaveLength(0);
  });

  it('surfaces a listing failure without attempting a delete', async () => {
    mockSend.mockRejectedValueOnce(Object.assign(new Error('Access Denied'), {name: 'AccessDenied'}));

    const result = await deleteFolder({
      bucket: 'us',
      prefix: 'alice/photos/',
      username: 'alice'
    });

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('AccessDenied');
    const delCmds = mockSend.mock.calls.filter((c) => c[0] instanceof DeleteObjectsCommand);
    expect(delCmds).toHaveLength(0);
  });
});

describe('copyObject', () => {
  it('copies with a URL-encoded CopySource (overwrite skips the HEAD)', async () => {
    mockSend.mockResolvedValueOnce({}); // CopyObject

    const result = await copyObject({
      bucket: 'us',
      sourceKey: 'alice/a.txt',
      destKey: 'alice/b.txt',
      username: 'alice',
      overwrite: true
    });

    expect(result).toEqual({success: true, data: {destKey: 'alice/b.txt'}});
    const cmd = mockSend.mock.calls[0][0];
    expect(cmd).toBeInstanceOf(CopyObjectCommand);
    expect(cmd.input).toMatchObject({
      Bucket: 'us',
      Key: 'alice/b.txt',
      CopySource: 'us/alice/a.txt'
    });
  });

  it('cross-bucket copy: CopySource from the source bucket, write to destBucket (SPEC-055 FR-004)', async () => {
    mockSend.mockResolvedValueOnce({}); // CopyObject (overwrite skips HEAD)

    const result = await copyObject({
      bucket: 'shared-bkt',
      destBucket: 'user-bkt',
      sourceKey: 'salesdata/athenaresults/alice/q.csv',
      destKey: 'alice/reports/out.csv',
      username: 'alice',
      overwrite: true
    });

    expect(result).toEqual({success: true, data: {destKey: 'alice/reports/out.csv'}});
    const cmd = mockSend.mock.calls[0][0];
    expect(cmd).toBeInstanceOf(CopyObjectCommand);
    expect(cmd.input).toMatchObject({
      Bucket: 'user-bkt',
      Key: 'alice/reports/out.csv',
      CopySource: 'shared-bkt/salesdata/athenaresults/alice/q.csv'
    });
  });

  it('cross-bucket collision check HEADs the DESTINATION bucket (SPEC-055 FR-004)', async () => {
    mockSend.mockResolvedValueOnce({}); // HEAD → exists in the dest bucket

    const result = await copyObject({
      bucket: 'shared-bkt',
      destBucket: 'user-bkt',
      sourceKey: 'salesdata/athenaresults/alice/q.csv',
      destKey: 'alice/reports/out.csv',
      username: 'alice'
    });

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('Collision');
    const head = mockSend.mock.calls[0][0];
    expect(head).toBeInstanceOf(HeadObjectCommand);
    expect(head.input).toMatchObject({Bucket: 'user-bkt', Key: 'alice/reports/out.csv'});
  });

  it('rejects the prefix marker as the source (no S3 call)', async () => {
    const result = await copyObject({
      bucket: 'us',
      sourceKey: 'alice/DO_NOT_DELETE.txt',
      destKey: 'alice/x.txt',
      username: 'alice',
      overwrite: true
    });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('ProtectedObject');
    expect(mockSend).not.toHaveBeenCalled();
  });

  it('rejects the prefix marker as the destination (no S3 call)', async () => {
    const result = await copyObject({
      bucket: 'us',
      sourceKey: 'alice/x.txt',
      destKey: 'alice/DO_NOT_DELETE.txt',
      username: 'alice',
      overwrite: true
    });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('ProtectedObject');
    expect(mockSend).not.toHaveBeenCalled();
  });

  it('refuses to overwrite when the destination exists and overwrite is false', async () => {
    mockSend.mockResolvedValueOnce({}); // HEAD → exists

    const result = await copyObject({
      bucket: 'us',
      sourceKey: 'alice/a.txt',
      destKey: 'alice/b.txt',
      username: 'alice'
    });

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('Collision');
    expect(mockSend).toHaveBeenCalledTimes(1); // only the HEAD
    expect(mockSend.mock.calls[0][0]).toBeInstanceOf(HeadObjectCommand);
  });

  it('proceeds when the destination is free (HEAD 404 → copy)', async () => {
    mockSend
      .mockRejectedValueOnce(notFoundError()) // HEAD → 404
      .mockResolvedValueOnce({}); // CopyObject

    const result = await copyObject({
      bucket: 'us',
      sourceKey: 'alice/a.txt',
      destKey: 'alice/b.txt',
      username: 'alice'
    });

    expect(result.success).toBe(true);
    expect(mockSend.mock.calls[1][0]).toBeInstanceOf(CopyObjectCommand);
  });

  it('never issues a delete (copy is strictly additive)', async () => {
    mockSend
      .mockRejectedValueOnce(notFoundError()) // HEAD → 404
      .mockResolvedValueOnce({}); // CopyObject

    await copyObject({
      bucket: 'us',
      sourceKey: 'alice/a.txt',
      destKey: 'alice/b.txt',
      username: 'alice'
    });

    const deletes = mockSend.mock.calls
      .map((c) => c[0])
      .filter((c) => c instanceof DeleteObjectCommand || c instanceof DeleteObjectsCommand);
    expect(deletes).toHaveLength(0);
  });

  it('retries once with a refreshed client on credential expiry', async () => {
    const refreshedSend = vi.fn().mockResolvedValueOnce({}); // CopyObject succeeds
    mockGetS3Client
      .mockResolvedValueOnce({success: true, data: {send: mockSend}})
      .mockResolvedValueOnce({success: true, data: {send: refreshedSend}});
    // First client's CopyObject fails with an expiry error so the helper refreshes.
    mockSend.mockRejectedValueOnce(Object.assign(new Error('expired'), {name: 'ExpiredToken'}));

    const result = await copyObject({
      bucket: 'us',
      sourceKey: 'alice/a.txt',
      destKey: 'alice/b.txt',
      username: 'alice',
      overwrite: true
    });

    expect(result).toEqual({success: true, data: {destKey: 'alice/b.txt'}});
    expect(refreshedSend).toHaveBeenCalledTimes(1);
  });
});

describe('moveObject', () => {
  it('copies then deletes the source', async () => {
    mockSend
      .mockResolvedValueOnce({}) // CopyObject
      .mockResolvedValueOnce({}); // DeleteObject

    const result = await moveObject({
      bucket: 'us',
      sourceKey: 'alice/a.txt',
      destKey: 'alice/b.txt',
      username: 'alice',
      overwrite: true
    });

    expect(result).toEqual({success: true, data: {destKey: 'alice/b.txt'}});
    expect(mockSend.mock.calls[0][0]).toBeInstanceOf(CopyObjectCommand);
    expect(mockSend.mock.calls[1][0]).toBeInstanceOf(DeleteObjectCommand);
    expect(mockSend.mock.calls[1][0].input).toEqual({
      Bucket: 'us',
      Key: 'alice/a.txt'
    });
  });

  it('is a no-op success when source and destination are equal', async () => {
    const result = await moveObject({
      bucket: 'us',
      sourceKey: 'alice/a.txt',
      destKey: 'alice/a.txt',
      username: 'alice'
    });
    expect(result).toEqual({success: true, data: {destKey: 'alice/a.txt'}});
    expect(mockSend).not.toHaveBeenCalled();
  });

  it('cross-connection move: copies into destBucket then deletes from the source bucket', async () => {
    mockSend
      .mockResolvedValueOnce({}) // CopyObject (into destBucket)
      .mockResolvedValueOnce({}); // DeleteObject (from source bucket)

    const result = await moveObject({
      bucket: 'us',
      sourceKey: 'alice/a.txt',
      destKey: 'team/a.txt',
      username: 'alice',
      destBucket: 'shared',
      overwrite: true
    });

    expect(result).toEqual({success: true, data: {destKey: 'team/a.txt'}});
    // Copy writes to the destination bucket, reading from the source bucket.
    expect(mockSend.mock.calls[0][0]).toBeInstanceOf(CopyObjectCommand);
    expect(mockSend.mock.calls[0][0].input).toMatchObject({
      Bucket: 'shared',
      Key: 'team/a.txt',
      CopySource: expect.stringContaining('us/')
    });
    // Delete removes the original from the SOURCE bucket.
    expect(mockSend.mock.calls[1][0]).toBeInstanceOf(DeleteObjectCommand);
    expect(mockSend.mock.calls[1][0].input).toEqual({Bucket: 'us', Key: 'alice/a.txt'});
  });

  it('cross-bucket same key is a real move, not a no-op', async () => {
    mockSend.mockResolvedValueOnce({}).mockResolvedValueOnce({});
    const result = await moveObject({
      bucket: 'us',
      sourceKey: 'alice/a.txt',
      destKey: 'alice/a.txt',
      username: 'alice',
      destBucket: 'shared',
      overwrite: true
    });
    expect(result.success).toBe(true);
    expect(mockSend).toHaveBeenCalledTimes(2); // copy + delete actually ran
  });

  it('leaves the source intact when the copy fails (no delete)', async () => {
    mockSend.mockRejectedValueOnce(Object.assign(new Error('Access Denied'), {name: 'AccessDenied'})); // CopyObject fails

    const result = await moveObject({
      bucket: 'us',
      sourceKey: 'alice/a.txt',
      destKey: 'alice/b.txt',
      username: 'alice',
      overwrite: true
    });

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('AccessDenied');
    const deletes = mockSend.mock.calls.map((c) => c[0]).filter((c) => c instanceof DeleteObjectCommand);
    expect(deletes).toHaveLength(0);
  });

  it('rejects the prefix marker as the source (no S3 call)', async () => {
    const result = await moveObject({
      bucket: 'us',
      sourceKey: 'alice/DO_NOT_DELETE.txt',
      destKey: 'alice/x.txt',
      username: 'alice',
      overwrite: true
    });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('ProtectedObject');
    expect(mockSend).not.toHaveBeenCalled();
  });
});

describe('moveFolder', () => {
  // Route mocked sends by command type + prefix so source/dest listings and the
  // per-key copy/delete can all be served from one implementation.
  function routeSends(opts: {
    sourcePages: {Contents: {Key: string}[]; IsTruncated?: boolean; NextContinuationToken?: string}[];
    destContents?: {Key: string}[];
    failCopyForDestKey?: string;
  }) {
    let sourcePage = 0;
    mockSend.mockImplementation((cmd) => {
      if (cmd instanceof ListObjectsV2Command) {
        if (cmd.input.Prefix === 'alice/photos/') {
          return Promise.resolve(opts.sourcePages[sourcePage++]);
        }
        return Promise.resolve({Contents: opts.destContents ?? [], IsTruncated: false});
      }
      if (cmd instanceof CopyObjectCommand) {
        if (cmd.input.Key === opts.failCopyForDestKey) {
          return Promise.reject(Object.assign(new Error('Access Denied'), {name: 'AccessDenied'}));
        }
        return Promise.resolve({});
      }
      return Promise.resolve({}); // DeleteObject
    });
  }

  it('recursively moves every key across pages, leaving no source behind', async () => {
    routeSends({
      sourcePages: [
        {
          Contents: [{Key: 'alice/photos/'}, {Key: 'alice/photos/a.jpg'}],
          IsTruncated: true,
          NextContinuationToken: 'T2'
        },
        {Contents: [{Key: 'alice/photos/b.jpg'}], IsTruncated: false}
      ]
    });
    const onProgress = vi.fn();

    const result = await moveFolder({
      bucket: 'us',
      sourcePrefix: 'alice/photos/',
      destPrefix: 'alice/archive/photos/',
      username: 'alice',
      onProgress
    });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.moved).toEqual(['alice/photos/', 'alice/photos/a.jpg', 'alice/photos/b.jpg']);
    expect(result.data.errors).toEqual([]);

    const copies = mockSend.mock.calls.map((c) => c[0]).filter((c) => c instanceof CopyObjectCommand);
    expect(copies.map((c) => c.input.Key)).toEqual([
      'alice/archive/photos/',
      'alice/archive/photos/a.jpg',
      'alice/archive/photos/b.jpg'
    ]);
    expect(copies[1].input.CopySource).toBe('us/alice/photos/a.jpg');

    const deletes = mockSend.mock.calls.map((c) => c[0]).filter((c) => c instanceof DeleteObjectCommand);
    expect(deletes.map((c) => c.input.Key)).toEqual(['alice/photos/', 'alice/photos/a.jpg', 'alice/photos/b.jpg']);

    expect(onProgress).toHaveBeenLastCalledWith(3, 3);
  });

  it('records a per-key copy failure, leaves that source, and continues', async () => {
    routeSends({
      sourcePages: [
        {
          Contents: [{Key: 'alice/photos/'}, {Key: 'alice/photos/a.jpg'}, {Key: 'alice/photos/b.jpg'}],
          IsTruncated: false
        }
      ],
      failCopyForDestKey: 'alice/archive/photos/a.jpg'
    });

    const result = await moveFolder({
      bucket: 'us',
      sourcePrefix: 'alice/photos/',
      destPrefix: 'alice/archive/photos/',
      username: 'alice'
    });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.moved).toEqual(['alice/photos/', 'alice/photos/b.jpg']);
    expect(result.data.errors).toEqual([{key: 'alice/photos/a.jpg', message: 'Access Denied'}]);

    // The failed key's source must not be deleted.
    const deletes = mockSend.mock.calls.map((c) => c[0]).filter((c) => c instanceof DeleteObjectCommand);
    expect(deletes.map((c) => c.input.Key)).toEqual(['alice/photos/', 'alice/photos/b.jpg']);
  });

  it('refuses up front when destinations already exist (Collision, no copies)', async () => {
    routeSends({
      sourcePages: [{Contents: [{Key: 'alice/photos/x.jpg'}], IsTruncated: false}],
      destContents: [{Key: 'alice/archive/photos/x.jpg'}]
    });

    const result = await moveFolder({
      bucket: 'us',
      sourcePrefix: 'alice/photos/',
      destPrefix: 'alice/archive/photos/',
      username: 'alice'
    });

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('Collision');
    expect(result.error.message).toMatch(/1 item/);

    const copies = mockSend.mock.calls.map((c) => c[0]).filter((c) => c instanceof CopyObjectCommand);
    expect(copies).toHaveLength(0);
  });

  it('rejects moving a folder into its own subtree (no S3 call)', async () => {
    const result = await moveFolder({
      bucket: 'us',
      sourcePrefix: 'alice/photos/',
      destPrefix: 'alice/photos/sub/',
      username: 'alice'
    });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('InvalidDestination');
    expect(mockSend).not.toHaveBeenCalled();
  });

  it('is a no-op success when source and destination prefixes are equal', async () => {
    const result = await moveFolder({
      bucket: 'us',
      sourcePrefix: 'alice/photos/',
      destPrefix: 'alice/photos/',
      username: 'alice'
    });
    expect(result).toEqual({success: true, data: {moved: [], errors: []}});
    expect(mockSend).not.toHaveBeenCalled();
  });
});

describe('copyFolder', () => {
  // Route mocked sends by command type + prefix so source/dest listings and the
  // per-key copy can all be served from one implementation. Mirrors moveFolder's
  // router, minus any delete handling (copy never deletes).
  function routeSends(opts: {
    sourcePages: {
      Contents: {Key: string}[];
      IsTruncated?: boolean;
      NextContinuationToken?: string;
    }[];
    destContents?: {Key: string}[];
    failCopyForDestKey?: string;
  }) {
    let sourcePage = 0;
    mockSend.mockImplementation((cmd) => {
      if (cmd instanceof ListObjectsV2Command) {
        if (cmd.input.Prefix === 'alice/photos/') {
          return Promise.resolve(opts.sourcePages[sourcePage++]);
        }
        return Promise.resolve({Contents: opts.destContents ?? [], IsTruncated: false});
      }
      if (cmd instanceof CopyObjectCommand) {
        if (cmd.input.Key === opts.failCopyForDestKey) {
          return Promise.reject(Object.assign(new Error('Access Denied'), {name: 'AccessDenied'}));
        }
        return Promise.resolve({});
      }
      return Promise.resolve({});
    });
  }

  it('recursively copies every key across pages, leaving the source intact (no delete)', async () => {
    routeSends({
      sourcePages: [
        {
          Contents: [{Key: 'alice/photos/'}, {Key: 'alice/photos/a.jpg'}],
          IsTruncated: true,
          NextContinuationToken: 'T2'
        },
        {Contents: [{Key: 'alice/photos/b.jpg'}], IsTruncated: false}
      ]
    });
    const onProgress = vi.fn();

    const result = await copyFolder({
      bucket: 'us',
      sourcePrefix: 'alice/photos/',
      destPrefix: 'alice/archive/photos/',
      username: 'alice',
      onProgress
    });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.copied).toEqual(['alice/photos/', 'alice/photos/a.jpg', 'alice/photos/b.jpg']);
    expect(result.data.errors).toEqual([]);

    const copies = mockSend.mock.calls.map((c) => c[0]).filter((c) => c instanceof CopyObjectCommand);
    expect(copies.map((c) => c.input.Key)).toEqual([
      'alice/archive/photos/',
      'alice/archive/photos/a.jpg',
      'alice/archive/photos/b.jpg'
    ]);
    expect(copies[1].input.CopySource).toBe('us/alice/photos/a.jpg');

    // The defining invariant: copy never deletes anything.
    const deletes = mockSend.mock.calls
      .map((c) => c[0])
      .filter((c) => c instanceof DeleteObjectCommand || c instanceof DeleteObjectsCommand);
    expect(deletes).toHaveLength(0);

    expect(onProgress).toHaveBeenLastCalledWith(3, 3);
  });

  it('records a per-key copy failure and continues (best-effort, no rollback)', async () => {
    routeSends({
      sourcePages: [
        {
          Contents: [{Key: 'alice/photos/'}, {Key: 'alice/photos/a.jpg'}, {Key: 'alice/photos/b.jpg'}],
          IsTruncated: false
        }
      ],
      failCopyForDestKey: 'alice/archive/photos/a.jpg'
    });

    const result = await copyFolder({
      bucket: 'us',
      sourcePrefix: 'alice/photos/',
      destPrefix: 'alice/archive/photos/',
      username: 'alice'
    });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.copied).toEqual(['alice/photos/', 'alice/photos/b.jpg']);
    expect(result.data.errors).toEqual([{key: 'alice/photos/a.jpg', message: 'Access Denied'}]);

    const deletes = mockSend.mock.calls
      .map((c) => c[0])
      .filter((c) => c instanceof DeleteObjectCommand || c instanceof DeleteObjectsCommand);
    expect(deletes).toHaveLength(0);
  });

  it('refuses up front when destinations already exist (Collision, no copies)', async () => {
    routeSends({
      sourcePages: [{Contents: [{Key: 'alice/photos/x.jpg'}], IsTruncated: false}],
      destContents: [{Key: 'alice/archive/photos/x.jpg'}]
    });

    const result = await copyFolder({
      bucket: 'us',
      sourcePrefix: 'alice/photos/',
      destPrefix: 'alice/archive/photos/',
      username: 'alice'
    });

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('Collision');
    expect(result.error.message).toMatch(/1 item/);

    const copies = mockSend.mock.calls.map((c) => c[0]).filter((c) => c instanceof CopyObjectCommand);
    expect(copies).toHaveLength(0);
  });

  it('rejects copying a folder into its own subtree (no S3 call)', async () => {
    const result = await copyFolder({
      bucket: 'us',
      sourcePrefix: 'alice/photos/',
      destPrefix: 'alice/photos/sub/',
      username: 'alice'
    });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('InvalidDestination');
    expect(mockSend).not.toHaveBeenCalled();
  });

  it('records the prefix marker as a per-key error and never sends it as a copy', async () => {
    // The recursive listing of a source folder can include the user's root marker
    // (here the source IS the user root, copied to a non-subtree dest). copyObject
    // refuses the marker, so it lands in errors and is never sent as a CopyObject;
    // the rest still copy. Dest is a sibling top-level prefix, not under the source.
    mockSend.mockImplementation((cmd) => {
      if (cmd instanceof ListObjectsV2Command) {
        if (cmd.input.Prefix === 'alice/') {
          return Promise.resolve({
            Contents: [{Key: 'alice/DO_NOT_DELETE.txt'}, {Key: 'alice/a.txt'}],
            IsTruncated: false
          });
        }
        return Promise.resolve({Contents: [], IsTruncated: false});
      }
      return Promise.resolve({});
    });

    const result = await copyFolder({
      bucket: 'us',
      sourcePrefix: 'alice/',
      destPrefix: 'backup-of-alice/',
      username: 'alice'
    });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.copied).toEqual(['alice/a.txt']);
    expect(result.data.errors).toHaveLength(1);
    expect(result.data.errors[0].key).toBe('alice/DO_NOT_DELETE.txt');

    const copies = mockSend.mock.calls.map((c) => c[0]).filter((c) => c instanceof CopyObjectCommand);
    expect(copies.map((c) => c.input.Key)).toEqual(['backup-of-alice/a.txt']);
  });

  it('is a no-op success when source and destination prefixes are equal', async () => {
    const result = await copyFolder({
      bucket: 'us',
      sourcePrefix: 'alice/photos/',
      destPrefix: 'alice/photos/',
      username: 'alice'
    });
    expect(result).toEqual({success: true, data: {copied: [], errors: []}});
    expect(mockSend).not.toHaveBeenCalled();
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
          expiration: new Date(Date.now() + secondsFromNow * 1000)
        })
      }
    };
  }

  it('builds a presigned GetObject URL with attachment disposition + default expiry', async () => {
    mockGetS3Client.mockResolvedValue({
      success: true,
      data: clientWithExpiry(3600)
    });
    mockGetSignedUrl.mockResolvedValue('https://signed.example/report.pdf');

    const result = await getDownloadUrl({bucket: 'us', key: 'alice/report.pdf'});

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.url).toBe('https://signed.example/report.pdf');
    expect(typeof result.data.expiresAt).toBe('string');

    const [, command, options] = mockGetSignedUrl.mock.calls[0];
    expect(command).toBeInstanceOf(GetObjectCommand);
    expect((command as GetObjectCommand).input).toMatchObject({
      Bucket: 'us',
      Key: 'alice/report.pdf',
      ResponseContentDisposition: 'attachment; filename="report.pdf"'
    });
    // Far-future credentials → uncapped default of 900s.
    expect(options).toEqual({expiresIn: 900});
  });

  it('defaults the filename to the last path segment', async () => {
    mockGetS3Client.mockResolvedValue({success: true, data: clientWithExpiry(3600)});
    mockGetSignedUrl.mockResolvedValue('https://signed');

    await getDownloadUrl({bucket: 'us', key: 'alice/docs/2024/q1.csv'});

    const [, command] = mockGetSignedUrl.mock.calls[0];
    expect((command as GetObjectCommand).input.ResponseContentDisposition).toBe('attachment; filename="q1.csv"');
  });

  it('caps the expiry to the remaining credential lifetime', async () => {
    mockGetS3Client.mockResolvedValue({success: true, data: clientWithExpiry(120)});
    mockGetSignedUrl.mockResolvedValue('https://signed');

    await getDownloadUrl({bucket: 'us', key: 'alice/f.txt', expiresInSeconds: 900});

    const options = mockGetSignedUrl.mock.calls[0][2];
    expect(options?.expiresIn).toBeGreaterThan(0);
    expect(options?.expiresIn).toBeLessThan(900); // capped below the requested 900
  });

  it('surfaces a no-credentials error after one forced-refresh retry, without signing', async () => {
    mockGetS3Client
      .mockResolvedValueOnce({
        success: false,
        error: {message: 'No AWS credentials — sign in required'}
      })
      .mockResolvedValueOnce({
        success: false,
        error: {message: 'No AWS credentials — sign in required'}
      });

    const result = await getDownloadUrl({bucket: 'us', key: 'alice/f.txt'});

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.message).toBe('No AWS credentials — sign in required');
    expect(mockGetS3Client).toHaveBeenCalledTimes(2);
    expect(mockGetS3Client).toHaveBeenNthCalledWith(2, true);
    expect(mockGetSignedUrl).not.toHaveBeenCalled();
  });
});

describe('objectExists', () => {
  it('returns true when HeadObject succeeds', async () => {
    mockSend.mockResolvedValueOnce({});
    const result = await objectExists({bucket: 'us', key: 'alice/f.txt'});
    expect(result).toEqual({success: true, data: true});
    expect(mockSend.mock.calls[0][0]).toBeInstanceOf(HeadObjectCommand);
  });

  it('returns false on NotFound (404), not an error', async () => {
    mockSend.mockRejectedValueOnce(notFoundError());
    const result = await objectExists({bucket: 'us', key: 'alice/missing'});
    expect(result).toEqual({success: true, data: false});
  });

  it('surfaces a non-404 error', async () => {
    mockSend.mockRejectedValueOnce(Object.assign(new Error('Access Denied'), {name: 'AccessDenied'}));
    const result = await objectExists({bucket: 'us', key: 'alice/f.txt'});
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('AccessDenied');
  });
});

describe('uploadPercent', () => {
  it('maps loaded/total to a clamped whole percent', () => {
    expect(uploadPercent(0, 100)).toBe(0);
    expect(uploadPercent(50, 100)).toBe(50);
    expect(uploadPercent(100, 100)).toBe(100);
    expect(uploadPercent(1, 3)).toBe(33);
    expect(uploadPercent(150, 100)).toBe(100); // clamp
  });

  it('treats a zero-byte file as 100% (no NaN/Infinity)', () => {
    expect(uploadPercent(0, 0)).toBe(100);
  });
});

describe('validateFolderName', () => {
  it('accepts a normal name', () => {
    expect(validateFolderName('documents')).toBeNull();
  });
  it('rejects empty / whitespace-only', () => {
    expect(validateFolderName('')).toMatch(/empty/i);
    expect(validateFolderName('   ')).toMatch(/empty/i);
  });
  it('rejects leading/trailing whitespace', () => {
    expect(validateFolderName(' docs')).toMatch(/spaces/i);
    expect(validateFolderName('docs ')).toMatch(/spaces/i);
  });
  it("rejects '/'", () => {
    expect(validateFolderName('a/b')).toMatch(/\//);
  });
  it('rejects control characters', () => {
    expect(validateFolderName('a\x01b')).toMatch(/control/i);
  });
});

describe('uploadFile', () => {
  function blob(size: number): Blob {
    return new Blob([new Uint8Array(size)]);
  }

  it('uploads via lib-storage and returns the key (overwrite skips the HEAD)', async () => {
    uploadState.doneImpl = async () => ({});
    const result = await uploadFile({
      bucket: 'us',
      key: 'alice/report.pdf',
      body: blob(10),
      contentType: 'application/pdf',
      overwrite: true
    });

    expect(result).toEqual({success: true, data: {key: 'alice/report.pdf'}});
    // overwrite:true → no HEAD collision check.
    expect(mockSend).not.toHaveBeenCalled();
    expect(uploadState.ctorArgs).toMatchObject({
      params: {
        Bucket: 'us',
        Key: 'alice/report.pdf',
        ContentType: 'application/pdf'
      },
      partSize: 5 * 1024 * 1024,
      queueSize: 4
    });
  });

  it('reports progress via onProgress', async () => {
    const onProgress = vi.fn();
    uploadState.doneImpl = async () => {
      uploadState.progressCb?.({loaded: 512, total: 1024});
      return {};
    };
    await uploadFile({
      bucket: 'us',
      key: 'alice/f.bin',
      body: blob(1024),
      contentType: 'application/octet-stream',
      overwrite: true,
      onProgress
    });
    expect(onProgress).toHaveBeenCalledWith(512, 1024);
  });

  it('refuses to overwrite when the key exists and overwrite is false (Collision)', async () => {
    mockSend.mockResolvedValueOnce({}); // HEAD → exists
    const result = await uploadFile({
      bucket: 'us',
      key: 'alice/report.pdf',
      body: blob(10),
      contentType: 'application/pdf'
    });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('Collision');
    expect(uploadState.ctorArgs).toBeNull(); // no upload attempted
  });

  it('proceeds when the key does not exist (HEAD 404 → upload)', async () => {
    mockSend.mockRejectedValueOnce(notFoundError()); // HEAD → 404
    uploadState.doneImpl = async () => ({});
    const result = await uploadFile({
      bucket: 'us',
      key: 'alice/new.pdf',
      body: blob(10),
      contentType: 'application/pdf'
    });
    expect(result.success).toBe(true);
    expect(uploadState.ctorArgs).not.toBeNull();
  });

  it('rejects a file over the maximum size before any request', async () => {
    const result = await uploadFile({
      bucket: 'us',
      key: 'alice/huge.bin',
      body: {size: MAX_UPLOAD_BYTES + 1} as Blob,
      contentType: 'application/octet-stream',
      overwrite: true
    });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('TooLarge');
    expect(uploadState.ctorArgs).toBeNull();
  });

  it('returns a cancelled result when the signal is already aborted', async () => {
    const controller = new AbortController();
    controller.abort();
    const result = await uploadFile({
      bucket: 'us',
      key: 'alice/f.bin',
      body: blob(10),
      contentType: 'application/octet-stream',
      overwrite: true,
      signal: controller.signal
    });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('Cancelled');
    expect(uploadState.ctorArgs).toBeNull();
  });

  it('aborts the upload and returns Cancelled when the signal fires mid-flight', async () => {
    const controller = new AbortController();
    uploadState.doneImpl = async () => {
      controller.abort();
      throw new Error('aborted');
    };
    const result = await uploadFile({
      bucket: 'us',
      key: 'alice/f.bin',
      body: blob(10),
      contentType: 'application/octet-stream',
      overwrite: true,
      signal: controller.signal
    });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('Cancelled');
    expect(uploadState.aborted).toBe(true); // upload.abort() was called
  });

  it('surfaces a no-credentials error without uploading', async () => {
    mockGetS3Client
      .mockResolvedValueOnce({success: false, error: {message: 'No AWS credentials — sign in required'}})
      .mockResolvedValueOnce({success: false, error: {message: 'No AWS credentials — sign in required'}});
    const result = await uploadFile({
      bucket: 'us',
      key: 'alice/f.bin',
      body: blob(10),
      contentType: 'application/octet-stream',
      overwrite: true // skip HEAD so the first getS3Client is uploadFile's own
    });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.message).toMatch(/No AWS credentials/);
    expect(uploadState.ctorArgs).toBeNull();
  });
});

describe('getObjectMetadata', () => {
  it('maps a HeadObject response onto ObjectMetadata', async () => {
    mockSend.mockResolvedValueOnce({
      ContentLength: 2048,
      ContentType: 'application/pdf',
      LastModified: new Date('2024-03-01T12:00:00Z'),
      ETag: '"abc123"',
      StorageClass: 'STANDARD_IA',
      Metadata: {author: 'alice', project: 'q1'}
    });

    const result = await getObjectMetadata({bucket: 'us', key: 'alice/report.pdf'});

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data).toEqual({
      key: 'alice/report.pdf',
      size: 2048,
      contentType: 'application/pdf',
      lastModified: new Date('2024-03-01T12:00:00Z'),
      etag: '"abc123"',
      storageClass: 'STANDARD_IA',
      userMetadata: {author: 'alice', project: 'q1'}
    });
    expect(mockSend.mock.calls[0][0]).toBeInstanceOf(HeadObjectCommand);
    expect(mockSend.mock.calls[0][0].input).toEqual({
      Bucket: 'us',
      Key: 'alice/report.pdf'
    });
  });

  it('defaults StorageClass to STANDARD and userMetadata to {} when S3 omits them', async () => {
    mockSend.mockResolvedValueOnce({
      ContentLength: 10,
      ContentType: 'text/plain',
      LastModified: new Date('2024-01-01T00:00:00Z'),
      ETag: '"e"'
      // no StorageClass, no Metadata
    });

    const result = await getObjectMetadata({bucket: 'us', key: 'alice/f.txt'});

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.storageClass).toBe('STANDARD');
    expect(result.data.userMetadata).toEqual({});
  });

  it('returns a NotFound error (not a throw) when the object is missing', async () => {
    mockSend.mockRejectedValueOnce(notFoundError());

    const result = await getObjectMetadata({bucket: 'us', key: 'alice/gone.txt'});

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('NotFound');
    expect(result.error.message).toMatch(/no longer exists/i);
  });

  it('retries once with refreshed credentials on an expired token', async () => {
    mockSend
      .mockRejectedValueOnce(Object.assign(new Error('token expired'), {name: 'ExpiredToken'}))
      .mockResolvedValueOnce({
        ContentLength: 1,
        ContentType: 'text/plain',
        LastModified: new Date('2024-01-01T00:00:00Z'),
        ETag: '"e"'
      });

    const result = await getObjectMetadata({bucket: 'us', key: 'alice/f.txt'});

    expect(result.success).toBe(true);
    expect(mockGetS3Client).toHaveBeenCalledTimes(2);
    expect(mockGetS3Client).toHaveBeenNthCalledWith(2, true);
  });
});

describe('createFolder', () => {
  it('creates a zero-byte marker at {prefix}{name}/ with directory content type', async () => {
    mockSend
      .mockRejectedValueOnce(notFoundError()) // HEAD → not found
      .mockResolvedValueOnce({}); // PUT → ok
    const result = await createFolder({bucket: 'us', prefix: 'alice/', name: 'photos'});

    expect(result).toEqual({success: true, data: {prefix: 'alice/photos/'}});
    const put = mockSend.mock.calls[1][0];
    expect(put).toBeInstanceOf(PutObjectCommand);
    expect(put.input).toMatchObject({
      Bucket: 'us',
      Key: 'alice/photos/',
      Body: '',
      ContentType: 'application/x-directory'
    });
  });

  it('rejects an invalid name before any request', async () => {
    const result = await createFolder({bucket: 'us', prefix: 'alice/', name: 'a/b'});
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('InvalidName');
    expect(mockSend).not.toHaveBeenCalled();
  });

  it('prompts collision when the folder already exists (no PUT)', async () => {
    mockSend.mockResolvedValueOnce({}); // HEAD → exists
    const result = await createFolder({bucket: 'us', prefix: 'alice/', name: 'photos'});
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('Collision');
    expect(mockSend).toHaveBeenCalledTimes(1); // only the HEAD
  });
});
