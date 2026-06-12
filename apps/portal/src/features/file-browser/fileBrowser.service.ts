import { ListObjectsV2Command, type S3Client } from '@aws-sdk/client-s3';
import { getS3Client, s3Client } from '../../lib/s3Client';
import type { FileList } from '../../types/s3.types';
import type { ServiceResult } from '../../types/service.types';

// SDK error names that mean the temporary credentials have expired mid-session.
// SPEC-013 FR-003: on these, retry once with getS3Client(true) so Amplify
// refreshes the Identity Pool credentials before the error is surfaced.
const EXPIRY_ERROR_CODES = new Set([
  'ExpiredToken',
  'ExpiredTokenException',
  'CredentialsProviderError',
  'InvalidToken',
]);

// Dev-only escape hatch (SPEC-013): browse a public/static test bucket without
// auth for local work without AWS. Honoured ONLY in a dev build, so the
// SPEC-001/002 anonymous/static-credential path is unreachable in production.
const devUnauthenticated =
  import.meta.env.DEV && import.meta.env.VITE_S3_DEV_UNAUTH === 'true';

export async function listFiles(
  bucket: string,
  prefix?: string,
): Promise<ServiceResult<FileList>> {
  if (devUnauthenticated) {
    return listWithClient(s3Client, bucket, prefix);
  }

  const clientResult = await getS3Client();
  if (!clientResult.success) return clientResult;

  const result = await listWithClient(clientResult.data, bucket, prefix);
  if (result.success || !isExpiryError(result.error.code)) return result;

  // Credentials expired mid-session — refresh once and retry transparently.
  const refreshed = await getS3Client(true);
  if (!refreshed.success) return refreshed;
  return listWithClient(refreshed.data, bucket, prefix);
}

function isExpiryError(code?: string): boolean {
  return code !== undefined && EXPIRY_ERROR_CODES.has(code);
}

async function listWithClient(
  client: S3Client,
  bucket: string,
  prefix?: string,
): Promise<ServiceResult<FileList>> {
  try {
    const command = new ListObjectsV2Command({
      Bucket: bucket,
      Prefix: prefix,
      Delimiter: '/',
    });

    const response = await client.send(command);

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
