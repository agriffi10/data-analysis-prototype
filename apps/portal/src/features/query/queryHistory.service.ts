import { GetObjectCommand, PutObjectCommand } from '@aws-sdk/client-s3';
import { getS3Client } from '../../lib/s3Client';
import { withCredentialRetry } from '../../lib/credentialRetry';
import type { ServiceResult } from '../../types/service.types';
import type { QueryHistory, QueryHistoryEntry } from './query.types';
import { QUERY_HISTORY_MAX } from './query.constants';

// SPEC-034 FR-007: a private, per-user query history stored as JSON alongside the
// user's results. This is the backend-free way to give each user a private history
// (the shared workgroup's ListQueryExecutions leaks all users and isn't granted),
// and it preserves SQL + stats indefinitely beyond Athena's ~45-day retention.
//
// The file lives in the protected `user_settings/` folder. Its IAM policy ALLOWS
// PutObject (overwrite) but DENIES delete — get/append/update only ever overwrite,
// never delete, so the file is writable yet tamper-resistant. The folder is hidden
// from the file browser. It is read-only to the user (SPEC-036): there is no
// delete/clear in v1.

const emptyHistory = (): QueryHistory => ({ version: 1, entries: [] });

function historyKey(username: string): string {
  return `${username}/user_settings/query-history.json`;
}

function bucket(): string {
  return import.meta.env.VITE_S3_USER_SPACE_BUCKET as string;
}

function toServiceError(err: unknown, fallback: string) {
  const e = err as { message?: string; name?: string };
  return {
    success: false as const,
    error: { message: e.message ?? fallback, code: e.name },
  };
}

function isNotFound(err: unknown): boolean {
  const e = err as { name?: string; $metadata?: { httpStatusCode?: number } };
  return e.name === 'NoSuchKey' || e.name === 'NotFound' || e.$metadata?.httpStatusCode === 404;
}

// Forgivingly parse the history file body: a malformed or legacy file falls back
// to empty rather than erroring (same spirit as the missing-file case).
function parseHistory(body: string | undefined): QueryHistory {
  if (!body) return emptyHistory();
  try {
    const parsed = JSON.parse(body) as QueryHistory;
    if (parsed?.version === 1 && Array.isArray(parsed.entries)) return parsed;
    return emptyHistory();
  } catch {
    return emptyHistory();
  }
}

// FR-007: read + parse the history file. A missing file is the empty state, not an
// error (same forgiving handling as the architecture's connections.json).
export async function getQueryHistory(username: string): Promise<ServiceResult<QueryHistory>> {
  return withCredentialRetry(getS3Client, async (client) => {
    try {
      const response = await client.send(new GetObjectCommand({ Bucket: bucket(), Key: historyKey(username) }));
      const body = await response.Body?.transformToString();
      return { success: true, data: parseHistory(body) };
    } catch (err) {
      if (isNotFound(err)) return { success: true, data: emptyHistory() };
      return toServiceError(err, 'Failed to load query history');
    }
  });
}

// Overwrite the history file (PutObject — never a delete). Concurrent writes are
// last-writer-wins on a single user's own file, which is acceptable here (one user,
// their own history); documented per FR-007.
async function writeHistory(username: string, history: QueryHistory): Promise<ServiceResult<void>> {
  return withCredentialRetry(getS3Client, async (client) => {
    try {
      await client.send(
        new PutObjectCommand({
          Bucket: bucket(),
          Key: historyKey(username),
          Body: JSON.stringify(history),
          ContentType: 'application/json',
        })
      );
      return { success: true, data: undefined };
    } catch (err) {
      return toServiceError(err, 'Failed to save query history');
    }
  });
}

// FR-007: prepend a new entry (newest-first), cap at QUERY_HISTORY_MAX dropping the
// oldest, and write back. Called at submit time so an interrupted tab still records
// the attempt (updateQueryHistoryEntry fills in the terminal status later).
export async function appendQueryHistory(
  username: string,
  entry: QueryHistoryEntry
): Promise<ServiceResult<QueryHistory>> {
  const current = await getQueryHistory(username);
  if (!current.success) return current;

  const entries = [entry, ...current.data.entries].slice(0, QUERY_HISTORY_MAX);
  const next: QueryHistory = { version: 1, entries };

  const written = await writeHistory(username, next);
  if (!written.success) return written;
  return { success: true, data: next };
}

// FR-007: update an existing entry in place (e.g. record terminal status + stats
// once polling completes) and write back. An unknown id is a no-op success.
export async function updateQueryHistoryEntry(
  username: string,
  queryExecutionId: string,
  patch: Partial<QueryHistoryEntry>
): Promise<ServiceResult<QueryHistory>> {
  const current = await getQueryHistory(username);
  if (!current.success) return current;

  let found = false;
  const entries = current.data.entries.map((e) => {
    if (e.queryExecutionId === queryExecutionId) {
      found = true;
      return { ...e, ...patch };
    }
    return e;
  });
  if (!found) return { success: true, data: current.data };

  const next: QueryHistory = { version: 1, entries };
  const written = await writeHistory(username, next);
  if (!written.success) return written;
  return { success: true, data: next };
}
