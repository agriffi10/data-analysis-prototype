import {describe, expect, it} from 'vitest';
import {patternOf} from '../../../test/pageSelection';
import {AREAS, areaOf, routerFor, type AreaRecord} from './index';

/**
 * The area records and the App Router's pages must agree, because each half is read without the
 * other: the seam sends a navigation to Next's router by the record, and Next renders the page the
 * file system has. A record saying `'app'` with no page sends the push to the optional catch-all,
 * which matches the path and renders the 404, since the table no longer builds it; a page under
 * `(signed-in)/` that no record claims renders outside the sign-in gate, since the chrome treats a
 * path no record claims as public.
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
  for (const record of records.filter((candidate) => candidate.router === 'app')) {
    for (const pattern of record.paths) {
      if (!served.has(pattern))
        findings.push(`${record.area} says 'app' but ${pattern} has no page under (signed-in)/`);
    }
  }
  for (const [pattern, file] of served) {
    const record = records.find((candidate) => candidate.paths.includes(pattern));
    if (!record) findings.push(`${file} serves ${pattern}, which no area record claims`);
    else if (record.router === 'catch-all')
      findings.push(`${file} serves ${pattern}, but ${record.area} says 'catch-all'`);
  }
  return findings;
}

const flipped = (area: AreaRecord['area']) =>
  AREAS.map((record) => (record.area === area ? {...record, router: 'app' as const} : record));

describe('the records and the pages', () => {
  it('agree on the tree as it stands', () => {
    expect(PAGE_FILES).toContain('[[...slug]]/page.tsx');
    expect(recordPageFindings(AREAS, PAGE_FILES)).toEqual([]);
  });

  it('agree once a move adds its pages and flips its record', () => {
    const pages = [
      ...PAGE_FILES,
      '(signed-in)/data-quality/page.tsx',
      '(signed-in)/data-quality/[space]/[requestId]/page.tsx'
    ];
    expect(recordPageFindings(flipped('data-quality'), pages)).toEqual([]);
  });

  it('find a record saying app with a path that has no page', () => {
    const pages = [...PAGE_FILES, '(signed-in)/data-quality/page.tsx'];
    expect(recordPageFindings(flipped('data-quality'), pages)).toEqual([
      "data-quality says 'app' but /data-quality/:space/:requestId has no page under (signed-in)/"
    ]);
  });

  it('find a page whose record says catch-all', () => {
    expect(recordPageFindings(AREAS, [...PAGE_FILES, '(signed-in)/files/page.tsx'])).toEqual([
      "(signed-in)/files/page.tsx serves /files, but files says 'catch-all'"
    ]);
  });

  it('find a page whose path no record claims', () => {
    expect(recordPageFindings(AREAS, [...PAGE_FILES, '(signed-in)/reports/page.tsx'])).toEqual([
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
    expect(routerFor('/nope')).toBe('catch-all');
  });
});
