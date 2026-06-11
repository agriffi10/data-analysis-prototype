import { ListObjectsV2Command } from '@aws-sdk/client-s3';
import { s3Client } from '../../lib/s3Client';
import type { FileList } from '../../types/s3.types';
import type { ServiceResult } from '../../types/service.types';

export async function listFiles(
  bucket: string,
  prefix?: string,
): Promise<ServiceResult<FileList>> {
  try {
    const command = new ListObjectsV2Command({
      Bucket: bucket,
      Prefix: prefix,
      Delimiter: '/',
    });

    const response = await s3Client.send(command);

    const folders = (response.CommonPrefixes ?? [])
      .filter((p): p is { Prefix: string } => typeof p.Prefix === 'string')
      .map((p) => ({
        type: 'folder' as const,
        prefix: p.Prefix,
        name: folderName(p.Prefix, prefix),
      }))
      .sort((a, b) => a.name.localeCompare(b.name));

    const files = (response.Contents ?? [])
      .filter((obj) => obj.Key !== undefined && obj.Key !== prefix)
      .map((obj) => ({
        type: 'file' as const,
        key: obj.Key!,
        name: fileName(obj.Key!),
        size: obj.Size ?? 0,
        lastModified: obj.LastModified ?? new Date(0),
      }))
      .sort((a, b) => a.name.localeCompare(b.name));

    return { success: true, data: { files, folders } };
  } catch (err) {
    const error = err as { message?: string; name?: string };
    return {
      success: false,
      error: {
        message: error.message ?? 'Unknown error listing files',
        code: error.name,
      },
    };
  }
}

function fileName(key: string): string {
  const parts = key.split('/');
  return parts[parts.length - 1] ?? key;
}

function folderName(folderPrefix: string, parentPrefix?: string): string {
  const withoutParent = parentPrefix
    ? folderPrefix.slice(parentPrefix.length)
    : folderPrefix;
  return withoutParent.replace(/\/$/, '');
}
