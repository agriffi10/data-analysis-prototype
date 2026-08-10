import {userSpaceBucket, userSettingsKey} from '../../lib/userSpace';
import {readJsonDocument, writeJsonDocument} from '../../lib/s3Json';
import {ok} from '../../lib/serviceResult';
import type {ServiceResult} from '../../types/service.types';
import type {QueryHistory, QueryHistoryEntry} from './query.types';
import {QUERY_HISTORY_MAX} from './query.constants';

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

const emptyHistory = (): QueryHistory => ({version: 1, entries: []});

function historyKey(username: string): string {
  return userSettingsKey(username, 'query-history.json');
}

// Parse for the WRITE path. Same reasoning as savedQueries.service.ts: the write is
// an unconditional PutObject, so a body misread as empty is COMMITTED as empty and
// one append discards the whole history. This file is the only record of a query
// beyond Athena's ~45-day retention and the user cannot re-create it — there is no
// clear/delete, by design. An absent or zero-byte body is still the empty history.
function parseHistoryForWrite(body: string | undefined): ServiceResult<QueryHistory> {
  if (!body) return ok(emptyHistory());
  try {
    const parsed = JSON.parse(body) as QueryHistory;
    if (parsed?.version === 1 && Array.isArray(parsed.entries)) return ok(parsed);
  } catch {
    // Fall through to the shared refusal below.
  }
  return {
    success: false,
    error: {
      message: 'Query history could not be read, so nothing was changed.',
      code: 'QueryHistoryUnreadable'
    }
  };
}

// The DISPLAY read, derived from the write parser so the two can never drift apart
// on what a valid history is. Same validation, different answer to an unreadable
// body: empty here, a refusal there.
function parseHistory(body: string | undefined): QueryHistory {
  const result = parseHistoryForWrite(body);
  return result.success ? result.data : emptyHistory();
}

// The read that precedes every write. Differs from `getQueryHistory` only in how it
// treats a body it cannot parse.
async function readHistoryForWrite(username: string): Promise<ServiceResult<QueryHistory>> {
  return readJsonDocument({
    bucket: userSpaceBucket(),
    key: historyKey(username),
    parse: parseHistoryForWrite,
    onMissing: () => ({success: true, data: emptyHistory()}),
    fallbackMessage: 'Failed to load query history'
  });
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

// Overwrite the history file (PutObject — never a delete). Concurrent writes
// are last-writer-wins on a single user's own file, which is acceptable here.
async function writeHistory(username: string, history: QueryHistory): Promise<ServiceResult<void>> {
  return writeJsonDocument({
    bucket: userSpaceBucket(),
    key: historyKey(username),
    value: history,
    fallbackMessage: 'Failed to save query history'
  });
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
): Promise<ServiceResult<QueryHistory>> {
  const current = await readHistoryForWrite(username);
  if (!current.success) return current;

  const entries = [entry, ...current.data.entries].slice(0, QUERY_HISTORY_MAX);
  const next: QueryHistory = {version: 1, entries};

  const written = await writeHistory(username, next);
  if (!written.success) return written;
  return {success: true, data: next};
}

/**
 * Updates an existing entry in place (e.g. records terminal status + stats
 * once polling completes) and writes back. An unknown id is a no-op success.
 */
export async function updateQueryHistoryEntry(
  username: string,
  queryExecutionId: string,
  patch: Partial<QueryHistoryEntry>
): Promise<ServiceResult<QueryHistory>> {
  const current = await readHistoryForWrite(username);
  if (!current.success) return current;

  let found = false;
  const entries = current.data.entries.map((e) => {
    if (e.queryExecutionId === queryExecutionId) {
      found = true;
      return {...e, ...patch};
    }
    return e;
  });
  if (!found) return {success: true, data: current.data};

  const next: QueryHistory = {version: 1, entries};
  const written = await writeHistory(username, next);
  if (!written.success) return written;
  return {success: true, data: next};
}
