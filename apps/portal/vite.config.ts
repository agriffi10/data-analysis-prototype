import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  // Some AWS SDK transitive deps (surfaced by @aws-sdk/lib-storage in SPEC-016)
  // reference Node's `global`, which doesn't exist in the browser and throws
  // "Can't find variable: global" at bundle load. Map it to `globalThis`.
  define: {
    global: 'globalThis',
  },
  plugins: [react(), tailwindcss()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
  },
});
