import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {apiRequest} from '../../lib/apiClient';
import {appendQueryHistory, getQueryHistory, updateQueryHistoryEntry} from './queryHistory.service';
import type {QueryHistory, QueryHistoryEntry} from './query.types';

vi.mock('../../lib/apiClient', () => ({apiRequest: vi.fn()}));

// ─── from queryHistory.service.test.ts ───

describe('queryHistory.service', () => {
  // A stateful fake user-space document, now behind the API rather than the SDK. The read route
  // returns the stored text (or NotFound when absent); the write route overwrites it; the copy
  // route is RECORDED rather than stored, so `stored()` keeps answering for the document under
  // test while `copies` shows what was set aside. `copyFails` denies the copy, which is the only
  // way to reach the refusal that must never become a silent overwrite.
  //
  // `commands` holds ROUTE IDS where it used to hold SDK command names. That is the same
  // assertion one layer out: the read-copy-write ORDER is what SPEC-159's quarantine turns on,
  // and it is observable either way.
  function fakeBucket(initial: string | null, opts: {copyFails?: boolean; putFails?: boolean} = {}) {
    let stored = initial;
    const commands: string[] = [];
    const copies: {key: string; source: string}[] = [];

    const send = vi.mocked(apiRequest);
    send.mockImplementation((async (route: string, options?: {body?: Record<string, unknown>; query?: Record<string, string>}) => {
      commands.push(route);
      if (route === 'objects.copy') {
        if (opts.copyFails) return {success: false, error: {message: '', code: 'AccessDenied'}};
        const body = options?.body ?? {};
        copies.push({
          key: String(body.destinationKey),
          source: `user-bucket/${String(body.sourceKey)}`
        });
        return {success: true, data: {key: String(body.destinationKey), etag: 'e'}};
      }
      if (route === 'objects.writeContent') {
        if (opts.putFails) return {success: false, error: {message: '', code: 'AccessDenied'}};
        stored = String((options?.body ?? {}).body);
        return {success: true, data: {key: String((options?.body ?? {}).key), etag: 'e'}};
      }
      if (stored === null) return {success: false, error: {message: '', code: 'NotFound'}};
      return {success: true, data: {body: stored, etag: 'e'}};
    }) as never);

    return {send, stored: () => stored, commands, copies};
  }

  function entry(id: string): QueryHistoryEntry {
    return {
      queryExecutionId: id,
      sql: 'SELECT 1',
      database: 'alice',
      submittedAt: '2026-06-18T10:00:00.000Z'
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

      expect(result).toEqual({success: true, data: {version: 1, entries: []}});
    });

    it('reads and parses an existing history file', async () => {
      fakeBucket(JSON.stringify({version: 1, entries: [entry('q1')]} as QueryHistory));

      const result = await getQueryHistory('alice');

      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.data.entries).toHaveLength(1);
      expect(result.data.entries[0].queryExecutionId).toBe('q1');
    });

    it('falls back to empty on a malformed file', async () => {
      fakeBucket('not json{');

      const result = await getQueryHistory('alice');

      expect(result).toEqual({success: true, data: {version: 1, entries: []}});
    });
  });

  describe('appendQueryHistory', () => {
    it('prepends newest-first and writes back', async () => {
      const fake = fakeBucket(JSON.stringify({version: 1, entries: [entry('old')]} as QueryHistory));

      const result = await appendQueryHistory('alice', entry('new'));

      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.data.entries.map((e) => e.queryExecutionId)).toEqual(['new', 'old']);
      // Persisted via PutObject (overwrite).
      expect(JSON.parse(fake.stored() as string).entries[0].queryExecutionId).toBe('new');
    });

    it('caps the list at QUERY_HISTORY_MAX, dropping the oldest', async () => {
      const existing = Array.from({length: 100}, (_, i) => entry(`old-${i}`));
      fakeBucket(JSON.stringify({version: 1, entries: existing} as QueryHistory));

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
      fakeBucket(JSON.stringify({version: 1, entries: [entry('q1')]} as QueryHistory));

      const result = await updateQueryHistoryEntry('alice', 'q1', {
        status: 'SUCCEEDED',
        dataScannedBytes: 2048,
        durationMs: 120
      });

      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.data.entries[0]).toMatchObject({
        queryExecutionId: 'q1',
        status: 'SUCCEEDED',
        dataScannedBytes: 2048,
        durationMs: 120
      });
    });

    it('is a no-op success (no write) for an unknown id', async () => {
      const fake = fakeBucket(JSON.stringify({version: 1, entries: [entry('q1')]} as QueryHistory));

      const result = await updateQueryHistoryEntry('alice', 'unknown', {
        status: 'FAILED'
      });

      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.data.entries[0].status).toBeUndefined();
      // Only the read happened — no PutObject.
      expect(fake.send).toHaveBeenCalledTimes(1);
    });
  });

  // ── The write path refuses a body it cannot read ─────────────────────────────
  // Same hazard as savedQueries, and worse to lose: this file is the only record
  // of a query beyond Athena's ~45-day retention, and the user cannot re-create it
  // (there is no clear/delete, by design).
  //
  // As there, only `append` could actually commit the empty document; `update` took
  // its not-found no-op branch first. `update` is covered because that no-op was
  // reported as success carrying the EMPTY history, which `useQueryHistory`'s
  // onWriteSuccess seeded into the cache — blanking the panel on a read fault.
  describe('the read-modify-write path never overwrites a history it cannot read', () => {
    const newer = [JSON.stringify({version: 2, entries: [entry('q1')]}), JSON.stringify({version: 2})];

    it('append sets the unreadable body aside, then writes', async () => {
      const fake = fakeBucket('not json{');

      const result = await appendQueryHistory('alice', entry('new'));

      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.recovered).toBe(true);
      expect(result.data.entries.map((e) => e.queryExecutionId)).toEqual(['new']);
      expect(fake.commands).toEqual(['objects.readContent', 'objects.copy', 'objects.writeContent']);
      expect(fake.copies[0].key).toMatch(
        /^alice\/user_settings\/query-history\.json\.unreadable-\d{8}T\d{6}Z-[0-9a-f]{8}\.json$/
      );
      expect(fake.copies[0].source).toBe('user-bucket/alice/user_settings/query-history.json');
    });

    it('update forfeits its unknown-id shortcut after a recovery, so the document is repaired', async () => {
      const fake = fakeBucket('not json{');

      const result = await updateQueryHistoryEntry('alice', 'q1', {status: 'SUCCEEDED'});

      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.recovered).toBe(true);
      expect(JSON.parse(fake.stored() as string)).toEqual({version: 1, entries: []});
    });

    it('refuses and writes nothing when the copy fails', async () => {
      const fake = fakeBucket('not json{', {copyFails: true});

      const result = await appendQueryHistory('alice', entry('new'));

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.error.code).toBe('QueryHistoryQuarantineFailed');
      expect(fake.commands).not.toContain('objects.writeContent');
      expect(fake.stored()).toBe('not json{');
    });

    it.each(newer)('refuses a NEWER document without copying or writing it (%#)', async (body) => {
      const fake = fakeBucket(body);

      const result = await appendQueryHistory('alice', entry('new'));

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.error.code).toBe('QueryHistoryNewerVersion');
      expect(fake.commands).toEqual(['objects.readContent']);
      expect(fake.stored()).toBe(body);
    });

    it.each(newer)('refuses a NEWER document on the update path too (%#)', async (body) => {
      const fake = fakeBucket(body);

      const result = await updateQueryHistoryEntry('alice', 'q1', {status: 'SUCCEEDED'});

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.error.code).toBe('QueryHistoryNewerVersion');
      expect(fake.commands).toEqual(['objects.readContent']);
      expect(fake.stored()).toBe(body);
    });

    it('leaves the DISPLAY read forgiving, for a newer document as well as a corrupt one', async () => {
      fakeBucket('not json{');
      expect(await getQueryHistory('alice')).toEqual({success: true, data: {version: 1, entries: []}});

      fakeBucket(JSON.stringify({version: 2, entries: [entry('q1')]}));
      expect(await getQueryHistory('alice')).toEqual({success: true, data: {version: 1, entries: []}});
    });
  });
});

// The SPEC-043 JSON store's tests are GONE, not skipped: SPEC-173 FR-007 deletes the
// store itself, and the `.sql`-object store that replaced it has its own file
// (`savedQueries.service.test.ts`). A repo-wide search for `saved-queries.json` now
// finds it only in docs.
