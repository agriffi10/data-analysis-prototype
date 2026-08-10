import {userSpaceBucket, userSettingsKey} from '../../lib/userSpace';
import {readJsonDocument, writeJsonDocument} from '../../lib/s3Json';
import {ok} from '../../lib/serviceResult';
import type {ServiceResult} from '../../types/service.types';
import type {SavedQueriesStore, SavedQuery} from './query.types';

// Per-user saved queries stored as JSON in the protected `user_settings/`
// folder, whose policy ALLOWS PutObject (overwrite) but DENIES delete — so
// create/update/remove only ever overwrite the whole file, never an S3 object
// delete. The folder is hidden from the file browser.

const emptyStore = (): SavedQueriesStore => ({version: 1, queries: []});

function storeKey(username: string): string {
  return userSettingsKey(username, 'saved-queries.json');
}

// Forgivingly parse the store body FOR DISPLAY: a malformed/legacy file falls
// back to empty rather than erroring, so a corrupt settings file never locks the
// user out of the Query page. Read-modify-WRITE uses `parseStoreForWrite`.
function parseStore(body: string | undefined): SavedQueriesStore {
  if (!body) return emptyStore();
  try {
    const parsed = JSON.parse(body) as SavedQueriesStore;
    if (parsed?.version === 1 && Array.isArray(parsed.queries)) return parsed;
    return emptyStore();
  } catch {
    return emptyStore();
  }
}

// The same body, parsed for the WRITE path, where "I couldn't understand this"
// must NOT become "this is empty". The write is an unconditional PutObject, so a
// body misread as empty is committed as empty — one Save would replace the whole
// library with the query being saved, and `user_settings/` denies delete + the
// bucket is unversioned, so there is no way back.
//
// This is the same hazard the control planes close with a conditional write
// (`shared-space-common/cache.py`: treating an unreadable object as absent is
// "safe only because the create path is conditional"). The browser has no
// precondition to fall back on, so it refuses instead. An ABSENT object is still
// the empty store — there is nothing to lose — and only an unreadable one fails.
function parseStoreForWrite(body: string | undefined): ServiceResult<SavedQueriesStore> {
  if (!body) return ok(emptyStore());
  try {
    const parsed = JSON.parse(body) as SavedQueriesStore;
    if (parsed?.version === 1 && Array.isArray(parsed.queries)) return ok(parsed);
  } catch {
    // Fall through to the shared refusal below.
  }
  return {
    success: false,
    error: {
      message: 'Saved queries could not be read, so nothing was changed.',
      code: 'SavedQueriesUnreadable'
    }
  };
}

// The read that precedes every write. Separate from `getSavedQueries` only in how
// it treats a body it cannot parse.
async function readStoreForWrite(username: string): Promise<ServiceResult<SavedQueriesStore>> {
  return readJsonDocument({
    bucket: userSpaceBucket(),
    key: storeKey(username),
    parse: parseStoreForWrite,
    onMissing: () => ({success: true, data: emptyStore()}),
    fallbackMessage: 'Failed to load saved queries'
  });
}

/** Reads + parses the store. A missing file is the empty state, not an error. */
export async function getSavedQueries(username: string): Promise<ServiceResult<SavedQueriesStore>> {
  return readJsonDocument({
    bucket: userSpaceBucket(),
    key: storeKey(username),
    parse: (body) => ok(parseStore(body)),
    onMissing: () => ({success: true, data: emptyStore()}),
    fallbackMessage: 'Failed to load saved queries'
  });
}

// Overwrite the store file (PutObject — never a delete). Last-writer-wins on a
// single user's own file is acceptable.
async function writeStore(username: string, store: SavedQueriesStore): Promise<ServiceResult<void>> {
  return writeJsonDocument({
    bucket: userSpaceBucket(),
    key: storeKey(username),
    value: store,
    fallbackMessage: 'Failed to save query'
  });
}

/**
 * Creates or replaces a saved query by id, then writes back. A matching id is
 * updated in place (keeping list position); a new id is prepended.
 */
export async function upsertSavedQuery(username: string, query: SavedQuery): Promise<ServiceResult<SavedQueriesStore>> {
  const current = await readStoreForWrite(username);
  if (!current.success) return current;

  const existingIdx = current.data.queries.findIndex((q) => q.id === query.id);
  const queries =
    existingIdx === -1
      ? [query, ...current.data.queries]
      : current.data.queries.map((q) => (q.id === query.id ? query : q));

  const next: SavedQueriesStore = {version: 1, queries};
  const written = await writeStore(username, next);
  if (!written.success) return written;
  return {success: true, data: next};
}

/**
 * Removes a saved query by id by rewriting the JSON without it (never an S3
 * delete). An unknown id is a no-op success.
 */
export async function removeSavedQuery(username: string, id: string): Promise<ServiceResult<SavedQueriesStore>> {
  const current = await readStoreForWrite(username);
  if (!current.success) return current;

  const queries = current.data.queries.filter((q) => q.id !== id);
  if (queries.length === current.data.queries.length) {
    return {success: true, data: current.data}; // unknown id → no-op
  }

  const next: SavedQueriesStore = {version: 1, queries};
  const written = await writeStore(username, next);
  if (!written.success) return written;
  return {success: true, data: next};
}
