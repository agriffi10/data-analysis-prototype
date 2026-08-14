/**
 * The one Node API a test needs, declared rather than enabled.
 *
 * `tsconfig.app.json` deliberately lists only `vite/client` and `vitest/globals`, so app
 * code cannot reach for a Node API that would not exist in the browser. SPEC-184's palette
 * has to be checked against `src/index.css` itself — Vitest does not process CSS, so both
 * `import '…?raw'` and a raw `import.meta.glob` of a stylesheet resolve to an empty string
 * (measured), and an empty string makes that check pass by finding nothing.
 *
 * Adding `"node"` to the app's `types` would give every module in `src/` the whole Node
 * surface to keep the guarantee for one test. This declares the single function instead.
 */
declare module 'node:fs' {
  export function readFileSync(path: string, encoding: 'utf8'): string;
}
