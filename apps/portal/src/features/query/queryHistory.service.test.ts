import { describe, it, expect, vi, beforeEach, afterEach, type MockedFunction } from 'vitest';

vi.mock('../../lib/s3Client', () => ({ getS3Client: vi.fn() }));

import { getS3Client } from '../../lib/s3Client';
import { getQueryHistory, appendQueryHistory, updateQueryHistoryEntry } from './queryHistory.service';
import type { QueryHistory, QueryHistoryEntry } from './query.types';

const mockGetClient = getS3Client as unknown as MockedFunction<() => Promise<unknown>>;

// A stateful fake user-space bucket: GetObject reads the stored JSON (or throws
// NoSuchKey when absent); PutObject (input has a Body) overwrites it.
function fakeBucket(initial: string | null) {
  let stored = initial;
  const send = vi.fn(async (cmd: { input: { Body?: string } }) => {
    if (cmd.input.Body !== undefined) {
      stored = cmd.input.Body;
      return {};
    }
    if (stored === null) {
      throw Object.assign(new Error('missing'), { name: 'NoSuchKey' });
    }
    const body = stored;
    return { Body: { transformToString: async () => body } };
  });
  mockGetClient.mockResolvedValue({ success: true, data: { send } });
  return { send, stored: () => stored };
}

function entry(id: string): QueryHistoryEntry {
  return {
    queryExecutionId: id,
    sql: 'SELECT 1',
    database: 'alice',
    submittedAt: '2026-06-18T10:00:00.000Z',
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-bucket');
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('getQueryHistory', () => {
  it('returns an empty history (no error) when the file is absent', async () => {
    fakeBucket(null);

    const result = await getQueryHistory('alice');

    expect(result).toEqual({ success: true, data: { version: 1, entries: [] } });
  });

  it('reads and parses an existing history file', async () => {
    fakeBucket(JSON.stringify({ version: 1, entries: [entry('q1')] } as QueryHistory));

    const result = await getQueryHistory('alice');

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.entries).toHaveLength(1);
    expect(result.data.entries[0].queryExecutionId).toBe('q1');
  });

  it('falls back to empty on a malformed file', async () => {
    fakeBucket('not json{');

    const result = await getQueryHistory('alice');

    expect(result).toEqual({ success: true, data: { version: 1, entries: [] } });
  });
});

describe('appendQueryHistory', () => {
  it('prepends newest-first and writes back', async () => {
    const fake = fakeBucket(JSON.stringify({ version: 1, entries: [entry('old')] } as QueryHistory));

    const result = await appendQueryHistory('alice', entry('new'));

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.entries.map((e) => e.queryExecutionId)).toEqual(['new', 'old']);
    // Persisted via PutObject (overwrite).
    expect(JSON.parse(fake.stored() as string).entries[0].queryExecutionId).toBe('new');
  });

  it('caps the list at QUERY_HISTORY_MAX, dropping the oldest', async () => {
    const existing = Array.from({ length: 100 }, (_, i) => entry(`old-${i}`));
    fakeBucket(JSON.stringify({ version: 1, entries: existing } as QueryHistory));

    const result = await appendQueryHistory('alice', entry('new'));

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.entries).toHaveLength(100);
    expect(result.data.entries[0].queryExecutionId).toBe('new');
    // old-99 (the previous oldest) is dropped.
    expect(result.data.entries.at(-1)?.queryExecutionId).toBe('old-98');
  });

  it('starts a fresh history when the file is absent', async () => {
    fakeBucket(null);

    const result = await appendQueryHistory('alice', entry('first'));

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.entries.map((e) => e.queryExecutionId)).toEqual(['first']);
  });
});

describe('updateQueryHistoryEntry', () => {
  it('updates a matching entry in place and writes back', async () => {
    fakeBucket(JSON.stringify({ version: 1, entries: [entry('q1')] } as QueryHistory));

    const result = await updateQueryHistoryEntry('alice', 'q1', {
      status: 'SUCCEEDED',
      dataScannedBytes: 2048,
      durationMs: 120,
    });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.entries[0]).toMatchObject({
      queryExecutionId: 'q1',
      status: 'SUCCEEDED',
      dataScannedBytes: 2048,
      durationMs: 120,
    });
  });

  it('is a no-op success (no write) for an unknown id', async () => {
    const fake = fakeBucket(JSON.stringify({ version: 1, entries: [entry('q1')] } as QueryHistory));

    const result = await updateQueryHistoryEntry('alice', 'unknown', {
      status: 'FAILED',
    });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.entries[0].status).toBeUndefined();
    // Only the read happened — no PutObject.
    expect(fake.send).toHaveBeenCalledTimes(1);
  });
});
