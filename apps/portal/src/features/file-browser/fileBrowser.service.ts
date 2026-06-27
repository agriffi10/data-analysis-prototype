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

// Credential-expiry detection + one-shot refresh-and-retry now live in the shared
// src/lib/credentialRetry helper (SPEC-034 FR-001), reused by the S3/Athena/Glue
// services. SPEC-013 FR-003 behavior is unchanged.

// Dev-only escape hatch (SPEC-013): browse a public/static test bucket without
// auth for local work without AWS. Honoured ONLY in a dev build, so the
// SPEC-001/002 anonymous/static-credential path is unreachable in production.
const devUnauthenticated = import.meta.env.DEV && import.meta.env.VITE_S3_DEV_UNAUTH === 'true';

// MaxKeys for the recursive collect-all-keys pass (delete/move, SPEC-018/019).
// 1000 is the S3 hard cap per page; a small page size here would only mean more
// round-trips. The user-facing listing page size is LISTING_PAGE_SIZE (SPEC-037).
const BULK_KEY_PAGE_SIZE = 1000;

export async function listFiles(
  bucket: string,
  prefix?: string,
  continuationToken?: string
): Promise<ServiceResult<FileListPage>> {
  if (devUnauthenticated) {
    return listWithClient(s3Client, bucket, prefix, continuationToken);
  }

  const clientResult = await getS3Client();
  if (!clientResult.success) return clientResult;

  const result = await listWithClient(clientResult.data, bucket, prefix, continuationToken);
  if (result.success || !isExpiryError(result.error.code)) return result;

  // Credentials expired mid-session — refresh once and retry transparently.
  const refreshed = await getS3Client(true);
  if (!refreshed.success) return refreshed;
  return listWithClient(refreshed.data, bucket, prefix, continuationToken);
}

async function listWithClient(
  client: S3Client,
  bucket: string,
  prefix?: string,
  continuationToken?: string
): Promise<ServiceResult<FileListPage>> {
  try {
    const command = new ListObjectsV2Command({
      Bucket: bucket,
      Prefix: prefix,
      Delimiter: '/',
      MaxKeys: LISTING_PAGE_SIZE,
      ContinuationToken: continuationToken
    });

    const response = await client.send(command);

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
    const error = err as {message?: string; name?: string};
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
// retrying once if they expired mid-session (SPEC-013 FR-003 pattern). Unlike
// listFiles, the marker/delete operations have no dev-unauthenticated fallback —
// they only run in the authenticated user-space flow (FilesPage gates on `user`).
async function withAuthenticatedClient<T>(
  op: (client: S3Client) => Promise<ServiceResult<T>>
): Promise<ServiceResult<T>> {
  return withCredentialRetry(getS3Client, op);
}

function toServiceError(err: unknown, fallback: string) {
  const e = err as {message?: string; name?: string};
  return {
    success: false as const,
    error: {message: e.message ?? fallback, code: e.name}
  };
}

function isNotFound(err: unknown): boolean {
  const e = err as {name?: string; $metadata?: {httpStatusCode?: number}};
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
      // HEAD first — never overwrite an existing marker (FR-001).
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

// S3's DeleteObjects hard limit: at most 1000 keys per request (SPEC-018 FR-002).
const DELETE_BATCH_SIZE = 1000;

function chunk<T>(items: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let i = 0; i < items.length; i += size) {
    chunks.push(items.slice(i, i + size));
  }
  return chunks;
}

// SPEC-018 FR-002: delete one or many objects in a single logical operation.
// Keys are chunked into ≤1000-key DeleteObjects requests; results aggregate
// across batches. The call never throws on partial failure — per-key errors S3
// returns (and the marker-guard refusal) are collected into `errors`, while the
// keys that succeeded are reported in `deleted`. Credential expiry mid-operation
// is retried once with refreshed credentials (the operation is idempotent —
// re-deleting an already-gone key is a success in S3).
//
// `username` is needed for the marker guard: the user's root marker
// (`{username}/DO_NOT_DELETE.txt`) is refused before the request and never sent
// to S3 (SPEC-014 FR-003 / SPEC-013 FR-001 defense in depth).
export async function deleteObjects(params: {
  bucket: string;
  keys: string[];
  username: string;
}): Promise<ServiceResult<DeleteResult>> {
  const {bucket, keys, username} = params;
  const markerKey = prefixMarkerKey(username);

  // Partition out the protected marker before touching S3 (FR-002).
  const markerErrors: DeleteResult['errors'] = [];
  const toDelete: string[] = [];
  for (const key of keys) {
    if (key === markerKey) {
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
// Deleted/Errors across batches. A whole-batch throw that is a credential-expiry
// error is propagated so withAuthenticatedClient refreshes and retries the whole
// operation; any other whole-batch failure records every key in that batch as an
// error and continues with the remaining batches (FR-002 partial failure).
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
          errors.push({
            key: e.Key,
            message: e.Message ?? e.Code ?? 'Failed to delete object'
          });
        }
      }
    } catch (err) {
      const e = err as {name?: string; message?: string};
      // Let credential expiry bubble up so the whole operation is retried once.
      if (isExpiryError(e.name)) return toServiceError(err, 'Failed to delete objects');
      // Other whole-batch failure: record each key and keep going.
      for (const key of batch) {
        errors.push({key, message: e.message ?? 'Failed to delete object'});
      }
    }
  }

  return {success: true, data: {deleted, errors}};
}

// SPEC-018 FR-003: delete a folder and everything beneath it. Lists every key
// under `prefix` recursively (no delimiter, paginating ListObjectsV2 past the
// 1000-key page cap), then batch-deletes via deleteObjects. The folder's own
// zero-byte marker key (`{prefix}`) is itself returned by the recursive listing,
// so an "empty" folder still disappears. A per-key failure never aborts the rest;
// the result reports total deleted and any failures.
export async function deleteFolder(params: {
  bucket: string;
  prefix: string;
  username: string;
}): Promise<ServiceResult<DeleteResult>> {
  const {bucket, prefix, username} = params;

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

// ── Move / rename (SPEC-019) ─────────────────────────────────────────────────

// Build the CopyObject `CopySource` value: `{bucket}/{key}`, with each path
// segment URL-encoded but the separators preserved. CopyObject is not auto-encoded
// by the SDK, so special characters in the key (spaces, %, etc.) must be escaped.
function buildCopySource(bucket: string, key: string): string {
  const encodedKey = key.split('/').map(encodeURIComponent).join('/');
  return `${bucket}/${encodedKey}`;
}

// SPEC-019 FR-001: copy a single object within the same bucket. Like uploadFile
// (SPEC-016), unless `overwrite` is true the destination is HEAD-checked first and
// the copy is refused with a `Collision` error rather than clobbering (versioning
// is off). The root marker may be neither source nor destination. Never throws.
export async function copyObject(params: {
  bucket: string;
  sourceKey: string;
  destKey: string;
  username: string;
  overwrite?: boolean;
}): Promise<ServiceResult<{destKey: string}>> {
  const {bucket, sourceKey, destKey, username, overwrite = false} = params;

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
    const exists = await objectExists({bucket, key: destKey});
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
          Bucket: bucket,
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

// SPEC-019 FR-001: move (= copy then delete the source). The source is deleted
// only after the copy succeeds — a failed copy leaves the source intact. A
// `sourceKey === destKey` request is a no-op success (rename to the same name).
export async function moveObject(params: {
  bucket: string;
  sourceKey: string;
  destKey: string;
  username: string;
  overwrite?: boolean;
}): Promise<ServiceResult<{destKey: string}>> {
  const {bucket, sourceKey, destKey, username, overwrite} = params;

  if (sourceKey === destKey) {
    return {success: true, data: {destKey}};
  }

  const copied = await copyObject({
    bucket,
    sourceKey,
    destKey,
    username,
    overwrite
  });
  if (!copied.success) return copied;

  const deleted = await deleteObject({bucket, key: sourceKey, username});
  if (!deleted.success) return deleted;

  return {success: true, data: {destKey}};
}

// SPEC-019 FR-004: move a folder and everything beneath it. Lists every key under
// `sourcePrefix` recursively, computes each destination by replacing the
// `sourcePrefix` portion with `destPrefix`, then moves each (copy-then-delete) so
// no source survives a successful move. Non-atomic: a key whose copy fails is left
// in place and recorded; the rest continue (FR-004). `onProgress` reports
// processed/total for large folders.
//
// Collision (FR-005): unless `overwrite` is true, the destinations are checked
// once up front (any existing destination object → a single `Collision` error
// naming the count) so the UI can confirm Overwrite-all or cancel.
export async function moveFolder(params: {
  bucket: string;
  sourcePrefix: string;
  destPrefix: string;
  username: string;
  overwrite?: boolean;
  onProgress?: (processed: number, total: number) => void;
}): Promise<ServiceResult<MoveResult>> {
  const {bucket, sourcePrefix, destPrefix, username, overwrite = false, onProgress} = params;

  if (sourcePrefix === destPrefix) {
    return {success: true, data: {moved: [], errors: []}};
  }
  // Moving a folder inside its own subtree would copy keys into themselves.
  if (destPrefix.startsWith(sourcePrefix)) {
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

  // Pre-flight collision check (FR-005): count destinations that already exist.
  if (!overwrite) {
    const existing = await withAuthenticatedClient((client) => listAllKeysUnderPrefix(client, bucket, destPrefix));
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
      overwrite: true
    });
    if (result.success) {
      moved.push(sourceKey);
    } else {
      errors.push({key: sourceKey, message: result.error.message});
    }
    onProgress?.(++processed, total);
  }

  return {success: true, data: {moved, errors}};
}

// ── Copy (SPEC-039) ──────────────────────────────────────────────────────────

// SPEC-039 FR-002: copy a folder and everything beneath it — the copy-only
// counterpart of moveFolder. Lists every key under `sourcePrefix` recursively,
// computes each destination by replacing the `sourcePrefix` portion with
// `destPrefix`, then copies each via copyObject. Unlike moveFolder, NO source is
// ever deleted (copy is strictly additive). Non-atomic and best-effort: a key
// whose copy fails is recorded and the rest continue. There is NO rollback — a
// partial copy leaves a partial duplicate under the destination, which the user
// can delete. `onProgress` reports processed/total for large folders.
//
// Collision (FR-005): unless `overwrite` is true, the destinations are checked
// once up front (any existing destination object → a single `Collision` error
// naming the count) so the UI can confirm Overwrite-all or cancel.
export async function copyFolder(params: {
  bucket: string;
  sourcePrefix: string;
  destPrefix: string;
  username: string;
  overwrite?: boolean;
  onProgress?: (processed: number, total: number) => void;
}): Promise<ServiceResult<CopyResult>> {
  const {bucket, sourcePrefix, destPrefix, username, overwrite = false, onProgress} = params;

  if (sourcePrefix === destPrefix) {
    return {success: true, data: {copied: [], errors: []}};
  }
  // Copying a folder inside its own subtree would copy keys into themselves.
  if (destPrefix.startsWith(sourcePrefix)) {
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

  // Pre-flight collision check (FR-005): count destinations that already exist.
  if (!overwrite) {
    const existing = await withAuthenticatedClient((client) => listAllKeysUnderPrefix(client, bucket, destPrefix));
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
      overwrite: true
    });
    if (result.success) {
      copied.push(sourceKey);
    } else {
      errors.push({key: sourceKey, message: result.error.message});
    }
    onProgress?.(++processed, total);
  }

  return {success: true, data: {copied, errors}};
}

// SPEC-015 FR-003. Default presigned-download lifetime: 15 minutes.
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

// SPEC-015 FR-003: generate a short-lived presigned GetObject URL so the browser
// can download a file directly from S3 (no backend). `ResponseContentDisposition`
// forces a save dialog with the real filename. The expiry defaults to 15 min and
// is capped to the remaining credential lifetime (the URL dies with the creds).
export async function getDownloadUrl(params: {
  bucket: string;
  key: string;
  fileName?: string; // defaults to the last path segment of the key
  expiresInSeconds?: number; // default 900, capped to credential TTL
}): Promise<ServiceResult<DownloadUrl>> {
  const {bucket, key} = params;
  const downloadName = params.fileName ?? fileName(key);
  const requested = params.expiresInSeconds ?? DEFAULT_DOWNLOAD_EXPIRY_SECONDS;

  // Acquire credentials; on none (signed out / expired) retry once with a forced
  // refresh before surfacing the error (FR-003).
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
      ResponseContentDisposition: `attachment; filename="${downloadName}"`
    });

    const url = await getSignedUrl(client, command, {expiresIn});
    const expiresAt = new Date(Date.now() + expiresIn * 1000).toISOString();
    return {success: true, data: {url, expiresAt}};
  } catch (err) {
    return toServiceError(err, 'Failed to generate download URL');
  }
}

// ── Upload + create folder (SPEC-016) ────────────────────────────────────────

// SPEC-016 FR-003: does an object already exist at this key? HEAD it; a
// NotFound/404 is a clean `false` (not an error). Callers use this to drive the
// warn-and-confirm collision prompt.
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

// SPEC-016 FR-002: map upload progress to a whole-number percentage. Guards the
// zero-byte case (total 0 → 100, never NaN/Infinity) and clamps to 0..100.
export function uploadPercent(loaded: number, total: number): number {
  if (!Number.isFinite(total) || total <= 0) return 100;
  const pct = Math.round((loaded / total) * 100);
  return Math.max(0, Math.min(100, pct));
}

// SPEC-016 FR-004: validate a new folder name before any request. Returns an
// error message, or null if the name is valid.
export function validateFolderName(name: string): string | null {
  if (name.trim().length === 0) return 'Folder name cannot be empty.';
  if (name !== name.trim()) return 'Folder name cannot start or end with spaces.';
  if (name.includes('/')) return "Folder name cannot contain '/'.";
  // eslint-disable-next-line no-control-regex
  if (/[\x00-\x1f]/.test(name)) return 'Folder name cannot contain control characters.';
  return null;
}

// SPEC-016 FR-001/FR-002/FR-003: upload a single file with the managed
// lib-storage Upload — single request at/below the 5 MiB part size, automatic
// multipart above it, with progress events. Never throws (returns ServiceResult).
//
// Collisions (FR-003): unless `overwrite` is true, HEAD-check first and refuse
// with a `Collision` error rather than clobbering (versioning is off). The caller
// resolves the collision (Overwrite → retry with overwrite:true; Rename → new key).
//
// Cancel: an optional AbortSignal aborts the upload (the SDK aborts the multipart
// upload, so no orphaned parts); the cancel *UI* is SPEC-020.
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

  // Collision guard (FR-003) unless the caller has chosen to overwrite.
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

  // Acquire credentials; one forced-refresh retry if missing (FR-001). The Upload
  // is a multi-call operation, so mid-flight expiry is surfaced, not retried.
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

    if (signal) {
      signal.addEventListener('abort', () => void upload.abort(), {once: true});
    }

    await upload.done();
    return {success: true, data: {key}};
  } catch (err) {
    if (signal?.aborted) {
      return {success: false, error: {message: 'Upload cancelled.', code: 'Cancelled'}};
    }
    return toServiceError(err, 'Failed to upload file');
  }
}

// SPEC-016 FR-004: create an empty folder as a zero-byte `{prefix}{name}/` marker
// object. Validates the name client-side and applies the same collision guard as
// upload (FR-003).
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

// ── Object metadata (SPEC-017) ───────────────────────────────────────────────

// SPEC-017 FR-001: fetch a single object's metadata via HeadObject (no body
// transfer). Maps the SDK response onto ObjectMetadata, defaulting StorageClass
// to "STANDARD" when S3 omits it. A NotFound/404 is surfaced as a clear
// ServiceResult error (the file was deleted out from under the listing), not a
// throw; credential expiry is retried once by withAuthenticatedClient.
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

// Test-only: reset the once-per-session marker guard between cases.
export function __resetPrefixMarkerCache(): void {
  ensuredMarkers.clear();
}
