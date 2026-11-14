/**
 * What the global setup hands every test file through `inject`.
 *
 * Declared once and included by both TypeScript projects: the Node project, which type-checks the
 * global setup that provides it, and the app project, which type-checks the test that reads it.
 */
declare module 'vitest' {
  export interface ProvidedContext {
    /** The module cache setting the run resolved, from the configuration file and the command line. */
    fsModuleCache: boolean;
  }
}

export {};
