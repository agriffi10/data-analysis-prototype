import {afterEach, describe, expect, it, vi} from 'vitest';
import {isExpiryError, withCredentialRetry} from './credentialRetry';
import {toUserMessage} from './errorMessages';
import {VITE_NAME, devFallbackValue, warnIfMisconfigured} from './env';
import {isPortalConfigured, missingRequiredConfig} from './runtimeConfig';
import {REQUIRED_CONFIG} from '../types/runtimeConfig.types';
import type {ServiceResult} from '../types/service.types';
import protectedLayoutSource from '../components/ProtectedLayout.tsx?raw';
import fileBrowserServiceSource from '../features/file-browser/fileBrowser.service.ts?raw';
import filesPageSource from '../routes/FilesPage.tsx?raw';

// ─── from credentialRetry.test.ts ───
describe('credentialRetry', () => {
  describe('isExpiryError', () => {
    it('is false for unknown / undefined codes', () => {
      expect(isExpiryError('AccessDenied')).toBe(false);
      expect(isExpiryError(undefined)).toBe(false);
    });
  });

  describe('withCredentialRetry', () => {
    const okClient = (id: string): ServiceResult<{id: string}> => ({
      success: true,
      data: {id}
    });

    it('does not retry on a non-expiry error', async () => {
      const getClient = vi.fn(async () => okClient('first'));
      const op = vi.fn(async () => ({
        success: false as const,
        error: {message: 'denied', code: 'AccessDenied'}
      }));

      const result = await withCredentialRetry(getClient, op);

      expect(result.success).toBe(false);
      expect(getClient).toHaveBeenCalledTimes(1);
      expect(op).toHaveBeenCalledTimes(1);
    });

    it('refreshes the client and retries once on a credential-expiry error', async () => {
      const getClient = vi
        .fn<(forceRefresh?: boolean) => Promise<ServiceResult<{id: string}>>>()
        .mockResolvedValueOnce(okClient('first'))
        .mockResolvedValueOnce(okClient('refreshed'));
      const op = vi
        .fn<(c: {id: string}) => Promise<ServiceResult<string>>>()
        .mockResolvedValueOnce({
          success: false,
          error: {message: 'expired', code: 'ExpiredToken'}
        })
        .mockResolvedValueOnce({success: true, data: 'done-after-refresh'});

      const result = await withCredentialRetry(getClient, op);

      expect(result).toEqual({success: true, data: 'done-after-refresh'});
      expect(getClient).toHaveBeenCalledTimes(2);
      expect(getClient).toHaveBeenNthCalledWith(2, true); // forced refresh
      expect(op).toHaveBeenCalledTimes(2);
      expect(op).toHaveBeenNthCalledWith(2, {id: 'refreshed'});
    });

    it('surfaces a client-acquisition failure without running the op', async () => {
      const getClient = vi.fn(async () => ({
        success: false as const,
        error: {message: 'no creds'}
      }));
      const op = vi.fn();

      const result = await withCredentialRetry(getClient, op);

      expect(result.success).toBe(false);
      expect(op).not.toHaveBeenCalled();
    });
  });
});

// ─── from devUnauthBypass.test.ts ───
describe('devUnauthBypass', () => {
  /**
   * The dev-only unauthenticated bypass, and the half of it that matters (SPEC-154 FR-006).
   *
   * `VITE_S3_DEV_UNAUTH=true` lets a developer browse a public test bucket without signing in.
   * Three modules read it, each at MODULE scope, each guarded by `import.meta.env.DEV`:
   *
   *   ProtectedLayout.tsx      — lets protected routes render with no session
   *   fileBrowser.service.ts   — drops SigV4 signing
   *   FilesPage.tsx            — renders the browser for a signed-out visitor
   *
   * The `DEV &&` half is the ONLY thing between a stray `VITE_S3_DEV_UNAUTH=true` in a
   * production build environment and a portal that renders protected routes to anyone. It had
   * ZERO test coverage — the flag was never stubbed anywhere in the suite — so nothing said the
   * guard was still there, and a refactor that dropped it would have looked like a tidy-up.
   *
   * TWO LAYERS, because neither alone is enough.
   *
   * The BEHAVIOURAL test is the one that matters, and it is the security claim stated directly:
   * with `DEV` false and the flag set to `'true'`, the file-browser service must still sign its
   * requests. `import.meta.env.DEV` is a live property under Vitest (`vite.config.ts` defines no
   * `DEV`), so `vi.stubEnv` + `vi.resetModules()` + a dynamic import genuinely re-evaluates the
   * module-scope const — the seam an earlier draft of this file wrongly claimed did not exist.
   *
   * The SOURCE tests cover what the behavioural one cannot reach: `ProtectedLayout` and
   * `FilesPage` compute the same expression, and a render-level test of either would prove the
   * guard held for that component only. Asserting that all three still conjoin
   * `import.meta.env.DEV`, and that each reads the flag exactly once, is what a reviewer checks
   * by eye — weaker than behaviour, and strictly stronger than the nothing that was here before.
   *
   * Sources come in through Vite's `?raw`, so a moved or renamed module is a build error here
   * rather than a check that quietly stops looking at anything.
   */

  const BYPASS_SITES = [
    ['ProtectedLayout.tsx', protectedLayoutSource],
    ['fileBrowser.service.ts', fileBrowserServiceSource],
    ['FilesPage.tsx', filesPageSource]
  ] as const;

  describe('the dev-unauth bypass is gated on DEV at every site', () => {
    it.each(BYPASS_SITES)('%s conjoins import.meta.env.DEV with the flag', (_name, source) => {
      // One expression, not "both strings appear somewhere in the file" — which two unrelated
      // lines would satisfy while the bypass ran in production.
      expect(source).toMatch(/import\.meta\.env\.DEV\s*&&\s*import\.meta\.env\.VITE_S3_DEV_UNAUTH === 'true'/);

      // And exactly one read, so a second ungated one cannot hide behind the guarded first.
      expect(source.match(/VITE_S3_DEV_UNAUTH/g) ?? []).toHaveLength(1);
    });
  });

  describe('with DEV false, the flag does NOT unsign requests', () => {
    afterEach(() => {
      vi.unstubAllEnvs();
      vi.resetModules();
    });

    /** Re-imports the service after stubbing, so its module-scope const is recomputed. */
    async function serviceWith(env: {DEV: boolean; flag: string}) {
      vi.stubEnv('DEV', env.DEV);
      vi.stubEnv('VITE_S3_DEV_UNAUTH', env.flag);
      vi.resetModules();
      const credentials = await import('./awsCredentials');
      const getSessionCredentials = vi.spyOn(credentials, 'getSessionCredentials');
      return {service: await import('../features/file-browser/fileBrowser.service'), getSessionCredentials};
    }

    it('still resolves credentials in a PRODUCTION build, flag or no flag', async () => {
      // THE SECURITY CLAIM. `listFiles` takes the unsigned path only when the bypass is on; if
      // the DEV conjunct were dropped, a stray VITE_S3_DEV_UNAUTH in a production build
      // environment would send every listing unsigned. Asserting the credential lookup HAPPENS
      // is how that shows up from outside the module.
      const {service, getSessionCredentials} = await serviceWith({DEV: false, flag: 'true'});

      await service.listFiles('some-bucket', 'alice/');

      expect(getSessionCredentials).toHaveBeenCalled();
    });

    it('takes the unsigned path in a DEV build with the flag on', async () => {
      // The other direction, so the test above cannot pass by the bypass being broken outright —
      // which would satisfy "credentials were resolved" for entirely the wrong reason.
      const {service, getSessionCredentials} = await serviceWith({DEV: true, flag: 'true'});

      await service.listFiles('some-bucket', 'alice/');

      expect(getSessionCredentials).not.toHaveBeenCalled();
    });
  });
});

// ─── from enqueueFifo.test.ts ───
describe('enqueueFifo', () => {
  // SPEC-150 FR-004. The queue-URL guard returns before `getIdToken` and before any
  // SQS call, so nothing here needs the AWS boundary mocked — an unset env var is
  // the whole precondition.

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  describe('enqueueFifoRequest — the missing-queue-URL guard', () => {
    it('surfaces that wording to the user instead of the generic fallback', () => {
      // The regression this closes: with no `code`, `toUserMessage` fell through every
      // MATCH_RULES pattern to GENERIC, and the documented deploy gotcha presented as
      // "Something went wrong."
      const {message} = toUserMessage({code: 'NotConfigured', message: 'Table refresh is not configured'});

      expect(message).toBe('Table refresh is not configured');
      expect(message).not.toContain('Something went wrong');
    });
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
    /**
     * Read behind an `import.meta.env.DEV` guard at their own call sites and
     * deliberately absent from `PortalEnvVar` — see `VITE_NAME`'s docstring, and the
     * bypass guard above, which asserts the set of modules naming the flag.
     */
    const DEV_ONLY = new Set([
      'VITE_S3_DEV_UNAUTH',
      'VITE_S3_BUCKET_NAME',
      'VITE_S3_ROOT_PREFIX',
      'VITE_AWS_ACCESS_KEY_ID',
      'VITE_AWS_SECRET_ACCESS_KEY'
    ]);

    const SOURCES = import.meta.glob('../**/*.{ts,tsx}', {
      query: '?raw',
      import: 'default',
      eager: true
    }) as Record<string, string>;

    it('lists every VITE_ name that appears outside a test file', () => {
      const registered: string[] = Object.values(VITE_NAME).filter((name) => name !== null);
      const known = new Set<string>([...registered, ...DEV_ONLY]);
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
      // Each queue URL degrades through `enqueueFifo`'s notConfiguredMessage, the
      // shared bucket through "no shared spaces", the identity pool through
      // "signed in but no credentials" — one feature each, not the app.
      stubAllRequired();
      vi.stubEnv('VITE_TABLE_BUILD_QUEUE_URL', '');
      vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', '');
      vi.stubEnv('VITE_COGNITO_IDENTITY_POOL_ID', '');
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
