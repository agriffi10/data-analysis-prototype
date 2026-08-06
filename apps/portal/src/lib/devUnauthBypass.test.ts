import {describe, it, expect} from 'vitest';
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
 * READ AS SOURCE RATHER THAN EXERCISED, deliberately, and the limitation is worth stating
 * plainly. The expression is evaluated once at module load from `import.meta.env`, which Vite
 * statically replaces at build time; there is no runtime seam to drive, and
 * `vi.stubEnv('DEV', false)` cannot retroactively change a binding a module already computed.
 * What CAN be asserted — and is exactly what a reviewer checks by eye — is that every site
 * still conjoins `import.meta.env.DEV`. A source assertion is weaker than a behavioural one
 * and is named as such; it is also strictly stronger than the nothing that was here before,
 * and it fails the moment someone deletes the guard.
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
