import {
  DeleteObjectCommand,
  HeadObjectCommand,
  ListObjectsV2Command,
  PutObjectCommand,
  type S3Client,
} from '@aws-sdk/client-s3';
import { getS3Client, s3Client } from '../../lib/s3Client';
import type { FileList } from '../../types/s3.types';
import type { ServiceResult } from '../../types/service.types';
import {
  PREFIX_MARKER_BODY,
  prefixMarkerKey,
} from './fileBrowser.constants';

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

// Runs an authenticated S3 operation, transparently refreshing credentials and
// retrying once if they expired mid-session (SPEC-013 FR-003 pattern). Unlike
// listFiles, the marker/delete operations have no dev-unauthenticated fallback —
// they only run in the authenticated user-space flow (FilesPage gates on `user`).
async function withAuthenticatedClient<T>(
  op: (client: S3Client) => Promise<ServiceResult<T>>,
): Promise<ServiceResult<T>> {
  const clientResult = await getS3Client();
  if (!clientResult.success) return clientResult;

  const result = await op(clientResult.data);
  if (result.success || !isExpiryError(result.error.code)) return result;

  const refreshed = await getS3Client(true);
  if (!refreshed.success) return refreshed;
  return op(refreshed.data);
}

function toServiceError(err: unknown, fallback: string) {
  const e = err as { message?: string; name?: string };
  return {
    success: false as const,
    error: { message: e.message ?? fallback, code: e.name },
  };
}

function isNotFound(err: unknown): boolean {
  const e = err as { name?: string; $metadata?: { httpStatusCode?: number } };
  // HeadObject on a missing key surfaces as `NotFound` (404) in the v3 SDK.
  return e.name === 'NotFound' || e.$metadata?.httpStatusCode === 404;
}

// SPEC-014 FR-001: idempotently guarantee the user's prefix marker exists. Best
// effort and non-blocking — callers log a warning on failure and carry on (it
// retries next session). The in-memory guard below ensures at most one HEAD per
// session regardless of how many times this is called (navigation, StrictMode).
const ensuredMarkers = new Set<string>();

export async function ensurePrefixMarker(params: {
  bucket: string;
  username: string;
}): Promise<ServiceResult<{ created: boolean }>> {
  const { bucket, username } = params;
  const key = prefixMarkerKey(username);
  const cacheKey = `${bucket}/${key}`;

  // Synchronous check-and-set before any await: dedupes concurrent/StrictMode
  // double-invocations and repeat navigation within a session. A fresh page load
  // (new session) starts with an empty set, so a prior failure retries then.
  if (ensuredMarkers.has(cacheKey)) {
    return { success: true, data: { created: false } };
  }
  ensuredMarkers.add(cacheKey);

  return withAuthenticatedClient<{ created: boolean }>(async (client) => {
    try {
      // HEAD first — never overwrite an existing marker (FR-001).
      await client.send(new HeadObjectCommand({ Bucket: bucket, Key: key }));
      return { success: true, data: { created: false } };
    } catch (err) {
      if (!isNotFound(err)) {
        // Expiry errors propagate the code so withAuthenticatedClient retries;
        // any other error is surfaced to the (non-blocking) caller.
        return toServiceError(err, 'Failed to check prefix marker');
      }
    }

    try {
      await client.send(
        new PutObjectCommand({
          Bucket: bucket,
          Key: key,
          Body: PREFIX_MARKER_BODY,
          ContentType: 'text/plain',
        }),
      );
      return { success: true, data: { created: true } };
    } catch (err) {
      return toServiceError(err, 'Failed to create prefix marker');
    }
  });
}

// SPEC-014 FR-002/FR-003: is this exact key the user's root prefix marker? Used
// both to hide it from listings and to block deletion. Matches only the root
// marker — a user's own `DO_NOT_DELETE.txt` inside a subfolder has a different
// key and is unaffected.
export function isPrefixMarkerKey(key: string, username: string): boolean {
  return key === prefixMarkerKey(username);
}

// SPEC-014 FR-003: delete an object, refusing to delete the prefix marker. This
// is UI-layer defense in depth only — the authoritative protection is the IAM
// deny on `*/DO_NOT_DELETE.txt` in SPEC-013 FR-001's role policy. (Single-object
// delete; recursive/multi-select delete is SPEC-018 and can reuse this guard.)
export async function deleteObject(params: {
  bucket: string;
  key: string;
  username: string;
}): Promise<ServiceResult<{ key: string }>> {
  const { bucket, key, username } = params;

  if (isPrefixMarkerKey(key, username)) {
    return {
      success: false,
      error: {
        message:
          'This file keeps your storage space active and cannot be deleted.',
        code: 'ProtectedObject',
      },
    };
  }

  return withAuthenticatedClient(async (client) => {
    try {
      await client.send(new DeleteObjectCommand({ Bucket: bucket, Key: key }));
      return { success: true, data: { key } };
    } catch (err) {
      return toServiceError(err, 'Failed to delete object');
    }
  });
}

// Test-only: reset the once-per-session marker guard between cases.
export function __resetPrefixMarkerCache(): void {
  ensuredMarkers.clear();
}
