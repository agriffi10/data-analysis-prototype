import {afterEach, describe, expect, it, vi} from 'vitest';
import {triggerBrowserDownload} from './fileBrowser.download';
import {formatSize} from './fileBrowser.format';
import {
  buildBreadcrumbs,
  fileExtension,
  fileParent,
  folderParts,
  isAtRoot,
  lastSegment,
  leafName,
  parentPrefix
} from './fileBrowser.paths';
import {
  HIDDEN_BROWSER_FOLDERS,
  PICKER_LOCKED_FOLDERS,
  UNDELETABLE_ROOT_FOLDERS,
  isRootFolderNamed,
  isUndeletableRootFolder
} from './protectedFolders';
import {createElement} from 'react';
import type {ReactNode} from 'react';
import {act, renderHook} from '@testing-library/react';
import {MemoryRouter} from 'react-router';
import {useFileSpace} from './useFileSpace';
import type {Connection} from '../connections/connection.types';

// ─── from fileBrowser.download.test.ts ───
describe('fileBrowser.download', () => {
  afterEach(() => vi.restoreAllMocks());

  describe('triggerBrowserDownload', () => {
    it('creates a rel=noopener anchor, clicks it, and cleans it up', () => {
      const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
      triggerBrowserDownload('https://signed.example/report.csv?x=1');
      expect(click).toHaveBeenCalledOnce();
      // The anchor is removed after the click — nothing lingers in the DOM.
      expect(document.querySelector('a[href="https://signed.example/report.csv?x=1"]')).toBeNull();
    });
  });
});

// ─── from fileBrowser.format.test.ts ───
describe('fileBrowser.format', () => {
  describe('formatSize — the SPEC-155 FR-007 ceiling', () => {
    it('formats across the byte boundaries', () => {
      expect(formatSize(0)).toBe('0 B');
      expect(formatSize(512)).toBe('512 B');
      expect(formatSize(1024)).toBe('1.0 KB');
      expect(formatSize(1_572_864)).toBe('1.5 MB');
      expect(formatSize(1_610_612_736)).toBe('1.5 GB');
    });
  });

  describe('formatSize reaches TB (SPEC-155 FR-007)', () => {
    it('renders a multi-terabyte object as TB, not thousands of GB', () => {
      // It used to stop at GB, so this read "3072.0 GB" here and "3.0 TB" in the query
      // status bar. S3 allows objects up to 5 TB, so the ceiling was reachable.
      expect(formatSize(3 * 1_099_511_627_776)).toBe('3.0 TB');
      expect(formatSize(1_099_511_627_776)).toBe('1.0 TB');
    });

    it('still shows GB just below the boundary', () => {
      expect(formatSize(1_099_511_627_775)).toBe('1024.0 GB');
    });
  });
});

// ─── from fileBrowser.paths.test.ts ───
describe('fileBrowser.paths', () => {
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
      expect(fileExtension('report.pdf.')).toBe('File'); // trailing dot → no ext
    });

    it('chips every compression suffix as ZIP rather than a bare GZ', () => {
      // The codec is not the answer the user acts on — "compressed" is — so they
      // deliberately collapse onto one label rather than reading GZIP vs ZSTD.
      expect(fileExtension('backup.tar.gz')).toBe('ZIP');
      expect(fileExtension('backup.TGZ')).toBe('ZIP');
      expect(fileExtension('logs.bz2')).toBe('ZIP');
      expect(fileExtension('logs.zst')).toBe('ZIP');
      expect(fileExtension('logs.xz')).toBe('ZIP');
      expect(fileExtension('bundle.7z')).toBe('ZIP');
      expect(fileExtension('archive.zip')).toBe('ZIP');
      expect(fileExtension('backup.tar.gz', {maxLen: 4})).toBe('ZIP'); // survives the upload-list cap
      expect(fileExtension('backup.tar')).toBe('TAR'); // an uncompressed archive is untouched
      expect(fileExtension('report.pdf')).toBe('PDF'); // unmapped extensions are untouched
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
});

// ─── from protectedFolders.test.ts ───
describe('protectedFolders', () => {
  describe('protectedFolders', () => {
    it('hides user_settings/ from the browser; locks athenaresults/ + user_settings/ from the picker', () => {
      expect(HIDDEN_BROWSER_FOLDERS).toContain('user_settings');
      expect(HIDDEN_BROWSER_FOLDERS).not.toContain('athenaresults');
      expect(PICKER_LOCKED_FOLDERS).toEqual(expect.arrayContaining(['athenaresults', 'user_settings']));
    });

    it('hides _data-quality-reports/ from BOTH the browser and the picker (SPEC-113 FR-004)', () => {
      // Both lists, not one: hidden-but-pasteable would be a folder the user can't
      // see and can still drop files into. Nothing else hides it — the leading `_`
      // is a Lambda-side convention the SPA never learned.
      expect(HIDDEN_BROWSER_FOLDERS).toContain('_data-quality-reports');
      expect(PICKER_LOCKED_FOLDERS).toContain('_data-quality-reports');
      expect(isRootFolderNamed('alice/_data-quality-reports/', 'alice/', HIDDEN_BROWSER_FOLDERS)).toBe(true);
      // Shared spaces keep their reports at the space root, so the same match holds there.
      expect(isRootFolderNamed('team-data/_data-quality-reports/', 'team-data/', HIDDEN_BROWSER_FOLDERS)).toBe(true);
    });

    it('matches a named folder only at the user root', () => {
      expect(isRootFolderNamed('alice/user_settings/', 'alice/', HIDDEN_BROWSER_FOLDERS)).toBe(true);
      // A nested folder that merely shares the name is a normal user folder.
      expect(isRootFolderNamed('alice/docs/user_settings/', 'alice/', HIDDEN_BROWSER_FOLDERS)).toBe(false);
      // Unrelated folders are untouched.
      expect(isRootFolderNamed('alice/photos/', 'alice/', HIDDEN_BROWSER_FOLDERS)).toBe(false);
    });

    // SPEC-150 FR-007. A FOURTH question — "may the user DESTROY it?" — deliberately
    // not a union of the other lists: athenaresults/ stays visible and browsable.
    describe('isUndeletableRootFolder', () => {
      it('covers athenaresults/ without changing what the browser shows', () => {
        expect(UNDELETABLE_ROOT_FOLDERS).toEqual(['athenaresults']);
        expect(HIDDEN_BROWSER_FOLDERS).not.toContain('athenaresults');
      });

      it('matches at a space root, personal or shared', () => {
        expect(isUndeletableRootFolder('alice/athenaresults/', 'alice/')).toBe(true);
        expect(isUndeletableRootFolder('project_alpha/athenaresults/', 'project_alpha/')).toBe(true);
      });

      it('does not match a nested or merely prefixed folder', () => {
        expect(isUndeletableRootFolder('alice/reports/athenaresults/', 'alice/')).toBe(false);
        expect(isUndeletableRootFolder('alice/athenaresults_old/', 'alice/')).toBe(false);
        expect(isUndeletableRootFolder('alice/photos/', 'alice/')).toBe(false);
      });
    });
  });
});

// ─── from useFileSpace.test.ts ───
describe('useFileSpace', () => {
  const personal: Connection = {id: 'personal', label: 'alice', database: 'alice', kind: 'personal'};
  const marketing: Connection = {
    id: 'marketing_data',
    label: 'marketing_data',
    database: 'marketing_data',
    kind: 'shared',
    status: 'active',
    role: 'member'
  };
  const provisioning: Connection = {
    id: 'sales_2026',
    label: 'sales_2026',
    database: 'sales_2026',
    kind: 'shared',
    status: 'provisioning',
    role: 'owner'
  };

  const ALL = [personal, marketing, provisioning];

  function setup(path: string, overrides: Partial<Parameters<typeof useFileSpace>[0]> = {}) {
    const wrapper = ({children}: {children: ReactNode}) =>
      createElement(MemoryRouter, {initialEntries: [path]}, children);
    return renderHook(
      () =>
        useFileSpace({
          username: 'alice',
          connections: ALL,
          isLoading: false,
          userSpaceBucket: 'user-bucket',
          sharedSpaceBucket: 'shared-bucket',
          ...overrides
        }),
      {wrapper}
    );
  }

  describe('useFileSpace (SPEC-057)', () => {
    it('defaults to the personal space when no ?space= is present', () => {
      const {result} = setup('/files');
      expect(result.current.activeSpaceId).toBe('personal');
      expect(result.current.space).toEqual({
        id: 'personal',
        bucket: 'user-bucket',
        rootPrefix: 'alice/',
        kind: 'personal',
        label: 'alice'
      });
      expect(result.current.fellBack).toBe(false);
    });

    it('targets a usable shared space from ?space=', () => {
      const {result} = setup('/files?space=marketing_data');
      expect(result.current.activeSpaceId).toBe('marketing_data');
      expect(result.current.space).toEqual({
        id: 'marketing_data',
        bucket: 'shared-bucket',
        rootPrefix: 'marketing_data/',
        kind: 'shared',
        label: 'marketing_data'
      });
      expect(result.current.fellBack).toBe(false);
    });

    it('falls back to personal with fellBack for an unknown ?space=', () => {
      const {result} = setup('/files?space=ghost');
      expect(result.current.space?.kind).toBe('personal');
      expect(result.current.fellBack).toBe(true);
    });

    it('falls back to personal for a not-yet-usable (provisioning) ?space=', () => {
      const {result} = setup('/files?space=sales_2026');
      expect(result.current.space?.kind).toBe('personal');
      expect(result.current.fellBack).toBe(true);
    });

    it('suppresses the fellBack notice while connections are still loading', () => {
      const {result} = setup('/files?space=ghost', {isLoading: true});
      expect(result.current.space?.kind).toBe('personal');
      expect(result.current.fellBack).toBe(false);
    });

    it('selectSpace switches the active space', () => {
      const {result} = setup('/files');
      act(() => result.current.selectSpace('marketing_data'));
      expect(result.current.activeSpaceId).toBe('marketing_data');
      expect(result.current.space?.bucket).toBe('shared-bucket');
    });

    it('selecting personal clears the ?space= param', () => {
      const {result} = setup('/files?space=marketing_data');
      expect(result.current.activeSpaceId).toBe('marketing_data');
      act(() => result.current.selectSpace('personal'));
      expect(result.current.activeSpaceId).toBe('personal');
      expect(result.current.fellBack).toBe(false);
    });

    it('dismissFellBack clears the stale space and the notice', () => {
      const {result} = setup('/files?space=ghost');
      expect(result.current.fellBack).toBe(true);
      act(() => result.current.dismissFellBack());
      expect(result.current.fellBack).toBe(false);
      expect(result.current.space?.kind).toBe('personal');
    });

    it('returns a null space when there is no username (dev/no-auth)', () => {
      const {result} = setup('/files', {username: null});
      expect(result.current.space).toBeNull();
    });

    it('returns a null space when the shared bucket is unconfigured', () => {
      const {result} = setup('/files?space=marketing_data', {sharedSpaceBucket: undefined});
      expect(result.current.space).toBeNull();
    });
  });
});
