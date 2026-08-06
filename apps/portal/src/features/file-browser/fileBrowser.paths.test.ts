import {describe, it, expect} from 'vitest';
import {
  leafName,
  fileParent,
  folderParts,
  lastSegment,
  fileExtension,
  isAtRoot,
  parentPrefix,
  buildBreadcrumbs
} from './fileBrowser.paths';

describe('fileBrowser.paths', () => {
  it('leafName returns the last segment of a file key', () => {
    expect(leafName('a/b/c.txt')).toBe('c.txt');
    expect(leafName('c.txt')).toBe('c.txt');
  });

  it('fileParent returns the parent prefix of a file key', () => {
    expect(fileParent('a/b/c.txt')).toBe('a/b/');
    expect(fileParent('c.txt')).toBe('');
  });

  it('folderParts splits a folder prefix into parent + leaf', () => {
    expect(folderParts('a/b/photos/')).toEqual({parent: 'a/b/', leaf: 'photos'});
    expect(folderParts('photos/')).toEqual({parent: '', leaf: 'photos'});
  });

  it('lastSegment tolerates a trailing slash (files and folders)', () => {
    expect(lastSegment('a/b/photos/')).toBe('photos');
    expect(lastSegment('a/b/c.txt')).toBe('c.txt');
  });

  it('fileExtension uppercases the extension with a fallback + optional cap', () => {
    expect(fileExtension('report.pdf')).toBe('PDF');
    expect(fileExtension('noext')).toBe('File');
    expect(fileExtension('noext', {fallback: 'FILE'})).toBe('FILE');
    expect(fileExtension('archive.tarball', {maxLen: 4})).toBe('TARB');
    expect(fileExtension('.gitignore')).toBe('File'); // leading dot → no ext
  });

  it('isAtRoot recognizes the space root (clamped and unclamped)', () => {
    expect(isAtRoot('alice/', 'alice/')).toBe(true);
    expect(isAtRoot('alice/docs/', 'alice/')).toBe(false);
    expect(isAtRoot('', '')).toBe(true); // unclamped (dev-unauth)
    expect(isAtRoot('sub/', '')).toBe(false);
  });

  it('parentPrefix drops the last segment and clamps to the root', () => {
    expect(parentPrefix('alice/docs/reports/', 'alice/')).toBe('alice/docs/');
    // One level below root → exactly the root.
    expect(parentPrefix('alice/docs/', 'alice/')).toBe('alice/');
    // Never steps above the root.
    expect(parentPrefix('alice/', 'alice/')).toBe('alice/');
    // Unclamped: up from a top-level folder → empty (root).
    expect(parentPrefix('docs/', '')).toBe('');
    expect(parentPrefix('docs/sub/', '')).toBe('docs/');
  });
});

describe('the navigation clamp is one implementation (SPEC-155 FR-006)', () => {
  it('never climbs above the space root, by ancestry and not merely by length', () => {
    // The picker's deleted copy clamped with `parent.length < rootPrefix.length`, which
    // passes for any sibling prefix that happens to be as long as the root: from
    // `alicia/x/` it would have returned `alicia/`, a DIFFERENT user's space, because
    // the string is the same length as `alice/`. Ancestry is the test, not length.
    expect(parentPrefix('alicia/x/', 'alice/')).toBe('alice/');
    expect(parentPrefix('alice/docs/reports/', 'alice/')).toBe('alice/docs/');
    expect(parentPrefix('alice/docs/', 'alice/')).toBe('alice/');
    expect(parentPrefix('alice/', 'alice/')).toBe('alice/');
  });

  it('agrees with isAtRoot about where the floor is', () => {
    // The `..` row is hidden exactly where climbing would be a no-op, in both the
    // browser and the picker — they call the same pair now.
    const root = 'team-data/';
    expect(isAtRoot(root, root)).toBe(true);
    expect(parentPrefix(root, root)).toBe(root);
    expect(isAtRoot('team-data/q1/', root)).toBe(false);
    expect(parentPrefix('team-data/q1/', root)).toBe(root);
  });
});

describe('buildBreadcrumbs', () => {
  it('clamps to the space root and labels it, never showing the raw root segment', () => {
    const crumbs = buildBreadcrumbs('alice/docs/reports/', 'alice/', 'My Files');
    expect(crumbs).toEqual([
      {label: 'My Files', prefix: 'alice/'},
      {label: 'docs', prefix: 'alice/docs/'},
      {label: 'reports', prefix: 'alice/docs/reports/'}
    ]);
  });

  it('is just the root crumb at the root', () => {
    expect(buildBreadcrumbs('alice/', 'alice/', 'My Files')).toEqual([{label: 'My Files', prefix: 'alice/'}]);
  });

  it('falls back to the root prefix\u2019s last segment when no label is given', () => {
    expect(buildBreadcrumbs('team-data/q1/', 'team-data/')[0]).toEqual({label: 'team-data', prefix: 'team-data/'});
  });

  it('is Home-rooted and unclamped when there is no space root (the dev-unauth path)', () => {
    expect(buildBreadcrumbs('docs/2026/', '')).toEqual([
      {label: 'Home', prefix: undefined},
      {label: 'docs', prefix: 'docs/'},
      {label: '2026', prefix: 'docs/2026/'}
    ]);
    expect(buildBreadcrumbs(undefined, '')).toEqual([{label: 'Home', prefix: undefined}]);
  });
});
