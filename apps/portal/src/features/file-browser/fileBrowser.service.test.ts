import { describe, it, expect, vi, beforeEach } from 'vitest';
import { listFiles } from './fileBrowser.service';

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
});

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
        },
      }),
    );
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
