import {createRequire} from 'node:module';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {defineConfig} from 'vitest/config';
import react from '@vitejs/plugin-react';

/**
 * `server-only`'s no-op entry. Its default entry throws by design outside a server bundle, which is
 * every Vitest file, so the server modules' own tests could not import them. Next resolves the
 * package itself when it builds, so this alias reaches the test runner and nothing else.
 */
const SERVER_ONLY_EMPTY = path.join(path.dirname(createRequire(import.meta.url).resolve('server-only')), 'empty.js');

/**
 * Next's App Router, modelled on jsdom's history. The real `next/navigation` needs the App Router
 * mounted around it, which no test has; the stand-in models the nine behaviours the navigation
 * seam and the pages rest on, each with a test of its own. Exact match only, so nothing else under `next/` moves.
 */
const NEXT_NAVIGATION_STAND_IN = fileURLToPath(new URL('./src/test/nextNavigation.ts', import.meta.url));

/**
 * Vitest's configuration, and nothing else: Next.js builds and serves the portal. Vite remains
 * because Vitest runs on it, so this file carries no build plugin and no build-time definition.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      {find: /^server-only$/, replacement: SERVER_ONLY_EMPTY},
      {find: /^next\/navigation$/, replacement: NEXT_NAVIGATION_STAND_IN}
    ]
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
    // Worker threads rather than forked processes: measurably faster to spawn, and
    // nothing here needs process isolation. `isolate` stays ON — turning it off shares
    // the module registry between files in a worker, and 122 of ours fail immediately
    // because one file's `vi.mock` then leaks into the next.
    pool: 'threads',
    // Vitest's own default, declared rather than inherited. Measured under parallel load, a longer
    // timeout bought nothing and would only make a hang fail later; a case whose waits cover
    // slow real work gets its own budget, and says why. `maxWorkers` is left to scale with the
    // machine's cores: the uncapped runs held under the same load, and a cap only slowed its run.
    testTimeout: 5_000,

    // Off, and a test refuses a run that resolved it on. The cache skips a module whose source holds
    // the literal `import.meta.glob(`, but caches one spelled any other way Vite accepts, such as with
    // a type argument, with the glob's file list frozen in: `renderApp` went on serving a deleted and
    // restored page as the 404. A rule about spelling would fail as silently as the skip does.
    fsModuleCache: false,
    globalSetup: ['./vitest.globalSetup.ts'],
    coverage: {
      provider: 'v8',
      // Pins the measured population to this app's TypeScript sources, which is what makes the
      // thresholds below mean anything: they are a fraction OF this list. Do not read it as what
      // puts untested files in the denominator — measured with and without it, the same rows and
      // the same percentages come back either way, and only the reported paths shift as the
      // common-prefix root climbs out of `src/`. It is the scope that is load-bearing here, not
      // the population.
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/**/*.test.{ts,tsx}',
        'src/**/*.types.ts',
        'src/**/*.d.ts',
        'src/test/**',
        'src/test-setup.ts',
        // The composition above the boot: the provider tree behind the dynamic import, and the
        // root layout and catch-all page Next renders around it. Their ORDER and REACH are what
        // matters, and `src/bootstrap.test.tsx` and the image's behaviour matrix assert those
        // directly; the boot itself is covered.
        'src/AppFrame.tsx',
        'src/app/layout.tsx',
        'src/app/\\[\\[...slug\\]\\]/page.tsx',
        // Emitted from the Python contract, so it is that declaration's coverage to earn,
        // not this suite's. It does not match the `.types.ts` rule above.
        'src/types/apiContract.generated.ts'
      ],
      reporter: ['text', 'text-summary', 'html', 'lcov'],
      // Coverage floor, held at 85 across the board and NOT ratcheted upward. The suite is
      // scoped to how a user drives a feature, not to every function a feature reaches, so a
      // higher floor gets met by testing internals rather than behaviour. Never lower it either
      // — a lowered floor is a visible one-line diff, which is why these are literals.
      thresholds: {
        statements: 85,
        branches: 85,
        functions: 85,
        lines: 85
      }
    }
  }
});
