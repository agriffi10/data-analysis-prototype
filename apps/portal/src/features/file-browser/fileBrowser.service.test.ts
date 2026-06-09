import { describe, it, expect, vi, beforeEach, type MockedFunction } from 'vitest';
import { listFiles } from './fileBrowser.service';

vi.mock('../../lib/s3Client', () => ({
  s3Client: {
    send: vi.fn(),
  },
}));

import { s3Client } from '../../lib/s3Client';

// S3Client.send is a heavily-overloaded generic; cast to a simpler mock type
// so mockResolvedValueOnce / mockRejectedValueOnce work under strict TS.
const mockSend = s3Client.send as unknown as MockedFunction<
  () => Promise<unknown>
>;

beforeEach(() => {
  vi.clearAllMocks();
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
      CommonPrefixes: [
        { Prefix: 'monkeys/' },
        { Prefix: 'ants/' },
      ],
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
    mockSend.mockResolvedValueOnce({
      Contents: [],
      CommonPrefixes: [],
    });

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
    const sdkError = Object.assign(new Error('Access Denied'), { name: 'AccessDenied' });
    mockSend.mockRejectedValueOnce(sdkError);

    const result = await listFiles('my-bucket');

    expect(result.success).toBe(false);
    if (result.success) return;

    expect(result.error.message).toBe('Access Denied');
    expect(result.error.code).toBe('AccessDenied');
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
});
