import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cx} from './cx';
import {formatPageTitle} from './formatPageTitle';
import {parseS3Url} from './s3Url';
import {sharedSpaceBucket, spaceBuckets, userSettingsKey, userSpaceBucket} from './userSpace';
import {setReturnPath, setReturnPathIfAbsent, takeReturnPath} from './returnPath';
import {formatAbsoluteDate, formatBytes, formatCount, formatDurationMs, formatRelativeTime} from './format';
import {formatSize} from '../features/file-browser/fileBrowser.format';
import {renderHook} from '@testing-library/react';
import {useBreakpoint, useIsMobile} from './useBreakpoint';

// ─── from cx.test.ts ───
describe('cx', () => {
  describe('cx', () => {
    it('joins truthy strings with spaces', () => {
      expect(cx('a', 'b', 'c')).toBe('a b c');
    });

    it('filters out falsy values', () => {
      expect(cx('a', false, null, undefined, 'b')).toBe('a b');
    });

    it('returns an empty string for all-falsy input', () => {
      expect(cx(false, null, undefined)).toBe('');
    });
  });
});

// ─── from formatPageTitle.test.ts ───
describe('formatPageTitle', () => {
  describe('formatPageTitle', () => {
    it('appends the app name with an em-dash when a page is given', () => {
      expect(formatPageTitle('Files')).toBe('Files — Data Workspace');
      expect(formatPageTitle('Not Found')).toBe('Not Found — Data Workspace');
    });

    it('returns just the app name for empty or omitted page', () => {
      expect(formatPageTitle('')).toBe('Data Workspace');
      expect(formatPageTitle()).toBe('Data Workspace');
    });
  });
});

// ─── from s3Url.test.ts ───
describe('s3Url', () => {
  describe('parseS3Url', () => {
    it('splits an s3:// URL into bucket and key', () => {
      expect(parseS3Url('s3://user-bucket/alice/athenaresults/q-1.csv')).toEqual({
        bucket: 'user-bucket',
        key: 'alice/athenaresults/q-1.csv'
      });
    });

    it('keeps a trailing slash in the key — normalising is the caller`s job', () => {
      // `parseTableLocation` adds one; the Save-results flow must not have one added.
      expect(parseS3Url('s3://shared-space/salesteam/2026/q1/')).toEqual({
        bucket: 'shared-space',
        key: 'salesteam/2026/q1/'
      });
    });

    it('trims surrounding whitespace — a catalog LOCATION can carry it', () => {
      expect(parseS3Url('  s3://user-space/alice/sales/  ')).toEqual({
        bucket: 'user-space',
        key: 'alice/sales/'
      });
    });

    it.each([
      ['not-an-s3-url'],
      ['https://user-bucket.s3.amazonaws.com/alice/f.csv'],
      ['s3://bucket-only'],
      ['s3://bucket-only/'],
      ['s3://'],
      ['']
    ])('returns null for %s', (value) => {
      expect(parseS3Url(value)).toBeNull();
    });

    it('returns null for undefined rather than throwing', () => {
      expect(parseS3Url(undefined)).toBeNull();
    });
  });
});

// ─── from userSpace.test.ts ───
describe('userSpace', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  describe('the bucket getters', () => {
    it('read at CALL time, so a stub set after import is seen', () => {
      // The rule these getters exist to enforce: a module-level `import.meta.env` const
      // is captured before `vi.stubEnv` runs, and a test would then silently exercise
      // the deployed bucket names instead of its own.
      vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'test-user-space');
      vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'test-shared-space');

      expect(userSpaceBucket()).toBe('test-user-space');
      expect(sharedSpaceBucket()).toBe('test-shared-space');

      vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'a-different-bucket');
      expect(userSpaceBucket()).toBe('a-different-bucket');
    });
  });

  describe('spaceBuckets', () => {
    it('returns both buckets as a pair', () => {
      vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'test-user-space');
      vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'test-shared-space');

      expect(spaceBuckets()).toEqual({user: 'test-user-space', shared: 'test-shared-space'});
    });

    it('reports an unset bucket as undefined, so a caller can branch on absence', () => {
      // The shape the resolvers need: `undefined`, never the string "undefined" and never
      // the empty string an unset repository variable interpolates to.
      vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'test-user-space');
      vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', '');

      expect(spaceBuckets()).toEqual({user: 'test-user-space', shared: undefined});
    });
  });

  describe('userSettingsKey', () => {
    it('builds the protected per-user document path', () => {
      expect(userSettingsKey('alice', 'query-history.json')).toBe('alice/user_settings/query-history.json');
    });
  });
});

// ─── from returnPath.test.ts ───
describe('returnPath', () => {
  const KEY = 'portal.returnPath';

  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('returnPath', () => {
    it('stores a path with setReturnPath and reads it back once', () => {
      setReturnPath('/query');
      expect(sessionStorage.getItem(KEY)).toBe('/query');
      expect(takeReturnPath()).toBe('/query');
      // takeReturnPath clears — a second read is null.
      expect(takeReturnPath()).toBeNull();
      expect(sessionStorage.getItem(KEY)).toBeNull();
    });

    it('takeReturnPath returns null when nothing is stored', () => {
      expect(takeReturnPath()).toBeNull();
    });

    it('setReturnPathIfAbsent stores only when no path is present', () => {
      setReturnPathIfAbsent('/files');
      expect(sessionStorage.getItem(KEY)).toBe('/files');
    });

    it('setReturnPathIfAbsent does not clobber an already-stored path', () => {
      setReturnPath('/query/tab-1'); // a specific protected path captured by the gate
      setReturnPathIfAbsent('/files'); // default sign-in destination — must not win
      expect(sessionStorage.getItem(KEY)).toBe('/query/tab-1');
    });

    it('setReturnPath swallows a storage failure (private browsing)', () => {
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new Error('QuotaExceeded');
      });
      expect(() => setReturnPath('/query')).not.toThrow();
    });

    it('takeReturnPath returns null when storage access throws', () => {
      vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('SecurityError');
      });
      expect(takeReturnPath()).toBeNull();
    });
  });
});

// ─── from format.test.ts ───
describe('format', () => {
  const NOW = Date.parse('2026-03-10T12:00:00Z');
  const ago = (ms: number) => new Date(NOW - ms).toISOString();

  describe('formatBytes', () => {
    it('formats byte sizes with sensible units + precision', () => {
      expect(formatBytes(undefined)).toBe('—');
      expect(formatBytes(512)).toBe('512 B');
      expect(formatBytes(2048)).toBe('2.0 KB');
      expect(formatBytes(1_258_291)).toBe('1.2 MB');
      expect(formatBytes(53_687_091)).toBe('51 MB'); // ≥10 drops the decimal
    });

    // SPEC-155 FR-007 aligned the two formatters' unit ceiling; SPEC-176 FR-004 moved
    // `formatBytes` here, out of `features/query/`, so neither feature owns a formatter
    // the other needs. The ceiling is the thing that must survive the move: a 3 TB figure
    // reading "3072.0 GB" on one screen and "3.0 TB" on another is the bug it closed.
    it("shares the TB ceiling with the file browser's formatSize", () => {
      const threeTb = 3 * 1_099_511_627_776;
      expect(formatBytes(threeTb)).toBe('3.0 TB');
      expect(formatSize(threeTb)).toBe('3.0 TB');
    });
  });

  describe('formatCount', () => {
    it('adds thousands separators', () => {
      expect(formatCount(1384)).toBe('1,384');
      expect(formatCount(0)).toBe('0');
    });
  });

  describe('formatDurationMs', () => {
    it('shows milliseconds below a second and seconds above', () => {
      expect(formatDurationMs(800)).toBe('800 ms');
      expect(formatDurationMs(1234)).toBe('1.2s');
    });

    it('renders an em dash for undefined', () => {
      expect(formatDurationMs(undefined)).toBe('—');
    });
  });

  describe('formatAbsoluteDate', () => {
    it('renders the one short-date shape three call sites had written out', () => {
      expect(formatAbsoluteDate('2026-03-03T09:30:00Z')).toBe('Mar 3, 2026');
    });

    it('accepts a Date as well as an ISO string', () => {
      expect(formatAbsoluteDate(new Date('2026-03-03T09:30:00Z'))).toBe('Mar 3, 2026');
    });

    it('yields an empty string for an unparseable value rather than "Invalid Date"', () => {
      expect(formatAbsoluteDate('not a date')).toBe('');
      expect(formatAbsoluteDate(new Date('nope'))).toBe('');
    });
  });

  describe('formatRelativeTime', () => {
    it.each([
      [2_000, 'just now'],
      [30_000, '30 sec ago'],
      [10 * 60_000, '10 min ago'],
      [5 * 3_600_000, '5 hr ago'],
      [26 * 3_600_000, 'Yesterday'],
      [3 * 86_400_000, '3 days ago']
    ])('renders %d ms ago as %s', (elapsed, expected) => {
      expect(formatRelativeTime(ago(elapsed), NOW)).toBe(expected);
    });

    it('falls back to the shared absolute date beyond a week', () => {
      // The collapse of the third date formatter: this used to be locale-dependent
      // (`toLocaleDateString()` with no options) while its two siblings pinned en-US.
      expect(formatRelativeTime('2026-01-15T09:30:00Z', NOW)).toBe('Jan 15, 2026');
    });

    it('returns an empty string for an unparseable timestamp', () => {
      expect(formatRelativeTime('not a date', NOW)).toBe('');
    });
  });
});

// ─── from useBreakpoint.test.ts ───
describe('useBreakpoint', () => {
  function setWidth(w: number) {
    Object.defineProperty(window, 'innerWidth', {value: w, writable: true, configurable: true});
  }

  describe('useBreakpoint', () => {
    afterEach(() => setWidth(1024));

    it('reports mobile below the tablet threshold (<900px)', () => {
      setWidth(500);
      expect(renderHook(() => useBreakpoint()).result.current).toEqual({
        isMobile: true,
        isTablet: false,
        isDesktop: false
      });
      expect(renderHook(() => useIsMobile()).result.current).toBe(true);
    });

    it('reports tablet in the [900, 1300) band', () => {
      setWidth(1000);
      expect(renderHook(() => useBreakpoint()).result.current).toEqual({
        isMobile: false,
        isTablet: true,
        isDesktop: false
      });
      expect(renderHook(() => useIsMobile()).result.current).toBe(false);
    });

    it('reports desktop at or above 1300px', () => {
      setWidth(1400);
      expect(renderHook(() => useBreakpoint()).result.current).toEqual({
        isMobile: false,
        isTablet: false,
        isDesktop: true
      });
    });

    it('treats the exact thresholds as inclusive lower bounds', () => {
      setWidth(900);
      expect(renderHook(() => useBreakpoint()).result.current.isTablet).toBe(true);
      setWidth(1300);
      expect(renderHook(() => useBreakpoint()).result.current.isDesktop).toBe(true);
    });
  });
});
