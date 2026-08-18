import {
  CopyObjectCommand,
  DeleteObjectCommand,
  DeleteObjectsCommand,
  GetObjectCommand,
  HeadObjectCommand,
  ListObjectsV2Command,
  PutObjectCommand,
  type S3Client
} from '@aws-sdk/client-s3';
import {getSignedUrl} from '@aws-sdk/s3-request-presigner';
import {Upload} from '@aws-sdk/lib-storage';
import {getS3Client, s3Client} from '../../lib/s3Client';
import {isExpiryError, withCredentialRetry} from '../../lib/credentialRetry';
import {toServiceError} from '../../lib/serviceResult';
import {isNotFound} from '../../lib/s3Errors';
import {undeletableRootFolderRefusal} from './protectedFolders';
import type {FileListPage} from '../../types/s3.types';
import type {ServiceResult} from '../../types/service.types';
import type {
  DownloadUrl,
  UploadResult,
  CreateFolderResult,
  ObjectMetadata,
  DeleteResult,
  MoveResult,
  CopyResult
} from './fileBrowser.types';
import {MAX_UPLOAD_BYTES, MULTIPART_PART_SIZE, PART_CONCURRENCY} from './fileBrowser.types';
import {LISTING_PAGE_SIZE, PREFIX_MARKER_BODY, prefixMarkerKey} from './fileBrowser.constants';

// Dev-only escape hatch: browse a public/static test bucket without auth for
// local work without AWS. Honoured ONLY in a dev build, so the unauthenticated
// path is unreachable in production.
const devUnauthenticated = import.meta.env.DEV && import.meta.env.VITE_S3_DEV_UNAUTH === 'true';

// MaxKeys for the recursive collect-all-keys pass (delete/move). 1000 is the S3
// hard cap per page; a smaller page here would only mean more round-trips. The
// user-facing listing page size is LISTING_PAGE_SIZE.
const BULK_KEY_PAGE_SIZE = 1000;

/**
 * Lists one page of folders + files under a prefix ('/'-delimited), refreshing
 * credentials and retrying once if they expired mid-session.
 */
export async function listFiles(
  bucket: string,
  prefix?: string,
  continuationToken?: string,
  abortSignal?: AbortSignal
): Promise<ServiceResult<FileListPage>> {
  if (devUnauthenticated) {
    return listWithClient(s3Client, bucket, prefix, continuationToken, abortSignal);
  }

  const clientResult = await getS3Client();
  if (!clientResult.success) return clientResult;

  const result = await listWithClient(clientResult.data, bucket, prefix, continuationToken, abortSignal);
  if (result.success || !isExpiryError(result.error.code)) return result;

  // Credentials expired mid-session — refresh once and retry transparently. The
  // signal is threaded through the retry too: dropping it here left SPEC-155
  // FR-006's guarantee (navigating out of a folder stops the request on the wire)
  // silently untrue on the one path where the listing takes longest.
  const refreshed = await getS3Client(true);
  if (!refreshed.success) return refreshed;
  return listWithClient(refreshed.data, bucket, prefix, continuationToken, abortSignal);
}

async function listWithClient(
  client: S3Client,
  bucket: string,
  prefix?: string,
  continuationToken?: string,
  abortSignal?: AbortSignal
): Promise<ServiceResult<FileListPage>> {
  try {
    const command = new ListObjectsV2Command({
      Bucket: bucket,
      Prefix: prefix,
      Delimiter: '/',
      MaxKeys: LISTING_PAGE_SIZE,
      ContinuationToken: continuationToken
    });

    // The SDK aborts the in-flight request, not just the promise —
    // navigating out of a folder mid-listing stops the request on the wire. TanStack
    // Query hands the caller a signal per query; this is where it lands.
    const response = await client.send(command, {abortSignal});

    const folders = (response.CommonPrefixes ?? [])
      .filter((p): p is {Prefix: string} => typeof p.Prefix === 'string')
      .map((p) => ({
        type: 'folder' as const,
        prefix: p.Prefix,
        name: folderName(p.Prefix, prefix)
      }))
      .sort((a, b) => a.name.localeCompare(b.name));

    const files = (response.Contents ?? [])
      .filter((obj) => obj.Key !== undefined && obj.Key !== prefix)
      .map((obj) => ({
        type: 'file' as const,
        key: obj.Key!,
        name: fileName(obj.Key!),
        size: obj.Size ?? 0,
        lastModified: obj.LastModified ?? new Date(0)
      }))
      .sort((a, b) => a.name.localeCompare(b.name));

    return {
      success: true,
      data: {
        files,
        folders,
        isTruncated: response.IsTruncated ?? false,
        nextContinuationToken: response.NextContinuationToken
      }
    };
  } catch (err) {
    const error = (typeof err === 'object' && err !== null ? err : {}) as {message?: string; name?: string};
    return {
      success: false,
      error: {
        message: error.message ?? 'Unknown error listing files',
        code: error.name
      }
    };
  }
}

function fileName(key: string): string {
  const parts = key.split('/');
  return parts[parts.length - 1] ?? key;
}

function folderName(folderPrefix: string, parentPrefix?: string): string {
  const withoutParent = parentPrefix ? folderPrefix.slice(parentPrefix.length) : folderPrefix;
  return withoutParent.replace(/\/$/, '');
}

// Runs an authenticated S3 operation, transparently refreshing credentials and
// retrying once if they expired mid-session. Unlike listFiles there is no
// dev-unauthenticated fallback — these operations only run in the authenticated
// user-space flow.
async function withAuthenticatedClient<T>(
  op: (client: S3Client) => Promise<ServiceResult<T>>
): Promise<ServiceResult<T>> {
  return withCredentialRetry(getS3Client, op);
}

// Once-per-session guard: at most one HEAD per bucket/marker no matter how many
// times ensurePrefixMarker runs (navigation, StrictMode).
const ensuredMarkers = new Set<string>();

/**
 * Idempotently guarantees the user's prefix-marker object exists. Best effort
 * and non-blocking — callers log a warning on failure and carry on (a fresh
 * session retries).
 */
export async function ensurePrefixMarker(params: {
  bucket: string;
  username: string;
}): Promise<ServiceResult<{created: boolean}>> {
  const {bucket, username} = params;
  const key = prefixMarkerKey(username);
  const cacheKey = `${bucket}/${key}`;

  // Synchronous check-and-set before any await: dedupes concurrent/StrictMode
  // double-invocations and repeat navigation within a session. A fresh page load
  // (new session) starts with an empty set, so a prior failure retries then.
  if (ensuredMarkers.has(cacheKey)) {
    return {success: true, data: {created: false}};
  }
  ensuredMarkers.add(cacheKey);

  return withAuthenticatedClient<{created: boolean}>(async (client) => {
    try {
      // HEAD first — never overwrite an existing marker.
      await client.send(new HeadObjectCommand({Bucket: bucket, Key: key}));
      return {success: true, data: {created: false}};
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
          ContentType: 'text/plain'
        })
      );
      return {success: true, data: {created: true}};
    } catch (err) {
      return toServiceError(err, 'Failed to create prefix marker');
    }
  });
}

/**
 * Is this exact key the user's root prefix marker? Used both to hide it from
 * listings and to block deletion. Matches only the root marker — a like-named
 * file inside a subfolder has a different key and is unaffected.
 */
export function isPrefixMarkerKey(key: string, username: string): boolean {
  return key === prefixMarkerKey(username);
}

/**
 * Deletes a single object, refusing to delete the prefix marker. The refusal is
 * UI-layer defense in depth only — the authoritative protection is the role
 * policy's IAM deny on every prefix's `DO_NOT_DELETE.txt`.
 */
export async function deleteObject(params: {
  bucket: string;
  key: string;
  username: string;
}): Promise<ServiceResult<{key: string}>> {
  const {bucket, key, username} = params;

  if (isPrefixMarkerKey(key, username)) {
    return {
      success: false,
      error: {
        message: 'This file keeps your storage space active and cannot be deleted.',
        code: 'ProtectedObject'
      }
    };
  }

  return withAuthenticatedClient(async (client) => {
    try {
      await client.send(new DeleteObjectCommand({Bucket: bucket, Key: key}));
      return {success: true, data: {key}};
    } catch (err) {
      return toServiceError(err, 'Failed to delete object');
    }
  });
}

// S3's DeleteObjects hard limit: at most 1000 keys per request.
const DELETE_BATCH_SIZE = 1000;

function chunk<T>(items: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let i = 0; i < items.length; i += size) {
    chunks.push(items.slice(i, i + size));
  }
  return chunks;
}

/**
 * Deletes one or many objects as a single logical operation. Keys are chunked
 * into ≤1000-key DeleteObjects requests; results aggregate across batches.
 * Never throws on partial failure — per-key errors (including the marker-guard
 * refusal) collect into `errors` while succeeded keys land in `deleted`.
 * Credential expiry mid-operation is retried once (safe: re-deleting an
 * already-gone key is a success in S3).
 *
 * @param params.username - identifies the root prefix marker, which is refused
 *   before the request and never sent to S3.
 */
export async function deleteObjects(params: {
  bucket: string;
  keys: string[];
  username: string;
}): Promise<ServiceResult<DeleteResult>> {
  const {bucket, keys, username} = params;
  const rootMarkerKey = prefixMarkerKey(username);

  // Partition out the protected marker before touching S3.
  const markerErrors: DeleteResult['errors'] = [];
  const toDelete: string[] = [];
  for (const key of keys) {
    if (key === rootMarkerKey) {
      markerErrors.push({
        key,
        message: 'This file keeps your storage space active and cannot be deleted.'
      });
    } else {
      toDelete.push(key);
    }
  }

  if (toDelete.length === 0) {
    return {success: true, data: {deleted: [], errors: markerErrors}};
  }

  const result = await withAuthenticatedClient((client) => deleteInBatches(client, bucket, toDelete));
  if (!result.success) return result;

  return {
    success: true,
    data: {
      deleted: result.data.deleted,
      errors: [...markerErrors, ...result.data.errors]
    }
  };
}

// Sends the keys as chunked DeleteObjects requests, aggregating S3's per-key
// Deleted/Errors across batches. A whole-batch credential-expiry throw is
// propagated so withAuthenticatedClient refreshes and retries the whole
// operation; any other whole-batch failure records every key in that batch as
// an error and continues with the remaining batches.
async function deleteInBatches(client: S3Client, bucket: string, keys: string[]): Promise<ServiceResult<DeleteResult>> {
  const deleted: string[] = [];
  const errors: DeleteResult['errors'] = [];

  for (const batch of chunk(keys, DELETE_BATCH_SIZE)) {
    try {
      const response = await client.send(
        new DeleteObjectsCommand({
          Bucket: bucket,
          Delete: {
            Objects: batch.map((Key) => ({Key})),
            Quiet: false
          }
        })
      );
      for (const d of response.Deleted ?? []) {
        if (d.Key) deleted.push(d.Key);
      }
      for (const e of response.Errors ?? []) {
        if (e.Key) {
          // e.Message/e.Code are raw S3 fields (technical); the surface maps
          // the code (e.g. AccessDenied) to friendly text.
          errors.push({
            key: e.Key,
            message: e.Message ?? e.Code ?? 'Failed to delete object',
            code: e.Code
          });
        }
      }
    } catch (err) {
      const e = (typeof err === 'object' && err !== null ? err : {}) as {name?: string; message?: string};
      // Let credential expiry bubble up so the whole operation is retried once.
      if (isExpiryError(e.name)) return toServiceError(err, 'Failed to delete objects');
      // Other whole-batch failure: record each key and keep going.
      for (const key of batch) {
        errors.push({key, message: e.message ?? 'Failed to delete object', code: e.name});
      }
    }
  }

  return {success: true, data: {deleted, errors}};
}

/**
 * Deletes a folder and everything beneath it: lists every key under `prefix`
 * recursively, then batch-deletes via deleteObjects. The folder's own zero-byte
 * marker key is itself returned by the recursive listing, so an "empty" folder
 * still disappears. A per-key failure never aborts the rest.
 *
 * @param params.rootPrefix - the SPACE root, which is what makes the protected-folder
 *   refusal below correct in a shared space as well as a personal one. Not derivable
 *   from `username`: in a shared space the root is the space name.
 */
export async function deleteFolder(params: {
  bucket: string;
  prefix: string;
  username: string;
  rootPrefix: string;
}): Promise<ServiceResult<DeleteResult>> {
  const {bucket, prefix, username, rootPrefix} = params;

  // Refused before any S3 request, like the prefix-marker guard above. The
  // authoritative protection is the role policy's `ResultsNoDelete` deny; this is
  // what stops the app offering an action its own IAM forbids.
  const refusal = undeletableRootFolderRefusal(prefix, rootPrefix, 'delete');
  if (refusal) {
    return {success: false, error: {message: refusal, code: 'ProtectedObject'}};
  }

  const listResult = await withAuthenticatedClient((client) => listAllKeysUnderPrefix(client, bucket, prefix));
  if (!listResult.success) return listResult;

  if (listResult.data.length === 0) {
    return {success: true, data: {deleted: [], errors: []}};
  }

  return deleteObjects({bucket, keys: listResult.data, username});
}

// Collects every object key under a prefix, paginating ListObjectsV2 past 1000
// keys. No Delimiter, so the listing is fully recursive (nested folders + the
// folder's own marker key are all returned).
async function listAllKeysUnderPrefix(
  client: S3Client,
  bucket: string,
  prefix: string
): Promise<ServiceResult<string[]>> {
  const keys: string[] = [];
  let continuationToken: string | undefined;

  try {
    do {
      const response = await client.send(
        new ListObjectsV2Command({
          Bucket: bucket,
          Prefix: prefix,
          MaxKeys: BULK_KEY_PAGE_SIZE,
          ContinuationToken: continuationToken
        })
      );
      for (const obj of response.Contents ?? []) {
        if (obj.Key) keys.push(obj.Key);
      }
      continuationToken = response.IsTruncated ? response.NextContinuationToken : undefined;
    } while (continuationToken);

    return {success: true, data: keys};
  } catch (err) {
    return toServiceError(err, 'Failed to list folder contents');
  }
}

// ── Move / rename ────────────────────────────────────────────────────────────

// Build the CopyObject `CopySource` value: `{bucket}/{key}`, with each path
// segment URL-encoded but the separators preserved. CopyObject is not auto-encoded
// by the SDK, so special characters in the key (spaces, %, etc.) must be escaped.
function buildCopySource(bucket: string, key: string): string {
  const encodedKey = key.split('/').map(encodeURIComponent).join('/');
  return `${bucket}/${encodedKey}`;
}

/**
 * Copies a single object. Unless `overwrite` is true the DESTINATION is
 * HEAD-checked first and the copy refused with a `Collision` error rather than
 * clobbering (versioning is off). The root marker may be neither source nor
 * destination. Never throws.
 */
export async function copyObject(params: {
  /** Source bucket. */
  bucket: string;
  sourceKey: string;
  destKey: string;
  username: string;
  /** Defaults to `bucket` (same-bucket copy); set to copy across buckets. */
  destBucket?: string;
  overwrite?: boolean;
}): Promise<ServiceResult<{destKey: string}>> {
  const {bucket, sourceKey, destKey, username, overwrite = false} = params;
  const destBucket = params.destBucket ?? bucket;

  if (isPrefixMarkerKey(sourceKey, username) || isPrefixMarkerKey(destKey, username)) {
    return {
      success: false,
      error: {
        message: 'This file keeps your storage space active and cannot be moved or renamed.',
        code: 'ProtectedObject'
      }
    };
  }

  if (!overwrite) {
    const exists = await objectExists({bucket: destBucket, key: destKey});
    if (!exists.success) return exists;
    if (exists.data) {
      return {
        success: false,
        error: {message: `"${destKey}" already exists.`, code: 'Collision'}
      };
    }
  }

  return withAuthenticatedClient(async (client) => {
    try {
      await client.send(
        new CopyObjectCommand({
          Bucket: destBucket,
          Key: destKey,
          CopySource: buildCopySource(bucket, sourceKey)
        })
      );
      return {success: true, data: {destKey}};
    } catch (err) {
      return toServiceError(err, 'Failed to copy object');
    }
  });
}

/**
 * Moves an object (S3 has no move: copy, then delete the source). The source is
 * deleted only after the copy succeeds — a failed copy leaves it intact. A
 * same-bucket `sourceKey === destKey` request is a no-op success.
 */
export async function moveObject(params: {
  /** Source bucket. */
  bucket: string;
  sourceKey: string;
  destKey: string;
  username: string;
  /** Defaults to `bucket` (same-bucket move); set to move to another connection's bucket. */
  destBucket?: string;
  overwrite?: boolean;
}): Promise<ServiceResult<{destKey: string}>> {
  const {bucket, sourceKey, destKey, username, overwrite} = params;
  const destBucket = params.destBucket ?? bucket;

  // Same bucket + same key is a no-op success (rename to the same name). Across
  // buckets the same key string is a distinct object, so the move still runs.
  if (bucket === destBucket && sourceKey === destKey) {
    return {success: true, data: {destKey}};
  }

  const copied = await copyObject({
    bucket,
    sourceKey,
    destKey,
    username,
    destBucket,
    overwrite
  });
  if (!copied.success) return copied;

  // Delete the source only after the copy lands — the source is in `bucket`.
  const deleted = await deleteObject({bucket, key: sourceKey, username});
  if (!deleted.success) return deleted;

  return {success: true, data: {destKey}};
}

/**
 * Moves a folder and everything beneath it: lists every key under
 * `sourcePrefix` recursively, rewrites each destination, then moves each
 * (copy-then-delete). Non-atomic — a key whose copy fails is left in place and
 * recorded while the rest continue.
 *
 * Unless `overwrite` is true, destinations are checked once up front; any
 * existing destination object yields a single `Collision` error naming the
 * count, so the UI can confirm Overwrite-all or cancel.
 *
 * @param params.rootPrefix - the SOURCE space's root, for the protected-folder
 *   refusal. A move is a copy plus a DELETE of the source, so `athenaresults/` is
 *   refused as a source for the same reason `deleteFolder` refuses it; it was
 *   already locked out as a destination by `PICKER_LOCKED_FOLDERS`.
 */
export async function moveFolder(params: {
  bucket: string;
  sourcePrefix: string;
  destPrefix: string;
  username: string;
  rootPrefix: string;
  /** Defaults to `bucket`; set to move into another connection's bucket. */
  destBucket?: string;
  overwrite?: boolean;
  /** Reports processed/total for large folders. */
  onProgress?: (processed: number, total: number) => void;
}): Promise<ServiceResult<MoveResult>> {
  const {bucket, sourcePrefix, destPrefix, username, rootPrefix, overwrite = false, onProgress} = params;
  const destBucket = params.destBucket ?? bucket;
  const sameBucket = destBucket === bucket;

  const refusal = undeletableRootFolderRefusal(sourcePrefix, rootPrefix, 'move');
  if (refusal) {
    return {success: false, error: {message: refusal, code: 'ProtectedObject'}};
  }

  // The no-op and into-itself guards only apply within a single bucket — across
  // buckets the same prefix string is a different location entirely.
  if (sameBucket && sourcePrefix === destPrefix) {
    return {success: true, data: {moved: [], errors: []}};
  }
  if (sameBucket && destPrefix.startsWith(sourcePrefix)) {
    return {
      success: false,
      error: {
        message: 'A folder cannot be moved into itself.',
        code: 'InvalidDestination'
      }
    };
  }

  const listed = await withAuthenticatedClient((client) => listAllKeysUnderPrefix(client, bucket, sourcePrefix));
  if (!listed.success) return listed;

  const sourceKeys = listed.data;
  if (sourceKeys.length === 0) {
    return {success: true, data: {moved: [], errors: []}};
  }

  const destKeyFor = (sourceKey: string) => destPrefix + sourceKey.slice(sourcePrefix.length);

  // Pre-flight collision check: count destinations that already exist in the
  // destination bucket.
  if (!overwrite) {
    const existing = await withAuthenticatedClient((client) => listAllKeysUnderPrefix(client, destBucket, destPrefix));
    if (!existing.success) return existing;
    const existingSet = new Set(existing.data);
    const collisions = sourceKeys.map(destKeyFor).filter((k) => existingSet.has(k)).length;
    if (collisions > 0) {
      return {
        success: false,
        error: {
          message: `${collisions} item(s) already exist at the destination.`,
          code: 'Collision'
        }
      };
    }
  }

  const moved: string[] = [];
  const errors: MoveResult['errors'] = [];
  const total = sourceKeys.length;
  let processed = 0;

  for (const sourceKey of sourceKeys) {
    // Destinations were verified clear (or the user chose overwrite), so each
    // per-key move skips its own HEAD with overwrite: true.
    const result = await moveObject({
      bucket,
      sourceKey,
      destKey: destKeyFor(sourceKey),
      username,
      destBucket,
      overwrite: true
    });
    if (result.success) {
      moved.push(sourceKey);
    } else {
      errors.push({key: sourceKey, message: result.error.message, code: result.error.code});
    }
    onProgress?.(++processed, total);
  }

  return {success: true, data: {moved, errors}};
}

// ── Copy ─────────────────────────────────────────────────────────────────────

/**
 * Copies a folder and everything beneath it — the copy-only counterpart of
 * moveFolder. Strictly additive: no source is ever deleted. Non-atomic and
 * best-effort — a key whose copy fails is recorded and the rest continue, with
 * NO rollback (a partial copy leaves a partial duplicate the user can delete).
 *
 * Unless `overwrite` is true, destinations are checked once up front; any
 * existing destination object yields a single `Collision` error naming the
 * count, so the UI can confirm Overwrite-all or cancel.
 */
export async function copyFolder(params: {
  bucket: string;
  sourcePrefix: string;
  destPrefix: string;
  username: string;
  /** Defaults to `bucket`; set to copy into another connection's bucket. */
  destBucket?: string;
  overwrite?: boolean;
  /** Reports processed/total for large folders. */
  onProgress?: (processed: number, total: number) => void;
}): Promise<ServiceResult<CopyResult>> {
  const {bucket, sourcePrefix, destPrefix, username, overwrite = false, onProgress} = params;
  const destBucket = params.destBucket ?? bucket;
  const sameBucket = destBucket === bucket;

  // The no-op and into-itself guards only apply within a single bucket.
  if (sameBucket && sourcePrefix === destPrefix) {
    return {success: true, data: {copied: [], errors: []}};
  }
  if (sameBucket && destPrefix.startsWith(sourcePrefix)) {
    return {
      success: false,
      error: {
        message: 'A folder cannot be copied into itself.',
        code: 'InvalidDestination'
      }
    };
  }

  const listed = await withAuthenticatedClient((client) => listAllKeysUnderPrefix(client, bucket, sourcePrefix));
  if (!listed.success) return listed;

  const sourceKeys = listed.data;
  if (sourceKeys.length === 0) {
    return {success: true, data: {copied: [], errors: []}};
  }

  const destKeyFor = (sourceKey: string) => destPrefix + sourceKey.slice(sourcePrefix.length);

  // Pre-flight collision check: count destinations that already exist in the
  // destination bucket.
  if (!overwrite) {
    const existing = await withAuthenticatedClient((client) => listAllKeysUnderPrefix(client, destBucket, destPrefix));
    if (!existing.success) return existing;
    const existingSet = new Set(existing.data);
    const collisions = sourceKeys.map(destKeyFor).filter((k) => existingSet.has(k)).length;
    if (collisions > 0) {
      return {
        success: false,
        error: {
          message: `${collisions} item(s) already exist at the destination.`,
          code: 'Collision'
        }
      };
    }
  }

  const copied: string[] = [];
  const errors: CopyResult['errors'] = [];
  const total = sourceKeys.length;
  let processed = 0;

  for (const sourceKey of sourceKeys) {
    // Destinations were verified clear (or the user chose overwrite), so each
    // per-key copy skips its own HEAD with overwrite: true.
    const result = await copyObject({
      bucket,
      sourceKey,
      destKey: destKeyFor(sourceKey),
      username,
      destBucket,
      overwrite: true
    });
    if (result.success) {
      copied.push(sourceKey);
    } else {
      errors.push({key: sourceKey, message: result.error.message, code: result.error.code});
    }
    onProgress?.(++processed, total);
  }

  return {success: true, data: {copied, errors}};
}

// Default presigned-download lifetime: 15 minutes.
const DEFAULT_DOWNLOAD_EXPIRY_SECONDS = 900;

// Remaining lifetime (seconds) on the client's temporary credentials, or
// undefined if it can't be determined. A presigned URL can never outlive the
// credentials that signed it, so we use this to cap the advertised expiry.
async function remainingCredentialSeconds(client: S3Client): Promise<number | undefined> {
  try {
    const provider = client.config?.credentials;
    if (typeof provider !== 'function') return undefined;
    const creds = await provider();
    if (!creds?.expiration) return undefined;
    const seconds = Math.floor((new Date(creds.expiration).getTime() - Date.now()) / 1000);
    return seconds > 0 ? seconds : 0;
  } catch {
    return undefined;
  }
}

/**
 * Generates a short-lived presigned GetObject URL so the browser can download a
 * file directly from S3 (no backend). `ResponseContentDisposition` forces a
 * save dialog with the real filename. The expiry defaults to 15 min and is
 * capped to the remaining credential lifetime (the URL dies with the creds).
 */
export async function getDownloadUrl(params: {
  bucket: string;
  key: string;
  /** Defaults to the last path segment of the key. */
  fileName?: string;
  /** Default 900; capped to the credential TTL. */
  expiresInSeconds?: number;
}): Promise<ServiceResult<DownloadUrl>> {
  const {bucket, key} = params;
  const downloadName = params.fileName ?? fileName(key);
  const requested = params.expiresInSeconds ?? DEFAULT_DOWNLOAD_EXPIRY_SECONDS;

  // Acquire credentials; on none (signed out / expired) retry once with a forced
  // refresh before surfacing the error.
  let clientResult = await getS3Client();
  if (!clientResult.success) {
    clientResult = await getS3Client(true);
    if (!clientResult.success) return clientResult;
  }
  const client = clientResult.data;

  try {
    const remaining = await remainingCredentialSeconds(client);
    const expiresIn = remaining === undefined ? requested : Math.min(requested, remaining);

    const command = new GetObjectCommand({
      Bucket: bucket,
      Key: key,
      // S3 permits `"` in a key, and a quote in the name would close the quoted-string
      // early and let the rest be read as Content-Disposition parameters. RFC 6266
      // quoted-string escaping: backslash the backslashes first, then the quotes.
      ResponseContentDisposition: `attachment; filename="${downloadName.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`
    });

    const url = await getSignedUrl(client, command, {expiresIn});
    return {success: true, data: {url}};
  } catch (err) {
    return toServiceError(err, 'Failed to generate download URL');
  }
}

// ── Upload + create folder ───────────────────────────────────────────────────

/**
 * Does an object already exist at this key? HEADs it; NotFound/404 is a clean
 * `false`, not an error. Drives the warn-and-confirm collision prompt.
 */
export async function objectExists(params: {bucket: string; key: string}): Promise<ServiceResult<boolean>> {
  const {bucket, key} = params;
  return withAuthenticatedClient(async (client) => {
    try {
      await client.send(new HeadObjectCommand({Bucket: bucket, Key: key}));
      return {success: true, data: true};
    } catch (err) {
      if (isNotFound(err)) return {success: true, data: false};
      return toServiceError(err, 'Failed to check whether the object exists');
    }
  });
}

/**
 * Maps upload progress to a whole-number percentage, guarding the zero-byte
 * case (total 0 → 100, never NaN/Infinity) and clamping to 0..100.
 */
export function uploadPercent(loaded: number, total: number): number {
  if (!Number.isFinite(total) || total <= 0) return 100;
  const pct = Math.round((loaded / total) * 100);
  return Math.max(0, Math.min(100, pct));
}

/**
 * Validates one path LEAF — a folder name, a file name, a saved query's name.
 *
 * The rules are the same wherever a user names a single S3 path segment; only the
 * noun changes, which is why the caller supplies it rather than each surface
 * re-deriving the four checks.
 *
 * @param name - The raw value the user typed.
 * @param label - Sentence-initial noun for the message, e.g. `Folder name`.
 * @returns An error message, or null when the name is valid.
 */
export function validateLeafName(name: string, label: string): string | null {
  if (name.trim().length === 0) return `${label} cannot be empty.`;
  if (name !== name.trim()) return `${label} cannot start or end with spaces.`;
  if (name.includes('/')) return `${label} cannot contain '/'.`;
  // eslint-disable-next-line no-control-regex
  if (/[\x00-\x1f]/.test(name)) return `${label} cannot contain control characters.`;
  return null;
}

/** Validates a new folder name before any request. Returns an error message, or null if valid. */
export function validateFolderName(name: string): string | null {
  return validateLeafName(name, 'Folder name');
}

/**
 * Uploads a single file with the managed lib-storage Upload — single request
 * at/below the 5 MiB part size, automatic multipart above it, with progress
 * events. Never throws.
 *
 * Unless `overwrite` is true the key is HEAD-checked first and the upload
 * refused with a `Collision` error rather than clobbering (versioning is off);
 * the caller resolves it (Overwrite → retry with overwrite:true; Rename → new
 * key). An optional AbortSignal cancels — the SDK aborts the multipart upload,
 * so no orphaned parts.
 */
export async function uploadFile(params: {
  bucket: string;
  key: string;
  body: Blob | File;
  contentType: string;
  overwrite?: boolean;
  onProgress?: (loaded: number, total: number) => void;
  signal?: AbortSignal;
}): Promise<ServiceResult<UploadResult>> {
  const {bucket, key, body, contentType, overwrite = false, onProgress, signal} = params;

  if (body.size > MAX_UPLOAD_BYTES) {
    return {
      success: false,
      error: {
        message: `File exceeds the maximum upload size of ${MAX_UPLOAD_BYTES} bytes.`,
        code: 'TooLarge'
      }
    };
  }

  if (signal?.aborted) {
    return {success: false, error: {message: 'Upload cancelled.', code: 'Cancelled'}};
  }

  // Collision guard unless the caller has chosen to overwrite.
  if (!overwrite) {
    const exists = await objectExists({bucket, key});
    if (!exists.success) return exists;
    if (exists.data) {
      return {
        success: false,
        error: {message: `"${key}" already exists.`, code: 'Collision'}
      };
    }
  }

  // Acquire credentials; one forced-refresh retry if missing. The Upload is a
  // multi-call operation, so mid-flight expiry is surfaced, not retried.
  let clientResult = await getS3Client();
  if (!clientResult.success) {
    clientResult = await getS3Client(true);
    if (!clientResult.success) return clientResult;
  }

  try {
    const upload = new Upload({
      client: clientResult.data,
      params: {Bucket: bucket, Key: key, Body: body, ContentType: contentType},
      partSize: MULTIPART_PART_SIZE,
      queueSize: PART_CONCURRENCY
    });

    if (onProgress) {
      upload.on('httpUploadProgress', (progress) => {
        onProgress(progress.loaded ?? 0, progress.total ?? body.size);
      });
    }

    // `{once: true}` fires the listener at most once but does NOT remove it when the
    // upload finishes normally — so a long-lived queue signal accumulated one closure
    // per completed file, each holding its Upload alive. Removed in `finally`.
    const onAbort = () => void upload.abort();
    signal?.addEventListener('abort', onAbort, {once: true});

    try {
      await upload.done();
      return {success: true, data: {key}};
    } finally {
      signal?.removeEventListener('abort', onAbort);
    }
  } catch (err) {
    if (signal?.aborted) {
      return {success: false, error: {message: 'Upload cancelled.', code: 'Cancelled'}};
    }
    return toServiceError(err, 'Failed to upload file');
  }
}

/**
 * Creates an empty folder as a zero-byte `{prefix}{name}/` marker object.
 * Validates the name client-side and applies the same collision guard as
 * upload.
 */
export async function createFolder(params: {
  bucket: string;
  prefix: string;
  name: string;
  overwrite?: boolean;
}): Promise<ServiceResult<CreateFolderResult>> {
  const {bucket, prefix, name, overwrite = false} = params;

  const nameError = validateFolderName(name);
  if (nameError) {
    return {success: false, error: {message: nameError, code: 'InvalidName'}};
  }

  const folderPrefix = `${prefix}${name}/`;

  if (!overwrite) {
    const exists = await objectExists({bucket, key: folderPrefix});
    if (!exists.success) return exists;
    if (exists.data) {
      return {
        success: false,
        error: {
          message: `A folder named "${name}" already exists.`,
          code: 'Collision'
        }
      };
    }
  }

  return withAuthenticatedClient(async (client) => {
    try {
      await client.send(
        new PutObjectCommand({
          Bucket: bucket,
          Key: folderPrefix,
          Body: '',
          ContentType: 'application/x-directory'
        })
      );
      return {success: true, data: {prefix: folderPrefix}};
    } catch (err) {
      return toServiceError(err, 'Failed to create folder');
    }
  });
}

// ── Object metadata ──────────────────────────────────────────────────────────

/**
 * Fetches a single object's metadata via HeadObject (no body transfer),
 * defaulting StorageClass to "STANDARD" when S3 omits it. NotFound (the file
 * was deleted out from under the listing) surfaces as a clear error, not a
 * throw.
 */
export async function getObjectMetadata(params: {bucket: string; key: string}): Promise<ServiceResult<ObjectMetadata>> {
  const {bucket, key} = params;
  return withAuthenticatedClient(async (client) => {
    try {
      const response = await client.send(new HeadObjectCommand({Bucket: bucket, Key: key}));
      return {
        success: true,
        data: {
          key,
          contentType: response.ContentType ?? 'application/octet-stream',
          size: response.ContentLength ?? 0,
          lastModified: response.LastModified ?? new Date(0),
          etag: response.ETag ?? '',
          storageClass: response.StorageClass ?? 'STANDARD',
          userMetadata: response.Metadata ?? {}
        }
      };
    } catch (err) {
      if (isNotFound(err)) {
        return {
          success: false,
          error: {message: 'This file no longer exists.', code: 'NotFound'}
        };
      }
      return toServiceError(err, 'Failed to load file details');
    }
  });
}

/** Test-only: resets the once-per-session marker guard between cases. */
export function __resetPrefixMarkerCache(): void {
  ensuredMarkers.clear();
}
