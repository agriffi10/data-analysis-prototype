import {describe, it, expect} from 'vitest';
import {parseMemberInput, parseMemberInputDetailed} from './memberInput';

/**
 * `parseMemberInput` had no direct unit test before SPEC-147 — it was exercised only through
 * `AddMembersDialog.test.tsx`. Its cases are pinned here BEFORE the detailed variant lands
 * beside it, because FR-006's criterion is that the original's behaviour is unchanged, and a
 * behaviour with no test is one a refactor can change without anything noticing.
 */
describe('parseMemberInput — unchanged by SPEC-147', () => {
  it('splits on commas, spaces and newlines', () => {
    expect(parseMemberInput('bob, cara\ndan  erin')).toEqual(['bob', 'cara', 'dan', 'erin']);
  });

  it('lowercases and de-duplicates', () => {
    expect(parseMemberInput('Bob bob BOB')).toEqual(['bob']);
  });

  it('DROPS anything failing the catalog-safe rule, silently', () => {
    // The silent drop is the shipped behaviour that consumers and their tests rely on. The
    // detailed variant below exists precisely because it is the wrong behaviour in a field
    // that can afford to say something.
    expect(parseMemberInput('bob alice@corp.com 9lives x')).toEqual(['bob']);
  });

  it('returns an empty list for empty input', () => {
    expect(parseMemberInput('')).toEqual([]);
    expect(parseMemberInput('   ,  ')).toEqual([]);
  });
});

describe('parseMemberInputDetailed', () => {
  it('reports what it rejected instead of dropping it', () => {
    expect(parseMemberInputDetailed('bob alice@corp.com 9lives')).toEqual({
      valid: ['bob'],
      invalid: ['alice@corp.com', '9lives']
    });
  });

  it('agrees with parseMemberInput on what is valid', () => {
    const raw = 'Bob, cara\n9lives  bob  x  dan_smith';
    expect(parseMemberInputDetailed(raw).valid).toEqual(parseMemberInput(raw));
  });

  it('reports invalid tokens AS TYPED, not lowercased', () => {
    // The user has to recognise what they pasted in order to fix it, and `bob smith` is a
    // different string from the `Bob Smith` on their clipboard.
    expect(parseMemberInputDetailed('Bob Smith!').invalid).toEqual(['Smith!']);
  });

  it('de-duplicates the valid list but keeps input order', () => {
    expect(parseMemberInputDetailed('cara bob cara').valid).toEqual(['cara', 'bob']);
  });

  it('returns two empty lists for empty input', () => {
    expect(parseMemberInputDetailed('  , \n ')).toEqual({valid: [], invalid: []});
  });

  it('treats a token that is merely too short as invalid rather than dropping it', () => {
    expect(parseMemberInputDetailed('ab')).toEqual({valid: [], invalid: ['ab']});
  });
});
