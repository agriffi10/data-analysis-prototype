import type {TestProject} from 'vitest/node';

/**
 * Hands the suite the module cache setting the run actually resolved, so a test can refuse it.
 *
 * Vitest's file-system module cache skips a module whose source holds the literal
 * `import.meta.glob(`, because a glob depends on other files, but it caches a module that spells the
 * call any other way Vite accepts, such as with a type argument, with the matched file list frozen
 * in. The resolved value is read here, in the main process, because a worker has no public way to
 * read it, and it covers a command-line `--fsModuleCache` as well as the configuration file.
 *
 * @param project - The project being set up.
 */
export function setup(project: TestProject): void {
  project.provide('fsModuleCache', project.config.fsModuleCache);
}
