import {ListObjectsV2Command, PutObjectCommand} from '@aws-sdk/client-s3';
import {getS3Client} from '../../lib/s3Client';
import {withCredentialRetry} from '../../lib/credentialRetry';
import {ok, toServiceError} from '../../lib/serviceResult';
import {readJsonDocument} from '../../lib/s3Json';
import {
  LISTING_PAGE_SIZE,
  PREFIX_MARKER_FILENAME,
  SAVED_QUERIES_FOLDER,
  SAVED_QUERIES_MARKER_BODY,
  deleteObject,
  isMarkerName,
  objectExists,
  validateLeafName
} from '../file-browser';
import type {ServiceResult} from '../../types/service.types';
import type {SavedQuery, SavedQueryLink, SavedQueryPage} from './savedQueries.types';
import type {QuerySpace} from '../catalog/catalog.types';

// SPEC-173: a saved query is a `.sql` OBJECT in a space's `saved_queries/` folder,
// not a row in a private JSON document. Its KEY is its identity, its FILENAME is its
// name and its LastModified is when it changed — there is nothing else to store,
// because a `.sql` file cannot carry a record without a sidecar this feature
// deliberately does not have.
//
// The folder itself is ORDINARY (SPEC-173 FR-002): anyone with access to the space may
// upload a CSV into it, copy a folder tree in, or make a subfolder. What keeps the load
// list coherent is the filter below — top-level `.sql` files and nothing else — not a
// write lock, which is why the filter is a requirement with tests rather than a
// precaution.

const SQL_EXTENSION = '.sql';

/** Longest basename a saved query may have, extension included. */
const MAX_NAME_LENGTH = 128;

/** The saved-queries folder at a space root: `{rootPrefix}saved_queries/`. */
export function savedQueriesPrefix(rootPrefix: string): string {
  return `${rootPrefix}${SAVED_QUERIES_FOLDER}/`;
}

// The basename a name maps to. A user who types `report.sql` gets `report.sql`, never
// `report.sql.sql` — matched case-insensitively, because `REPORT.SQL` is one too.
//
// A TYPED extension is lowercased (SPEC-175 FR-002 AC4), and the reason is that
// `savedQueryName` strips it case-insensitively: left alone, `report.SQL` and `report.sql`
// are two distinct objects that BOTH render as `report` in the load list and on a tab, and
// a re-save from a tab linked to one resolves to the other and replaces the wrong file.
// The stem is untouched — `REPORT` and `report` stay two visibly different names.
function basenameFor(name: string): string {
  const ext = name.slice(-SQL_EXTENSION.length).toLowerCase();
  return ext === SQL_EXTENSION ? `${name.slice(0, -SQL_EXTENSION.length)}${SQL_EXTENSION}` : `${name}${SQL_EXTENSION}`;
}

/** The S3 key a saved query of this name lives at, in this space. */
export function savedQueryKey(rootPrefix: string, name: string): string {
  return `${savedQueriesPrefix(rootPrefix)}${basenameFor(name)}`;
}

/**
 * The name a key carries: its basename, with a trailing `.sql` removed.
 *
 * The single source of a saved query's name, so a tab label and a list row can never
 * disagree about what a file is called (SPEC-173 FR-006).
 */
export function savedQueryName(key: string): string {
  const basename = key.slice(key.lastIndexOf('/') + 1);
  return basename.toLowerCase().endsWith(SQL_EXTENSION) ? basename.slice(0, -SQL_EXTENSION.length) : basename;
}

/**
 * Whether saving under this name, into this space, targets the file a tab is linked to.
 *
 * The ONE rule behind two behaviours that must agree (SPEC-175 FR-004): the dialog says
 * "replacing the file this tab was opened from", and the host writes with `overwrite`
 * and raises no second confirm. Judged on the KEY the save resolves to — a different
 * name in the tab's own space, or the same name in another, is a different file.
 *
 * @param link - The active tab's link, or undefined when it has none.
 * @param space - The space chosen in the dialog.
 * @param name - The raw name typed in the dialog.
 * @returns True when the resulting object is exactly the linked one.
 */
export function isLinkedSavedQuery(link: SavedQueryLink | undefined, space: QuerySpace, name: string): boolean {
  if (!link || name.trim().length === 0) return false;
  return link.bucket === space.bucket && link.key === savedQueryKey(space.rootPrefix, name.trim());
}

/**
 * Validates a saved query's name before any request.
 *
 * The leaf-name rule every other single-segment name in the app uses, plus a length
 * ceiling on the RESULTING basename — the `.sql` the user may not have typed still
 * counts toward the key.
 *
 * @param name - The raw value the user typed.
 * @returns An error message, or null when the name is valid.
 */
export function validateSavedQueryName(name: string): string | null {
  const leaf = validateLeafName(name, 'Query name');
  if (leaf) return leaf;
  if (basenameFor(name).length > MAX_NAME_LENGTH) {
    return `Query name cannot be longer than ${MAX_NAME_LENGTH} characters.`;
  }
  return null;
}

// Once-per-session guard, keyed by bucket + key: at most one existence check per space
// per session no matter how many times the workspace mounts. Mirrors
// `ensurePrefixMarker`'s, and for the same reason — a fresh page load retries.
const ensuredFolders = new Set<string>();

/**
 * Idempotently guarantees a space's `saved_queries/` folder exists.
 *
 * S3 has no folders — a prefix exists only while an object lives under it — so the
 * folder is held open by a marker at `{root}saved_queries/DO_NOT_DELETE.txt`, the same
 * mechanism every space root already uses. Best effort: a failure is not fatal to
 * anything the user is doing, because writing a saved query creates the prefix anyway.
 *
 * @param space - The space whose folder to guarantee.
 * @returns Success (whether or not it had to write); a failed head or put as a failure.
 */
export async function ensureSavedQueriesFolder(space: QuerySpace): Promise<ServiceResult<void>> {
  const key = `${savedQueriesPrefix(space.rootPrefix)}${PREFIX_MARKER_FILENAME}`;
  const cacheKey = `${space.bucket}/${key}`;

  // Synchronous check-and-set before any await, so a StrictMode double-invocation or a
  // remount cannot both get past it.
  if (ensuredFolders.has(cacheKey)) return ok(undefined);
  ensuredFolders.add(cacheKey);

  const exists = await objectExists({bucket: space.bucket, key});
  if (!exists.success) return exists;
  if (exists.data) return ok(undefined);

  return withCredentialRetry(getS3Client, async (client) => {
    try {
      await client.send(
        new PutObjectCommand({
          Bucket: space.bucket,
          Key: key,
          Body: SAVED_QUERIES_MARKER_BODY,
          ContentType: 'text/plain'
        })
      );
      return ok(undefined);
    } catch (err) {
      return toServiceError(err, 'Failed to create the saved queries folder');
    }
  });
}

/**
 * One page of a space's saved queries, in S3's own (lexicographic) order.
 *
 * `Delimiter: '/'` is load-bearing, not incidental: the listing is ONE level, so
 * `saved_queries/archive/old.sql` is a file in a folder and not a saved query. The
 * `.sql` filter is the other half — every other object in the folder is a normal file
 * that belongs to the file browser and is invisible here.
 *
 * The order is S3's, unmodified. Sorting by last-modified across a paginated listing is
 * a lie: the newest query may sit on page nine, and re-sorting the loaded pages makes
 * rows the user has already seen jump as later pages arrive.
 *
 * @param params.space - The space to list.
 * @param params.continuationToken - S3's token for the next page.
 * @param params.signal - Cancels the request when the query is dropped.
 * @returns The page, or a failure. A missing folder is an EMPTY page, not an error.
 */
export async function listSavedQueries(params: {
  space: QuerySpace;
  continuationToken?: string;
  signal?: AbortSignal;
}): Promise<ServiceResult<SavedQueryPage>> {
  const {space, continuationToken, signal} = params;
  const prefix = savedQueriesPrefix(space.rootPrefix);

  return withCredentialRetry(getS3Client, async (client) => {
    try {
      const response = await client.send(
        new ListObjectsV2Command({
          Bucket: space.bucket,
          Prefix: prefix,
          Delimiter: '/',
          MaxKeys: LISTING_PAGE_SIZE,
          ContinuationToken: continuationToken
        }),
        {abortSignal: signal}
      );

      const queries = (response.Contents ?? [])
        .filter((obj): obj is typeof obj & {Key: string} => typeof obj.Key === 'string')
        .filter((obj) => isSavedQueryKey(obj.Key, prefix))
        .map((obj) => ({
          spaceId: space.id,
          bucket: space.bucket,
          key: obj.Key,
          name: savedQueryName(obj.Key),
          updatedAt: (obj.LastModified ?? new Date(0)).toISOString(),
          size: obj.Size ?? 0
        }));

      return ok({
        queries,
        isTruncated: response.IsTruncated ?? false,
        nextContinuationToken: response.NextContinuationToken
      });
    } catch (err) {
      return toServiceError(err, 'Failed to load saved queries');
    }
  });
}

// A key is offered as a saved query when it sits DIRECTLY in the folder, its basename
// ends `.sql` (case-insensitively), and it is not the folder marker. A `CommonPrefixes`
// entry never reaches here — a subfolder is never a saved query.
//
// The depth check is belt to the delimiter's braces: S3 will not return a nested key for
// a delimited listing, and this is what makes that a property of the STORE rather than a
// property of one request's parameters.
function isSavedQueryKey(key: string, prefix: string): boolean {
  const relative = key.slice(prefix.length);
  if (!key.startsWith(prefix) || relative.includes('/')) return false;
  return relative.toLowerCase().endsWith(SQL_EXTENSION) && !isMarkerName(key);
}

/**
 * Reads a saved query's SQL.
 *
 * Fetched only when a query is OPENED — never to render a list row, which would cost a
 * GetObject per row every time the drawer opens.
 *
 * @param params.bucket - The space's bucket.
 * @param params.key - The saved query's key.
 * @returns The object body as a string, or a failure naming the query.
 */
export async function readSavedQuery(params: {bucket: string; key: string}): Promise<ServiceResult<string>> {
  const {bucket, key} = params;
  return readJsonDocument<string>({
    bucket,
    key,
    parse: (body) => ok(body ?? ''),
    onMissing: () => ({
      success: false,
      error: {message: `“${savedQueryName(key)}” no longer exists.`, code: 'SavedQueryNotFound'}
    }),
    fallbackMessage: `Failed to open “${savedQueryName(key)}”`
  });
}

/**
 * Writes a saved query, refusing to clobber an existing one unless asked.
 *
 * The collision check is a HEAD on the exact KEY, not a scan of a loaded list: the list
 * is paginated and the target space may not be the one on screen, so an in-memory scan
 * stopped being sound. One visible consequence is accepted — S3 keys are
 * case-sensitive, so `Report` and `report` are two saved queries.
 *
 * @param params.space - The space to write into.
 * @param params.name - The user-supplied name; validated before any request.
 * @param params.sql - The editor buffer to store.
 * @param params.overwrite - Skip the collision check and replace.
 * @returns The `SavedQuery` just written, or a failure (`InvalidName` / `Collision`).
 */
export async function writeSavedQuery(params: {
  space: QuerySpace;
  name: string;
  sql: string;
  overwrite?: boolean;
}): Promise<ServiceResult<SavedQuery>> {
  const {space, name, sql, overwrite = false} = params;

  const nameError = validateSavedQueryName(name);
  if (nameError) return {success: false, error: {message: nameError, code: 'InvalidName'}};

  const key = savedQueryKey(space.rootPrefix, name);

  if (!overwrite) {
    const exists = await objectExists({bucket: space.bucket, key});
    if (!exists.success) return exists;
    if (exists.data) {
      return {
        success: false,
        error: {message: `“${savedQueryName(key)}” already exists.`, code: 'Collision'}
      };
    }
  }

  return withCredentialRetry(getS3Client, async (client) => {
    try {
      await client.send(
        new PutObjectCommand({
          Bucket: space.bucket,
          Key: key,
          Body: sql,
          ContentType: 'text/plain; charset=utf-8'
        })
      );
      return ok({
        spaceId: space.id,
        bucket: space.bucket,
        key,
        name: savedQueryName(key),
        updatedAt: new Date().toISOString(),
        size: new TextEncoder().encode(sql).length
      });
    } catch (err) {
      return toServiceError(err, 'Failed to save query');
    }
  });
}

/**
 * Deletes a saved query.
 *
 * A real `DeleteObject` now, where the JSON store rewrote a document — delegated so the
 * existing prefix-marker refusal applies unchanged.
 *
 * @param params.bucket - The space's bucket.
 * @param params.key - The saved query's key.
 * @param params.username - The signed-in user, for the marker guard.
 * @returns Success, or the delete's own failure.
 */
export async function deleteSavedQuery(params: {
  bucket: string;
  key: string;
  username: string;
}): Promise<ServiceResult<void>> {
  const deleted = await deleteObject(params);
  return deleted.success ? ok(undefined) : deleted;
}

/** Test-only: resets the once-per-session folder guard between cases. */
export function __resetSavedQueriesFolderCache(): void {
  ensuredFolders.clear();
}
