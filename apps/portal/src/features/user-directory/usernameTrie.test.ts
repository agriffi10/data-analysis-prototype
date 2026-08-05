import {describe, expect, it} from 'vitest';
import {MAX_INDEXED_USERNAMES, buildIndex, search, searchWithCost} from './usernameTrie';

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

  it('walks the trie for the prefix band and never scans the full list', () => {
    // The claim under test: prefix cost is a function of the QUERY and the subtree it
    // enumerates, not of the directory size. A scan-everything implementation passes every
    // ranking test above and fails this one.
    const {nodesVisited, results} = searchWithCost(big, 'user000001');
    expect(results).toHaveLength(1);
    expect(nodesVisited).toBeLessThan(40);
    expect(nodesVisited).toBeLessThan(big.size / 100);
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
