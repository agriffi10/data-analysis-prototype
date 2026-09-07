import {apiRequest} from '../../lib/apiClient';
import {SYSTEM_FOLDER_GROUP_NAME} from './systemFolders';
import {spaceFor} from '../../lib/objectSpace';
import {fromApiFailure, ok} from '../../lib/serviceResult';
import type {FileListPage} from '../../types/s3.types';
import type {ServiceResult} from '../../types/service.types';
import type {SpaceRef} from '../../types/apiContract.generated';
import type {DownloadUrl, UploadResult, CreateFolderResult, ObjectMetadata} from './fileBrowser.types';
import {maxUploadBytes} from './uploadLimits';
import {uploadParts} from './multipartUpload';
import {putBytes, uploadCancelled, uploadRejection} from './xhrUpload';
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
 * Is there an object at exactly this key?
 *
 * The OBJECT-level twin of `folderExists`, and the difference is the whole point: that one asks
 * whether anything lives *under* a prefix and passes `target: 'prefix'`; this one asks about one
 * key and leaves `target` at the route's default. Asking the prefix question about a file key
 * would answer true for `report.csv` when only `report.csv.bak` existed.
 *
 * **A failure is NOT an answer.** A 403 in particular means "the space may hold a file you cannot
 * see", which for a caller about to write there is closer to occupied than to free — but that is
 * the caller's call to make from the code, not a decision to bury here by returning `true`.
 *
 * @param params.bucket - The bucket.
 * @param params.key - The full object key.
 * @returns True when an object exists at that key.
 */
export async function objectExists(params: {bucket: string; key: string}): Promise<ServiceResult<boolean>> {
  const {bucket, key} = params;
  const answer = await apiRequest('objects.exists', {
    query: {...spaceQuery(bucket, key), key}
  });
  if (!answer.success) return fromApiFailure(answer.error, 'Failed to check whether the file exists');
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

/**
 * Validates a new folder name before any request. Returns an error message, or null if valid.
 *
 * Refuses `system_settings` on top of the leaf rules, because the listing spends that name on
 * the group row that gathers the app-managed folders. A real folder wearing it puts two rows
 * of the same name at a space root — one openable, one a disclosure — and the path that pays
 * is archive discovery: a user hunting for the id a restore needs opens the empty one they
 * made and concludes the receipts are gone. Refused at every depth rather than only at the
 * root, so the name means one thing wherever it is read.
 */
export function validateFolderName(name: string): string | null {
  const leaf = validateLeafName(name, 'Folder name');
  if (leaf !== null) return leaf;
  if (name === SYSTEM_FOLDER_GROUP_NAME)
    return `“${SYSTEM_FOLDER_GROUP_NAME}” is a name the file list uses. Pick another.`;
  return null;
}

/**
 * Uploads one file, by whichever path the SERVER chose for it.
 *
 * **The browser does not hold the threshold, and that is the point.** `objects.upload` answers
 * either a presigned `PUT` or a multipart plan, so the size at which one becomes the other is a
 * policy number living in exactly one place. A browser-side fork would need a second copy of it,
 * and a drifted copy sends files down the wrong path with nothing failing.
 *
 * **`XMLHttpRequest`, not `fetch`, and the reason is the progress bar.** `fetch` fires no
 * upload-progress event, so an implementation built on it uploads correctly and leaves the bar at
 * 0% until it jumps to 100% — a shipped feature deleted by a transport choice, with every "the
 * upload succeeded" test still green. The transport lives in `xhrUpload`, which both paths call.
 *
 * The 5 GiB ceiling is unchanged: it is exactly the single-`PUT` cap, and exactly what the
 * configured maximum already clamped to. Multipart would technically permit 5 TiB and deliberately
 * does not raise it — that is a product decision about cost and blast radius, not a technical one.
 *
 * @param params.bucket - The bucket to write into.
 * @param params.key - The object key.
 * @param params.body - The bytes.
 * @param params.contentType - Signed into the URL, so it must be the type actually sent.
 * @param params.overwrite - Replace an occupied key. With false and the key taken the route creates
 *   nothing at all — it refuses before handing out any capability.
 * @param params.onProgress - Called with bytes sent and the total, repeatedly. On a multipart
 *   upload this is the AGGREGATE across parts, and it is monotonic across a retry.
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

  const space = spaceFor(bucket, key);
  const begun = await apiRequest('objects.upload', {
    body: {space, key, contentType, overwrite, size: body.size},
    signal
  });
  if (!begun.success) {
    if (begun.error.code === 'Conflict') {
      return {success: false, error: {message: `"${key}" already exists.`, code: 'Collision'}};
    }
    return fromApiFailure(begun.error, 'Failed to upload file');
  }

  // Checked AGAIN, after the route answered. `addEventListener('abort')` on an already-fired signal
  // never runs, so a cancel that lands while the plan is being fetched would otherwise attach a
  // listener to a spent signal and send the bytes anyway — the queue row going straight from
  // `uploading` to Succeeded for a file the user stopped.
  if (signal?.aborted) return cancelled();

  const plan = begun.data;

  // Every member is checked at RUNTIME. The generated type is one object with optional members and
  // a `mode` discriminant that narrows nothing else — the contract's vocabulary is closed and
  // carries no union other than `X | None`, so widening it for this is what that rule forbids.
  if (plan.mode === 'multipart') {
    if (plan.uploadId === undefined || plan.partSize === undefined || plan.partCount === undefined) {
      return unusablePlan();
    }
    // **Checked as ARITHMETIC, not merely as presence.** A plan whose parts cannot cover the file
    // is the one bad answer that fails SILENTLY and SUCCESSFULLY: the parts upload, the assembly
    // succeeds because every ETag is genuine, and the user is told their file is saved while what
    // is stored is a prefix of it. The progress bar cannot show it either — the aggregate clamps
    // to the file's size and the queue then pins a finished row to 100%. Refused instead, on the
    // same named code as a missing member, because a truncated file reported as success is worse
    // than an upload that did not start.
    if (plan.partSize < 1 || plan.partCount < 1 || plan.partSize * plan.partCount < body.size) {
      return unusablePlan();
    }

    return uploadParts({
      space,
      key,
      body,
      contentType,
      uploadId: plan.uploadId,
      partSize: plan.partSize,
      partCount: plan.partCount,
      overwrite,
      onProgress,
      signal
    });
  }

  if (plan.url === undefined || plan.expiresAt === undefined) return unusablePlan();

  return sendBytes({
    url: plan.url,
    key,
    body,
    contentType,
    onProgress,
    signal,
    expiresAt: plan.expiresAt
  });
}

/**
 * The answer for a create response whose chosen branch cannot be used.
 *
 * Reachable only from a deploy skew or a contract change, and it is a named code rather than a
 * crash so the user gets a sentence instead of a stalled row.
 */
function unusablePlan(): ServiceResult<never> {
  return {
    success: false,
    error: {message: 'The upload could not be started.', code: 'UploadPlanUnusable'}
  };
}

/** The one wording for an upload the user stopped, delegated so both paths say it identically. */
function cancelled(): ServiceResult<never> {
  return uploadCancelled();
}

/** What `sendBytes` takes. `expiresAt` tells an expired link from a denial on a 403. */
type TransferParams = {
  url: string;
  key: string;
  body: Blob | File;
  contentType: string;
  onProgress?: (loaded: number, total: number) => void;
  signal?: AbortSignal;
  expiresAt: string;
};

/**
 * The single-`PUT` transfer, over the transport both upload paths share.
 *
 * Nothing here names `XMLHttpRequest` any more — it lives in `xhrUpload`, which the part loop
 * calls too. One copy, because otherwise the abort handling, the progress plumbing and the
 * expiry-versus-denial mapping are each written twice and diverge in the path nobody tests.
 */
async function sendBytes(params: TransferParams): Promise<ServiceResult<UploadResult>> {
  const {url, key, body, contentType, onProgress, signal, expiresAt} = params;

  const sent = await putBytes({
    url,
    body,
    contentType,
    // The whole file is one request, so its own `loaded` IS the aggregate.
    onProgress: onProgress ? (loaded) => onProgress(loaded, body.size) : undefined,
    signal
  });
  if (!sent.success) return sent;

  const {status} = sent.data;
  if (status >= 200 && status < 300) return ok({key});
  return uploadRejection(status, expiresAt);
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
