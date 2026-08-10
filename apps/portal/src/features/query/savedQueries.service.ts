import {userSpaceBucket, userSettingsKey} from '../../lib/userSpace';
import {classifyDocument, quarantineDocument, readJsonDocument, writeJsonDocument} from '../../lib/s3Json';
import type {DocumentParse, WriteOutcome} from '../../lib/s3Json';
import {ok} from '../../lib/serviceResult';
import type {ServiceResult} from '../../types/service.types';
import type {SavedQueriesStore, SavedQuery} from './query.types';

// Per-user saved queries stored as JSON in the protected `user_settings/`
// folder, whose policy ALLOWS PutObject (overwrite) but DENIES delete — so
// create/update/remove only ever overwrite the whole file, never an S3 object
// delete. The folder is hidden from the file browser.

const STORE_VERSION = 1;

const emptyStore = (): SavedQueriesStore => ({version: STORE_VERSION, queries: []});

function storeKey(username: string): string {
  return userSettingsKey(username, 'saved-queries.json');
}

// Classification for the WRITE path, where "I can't read this" must NOT become "this
// is empty": the write is an unconditional PutObject, so a body misread as empty is
// COMMITTED as empty, and one Save would replace the whole library with the query
// being saved. A body from a NEWER build is told apart from a corrupt one here —
// only the corrupt one may be set aside and rewritten.
function classifyStore(body: string | undefined): DocumentParse<SavedQueriesStore> {
  return classifyDocument({
    body,
    version: STORE_VERSION,
    empty: emptyStore,
    isReadable: (document) => Array.isArray(document.queries)
  });
}

// The DISPLAY read, derived from the write classifier rather than written out again
// so the two can never disagree about what a valid store is — a tightened write
// parser and a stale display one would fail every save for a store the panel shows
// as fine. Same validation, different answer to an unusable body: empty here (a
// corrupt file must not lock the user out of the page), a refusal or a recovery there.
function parseStore(body: string | undefined): SavedQueriesStore {
  const parsed = classifyStore(body);
  return parsed.readable ? parsed.value : emptyStore();
}

// The read that precedes every write. Differs from `getSavedQueries` only in how it
// treats a body it cannot parse.
async function readStoreForWrite(username: string): Promise<ServiceResult<DocumentParse<SavedQueriesStore>>> {
  return readJsonDocument<DocumentParse<SavedQueriesStore>>({
    bucket: userSpaceBucket(),
    key: storeKey(username),
    parse: (body) => ok(classifyStore(body)),
    onMissing: () => ok({readable: true, value: emptyStore()}),
    fallbackMessage: 'Failed to load saved queries'
  });
}

/**
 * The store a write should be applied to, quarantining an unreadable document first.
 *
 * The three outcomes the whole spec turns on. A readable store is returned as-is. A
 * NEWER one is refused untouched — overwriting it would downgrade a document a newer
 * tab wrote. An unparseable one is copied aside and the write proceeds from the empty
 * store, and the copy is a PRECONDITION: if it fails the caller refuses exactly as it
 * did before, because a failed quarantine must never become a silent overwrite.
 *
 * `recovered` travels with the store so the caller can both write it and say what
 * became of the user's earlier queries.
 */
async function storeForWrite(username: string): Promise<ServiceResult<{store: SavedQueriesStore; recovered: boolean}>> {
  const current = await readStoreForWrite(username);
  if (!current.success) return current;
  if (current.data.readable) return ok({store: current.data.value, recovered: false});

  if (current.data.reason === 'newer') {
    return {
      success: false,
      error: {
        message: 'Saved queries were written by a newer version of this app.',
        code: 'SavedQueriesNewerVersion'
      }
    };
  }

  const quarantined = await quarantineDocument({bucket: userSpaceBucket(), key: storeKey(username)});
  if (!quarantined.success) {
    return {
      success: false,
      error: {
        message: 'Saved queries could not be read, so nothing was changed.',
        code: 'SavedQueriesQuarantineFailed'
      }
    };
  }

  return ok({store: emptyStore(), recovered: true});
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
 *
 * Reports `recovered` when the previous document was unreadable and had to be
 * quarantined — the save succeeded, but the queries that were there before are not
 * in the returned store.
 */
export async function upsertSavedQuery(username: string, query: SavedQuery): Promise<WriteOutcome<SavedQueriesStore>> {
  const current = await storeForWrite(username);
  if (!current.success) return current;
  const {store, recovered} = current.data;

  const existingIdx = store.queries.findIndex((q) => q.id === query.id);
  const queries =
    existingIdx === -1 ? [query, ...store.queries] : store.queries.map((q) => (q.id === query.id ? query : q));

  const next: SavedQueriesStore = {version: STORE_VERSION, queries};
  const written = await writeStore(username, next);
  if (!written.success) return written;
  return {success: true, data: next, recovered};
}

/**
 * Removes a saved query by id by rewriting the JSON without it (never an S3
 * delete). An unknown id is a no-op success.
 */
export async function removeSavedQuery(username: string, id: string): Promise<WriteOutcome<SavedQueriesStore>> {
  const current = await storeForWrite(username);
  if (!current.success) return current;
  const {store, recovered} = current.data;

  const queries = store.queries.filter((q) => q.id !== id);
  // The no-op shortcut is forfeited after a recovery: the store in hand is the empty
  // one, and returning early would leave the unreadable document in place with its
  // quarantine copy already taken — broken, and now silently so.
  if (queries.length === store.queries.length && !recovered) {
    return {success: true, data: store, recovered}; // unknown id → no-op
  }

  const next: SavedQueriesStore = {version: STORE_VERSION, queries};
  const written = await writeStore(username, next);
  if (!written.success) return written;
  return {success: true, data: next, recovered};
}
