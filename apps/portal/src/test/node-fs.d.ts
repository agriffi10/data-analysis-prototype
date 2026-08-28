/**
 * The one Node API a test needs, declared rather than enabled.
 *
 * `tsconfig.app.json` deliberately lists only `vite/client` and `vitest/globals`, so app
 * code cannot reach for a Node API that would not exist in the browser.
 *
 * Two tests need it, and naming both is the point: `formatting.test.ts` pins the palette
 * against `src/index.css`, and `lib/runtimeConfig.test.ts` pins the config keys against
 * `.env.example`. The palette check was once deleted while this file stayed — its consumer
 * count never reached zero, so nothing pointed at the gap, and the docstring went on giving
 * a reason that had stopped being true.
 *
 * Both read the file rather than importing it. Vitest does not process CSS, so both
 * `import '…?raw'` and a raw `import.meta.glob` of a stylesheet resolve to an empty string
 * (measured), and an empty string makes such a check pass by finding nothing.
 *
 * Adding `"node"` to the app's `types` would give every module in `src/` the whole Node
 * surface to keep the guarantee for one test. This declares the single function instead.
 */
declare module 'node:fs' {
  export function readFileSync(path: string, encoding: 'utf8'): string;
}
