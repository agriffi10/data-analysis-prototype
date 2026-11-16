import {describe, expect, it} from 'vitest';
import {patternOf} from '../../../test/pageSelection';
import {AREAS, areaOf, type AreaRecord} from './index';

/**
 * The area records and the App Router's signed-in pages must agree, because each half is read
 * without the other: the chrome decides by the records whether a path is signed in, and Next renders
 * the page the file system has. A record path with no page renders the not-found page inside the
 * shell; a page under `(signed-in)/` that no record claims renders outside the sign-in gate, since
 * the chrome treats a path no record claims as public.
 */

/** Every page file on disk, by its path under `src/app/`. Globbed whole: brackets and parentheses are glob syntax. */
const PAGE_FILES = Object.keys(import.meta.glob('../../../app/**/page.tsx')).map((file) =>
  file.slice('../../../app/'.length)
);

/**
 * Where the records and the signed-in pages disagree.
 *
 * @param records - The area records.
 * @param pageFiles - Every page file, by its path under `src/app/`.
 * @returns A finding per disagreement, naming the area and the path.
 */
function recordPageFindings(records: readonly AreaRecord[], pageFiles: readonly string[]): string[] {
  const served = new Map<string, string>();
  for (const file of pageFiles.filter((page) => page.startsWith('(signed-in)/'))) {
    const pattern = patternOf(file);
    if (pattern) served.set(pattern, file);
  }
  const findings: string[] = [];
  for (const record of records) {
    for (const pattern of record.paths) {
      if (!served.has(pattern)) findings.push(`${record.area} claims ${pattern}, which has no page under (signed-in)/`);
    }
  }
  for (const [pattern, file] of served) {
    if (!records.some((record) => record.paths.includes(pattern)))
      findings.push(`${file} serves ${pattern}, which no area record claims`);
  }
  return findings;
}

/** The guard's own cases run on a fixed tree, so a change to the real one never moves what they plant. */
const FIXTURE_RECORDS: readonly AreaRecord[] = [
  {area: 'files', paths: ['/files']},
  {area: 'data-quality', paths: ['/data-quality', '/data-quality/:space/:requestId']}
];
// The public pages outside the group, which no record claims and none should: the guard reads only
// `(signed-in)/`, or it would call the landing page an unclaimed area.
const FIXTURE_PAGES: readonly string[] = [
  'page.tsx',
  'about/page.tsx',
  '(signed-in)/files/page.tsx',
  '(signed-in)/data-quality/page.tsx',
  '(signed-in)/data-quality/[space]/[requestId]/page.tsx'
];

describe('the records and the pages', () => {
  it('agree on the tree as it stands', () => {
    expect(PAGE_FILES).toContain('page.tsx');
    expect(PAGE_FILES).toContain('(signed-in)/files/page.tsx');
    expect(recordPageFindings(AREAS, PAGE_FILES)).toEqual([]);
  });

  it('agree on the fixture', () => {
    expect(recordPageFindings(FIXTURE_RECORDS, FIXTURE_PAGES)).toEqual([]);
  });

  it('find a record path that has no page', () => {
    const pages = FIXTURE_PAGES.filter((page) => !page.includes('[requestId]'));
    expect(recordPageFindings(FIXTURE_RECORDS, pages)).toEqual([
      'data-quality claims /data-quality/:space/:requestId, which has no page under (signed-in)/'
    ]);
  });

  it('find a page whose path no record claims', () => {
    expect(recordPageFindings(FIXTURE_RECORDS, [...FIXTURE_PAGES, '(signed-in)/reports/page.tsx'])).toEqual([
      '(signed-in)/reports/page.tsx serves /reports, which no area record claims'
    ]);
  });
});

describe('the records', () => {
  it('call a path public when no area claims it, matched whole and case-sensitively', () => {
    expect(areaOf('/')).toBeNull();
    expect(areaOf('/nope')).toBeNull();
    expect(areaOf('/Files')).toBeNull();
    expect(areaOf('/files/extra')).toBeNull();
    expect(areaOf('/data-quality/alice/req-1')?.area).toBe('data-quality');
    expect(areaOf('/fil%65s')?.area).toBe('files');
  });
});
