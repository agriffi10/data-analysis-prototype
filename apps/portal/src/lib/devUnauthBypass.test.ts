import {describe, it, expect, vi, afterEach} from 'vitest';
import protectedLayoutSource from '../components/ProtectedLayout.tsx?raw';
import fileBrowserServiceSource from '../features/file-browser/fileBrowser.service.ts?raw';
import filesPageSource from '../routes/FilesPage.tsx?raw';

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
