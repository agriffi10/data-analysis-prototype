import {describe, it, expect, vi, beforeEach, afterEach, type MockedFunction} from 'vitest';

vi.mock('../../lib/s3Client', () => ({getS3Client: vi.fn()}));

import {getS3Client} from '../../lib/s3Client';
import {getSavedQueries, upsertSavedQuery, removeSavedQuery} from './savedQueries.service';
import type {SavedQueriesStore, SavedQuery} from './query.types';

const mockGetClient = getS3Client as unknown as MockedFunction<() => Promise<unknown>>;

// Stateful fake user-space bucket: GetObject reads the stored JSON (throws
// NoSuchKey when absent); a command carrying a Body is a PutObject overwrite.
// A DeleteObjectCommand would carry no Body and no read intent — tracked so we
// can assert it's NEVER issued (delete is IAM-denied in athenaresults/).
function fakeBucket(initial: string | null) {
  let stored = initial;
  const commands: string[] = [];
  const send = vi.fn(async (cmd: {constructor: {name: string}; input: {Body?: string}}) => {
    commands.push(cmd.constructor.name);
    if (cmd.input.Body !== undefined) {
      stored = cmd.input.Body;
      return {};
    }
    if (stored === null) {
      throw Object.assign(new Error('missing'), {name: 'NoSuchKey'});
    }
    const body = stored;
    return {Body: {transformToString: async () => body}};
  });
  mockGetClient.mockResolvedValue({success: true, data: {send}});
  return {send, stored: () => stored, commands};
}

function sq(id: string, name = id, sql = 'SELECT 1'): SavedQuery {
  return {
    id,
    name,
    sql,
    database: 'alice',
    createdAt: '2026-06-18T10:00:00.000Z',
    updatedAt: '2026-06-18T10:00:00.000Z'
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-bucket');
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('getSavedQueries', () => {
  it('returns an empty store (no error) when the file is absent', async () => {
    fakeBucket(null);
    const result = await getSavedQueries('alice');
    expect(result).toEqual({success: true, data: {version: 1, queries: []}});
  });

  it('reads and parses an existing store', async () => {
    fakeBucket(JSON.stringify({version: 1, queries: [sq('a')]} as SavedQueriesStore));
    const result = await getSavedQueries('alice');
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.queries.map((q) => q.id)).toEqual(['a']);
  });

  it('falls back to empty on a malformed file', async () => {
    fakeBucket('not json{');
    const result = await getSavedQueries('alice');
    expect(result).toEqual({success: true, data: {version: 1, queries: []}});
  });
});

describe('upsertSavedQuery', () => {
  it('creates a new query (prepended) when the id is unseen', async () => {
    const fake = fakeBucket(JSON.stringify({version: 1, queries: [sq('a')]} as SavedQueriesStore));
    const result = await upsertSavedQuery('alice', sq('b'));
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.queries.map((q) => q.id)).toEqual(['b', 'a']);
    expect((JSON.parse(fake.stored() as string) as SavedQueriesStore).queries).toHaveLength(2);
  });

  it('replaces in place when the id already exists', async () => {
    fakeBucket(
      JSON.stringify({
        version: 1,
        queries: [sq('a', 'A', 'SELECT 1'), sq('b')]
      } as SavedQueriesStore)
    );
    const result = await upsertSavedQuery('alice', sq('a', 'A2', 'SELECT 2'));
    expect(result.success).toBe(true);
    if (!result.success) return;
    // Same position, updated content.
    expect(result.data.queries.map((q) => q.id)).toEqual(['a', 'b']);
    expect(result.data.queries[0].name).toBe('A2');
    expect(result.data.queries[0].sql).toBe('SELECT 2');
  });
});

describe('removeSavedQuery', () => {
  it('rewrites the JSON without the entry — never an S3 delete', async () => {
    const fake = fakeBucket(
      JSON.stringify({
        version: 1,
        queries: [sq('a'), sq('b')]
      } as SavedQueriesStore)
    );
    const result = await removeSavedQuery('alice', 'a');
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.queries.map((q) => q.id)).toEqual(['b']);
    // Persisted via overwrite; no DeleteObjectCommand ever issued.
    expect(fake.commands).not.toContain('DeleteObjectCommand');
    expect(fake.commands).toContain('PutObjectCommand');
  });

  it('is a no-op success for an unknown id (no write)', async () => {
    const fake = fakeBucket(JSON.stringify({version: 1, queries: [sq('a')]} as SavedQueriesStore));
    const result = await removeSavedQuery('alice', 'missing');
    expect(result.success).toBe(true);
    expect(fake.commands).not.toContain('PutObjectCommand');
  });
});
