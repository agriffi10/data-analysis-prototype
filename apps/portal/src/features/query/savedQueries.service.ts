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

// Forgivingly parse the store body: a malformed/legacy file falls back to empty
// rather than erroring (same spirit as the missing-file case).
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
  const current = await getSavedQueries(username);
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
  const current = await getSavedQueries(username);
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
