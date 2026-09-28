import {describe, expect, it} from 'vitest';
import corpusText from '../../../../../lambdas/archive-common/archive_name_corpus.json?raw';
import {archiveNameRefusal, normalizeArchiveName} from './archiveName';

type Case = {why: string; raw: string; normalized: string | null; repeat?: number};

/**
 * The name rule, run against the corpus the plane runs too.
 *
 * The plane cannot import TypeScript and this cannot import Python, so the two rules are held
 * together by one list of raw names and what each must become. Constants alone would miss the
 * likelier drift — a `.trim()` agrees with every constant and strips a no-break space the plane
 * keeps.
 */
const cases = (JSON.parse(corpusText) as {cases: Case[]}).cases.map((entry) => ({
  ...entry,
  raw: entry.raw.repeat(entry.repeat ?? 1),
  normalized: entry.normalized === null ? null : entry.normalized.repeat(entry.repeat ?? 1)
}));

describe('the archive name rule', () => {
  it.each(cases)('$why', ({raw, normalized}) => {
    const outcome = archiveNameRefusal(raw) === null ? normalizeArchiveName(raw) : null;

    expect(outcome).toBe(normalized);
  });

  it('reads the corpus, rather than passing over an empty one', () => {
    expect(cases.length).toBeGreaterThan(20);
    expect(cases.some((entry) => entry.normalized === null)).toBe(true);
    expect(cases.some((entry) => entry.normalized === '')).toBe(true);
  });
});
