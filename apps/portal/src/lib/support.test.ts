import {afterEach, describe, expect, it, vi} from 'vitest';
import {toUserMessage} from './errorMessages';
import {VITE_NAME, devFallbackValue, warnIfMisconfigured} from './env';
import {isPortalConfigured, missingRequiredConfig} from './runtimeConfig';
import {REQUIRED_CONFIG} from '../types/runtimeConfig.types';

// ─── the NotConfigured rule, now with no producer ───
describe('NotConfigured', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('still resolves to its own wording rather than the generic fallback', () => {
    // NO PRODUCER REMAINS. The eight enqueue paths that raised this each guarded a queue URL
    // read in the browser, and the browser no longer reads one — the queue URLs are the API
    // function's configuration, and an unset one is a fault it reports.
    //
    // The rule is kept rather than deleted because it is a passthrough rule, and the
    // disjointness guard in `apiContract.guard.test.ts` is written against the computed
    // passthrough set: removing it would move a code between two derived sets for no reason
    // beyond tidiness. If a future caller mints this code, it must still reach the user as its
    // own sentence rather than as "Something went wrong."
    const {message} = toUserMessage({code: 'NotConfigured', message: 'Table refresh is not configured'});

    expect(message).toBe('Table refresh is not configured');
    expect(message).not.toContain('Something went wrong');
  });
});

// ─── from env.test.ts ───
describe('env', () => {
  /**
   * The registry is only useful if it is COMPLETE, and nothing enforced that until
   * `VITE_ARCHIVE_QUEUE_URL` shipped read by `archive.service.ts`, wired into
   * `deploy-app.yml` and absent from this module — so an unset repository variable
   * made Archive and Restore silently do nothing, which is the exact failure
   * `warnIfMisconfigured` exists to name. A hand-kept list rots; this one is derived
   * from the source that reads the variables.
   */
  describe('the registry names every VITE_ variable the app reads', () => {
    const SOURCES = import.meta.glob('../**/*.{ts,tsx}', {
      query: '?raw',
      import: 'default',
      eager: true
    }) as Record<string, string>;

    it('lists every VITE_ name that appears outside a test file', () => {
      const registered: string[] = Object.values(VITE_NAME).filter((name) => name !== null);
      const known = new Set<string>(registered);
      const unregistered = new Map<string, string>();

      for (const [path, source] of Object.entries(SOURCES)) {
        if (path.includes('.test.') || path.includes('/test/')) continue;
        // The registry module itself — matched by exact path, not basename, so a
        // future `features/foo/env.ts` is scanned rather than silently exempt. Its
        // docstrings carry placeholder names (`import.meta.env.VITE_X`) that are not
        // variables, and its own reads go through the registry by construction.
        if (path === './env.ts') continue;
        for (const name of source.match(/VITE_[A-Z0-9_]+/g) ?? []) {
          if (!known.has(name)) unregistered.set(name, path);
        }
      }

      expect(Object.keys(SOURCES).length).toBeGreaterThan(0);
      expect([...unregistered.entries()]).toEqual([]);
    });
  });

  /** Set every required variable, so a test can then unset exactly the one it cares about. */
  function stubAllRequired(): void {
    for (const key of REQUIRED_CONFIG) vi.stubEnv(VITE_NAME[key] as string, `value-for-${key}`);
  }

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  describe('devFallbackValue', () => {
    it('reads at CALL time, so a stub set after import is seen', () => {
      vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'test-bucket');
      expect(devFallbackValue('userSpaceBucket')).toBe('test-bucket');
    });

    it('ACCEPTED: every key currently HAS a variable, so the null branch is unreachable', () => {
      // This used to assert the one key with no `VITE_` variable read as undefined. `apiBaseUrl`
      // gained one when it became required, and no key is null now — so the case the old test
      // named no longer exists, and it would have kept passing for a reason it disowns.
      //
      // Pinned rather than deleted: `devFallbackValue`'s null branch and `PortalEnvVar`'s
      // `Exclude<…, null>` both exist for a key without one, and a later key may reintroduce the
      // case. If this reddens, a key has gone back to having no fallback — REVISIT whether that is
      // right (a REQUIRED one must not, or the dev boot warning names nothing), do not delete it.
      const unpaired = Object.entries(VITE_NAME).filter(([, name]) => name === null);

      expect(unpaired).toEqual([]);
    });
  });

  describe('missingRequiredConfig', () => {
    it('names the key that is missing', () => {
      stubAllRequired();
      vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', '');
      expect(missingRequiredConfig()).toEqual(['userSpaceBucket']);
      expect(isPortalConfigured()).toBe(false);
    });

    it('does not require the keys with their own degraded path', () => {
      // The shared bucket degrades through "no shared spaces" — one feature, not the app.
      // The queue URLs and the Identity Pool used to be the other examples and are no longer
      // browser configuration at all.
      stubAllRequired();
      vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', '');
      expect(isPortalConfigured()).toBe(true);
    });
  });

  describe('warnIfMisconfigured', () => {
    it('names every missing variable in dev', () => {
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
      stubAllRequired();
      vi.stubEnv('VITE_AWS_REGION', '');
      vi.stubEnv('DEV', true);

      warnIfMisconfigured();

      expect(warn).toHaveBeenCalledOnce();
      expect(warn.mock.calls[0][0]).toContain('VITE_AWS_REGION');
    });

    it('says nothing when the portal is configured', () => {
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
      stubAllRequired();
      vi.stubEnv('DEV', true);

      warnIfMisconfigured();

      expect(warn).not.toHaveBeenCalled();
    });
  });
});
