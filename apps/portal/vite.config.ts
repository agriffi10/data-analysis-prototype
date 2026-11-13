import {createRequire} from 'node:module';
import path from 'node:path';
import {defineConfig} from 'vitest/config';
import react from '@vitejs/plugin-react';

/**
 * `server-only`'s no-op entry. Its default entry throws by design outside a server bundle, which is
 * every Vitest file, so the server modules' own tests could not import them. Next resolves the
 * package itself when it builds, so this alias reaches the test runner and nothing else.
 */
const SERVER_ONLY_EMPTY = path.join(path.dirname(createRequire(import.meta.url).resolve('server-only')), 'empty.js');

/**
 * Vitest's configuration, and nothing else: Next.js builds and serves the portal. Vite remains
 * because Vitest runs on it, so this file carries no build plugin and no build-time definition.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {'server-only': SERVER_ONLY_EMPTY}
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
        'src/AppRoot.tsx',
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
