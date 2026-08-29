import {apiRequest} from '../../lib/apiClient';
import {spaceFor} from '../../lib/objectSpace';
import {fromApiFailure, ok, toServiceError} from '../../lib/serviceResult';
import type {FileListPage} from '../../types/s3.types';
import type {ServiceResult} from '../../types/service.types';
import type {SpaceRef} from '../../types/apiContract.generated';
import type {DownloadUrl, UploadResult, CreateFolderResult, ObjectMetadata} from './fileBrowser.types';
import {maxUploadBytes} from './uploadLimits';
import {PREFIX_MARKER_BODY, prefixMarkerKey} from './fileBrowser.constants';

/**
 * The flattened space a GET route's query carries.
 *
 * A query string holds strings and nothing else, so a `GET` route cannot take the `SpaceRef` every
 * `POST` body carries. The divergence looks like sloppiness and is the constraint.
 */
function spaceQuery(bucket: string, keyOrPrefix: string): {spaceKind: SpaceRef['kind']; spaceName: string} {
  const space = spaceFor(bucket, keyOrPrefix);
  return {spaceKind: space.kind, spaceName: space.name};
}

/**
 * Lists one page of folders + files under a prefix.
 *
 * The listing stays browser-driven — a page at a time, on the user's navigation — and only its
 * transport changed. The route delimits and bounds the page itself, so the two parameters that
 * used to travel (`Delimiter`, `MaxKeys`) are the route's business now.
 *
 * @param bucket - The bucket the space lives in.
 * @param prefix - The folder to list; its first segment names the space.
 * @param continuationToken - S3's token, opaque and round-tripped unmodified.
 * @param abortSignal - Dropped-query signal. **It stops the browser waiting, not the request on
 *   the wire** — a Lambda invocation cannot be cancelled, so the listing completes server-side and
 *   the answer is discarded. That is a real change from the SDK path, which aborted the socket.
 * @returns One page, or a failure.
 */
export async function listFiles(
  bucket: string,
  prefix?: string,
  continuationToken?: string,
  abortSignal?: AbortSignal
): Promise<ServiceResult<FileListPage>> {
  const listed = await apiRequest('objects.list', {
    query: {
      ...spaceQuery(bucket, prefix ?? ''),
      ...(prefix ? {prefix} : {}),
      ...(continuationToken ? {nextToken: continuationToken} : {})
    },
    signal: abortSignal
  });
  if (!listed.success) return fromApiFailure(listed.error, 'Unknown error listing files');

  const folders = listed.data.items
    .filter((item) => item.kind === 'folder')
    .map((item) => ({type: 'folder' as const, prefix: item.key, name: folderName(item.key, prefix)}))
    .sort((a, b) => a.name.localeCompare(b.name));

  const files = listed.data.items
    .filter((item) => item.kind === 'file')
    .map((item) => ({
      type: 'file' as const,
      key: item.key,
      name: fileName(item.key),
      size: item.size ?? 0,
      lastModified: item.lastModified ? new Date(item.lastModified) : new Date(0)
    }))
    .sort((a, b) => a.name.localeCompare(b.name));

  return ok({
    files,
    folders,
    isTruncated: listed.data.nextToken !== null,
    nextContinuationToken: listed.data.nextToken ?? undefined
  });
}

function fileName(key: string): string {
  const parts = key.split('/');
  return parts[parts.length - 1] ?? key;
}

function folderName(folderPrefix: string, parentPrefix?: string): string {
  const withoutParent = parentPrefix ? folderPrefix.slice(parentPrefix.length) : folderPrefix;
  return withoutParent.replace(/\/$/, '');
}

// Once-per-session guard: at most one write attempt per bucket/marker no matter how many
// times ensurePrefixMarker runs (navigation, StrictMode).
const ensuredMarkers = new Set<string>();

/**
 * Idempotently guarantees the user's prefix-marker object exists.
 *
 * Best effort and non-blocking — callers log a warning on failure and carry on (a fresh session
 * retries).
 *
 * **One call, not two.** The existence check the browser used to make first now lives inside the
 * write route: `overwrite: false` returns `Conflict` when the marker is already there, which is
 * this function's success case. Asking separately paid for two round trips to learn one thing, and
 * let the two answers disagree.
 *
 * @param params.bucket - The bucket holding the space.
 * @param params.username - The signed-in user, whose root the marker sits at.
 * @returns Whether it had to write one.
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
  if (ensuredMarkers.has(cacheKey)) return ok({created: false});
  ensuredMarkers.add(cacheKey);

  const written = await apiRequest('objects.writeContent', {
    body: {
      space: spaceFor(bucket, key),
      key,
      body: PREFIX_MARKER_BODY,
      contentType: 'text/plain',
      overwrite: false
    }
  });
  if (written.success) return ok({created: true});
  if (written.error.code === 'Conflict') return ok({created: false});
  return fromApiFailure(written.error, 'Failed to create prefix marker');
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
 * Deletes a single object, refusing to delete the prefix marker.
 *
 * The refusal here is the affordance; the route refuses every marker key by basename and both
 * bucket policies deny it outright, so this is the innermost of three.
 *
 * @param params.bucket - The bucket holding the object.
 * @param params.key - The object key.
 * @param params.username - The signed-in user, for the marker guard.
 * @returns The key deleted, or a failure.
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

  const deleted = await apiRequest('objects.delete', {body: {space: spaceFor(bucket, key), key}});
  if (!deleted.success) return fromApiFailure(deleted.error, 'Failed to delete object');
  return ok({key});
}

/**
 * Copies a single object, refusing an occupied destination unless `overwrite`.
 *
 * The collision check moved inside the route, so a copy costs one call rather than two and the
 * check cannot disagree with the copy it guards. The refusal's wording is still minted here, from
 * the destination key this caller already holds — the wire carries a code, never a sentence.
 *
 * @param params.bucket - The source bucket.
 * @param params.sourceKey - The object to copy.
 * @param params.destKey - Where to put it.
 * @param params.username - The signed-in user, for the marker guard.
 * @param params.destBucket - Defaults to `bucket`; set to copy across buckets.
 * @param params.overwrite - Replace an occupied destination.
 * @returns The destination key, or a failure (`ProtectedObject` / `Collision`).
 */
export async function copyObject(params: {
  bucket: string;
  sourceKey: string;
  destKey: string;
  username: string;
  destBucket?: string;
  overwrite?: boolean;
}): Promise<ServiceResult<{destKey: string}>> {
  const {bucket, sourceKey, destKey, username, overwrite = false} = params;
  const destBucket = params.destBucket ?? bucket;

  const refusal = markerRefusal(sourceKey, destKey, username);
  if (refusal) return refusal;

  const copied = await apiRequest('objects.copy', {
    body: {
      source: spaceFor(bucket, sourceKey),
      sourceKey,
      destination: spaceFor(destBucket, destKey),
      destinationKey: destKey,
      overwrite
    }
  });
  if (!copied.success) return collisionOr(copied.error, destKey, 'Failed to copy object');
  return ok({destKey});
}

/**
 * Moves an object.
 *
 * **One route, not a copy call followed by a delete call.** Two calls put a closed tab between
 * them, and with versioning off that is a lost file rather than a failed move.
 *
 * A same-bucket `sourceKey === destKey` request is a no-op success — renaming a file to the name
 * it already has.
 *
 * @param params.bucket - The source bucket.
 * @param params.sourceKey - The object to move.
 * @param params.destKey - Where to put it.
 * @param params.username - The signed-in user, for the marker guard.
 * @param params.destBucket - Defaults to `bucket`; set to move across buckets.
 * @param params.overwrite - Replace an occupied destination.
 * @returns The destination key, or a failure.
 */
export async function moveObject(params: {
  bucket: string;
  sourceKey: string;
  destKey: string;
  username: string;
  destBucket?: string;
  overwrite?: boolean;
}): Promise<ServiceResult<{destKey: string}>> {
  const {bucket, sourceKey, destKey, username, overwrite = false} = params;
  const destBucket = params.destBucket ?? bucket;

  if (bucket === destBucket && sourceKey === destKey) return ok({destKey});

  const refusal = markerRefusal(sourceKey, destKey, username);
  if (refusal) return refusal;

  const moved = await apiRequest('objects.move', {
    body: {
      source: spaceFor(bucket, sourceKey),
      sourceKey,
      destination: spaceFor(destBucket, destKey),
      destinationKey: destKey,
      overwrite
    }
  });
  if (!moved.success) return collisionOr(moved.error, destKey, 'Failed to move object');
  return ok({destKey});
}

// The one wording for a marker used as either end of a copy or a move. Both operations refuse it
// for the same reason and said so in the same sentence; one copy keeps them from drifting.
function markerRefusal(sourceKey: string, destKey: string, username: string): ServiceResult<never> | undefined {
  if (!isPrefixMarkerKey(sourceKey, username) && !isPrefixMarkerKey(destKey, username)) return undefined;
  return {
    success: false,
    error: {
      message: 'This file keeps your storage space active and cannot be moved or renamed.',
      code: 'ProtectedObject'
    }
  };
}

// `Conflict` is the one API code this surface re-words rather than passes on: `Collision` is a
// `passthrough` code, so it may never travel on the wire, and the sentence is minted here from the
// destination key the caller already has. Every other code falls through to `toUserMessage`.
function collisionOr(error: {message: string; code?: string}, destKey: string, fallback: string): ServiceResult<never> {
  if (error.code === 'Conflict') {
    return {success: false, error: {message: `"${destKey}" already exists.`, code: 'Collision'}};
  }
  return fromApiFailure(error, fallback);
}

/**
 * Mints a short-lived presigned `GET` so the browser downloads bytes straight from S3.
 *
 * The URL is signed server-side by the caller's own assumed session and clamped to that session's
 * remaining life, so it cannot outlive the credential that signed it. `expiresAt` comes back so a
 * caller can tell an expired link from a denial.
 *
 * @param params.bucket - The bucket holding the object.
 * @param params.key - The object key.
 * @param params.fileName - The name to offer the browser; defaults to the key's last segment.
 * @returns The URL and when it dies, or a failure.
 */
export async function getDownloadUrl(params: {
  bucket: string;
  key: string;
  fileName?: string;
}): Promise<ServiceResult<DownloadUrl>> {
  const {bucket, key} = params;
  const downloadName = params.fileName ?? fileName(key);

  const minted = await apiRequest('objects.downloadUrl', {
    body: {space: spaceFor(bucket, key), key, fileName: downloadName}
  });
  if (!minted.success) return fromApiFailure(minted.error, 'Failed to generate download URL');
  return ok({url: minted.data.url, expiresAt: minted.data.expiresAt});
}

/**
 * Does an object already exist at this key?
 *
 * A miss is `data: false`, never a failure — the route answers 200 either way, because mapping
 * absence onto the error arm would turn every collision check into something the caller has to
 * re-interpret.
 *
 * @param params.bucket - The bucket.
 * @param params.key - The exact object key.
 * @returns Whether it is there.
 */
export async function objectExists(params: {bucket: string; key: string}): Promise<ServiceResult<boolean>> {
  const {bucket, key} = params;
  const answer = await apiRequest('objects.exists', {query: {...spaceQuery(bucket, key), key}});
  if (!answer.success) return fromApiFailure(answer.error, 'Failed to check whether the object exists');
  return ok(answer.data.exists);
}

/**
 * Does anything at all live under this prefix?
 *
 * **A RAW, UNFILTERED answer, and that is the whole point.** The browser's own listing is not an
 * answer to this question: it drops the prefix's own marker object and hides every
 * `DO_NOT_DELETE.txt` by basename — so an empty folder made with "New folder", and a
 * `saved_queries/` holding only its marker, both come back with nothing in them while being
 * perfectly present. Reading "empty" as "deleted" would tell a user their folder was gone and take
 * its actions away. The route answers this from the raw page, which is why it is `target: 'prefix'`
 * on the existence route rather than a listing call.
 *
 * @param params.bucket - The bucket.
 * @param params.prefix - The folder prefix, trailing slash included.
 * @returns True when at least one key lives under it.
 */
export async function folderExists(params: {bucket: string; prefix: string}): Promise<ServiceResult<boolean>> {
  const {bucket, prefix} = params;
  const answer = await apiRequest('objects.exists', {
    query: {...spaceQuery(bucket, prefix), key: prefix, target: 'prefix'}
  });
  if (!answer.success) return fromApiFailure(answer.error, 'Failed to check whether the folder exists');
  return ok(answer.data.exists);
}

/**
 * The first unused `{name} (N)` under a prefix, resolved in ONE call.
 *
 * The browser used to walk `(1)` … `(999)` with a `HeadObject` each. Behind the API every one of
 * those probes becomes a browser → API → S3 round trip, which is strictly worse than what it
 * replaced, so the walk moved to the route and the naming rule moved with it — two
 * implementations of `{name} (N)` look identical until one of them changes.
 *
 * **Exhaustion and failure are now distinguishable, and they were not before.** The old loop
 * returned `null` for both, and the caller rendered one sentence for either. A taken-999 answer is
 * a `Conflict`; anything else is a real failure with its own code.
 *
 * @param params.bucket - The bucket.
 * @param params.prefix - The folder the copy will sit in.
 * @param params.baseName - The source's leaf name.
 * @param params.kind - A folder has no extension to preserve; a file does.
 * @returns The free leaf name, without its prefix.
 */
export async function firstFreeName(params: {
  bucket: string;
  prefix: string;
  baseName: string;
  kind: 'file' | 'folder';
}): Promise<ServiceResult<string>> {
  const {bucket, prefix, baseName, kind} = params;
  const found = await apiRequest('objects.freeName', {
    body: {space: spaceFor(bucket, prefix), prefix, baseName, kind}
  });
  if (found.success) return ok(found.data.name);
  if (found.error.code === 'Conflict') {
    return {
      success: false,
      error: {message: 'Could not find an available name for the copy.', code: 'NoFreeName'}
    };
  }
  return fromApiFailure(found.error, 'Could not find an available name for the copy.');
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
 * Uploads one file: a presigned `PUT`, sent by this browser straight to S3.
 *
 * **`XMLHttpRequest`, not `fetch`, and the reason is the progress bar.** `fetch` fires no
 * upload-progress event, so an implementation built on it uploads correctly and leaves the bar at
 * 0% until it jumps to 100% — a shipped feature deleted by a transport choice, with every "the
 * upload succeeded" test still green.
 *
 * Three consequences of one `PUT` where `lib-storage` auto-multiparted: the 5 GiB ceiling is
 * unchanged (it is exactly the single-`PUT` cap, and exactly what the configured maximum already
 * clamped to); there is **no part-level retry** any more, so a dropped connection restarts the
 * whole file; and the URL's expiry is evaluated when S3 receives the request, not when the transfer
 * finishes, which is what makes a long upload through a 15-minute window sound.
 *
 * @param params.bucket - The bucket to write into.
 * @param params.key - The object key.
 * @param params.body - The bytes.
 * @param params.contentType - Signed into the URL, so it must be the type actually sent.
 * @param params.overwrite - Replace an occupied key. With false and the key taken the route mints
 *   no URL at all — it refuses before handing out the capability.
 * @param params.onProgress - Called with bytes sent and the total, repeatedly, during the transfer.
 * @param params.signal - Aborts the transfer; resolves to `Cancelled`.
 * @returns The key written, or a failure.
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

  const maxBytes = maxUploadBytes();
  if (body.size > maxBytes) {
    return {
      success: false,
      error: {message: `File exceeds the maximum upload size of ${maxBytes} bytes.`, code: 'TooLarge'}
    };
  }

  if (signal?.aborted) return cancelled();

  const minted = await apiRequest('objects.uploadUrl', {
    body: {space: spaceFor(bucket, key), key, contentType, overwrite}
  });
  if (!minted.success) {
    if (minted.error.code === 'Conflict') {
      return {success: false, error: {message: `"${key}" already exists.`, code: 'Collision'}};
    }
    return fromApiFailure(minted.error, 'Failed to upload file');
  }

  return sendBytes({url: minted.data.url, key, body, contentType, onProgress, signal});
}

/** The one wording for an upload the user stopped, minted at both of the two places it can happen. */
function cancelled(): ServiceResult<never> {
  return {success: false, error: {message: 'Upload cancelled.', code: 'Cancelled'}};
}

/** What `sendBytes` and `sendOverXhr` both take. */
type TransferParams = {
  url: string;
  key: string;
  body: Blob | File;
  contentType: string;
  onProgress?: (loaded: number, total: number) => void;
  signal?: AbortSignal;
};

// The transfer itself. Separate from `uploadFile` so the promise wrapper — which cannot `await`
// anything — has nothing in it but the request and its outcomes.
function sendBytes(params: TransferParams): Promise<ServiceResult<UploadResult>> {
  return new Promise((resolve) => {
    // EVERYTHING below is inside the try, and that is the point. A service in this app never
    // throws, and a promise executor that throws REJECTS rather than resolving — which the upload
    // queue awaits with no catch, so the item would sit in `uploading` forever, its concurrency
    // slot never freed and nothing said to the user. `xhr.open` throws on a malformed URL and
    // `setRequestHeader` on an invalid header value, both reachable from a route answer.
    try {
      sendOverXhr(params, resolve);
    } catch (err) {
      resolve(toServiceError(err, 'Failed to upload file'));
    }
  });
}

// The request itself. Separated only so the executor above is nothing but its own guard — a `try`
// wrapping thirty lines is a `try` whose scope nobody re-reads.
function sendOverXhr(params: TransferParams, resolve: (result: ServiceResult<UploadResult>) => void): void {
  const {url, key, body, contentType, onProgress, signal} = params;
  {
    const xhr = new XMLHttpRequest();
    // Listening on `xhr.upload`, not on `xhr`: the request's own progress events describe the
    // RESPONSE download, which for a `PUT` is empty and fires once at the end.
    if (onProgress) {
      xhr.upload.addEventListener('progress', (event) => {
        onProgress(event.loaded, event.lengthComputable ? event.total : body.size);
      });
    }

    const onAbort = () => xhr.abort();
    // Removed on every path, not left to `{once: true}`: that fires the listener at most once but
    // does not detach it, so a long-lived queue signal accumulated one closure per completed file.
    const settle = (result: ServiceResult<UploadResult>) => {
      signal?.removeEventListener('abort', onAbort);
      resolve(result);
    };

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) return settle(ok({key}));
      // S3's own body is XML and technical, and it is never shown: the code is what the surface
      // maps. A 403 here is an expired or mis-signed URL, which reads to a user as a failed upload.
      settle({success: false, error: {message: 'Failed to upload file.', code: `Http${xhr.status}`}});
    });
    xhr.addEventListener('error', () =>
      settle({success: false, error: {message: 'Failed to upload file.', code: 'NetworkUnavailable'}})
    );
    xhr.addEventListener('abort', () => settle(cancelled()));

    signal?.addEventListener('abort', onAbort);

    xhr.open('PUT', url);
    // The SIGNED content type, byte for byte. A different one here fails the signature check at S3
    // and returns a 403 that reads as a permissions problem.
    xhr.setRequestHeader('Content-Type', contentType);
    xhr.send(body);
  }
}

/**
 * Creates an empty folder as a zero-byte `{prefix}{name}/` marker object.
 *
 * One call: the name is validated here, and the collision the browser used to `HEAD` for is the
 * write route's own `Conflict`.
 *
 * @param params.bucket - The bucket.
 * @param params.prefix - The folder to create it in.
 * @param params.name - The new folder's leaf name.
 * @param params.overwrite - Replace an existing folder marker.
 * @returns The new folder's prefix, or a failure (`InvalidName` / `Collision`).
 */
export async function createFolder(params: {
  bucket: string;
  prefix: string;
  name: string;
  overwrite?: boolean;
}): Promise<ServiceResult<CreateFolderResult>> {
  const {bucket, prefix, name, overwrite = false} = params;

  const nameError = validateFolderName(name);
  if (nameError) return {success: false, error: {message: nameError, code: 'InvalidName'}};

  const folderPrefix = `${prefix}${name}/`;

  const written = await apiRequest('objects.writeContent', {
    body: {
      space: spaceFor(bucket, folderPrefix),
      key: folderPrefix,
      body: '',
      contentType: 'application/x-directory',
      overwrite
    }
  });
  if (written.success) return ok({prefix: folderPrefix});
  if (written.error.code === 'Conflict') {
    return {success: false, error: {message: `A folder named "${name}" already exists.`, code: 'Collision'}};
  }
  return fromApiFailure(written.error, 'Failed to create folder');
}

/**
 * Fetches a single object's metadata — no body transfer.
 *
 * `userMetadata` arrives as rows because a query-free wire contract has no mapping type; it is
 * folded back into the record the panel has always rendered.
 *
 * @param params.bucket - The bucket.
 * @param params.key - The object key.
 * @returns The metadata, or a failure. A key that has since been deleted is `NotFound`.
 */
export async function getObjectMetadata(params: {bucket: string; key: string}): Promise<ServiceResult<ObjectMetadata>> {
  const {bucket, key} = params;
  const head = await apiRequest('objects.metadata', {query: {...spaceQuery(bucket, key), key}});
  if (!head.success) {
    if (head.error.code === 'NotFound') {
      return {success: false, error: {message: 'This file no longer exists.', code: 'NotFound'}};
    }
    return fromApiFailure(head.error, 'Failed to load file details');
  }

  return ok({
    key: head.data.key,
    contentType: head.data.contentType,
    size: head.data.size,
    lastModified: head.data.lastModified ? new Date(head.data.lastModified) : new Date(0),
    etag: head.data.etag,
    storageClass: head.data.storageClass,
    userMetadata: Object.fromEntries(head.data.userMetadata.map((entry) => [entry.name, entry.value]))
  });
}

/** Test-only: resets the once-per-session marker guard between cases. */
export function __resetPrefixMarkerCache(): void {
  ensuredMarkers.clear();
}
