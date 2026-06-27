import { GetObjectCommand, PutObjectCommand } from '@aws-sdk/client-s3';
import { getS3Client } from '../../lib/s3Client';
import { withCredentialRetry } from '../../lib/credentialRetry';
import type { ServiceResult } from '../../types/service.types';
import type { SavedQueriesStore, SavedQuery } from './query.types';

// SPEC-043 FR-004: per-user saved queries stored as JSON, mirroring the SPEC-034
// history store. Lives in the protected `user_settings/` folder whose policy
// ALLOWS PutObject (overwrite) but DENIES delete — so create/update/remove only
// ever overwrite the whole file, never an S3 object delete. The folder is hidden
// from the file browser.

const emptyStore = (): SavedQueriesStore => ({ version: 1, queries: [] });

function storeKey(username: string): string {
  return `${username}/user_settings/saved-queries.json`;
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

// FR-004: read + parse the store. A missing file is the empty state, not an error.
export async function getSavedQueries(username: string): Promise<ServiceResult<SavedQueriesStore>> {
  return withCredentialRetry(getS3Client, async (client) => {
    try {
      const response = await client.send(new GetObjectCommand({ Bucket: bucket(), Key: storeKey(username) }));
      const body = await response.Body?.transformToString();
      return { success: true, data: parseStore(body) };
    } catch (err) {
      if (isNotFound(err)) return { success: true, data: emptyStore() };
      return toServiceError(err, 'Failed to load saved queries');
    }
  });
}

// Overwrite the store file (PutObject — never a delete). Last-writer-wins on a
// single user's own file, acceptable as for history (FR-004).
async function writeStore(username: string, store: SavedQueriesStore): Promise<ServiceResult<void>> {
  return withCredentialRetry(getS3Client, async (client) => {
    try {
      await client.send(
        new PutObjectCommand({
          Bucket: bucket(),
          Key: storeKey(username),
          Body: JSON.stringify(store),
          ContentType: 'application/json',
        })
      );
      return { success: true, data: undefined };
    } catch (err) {
      return toServiceError(err, 'Failed to save query');
    }
  });
}

// FR-004: create or replace a saved query by id, then write back. A matching id
// is updated in place (keeping list position); a new id is prepended.
export async function upsertSavedQuery(username: string, query: SavedQuery): Promise<ServiceResult<SavedQueriesStore>> {
  const current = await getSavedQueries(username);
  if (!current.success) return current;

  const existingIdx = current.data.queries.findIndex((q) => q.id === query.id);
  const queries =
    existingIdx === -1
      ? [query, ...current.data.queries]
      : current.data.queries.map((q) => (q.id === query.id ? query : q));

  const next: SavedQueriesStore = { version: 1, queries };
  const written = await writeStore(username, next);
  if (!written.success) return written;
  return { success: true, data: next };
}

// FR-004 / FR-007: remove a saved query by id by rewriting the JSON without it
// (never an S3 delete). An unknown id is a no-op success.
export async function removeSavedQuery(username: string, id: string): Promise<ServiceResult<SavedQueriesStore>> {
  const current = await getSavedQueries(username);
  if (!current.success) return current;

  const queries = current.data.queries.filter((q) => q.id !== id);
  if (queries.length === current.data.queries.length) {
    return { success: true, data: current.data }; // unknown id → no-op
  }

  const next: SavedQueriesStore = { version: 1, queries };
  const written = await writeStore(username, next);
  if (!written.success) return written;
  return { success: true, data: next };
}
