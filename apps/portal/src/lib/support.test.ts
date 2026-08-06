import {afterEach, describe, expect, it, vi} from 'vitest';
import {isExpiryError, withCredentialRetry} from './credentialRetry';
import {enqueueFifoRequest} from './enqueueFifo';
import {toUserMessage} from './errorMessages';
import {enqueueQualityCheck} from '../features/data-quality/dataQuality.service';
import {enqueueNotificationAction} from '../features/notifications/notifications.service';
import {enqueueSharedSpaceRequest} from '../features/shared-spaces/sharedSpaces.service';
import {enqueueTableBuild, enqueueTableRefresh} from '../features/table-builder/tableBuild.service';
import {enqueueTableShare} from '../features/table-share/tableShare.service';
import {REQUIRED_ENV, envVar, isPortalConfigured, missingRequiredEnv, warnIfMisconfigured} from './env';
import {QueryClient} from '@tanstack/react-query';
import {invalidateListing} from './queryClient';
import {fileBrowserKeys} from '../features/file-browser/fileBrowserKeys';
import type {ServiceResult} from '../types/service.types';
import protectedLayoutSource from '../components/ProtectedLayout.tsx?raw';
import fileBrowserServiceSource from '../features/file-browser/fileBrowser.service.ts?raw';
import filesPageSource from '../routes/FilesPage.tsx?raw';

// ─── from credentialRetry.test.ts ───
describe('credentialRetry', () => {
  describe('isExpiryError', () => {
    it('recognizes the credential-expiry SDK error names', () => {
      expect(isExpiryError('ExpiredToken')).toBe(true);
      expect(isExpiryError('ExpiredTokenException')).toBe(true);
      expect(isExpiryError('CredentialsProviderError')).toBe(true);
      expect(isExpiryError('InvalidToken')).toBe(true);
    });

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

    it('runs the op once on success — no refresh', async () => {
      const getClient = vi.fn(async () => okClient('first'));
      const op = vi.fn(async () => ({success: true as const, data: 'done'}));

      const result = await withCredentialRetry(getClient, op);

      expect(result).toEqual({success: true, data: 'done'});
      expect(getClient).toHaveBeenCalledTimes(1);
      expect(op).toHaveBeenCalledTimes(1);
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

    it('returns the refreshed-client error if the refresh itself fails', async () => {
      const getClient = vi
        .fn<(forceRefresh?: boolean) => Promise<ServiceResult<{id: string}>>>()
        .mockResolvedValueOnce(okClient('first'))
        .mockResolvedValueOnce({
          success: false,
          error: {message: 'refresh failed'}
        });
      const op = vi.fn(async () => ({
        success: false as const,
        error: {message: 'expired', code: 'ExpiredToken'}
      }));

      const result = await withCredentialRetry(getClient, op);

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.error.message).toBe('refresh failed');
      expect(op).toHaveBeenCalledTimes(1); // never retried
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

    it('covers every module that reads the flag — the list above is not stale', async () => {
      // Guards the guard. A fourth site added without joining BYPASS_SITES would be an ungated
      // bypass this file silently says nothing about. `import.meta.glob` is Vite's own module
      // graph, so nothing here depends on a hand-maintained path list.
      const all = import.meta.glob('../**/*.{ts,tsx}', {query: '?raw', import: 'default', eager: true});

      const readers = Object.entries(all)
        .filter(([path]) => !/\.test\.tsx?$/.test(path))
        .filter(([, source]) => String(source).includes('VITE_S3_DEV_UNAUTH'))
        .map(([path]) => path.split('/').pop());

      expect(readers.sort()).toEqual(
        BYPASS_SITES.map(([name]) => name)
          .slice()
          .sort()
      );
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
    it('codes the failure NotConfigured so the authored wording can be mapped', async () => {
      const result = await enqueueFifoRequest({
        queueUrl: undefined,
        notConfiguredMessage: 'Table refresh is not configured',
        build: () => {
          throw new Error('build must not run when the queue URL is missing');
        }
      });

      expect(result).toEqual({
        success: false,
        error: {message: 'Table refresh is not configured', code: 'NotConfigured'}
      });
    });

    it('surfaces that wording to the user instead of the generic fallback', () => {
      // The regression this closes: with no `code`, `toUserMessage` fell through every
      // MATCH_RULES pattern to GENERIC, and the documented deploy gotcha presented as
      // "Something went wrong."
      const {message} = toUserMessage({code: 'NotConfigured', message: 'Table refresh is not configured'});

      expect(message).toBe('Table refresh is not configured');
      expect(message).not.toContain('Something went wrong');
    });
  });

  // Every `notConfiguredMessage` in the app, with the env var whose absence produces
  // it. A seventh control plane added without a row here is a message a user cannot
  // see — which is the defect this FR fixes, not a new one.
  const CALL_SITES: {name: string; envVar: string; message: string; call: () => Promise<ServiceResult<unknown>>}[] = [
    {
      name: 'sharedSpaces.service — enqueueSharedSpaceRequest',
      envVar: 'VITE_SHARED_SPACE_QUEUE_URL',
      message: 'Shared connections are not configured',
      call: () => enqueueSharedSpaceRequest({action: 'create', actor: 'alice', space: 'project_alpha'})
    },
    {
      name: 'dataQuality.service — enqueueQualityCheck',
      envVar: 'VITE_DATA_QUALITY_QUEUE_URL',
      message: 'Data quality checks are not configured',
      call: () =>
        enqueueQualityCheck({
          requestId: 'req-1',
          space: {kind: 'personal', bucket: 'bucket', prefix: 'alice/'},
          location: 'alice/sales/'
        })
    },
    {
      name: 'tableShare.service — enqueueTableShare',
      envVar: 'VITE_TABLE_SHARE_QUEUE_URL',
      message: 'Table sharing is not configured',
      call: () =>
        enqueueTableShare({
          source: {database: 'alice', table: 'sales'},
          tableName: 'sales',
          recipients: [{kind: 'user', name: 'bob'}]
        })
    },
    {
      name: 'notifications.service — enqueueNotificationAction',
      envVar: 'VITE_NOTIFICATIONS_QUEUE_URL',
      message: 'Notifications are not configured',
      call: () => enqueueNotificationAction({action: 'markAllRead', username: 'alice'})
    },
    {
      name: 'tableBuild.service — enqueueTableBuild',
      envVar: 'VITE_TABLE_BUILD_QUEUE_URL',
      message: 'Table creation is not configured',
      call: () =>
        enqueueTableBuild({
          space: {kind: 'personal', bucket: 'bucket', prefix: 'alice/sales/', database: 'alice'},
          tableName: 'sales',
          partitionKeys: []
        })
    },
    {
      name: 'tableBuild.service — enqueueTableRefresh',
      envVar: 'VITE_TABLE_BUILD_QUEUE_URL',
      message: 'Table refresh is not configured',
      call: () =>
        enqueueTableRefresh({
          space: {kind: 'personal', bucket: 'bucket', prefix: 'alice/sales/', database: 'alice'},
          tableName: 'sales'
        })
    }
  ];

  describe('every "not configured" message reaches the user', () => {
    it.each(CALL_SITES)('$name', async ({envVar, message, call}) => {
      vi.stubEnv(envVar, undefined);

      const result = await call();

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.error.code).toBe('NotConfigured');
      // The assertion that matters is the MAPPED text, not the raw one: the raw
      // message was always correct, and was always thrown away by the mapper.
      expect(toUserMessage(result.error).message).toBe(message);
    });
  });
});

// ─── from env.test.ts ───
describe('env', () => {
  /** Set every required variable, so a test can then unset exactly the one it cares about. */
  function stubAllRequired(): void {
    for (const name of REQUIRED_ENV) vi.stubEnv(name, `value-for-${name}`);
  }

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  describe('envVar', () => {
    it('reads at CALL time, so a stub set after import is seen', () => {
      vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'test-bucket');
      expect(envVar('VITE_S3_USER_SPACE_BUCKET')).toBe('test-bucket');
    });

    it('treats the empty string as unset — an unset repo variable interpolates to ""', () => {
      vi.stubEnv('VITE_ATHENA_WORKGROUP', '');
      expect(envVar('VITE_ATHENA_WORKGROUP')).toBeUndefined();
    });
  });

  describe('missingRequiredEnv', () => {
    it('is empty when every required variable is set', () => {
      stubAllRequired();
      expect(missingRequiredEnv()).toEqual([]);
      expect(isPortalConfigured()).toBe(true);
    });

    it('names the variable that is missing', () => {
      stubAllRequired();
      vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', '');
      expect(missingRequiredEnv()).toEqual(['VITE_S3_USER_SPACE_BUCKET']);
      expect(isPortalConfigured()).toBe(false);
    });

    it('does not require the variables with their own degraded path', () => {
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

    it('stays silent in a production build even when a variable is missing', () => {
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
      stubAllRequired();
      vi.stubEnv('VITE_AWS_REGION', ''); // genuinely missing, not merely absent from the ambient env
      vi.stubEnv('DEV', false);

      warnIfMisconfigured();

      expect(warn).not.toHaveBeenCalled();
    });
  });
});

// ─── from queryClient.test.ts ───
describe('queryClient', () => {
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
});
