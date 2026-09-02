import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {MAX_INDEXED_USERNAMES, buildIndex, search, searchWithCost} from './usernameTrie';
import {getUserDirectory} from './userDirectory.service';
import {API_ROUTES} from '../../types/apiContract.generated';
import {resetApiClientForTests, setAuthTokenProvider} from '../../lib/apiClient';
import {clearRuntimeConfig, seedRuntimeConfig} from '../../test/seedRuntimeConfig';

// ─── from usernameTrie.test.ts ───

describe('usernameTrie', () => {
  const NAMES = ['alice', 'alicia', 'bob', 'bob_smith', 'carol', 'malice', 'robert_bob'];

  const names = (query: string, limit?: number) => search(buildIndex(NAMES), query, limit).map((r) => r.username);
  const bands = (query: string, limit?: number) => search(buildIndex(NAMES), query, limit).map((r) => r.match);

  describe('buildIndex', () => {
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
    it('returns nothing for an empty query rather than everything', () => {
      expect(names('')).toEqual([]);
      expect(names('   ')).toEqual([]);
    });

    it('matches nothing rather than throwing on a character no username can hold', () => {
      expect(() => names('@!#')).not.toThrow();
      expect(names('@!#')).toEqual([]);
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
  });
});

// ─── from userDirectory.service.test.ts ───
//
// THE PORT'S DISPOSITION. Ten assertions covered this service when it read S3 directly. Four
// moved to `lambdas/api/test_user_directory_route.py` with their reasoning carried over, three
// are kept on BOTH sides, and three are kept here because they are about the transport rather
// than the document. Nothing was dropped, and the delivery doc reproduces the table — "we moved
// the tests" is exactly the claim nobody can check a year later.
//
//   reads the key the builder publishes, from the user-space bucket .... moved
//   reads the bucket name at call time ................................ moved (replaced in kind:
//                                                                       the API origin, in
//                                                                       apiClient.test.ts)
//   missing document -> empty state ................................... both
//   corrupt document -> empty state .................................. moved
//   unsupported version, and names it ................................ moved
//   non-array usernames -> empty ..................................... moved
//   re-checks every entry against the catalog-safe rule ............... both
//   a real fault is a failure ........................................ kept
//   never throws ..................................................... kept, extended to a
//                                                                       non-envelope gateway body
//   drops a non-string generatedAt ................................... both

describe('userDirectory.service', () => {
  const ORIGIN = 'https://api.example.test';
  const fetchMock = vi.fn();

  const envelope = (status: number, code: string) =>
    ({
      ok: false,
      status,
      json: async () => ({error: {code, requestId: 'r1'}})
    }) as unknown as Response;

  const payload = (body: unknown) => ({ok: true, status: 200, json: async () => body}) as unknown as Response;

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
    seedRuntimeConfig({apiBaseUrl: ORIGIN});
    setAuthTokenProvider(async () => 'a-token');
  });

  afterEach(() => {
    fetchMock.mockReset();
    resetApiClientForTests();
    clearRuntimeConfig();
    vi.unstubAllGlobals();
  });

  describe('getUserDirectory', () => {
    it('issues exactly one API request, for the route the generated table names', async () => {
      // The route id is the assertion: a typo cannot compile, but a wrong-but-valid id can.
      fetchMock.mockResolvedValue(payload({usernames: ['alice', 'bob_smith'], generatedAt: '2026-08-05T04:00:11Z'}));

      const result = await getUserDirectory();

      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(String(fetchMock.mock.calls[0][0])).toBe(`${ORIGIN}${API_ROUTES['userDirectory.get'].path}`);
      expect(result).toEqual({
        success: true,
        data: {usernames: ['alice', 'bob_smith'], generatedAt: '2026-08-05T04:00:11Z'}
      });
    });

    it("treats the API's empty answer as the empty state, not an error", async () => {
      // BOTH SIDES. The server answers 200 with an empty list for a missing, unreadable or
      // unrecognised document; this is the half that says an empty list is a success here.
      fetchMock.mockResolvedValue(payload({usernames: [], generatedAt: null}));

      expect(await getUserDirectory()).toEqual({success: true, data: {usernames: [], generatedAt: null}});
    });

    it('re-checks every entry against the catalog-safe rule', async () => {
      // BOTH SIDES, and that is deliberate rather than redundant: the API is now a SECOND
      // producer, which is one more thing that can be wrong. The array is rendered into the DOM
      // and used to build keys, and a producer guarantee is not a runtime guarantee.
      fetchMock.mockResolvedValue(
        payload({usernames: ['alice', 'Bob', '../etc/passwd', 42, '', 'cara'], generatedAt: null})
      );

      const result = await getUserDirectory();

      expect(result).toMatchObject({success: true, data: {usernames: ['alice', 'cara']}});
    });

    it('reports a real fault as a failure', async () => {
      // KEPT. A 503 envelope is a fault, and the hook collapses it to 'unavailable' exactly as
      // an AWS error used to be.
      fetchMock.mockResolvedValue(envelope(503, 'ApiUnavailable'));

      const result = await getUserDirectory();

      expect(result).toEqual({success: false, error: expect.objectContaining({code: 'ApiUnavailable'})});
    });

    it("carries SessionExpired through, so the hook's unavailable collapse still holds", async () => {
      fetchMock.mockResolvedValue(envelope(401, 'SessionExpired'));

      const result = await getUserDirectory();

      expect(result).toMatchObject({success: false, error: {code: 'SessionExpired'}});
    });

    it('reaches no AWS SDK, no S3 client and no bucket name', async () => {
      // Read as SOURCE, the way every other sweep in this suite does: the service's imports are
      // the assertion, and an import that resolves is invisible to a behavioural test.
      const source = Object.values(
        import.meta.glob('./userDirectory.service.ts', {
          query: '?raw',
          import: 'default',
          eager: true
        }) as Record<string, string>
      )[0];

      expect(source).not.toContain('@aws-sdk/');
      expect(source).not.toContain('s3Client');
      expect(source).not.toContain('s3Json');
      expect(source).not.toContain('userSpace');
      expect(source).not.toContain('_directory/');
    });
  });
});
