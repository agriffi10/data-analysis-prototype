/**
 * The lint config, declared so a test can read its shape.
 *
 * `eslintConfigShape.test.ts` imports `eslint.config.js` to enumerate the entries that
 * declare `no-restricted-imports`. The file sits outside `tsconfig.app.json`'s
 * `"include": ["src"]`, so `tsc -b` cannot see it and raises TS7016 without this — the
 * gate `npm run test` never reaches, which is how a test that resolves under Vitest can
 * still redden the build.
 *
 * Typed as the one shape the test walks, not as ESLint's full `Linter.Config`: adding
 * `@types/eslint` to the app's `types` would hand every module in `src/` a linter API to
 * keep the guarantee for one test, the trade `node-fs.d.ts` records making the other way.
 */
declare module '*/eslint.config.js' {
  type RestrictedImportPattern = {group: string[]; message: string};
  type ConfigEntry = {
    files?: string[];
    rules?: {
      'no-restricted-imports'?: unknown;
      [rule: string]: unknown;
    };
    [key: string]: unknown;
  };
  const config: ConfigEntry[];
  export default config;
  export type {ConfigEntry, RestrictedImportPattern};
}
