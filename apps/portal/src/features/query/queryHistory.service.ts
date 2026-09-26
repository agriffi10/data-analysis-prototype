import {userSpaceBucket, userSettingsKey} from '../../lib/userSpace';
import {classifyDocument, quarantineDocument, readJsonDocument, writeJsonDocument} from '../../lib/s3Json';
import type {DocumentParse, WriteOutcome} from '../../lib/s3Json';
import {ok} from '../../lib/serviceResult';
import type {ServiceResult} from '../../types/service.types';
import type {QueryHistory, QueryHistoryEntry} from './query.types';
import {QUERY_HISTORY_MAX, QUERY_HISTORY_MAX_BYTES} from './query.constants';
import {wireBytes} from '../../lib/wireBytes';

// A private, per-user query history stored as JSON alongside the user's
// results. This is the backend-free way to give each user a private history
// (the shared workgroup's ListQueryExecutions leaks all users and isn't
// granted), and it preserves SQL + stats beyond Athena's ~45-day retention.
//
// The file lives in the protected `user_settings/` folder. Its IAM policy
// ALLOWS PutObject (overwrite) but DENIES delete — get/append/update only
// ever overwrite, never delete, so the file is writable yet tamper-resistant.
// The folder is hidden from the file browser. History is read-only to the
// user: there is no delete/clear.

const HISTORY_VERSION = 1;

const emptyHistory = (): QueryHistory => ({version: HISTORY_VERSION, entries: []});

function historyKey(username: string): string {
  return userSettingsKey(username, 'query-history.json');
}

// Classification for the WRITE path. Same reasoning as savedQueries.service.ts: the
// write is an unconditional PutObject, so a body misread as empty is COMMITTED as
// empty and one append discards the whole history. This file is the only record of a
// query beyond Athena's ~45-day retention and the user cannot re-create it — there is
// no clear/delete, by design.
function classifyHistory(body: string | undefined): DocumentParse<QueryHistory> {
  return classifyDocument({
    body,
    version: HISTORY_VERSION,
    empty: emptyHistory,
    isReadable: (document) => Array.isArray(document.entries)
  });
}

// The DISPLAY read, derived from the write classifier so the two can never drift
// apart on what a valid history is. Same validation, different answer to an unusable
// body: empty here, a refusal or a recovery there.
function parseHistory(body: string | undefined): QueryHistory {
  const parsed = classifyHistory(body);
  return parsed.readable ? parsed.value : emptyHistory();
}

// The read that precedes every write. Differs from `getQueryHistory` only in how it
// treats a body it cannot parse.
async function readHistoryForWrite(username: string): Promise<ServiceResult<DocumentParse<QueryHistory>>> {
  return readJsonDocument<DocumentParse<QueryHistory>>({
    bucket: userSpaceBucket(),
    key: historyKey(username),
    parse: (body) => ok(classifyHistory(body)),
    onMissing: () => ok({readable: true, value: emptyHistory()}),
    // A document over the API's cap can be neither read nor rewritten, so it is set aside like an
    // unparseable one rather than refusing every write from now on.
    onTooLarge: () => ok({readable: false, reason: 'unparseable'}),
    fallbackMessage: 'Failed to load query history'
  });
}

/**
 * The history a write should be applied to, quarantining an unreadable document first.
 *
 * `savedQueries.service.ts`'s `storeForWrite`, for the other document: readable is
 * used as-is, NEWER is refused untouched (overwriting would downgrade what a newer tab
 * wrote), unparseable is copied aside and the write proceeds from the empty history —
 * and only if that copy succeeded, because a failed quarantine must never become a
 * silent overwrite.
 *
 * The user is not told about any of it (these writes are a side effect of running a
 * query, not something they asked for), but the document still recovers rather than
 * staying broken forever.
 */
async function historyForWrite(username: string): Promise<ServiceResult<{history: QueryHistory; recovered: boolean}>> {
  const current = await readHistoryForWrite(username);
  if (!current.success) return current;
  if (current.data.readable) return ok({history: current.data.value, recovered: false});

  if (current.data.reason === 'newer') {
    return {
      success: false,
      error: {
        message: 'Query history was written by a newer version of this app.',
        code: 'QueryHistoryNewerVersion'
      }
    };
  }

  const quarantined = await quarantineDocument({bucket: userSpaceBucket(), key: historyKey(username)});
  if (!quarantined.success) {
    return {
      success: false,
      error: {
        message: 'Query history could not be read, so nothing was changed.',
        code: 'QueryHistoryQuarantineFailed'
      }
    };
  }

  return ok({history: emptyHistory(), recovered: true});
}

/** Reads + parses the history file. A missing file is the empty state, not an error. */
export async function getQueryHistory(username: string): Promise<ServiceResult<QueryHistory>> {
  return readJsonDocument({
    bucket: userSpaceBucket(),
    key: historyKey(username),
    parse: (body) => ok(parseHistory(body)),
    onMissing: () => ({success: true, data: emptyHistory()}),
    fallbackMessage: 'Failed to load query history'
  });
}

// Overwrite the history file (PutObject — never a delete). Writes from two
// browser tabs or devices are last-writer-wins on a user's own file, which is
// acceptable here; this tab's own writes are queued by `serialised`.
async function writeHistory(username: string, history: QueryHistory): Promise<ServiceResult<void>> {
  return writeJsonDocument({
    bucket: userSpaceBucket(),
    key: historyKey(username),
    value: history,
    fallbackMessage: 'Failed to save query history'
  });
}

/** The tail of each user's queued history writes, so a write can start after the one before it. */
const pendingWrites = new Map<string, Promise<unknown>>();

/**
 * Runs one read-modify-write of a user's history after every earlier one has landed.
 *
 * Every write reads the whole file and puts it back, so two in flight at once lose whichever lands
 * first. A batch makes two on every statement boundary — the update that finalises one statement
 * and the append that records the next — and nothing else orders them.
 *
 * @param username - Whose history file the write touches; users do not wait on each other.
 * @param write - The read-modify-write to run.
 * @returns The write's own result, once it has run.
 */
function serialised<T>(username: string, write: () => Promise<T>): Promise<T> {
  const previous = pendingWrites.get(username) ?? Promise.resolve();
  const next = previous.then(write, write);
  pendingWrites.set(username, next);
  const forget = () => {
    if (pendingWrites.get(username) === next) pendingWrites.delete(username);
  };
  next.then(forget, forget);
  return next;
}

/**
 * Prepends a new entry (newest-first), caps at QUERY_HISTORY_MAX dropping the
 * oldest, and writes back. Called at submit time so an interrupted tab still
 * records the attempt (updateQueryHistoryEntry fills in the terminal status
 * later).
 */
export async function appendQueryHistory(
  username: string,
  entry: QueryHistoryEntry
): Promise<WriteOutcome<QueryHistory>> {
  return serialised(username, async () => {
    const current = await historyForWrite(username);
    if (!current.success) return current;
    const {history, recovered} = current.data;

    let entries = [entry, ...history.entries].slice(0, QUERY_HISTORY_MAX);
    while (entries.length > 1 && wireBytes({version: HISTORY_VERSION, entries}) > QUERY_HISTORY_MAX_BYTES) {
      entries = entries.slice(0, -1);
    }
    const next: QueryHistory = {version: HISTORY_VERSION, entries};

    const written = await writeHistory(username, next);
    if (!written.success) return written;
    return {success: true, data: next, recovered};
  });
}

/**
 * Updates an existing entry in place (e.g. records terminal status + stats
 * once polling completes) and writes back. An unknown id is a no-op success.
 */
export async function updateQueryHistoryEntry(
  username: string,
  queryExecutionId: string,
  patch: Partial<QueryHistoryEntry>
): Promise<WriteOutcome<QueryHistory>> {
  return serialised(username, async () => {
    const current = await historyForWrite(username);
    if (!current.success) return current;
    const {history, recovered} = current.data;

    let found = false;
    const entries = history.entries.map((e) => {
      if (e.queryExecutionId === queryExecutionId) {
        found = true;
        return {...e, ...patch};
      }
      return e;
    });
    // After a recovery the write is no longer optional, or the
    // unreadable document survives its own quarantine and stays broken.
    if (!found && !recovered) return {success: true, data: history, recovered};

    const next: QueryHistory = {version: HISTORY_VERSION, entries};
    const written = await writeHistory(username, next);
    if (!written.success) return written;
    return {success: true, data: next, recovered};
  });
}
