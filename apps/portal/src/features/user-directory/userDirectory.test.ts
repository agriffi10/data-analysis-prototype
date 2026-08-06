import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {MAX_INDEXED_USERNAMES, buildIndex, search, searchWithCost} from './usernameTrie';
import {DIRECTORY_KEY, getUserDirectory} from './userDirectory.service';
import {getS3Client} from '../../lib/s3Client';

// ─── from usernameTrie.test.ts ───
describe('usernameTrie', () => {
  const NAMES = ['alice', 'alicia', 'bob', 'bob_smith', 'carol', 'malice', 'robert_bob'];

  const names = (query: string, limit?: number) => search(buildIndex(NAMES), query, limit).map((r) => r.username);
  const bands = (query: string, limit?: number) => search(buildIndex(NAMES), query, limit).map((r) => r.match);

  describe('buildIndex', () => {
    it('de-duplicates and orders the scan target', () => {
      const index = buildIndex(['carol', 'alice', 'carol']);
      expect(index.ordered).toEqual(['alice', 'carol']);
      expect(index.size).toBe(2);
      expect(index.truncated).toBe(false);
    });

    it('caps the index and reports the truncation', () => {
      const many = Array.from({length: MAX_INDEXED_USERNAMES + 5}, (_, n) => `user${String(n).padStart(6, '0')}`);
      const index = buildIndex(many);
      expect(index.size).toBe(MAX_INDEXED_USERNAMES);
      expect(index.truncated).toBe(true);
    });
  });

  describe('search — ranking', () => {
    it('puts the exact match first', () => {
      expect(names('bob')).toEqual(['bob', 'bob_smith', 'robert_bob']);
      expect(bands('bob')).toEqual(['exact', 'prefix', 'substring']);
    });

    it('puts prefix matches before substring matches', () => {
      expect(names('ali')).toEqual(['alice', 'alicia', 'malice']);
      expect(bands('ali')).toEqual(['prefix', 'prefix', 'substring']);
    });

    it('orders each band alphabetically', () => {
      expect(names('o')).toEqual(['bob', 'bob_smith', 'carol', 'robert_bob']);
    });

    it('never returns a username twice when it matches two ways', () => {
      // `bob` is the exact match AND a prefix match AND a substring of itself.
      const results = search(buildIndex(NAMES), 'bob');
      expect(new Set(results.map((r) => r.username)).size).toBe(results.length);
    });

    it('truncates the lowest band first', () => {
      // 'bob' would give exact + prefix + substring; a limit of 2 must drop the substring one,
      // never the exact one.
      expect(names('bob', 2)).toEqual(['bob', 'bob_smith']);
      expect(names('bob', 1)).toEqual(['bob']);
    });

    it('is deterministic', () => {
      const index = buildIndex(NAMES);
      expect(search(index, 'b')).toEqual(search(index, 'b'));
    });
  });

  describe('search — input handling', () => {
    it('trims and lowercases the query', () => {
      // `malice` rides along as a substring match — which is the point of the substring band and
      // is why someone looking for `bob_smith` can type `smith`.
      expect(names('  ALICE  ')).toEqual(['alice', 'malice']);
    });

    it('returns nothing for an empty query rather than everything', () => {
      expect(names('')).toEqual([]);
      expect(names('   ')).toEqual([]);
    });

    it('searches a single character normally — there is no minimum length', () => {
      expect(names('c')).toEqual(['carol', 'alice', 'alicia', 'malice']);
    });

    it('matches nothing rather than throwing on a character no username can hold', () => {
      expect(() => names('@!#')).not.toThrow();
      expect(names('@!#')).toEqual([]);
    });

    it('handles an empty index', () => {
      expect(search(buildIndex([]), 'anything')).toEqual([]);
    });
  });

  describe('search — the cost bound', () => {
    const big = buildIndex(Array.from({length: MAX_INDEXED_USERNAMES}, (_, n) => `user${String(n).padStart(6, '0')}`));

    it('walks the trie for the prefix band rather than scanning', () => {
      // The claim under test is about the PREFIX BAND ONLY: its cost is a function of the query
      // and the subtree it enumerates, not of the directory size. A scan-everything prefix
      // implementation passes every ranking test above and fails this one.
      //
      // It deliberately says nothing about the substring band — see the test below, which is
      // where that cost is stated honestly rather than left implied by this one's name.
      const {nodesVisited, results} = searchWithCost(big, 'user000001');
      expect(results).toHaveLength(1);
      expect(nodesVisited).toBeLessThan(40);
      expect(nodesVisited).toBeLessThan(big.size / 100);
    });

    it('DOES scan the whole list when the prefix band cannot fill the limit', () => {
      // The honest statement of the cost, pinned so nobody reads the test above as meaning more
      // than it does. The substring band is skipped only when the prefix band FILLS the limit —
      // so a query with fewer than `limit` matches, including a fully-typed exact name (the
      // commonest typeahead endpoint), pays a full linear scan per keystroke.
      //
      // That is the documented contract (SPEC-147 FR-003), not a defect, and it is bounded: the
      // 20,000 cap exists so this stays a scan of a known size. Narrowing it — e.g. skipping the
      // band on an exact match — would CHANGE RANKING, dropping the substring matches that make
      // `smith` find `bob_smith`, so it is not a free optimisation.
      const {namesScanned, results} = searchWithCost(big, 'user000001');
      expect(results).toHaveLength(1);
      expect(namesScanned).toBe(big.size);
    });

    it('skips the substring scan entirely when the prefix band filled the limit', () => {
      const {namesScanned, results} = searchWithCost(big, 'user00000', 8);
      expect(results).toHaveLength(8);
      expect(results.every((r) => r.match === 'prefix')).toBe(true);
      expect(namesScanned).toBe(0);
    });

    it('short-circuits the substring scan once the limit is reached', () => {
      // '00001' is a substring, never a prefix — so this is the linear band, and the point is
      // that it stops early rather than reading all 20,000.
      const {namesScanned, results} = searchWithCost(big, '00001', 4);
      expect(results).toHaveLength(4);
      expect(results.every((r) => r.match === 'substring')).toBe(true);
      expect(namesScanned).toBeLessThan(big.size);
    });

    it('answers a prefix-heavy query over 20,000 entries quickly', () => {
      const started = performance.now();
      for (let n = 0; n < 200; n += 1) search(big, 'user01');
      expect(performance.now() - started).toBeLessThan(1000);
    });

    it('answers a substring-only query over 20,000 entries quickly', () => {
      const started = performance.now();
      for (let n = 0; n < 20; n += 1) search(big, '999');
      expect(performance.now() - started).toBeLessThan(1000);
    });
  });
});

// ─── from userDirectory.service.test.ts ───
vi.mock('../../lib/s3Client', () => ({getS3Client: vi.fn()}));
vi.mock('../../lib/awsCredentials', () => ({
  getSessionCredentials: vi.fn().mockResolvedValue({success: true, data: {}})
}));

describe('userDirectory.service', () => {
  const send = vi.fn();

  const awsError = (name: string, status?: number) =>
    Object.assign(new Error(name), {name, $metadata: status ? {httpStatusCode: status} : {}});

  const body = (value: unknown) => ({
    Body: {transformToString: async () => (typeof value === 'string' ? value : JSON.stringify(value))}
  });

  const document = (over: Record<string, unknown> = {}) => ({
    version: 1,
    generatedAt: '2026-08-05T04:00:11Z',
    count: 2,
    usernames: ['alice', 'bob_smith'],
    ...over
  });

  beforeEach(() => {
    vi.clearAllMocks();
    send.mockReset();
    vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
    vi.mocked(getS3Client).mockResolvedValue({success: true, data: {send} as never});
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  describe('getUserDirectory', () => {
    it('reads the key SPEC-146 publishes, from the user-space bucket', async () => {
      send.mockResolvedValue(body(document()));

      const result = await getUserDirectory();

      expect(DIRECTORY_KEY).toBe('_directory/usernames.json');
      const command = send.mock.calls[0][0];
      expect(command.input).toMatchObject({Bucket: 'user-space', Key: '_directory/usernames.json'});
      expect(result).toEqual({
        success: true,
        data: {usernames: ['alice', 'bob_smith'], generatedAt: '2026-08-05T04:00:11Z'}
      });
    });

    it('reads the bucket name at call time, not module load', async () => {
      // A module-level `import.meta.env` const would have been captured before `stubEnv` ran.
      vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'a-different-bucket');
      send.mockResolvedValue(body(document()));

      await getUserDirectory();

      expect(send.mock.calls[0][0].input.Bucket).toBe('a-different-bucket');
    });

    it('treats a missing document as the empty state, not an error', async () => {
      // The ordinary state of the bucket until the builder's first run.
      send.mockRejectedValue(awsError('NoSuchKey', 404));

      expect(await getUserDirectory()).toEqual({success: true, data: {usernames: [], generatedAt: null}});
    });

    it('treats a corrupt document as the empty state', async () => {
      send.mockResolvedValue(body('{not json'));

      expect(await getUserDirectory()).toEqual({success: true, data: {usernames: [], generatedAt: null}});
    });

    it('refuses a version it does not understand, and names it', async () => {
      // A shape this reader does not understand is not a shape it should guess at.
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
      send.mockResolvedValue(body(document({version: 2})));

      const result = await getUserDirectory();

      expect(result).toEqual({success: true, data: {usernames: [], generatedAt: null}});
      expect(warn.mock.calls[0][0]).toContain('2');
      warn.mockRestore();
    });

    it('treats a non-array usernames field as empty', async () => {
      send.mockResolvedValue(body(document({usernames: {alice: true}})));

      expect((await getUserDirectory()) as never).toMatchObject({data: {usernames: []}});
    });

    it('re-checks every entry against the catalog-safe rule', async () => {
      // The producer already guarantees this. The consumer re-checks because the array is
      // rendered into the DOM and used to build keys, and a producer guarantee is not a runtime
      // guarantee — the object is one `aws s3 cp` away from holding anything.
      send.mockResolvedValue(body(document({usernames: ['alice', 'Bob', '../etc/passwd', 42, '', 'cara']})));

      const result = await getUserDirectory();

      expect(result).toMatchObject({success: true, data: {usernames: ['alice', 'cara']}});
    });

    it('reports a real fault as a failure', async () => {
      send.mockRejectedValue(awsError('AccessDenied', 403));

      const result = await getUserDirectory();

      expect(result.success).toBe(false);
    });

    it('never throws', async () => {
      send.mockImplementation(() => {
        throw new TypeError('something unexpected');
      });

      await expect(getUserDirectory()).resolves.toMatchObject({success: false});
    });

    it('drops generatedAt when it is not a string, keeping the usernames', async () => {
      send.mockResolvedValue(body(document({generatedAt: 12345})));

      expect(await getUserDirectory()).toMatchObject({data: {usernames: ['alice', 'bob_smith'], generatedAt: null}});
    });
  });
});
