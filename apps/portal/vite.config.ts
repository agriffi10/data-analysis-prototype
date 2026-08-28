import {defineConfig} from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  // Some AWS SDK transitive deps (surfaced by @aws-sdk/lib-storage in SPEC-016)
  // reference Node's `global`, which doesn't exist in the browser and throws
  // "Can't find variable: global" at bundle load. Map it to `globalThis`.
  define: {
    global: 'globalThis'
  },
  plugins: [react(), tailwindcss()],
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
      // `all` defaults to true in Vitest 4 with `include` set, so every source
      // file is reported — not just the ones a test happens to import.
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/**/*.test.{ts,tsx}',
        'src/**/*.types.ts',
        'src/**/*.d.ts',
        'src/test/**',
        'src/test-setup.ts',
        // The bootstrap, in two files only because the dynamic-import boundary forces
        // the split. Both are composition; their ORDER and REACH are what matters, and
        // `src/bootstrap.test.tsx` asserts those directly.
        'src/main.tsx',
        'src/AppRoot.tsx',
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
