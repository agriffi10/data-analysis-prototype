import {afterEach, describe, expect, it, vi} from 'vitest';
import {triggerBrowserDownload} from './fileBrowser.download';
import {formatSize} from './fileBrowser.format';
import {buildBreadcrumbs, fileExtension, folderParts, isAtRoot, leafName, parentPrefix} from './fileBrowser.paths';
import {
  HIDDEN_BROWSER_FOLDERS,
  PICKER_LOCKED_FOLDERS,
  UNDELETABLE_ROOT_FOLDERS,
  undeletableRootFolderRefusal,
  isRootFolderNamed
} from './protectedFolders';
import {
  PREFIX_MARKER_BODY,
  PREFIX_MARKER_FILENAME,
  SAVED_QUERIES_FOLDER,
  SAVED_QUERIES_MARKER_BODY,
  isMarkerName
} from './fileBrowser.constants';
// Read through Vite's own `?raw` / `import.meta.glob` rather than `node:fs`: the app
import {createElement} from 'react';
import type {ReactNode} from 'react';
import {act, renderHook} from '@testing-library/react';
import {MemoryRouter, useNavigate} from 'react-router';
import {useFileSpace} from './useFileSpace';
import type {Connection} from '../connections/connection.types';
import {QueryClient} from '@tanstack/react-query';
import {fileBrowserKeys} from './fileBrowserKeys';
import {invalidateListing} from './invalidateListing';

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

    it('folderParts splits a folder prefix into parent + leaf', () => {
      expect(folderParts('a/b/photos/')).toEqual({parent: 'a/b/', leaf: 'photos'});
      expect(folderParts('photos/')).toEqual({parent: '', leaf: 'photos'});
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
  describe('the three lists, member for member', () => {
    // Spelled out as literals on purpose. Every other assertion in this file is a `toContain`, which
    // passes under a widening; these compare the whole list, so re-pointing a member to a shared
    // name cannot add, drop or reorder one unnoticed.
    it('hides exactly these four', () => {
      expect(HIDDEN_BROWSER_FOLDERS).toEqual(['user_settings', '_data-quality-reports', '_directory', '_config']);
    });

    it('locks exactly these eight out of the picker', () => {
      expect(PICKER_LOCKED_FOLDERS).toEqual([
        'athenaresults',
        'user_settings',
        '_data-quality-reports',
        '_directory',
        '_config',
        'shared_tables',
        'archive',
        'system_settings'
      ]);
    });

    it('refuses to destroy exactly these four', () => {
      expect(UNDELETABLE_ROOT_FOLDERS).toEqual(['athenaresults', 'saved_queries', 'archive', 'system_settings']);
    });
  });

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

    it('hides _config/ from BOTH lists, in parity with _directory/ (SPEC-162)', () => {
      // Both are bucket-ROOT folders, so these per-prefix lists cannot actually reach
      // either — the portal role's prefix-conditioned ListBucket is what really keeps them
      // out of the browser. They are listed for parity, because the lists have already
      // drifted apart from each other once and adding to both is cheaper than reasoning
      // about which one matters.
      expect(HIDDEN_BROWSER_FOLDERS).toContain('_config');
      expect(PICKER_LOCKED_FOLDERS).toContain('_config');
      expect(HIDDEN_BROWSER_FOLDERS).toContain('_directory');
      expect(PICKER_LOCKED_FOLDERS).toContain('_directory');
    });

    // SPEC-150 FR-007. A FOURTH question — "may the user DESTROY it?" — deliberately
    // not a union of the other lists: athenaresults/ stays visible and browsable.
    describe('the undeletable-root list', () => {
      it('covers athenaresults/ without changing what the browser shows', () => {
        expect(UNDELETABLE_ROOT_FOLDERS).toContain('athenaresults');
        expect(HIDDEN_BROWSER_FOLDERS).not.toContain('athenaresults');
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

  type Params = Parameters<typeof useFileSpace>[0];

  // Later props arrive through `rerender`, the way a settled read of the list reaches the hook. `navigate`
  // rides along so a test can go Back, which no hook result offers.
  function setup(path: string, overrides: Partial<Params> = {}) {
    const wrapper = ({children}: {children: ReactNode}) =>
      createElement(MemoryRouter, {initialEntries: [path]}, children);
    const rereadList = vi.fn().mockResolvedValue(undefined);
    const rendered = renderHook(
      (props: Partial<Params>) => ({
        ...useFileSpace({
          username: 'alice',
          connections: ALL,
          listReadsSettled: 0,
          rereadList,
          userSpaceBucket: 'user-bucket',
          sharedSpaceBucket: 'shared-bucket',
          ...overrides,
          ...props
        }),
        navigate: useNavigate()
      }),
      {wrapper, initialProps: {}}
    );
    return {...rendered, rereadList};
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

    // Deep links name the personal space explicitly; it must resolve, not read as a vanished space.
    it('resolves an explicit ?space=personal to the personal space without a fallback', () => {
      const {result} = setup('/files?space=personal');
      expect(result.current.space?.kind).toBe('personal');
      expect(result.current.fellBack).toBe(false);
    });

    it('falls back to personal for a not-yet-usable (provisioning) ?space=, on a read since the link', () => {
      const {result, rerender, rereadList} = setup('/files?space=sales_2026');
      expect(result.current.pending).toBe(true);
      expect(rereadList).toHaveBeenCalledOnce();

      rerender({listReadsSettled: 1});
      expect(result.current.space?.kind).toBe('personal');
      expect(result.current.fellBack).toBe(true);
    });

    it('asks again on Back into a space the list lacks, though a read settled after it was last followed', () => {
      // A POP is not a follow, but it re-arms on the value. Keyed on the navigation alone, Back onto a
      // space refused earlier would be refused again on whatever read settled in between, and that read
      // may predate the user joining it.
      const {result, rerender, rereadList} = setup('/files?space=sales_2026');
      rerender({listReadsSettled: 1});
      expect(result.current.fellBack).toBe(true);

      act(() => result.current.selectSpace('marketing_data'));
      rerender({listReadsSettled: 2});
      expect(rereadList).toHaveBeenCalledOnce();

      act(() => void result.current.navigate(-1));
      expect(result.current.pending).toBe(true);
      expect(result.current.fellBack).toBe(false);
      expect(rereadList).toHaveBeenCalledTimes(2);
    });

    it('asks again for a link followed while waiting, in the render where the awaited read settles', () => {
      // The count is read at render, as `useConnections` reads the query cache, so a read that settled
      // before React heard of it is counted by the navigation's own render. That render notes it as the
      // new link's start and the wait goes on — and with the re-read keyed on `pending` alone, which
      // never changed, nothing asked for the read that ends it.
      const reads = {settled: 0};
      const {result, rereadList} = setup('/files?space=sales_2026', {
        get listReadsSettled() {
          return reads.settled;
        }
      });
      expect(rereadList).toHaveBeenCalledOnce();

      act(() => {
        reads.settled = 1;
        void result.current.navigate('/files?space=sales_2026');
      });
      expect(result.current.pending).toBe(true);
      expect(rereadList).toHaveBeenCalledTimes(2);
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

    it('returns a null space when there is no username (dev/no-auth)', () => {
      const {result} = setup('/files', {username: null});
      expect(result.current.space).toBeNull();
    });
  });
});

// ─── from lib/support.test.ts, which had it via lib/queryClient ───
describe('invalidateListing', () => {
  it('invalidates exactly the listing key for the given bucket + prefix', async () => {
    const client = new QueryClient();
    const spy = vi.spyOn(client, 'invalidateQueries').mockResolvedValue();

    await invalidateListing(client, 'my-bucket', 'alice/');

    expect(spy).toHaveBeenCalledWith({
      queryKey: fileBrowserKeys.list('my-bucket', 'alice/')
    });
  });

  it('produces a key that matches the factory (single source of truth)', () => {
    expect(fileBrowserKeys.list('b', 'p/')).toEqual(['file-browser', 'list', 'b', 'p/']);
  });
});

// ─── SPEC-173: the saved-queries folder, its marker and its protections ───
describe('the saved_queries/ folder (SPEC-173)', () => {
  describe('the three lists stay three lists (FR-002)', () => {
    it('is undeletable ONLY — visible, pasteable, undestroyable', () => {
      // A later edit that "tidies" the lists into a union fails here. This folder's
      // answers are yes / yes / no, and the narrowness is the design: a folder the
      // user cannot treat as a folder is a folder they will fight.
      expect(UNDELETABLE_ROOT_FOLDERS).toContain(SAVED_QUERIES_FOLDER);
      expect(HIDDEN_BROWSER_FOLDERS).not.toContain(SAVED_QUERIES_FOLDER);
      expect(PICKER_LOCKED_FOLDERS).not.toContain(SAVED_QUERIES_FOLDER);
    });

    it('names saved queries in its refusal, and query results in theirs', () => {
      expect(undeletableRootFolderRefusal('alice/saved_queries/', 'alice/', 'delete')).toMatch(/saved queries/i);
      expect(undeletableRootFolderRefusal('alice/saved_queries/', 'alice/', 'move')).toMatch(/moved or renamed/i);
      expect(undeletableRootFolderRefusal('alice/system_settings/athenaresults/', 'alice/', 'delete')).toMatch(
        /query results/i
      );
      expect(undeletableRootFolderRefusal('alice/photos/', 'alice/', 'delete')).toBeNull();
      // The results folder moved, so the depth-one name is an ordinary folder — and `saved_queries`
      // did NOT move, which is why the row above still names it at the space root.
      expect(undeletableRootFolderRefusal('alice/athenaresults/', 'alice/', 'delete')).toBeNull();
    });
  });

  describe('the marker (FR-001/FR-003)', () => {
    it('reuses the marker FILENAME, because the IAM Deny keys on that exact basename', () => {
      expect(SAVED_QUERIES_FOLDER).toBe('saved_queries');
      expect(PREFIX_MARKER_FILENAME).toBe('DO_NOT_DELETE.txt');
    });

    it('has its own body text, which never claims to keep a PERSONAL space alive', () => {
      // PREFIX_MARKER_BODY says "your personal storage space", which is wrong in a
      // shared space and wrong about what this folder is.
      expect(SAVED_QUERIES_MARKER_BODY).not.toBe(PREFIX_MARKER_BODY);
      expect(SAVED_QUERIES_MARKER_BODY).not.toMatch(/personal/i);
      expect(SAVED_QUERIES_MARKER_BODY).toMatch(/saved queries/i);
    });

    it('matches a marker by BASENAME, at any depth, in either bucket', () => {
      expect(isMarkerName('alice/DO_NOT_DELETE.txt')).toBe(true);
      expect(isMarkerName('alice/saved_queries/DO_NOT_DELETE.txt')).toBe(true);
      expect(isMarkerName('project_alpha/saved_queries/DO_NOT_DELETE.txt')).toBe(true);
      expect(isMarkerName('DO_NOT_DELETE.txt')).toBe(true);
    });

    it('is exact and case-sensitive, as S3 keys are', () => {
      expect(isMarkerName('alice/DO_NOT_DELETE.txt.bak')).toBe(false);
      expect(isMarkerName('alice/notes/do_not_delete.txt')).toBe(false);
      expect(isMarkerName('alice/XDO_NOT_DELETE.txt')).toBe(false);
    });
  });
});
