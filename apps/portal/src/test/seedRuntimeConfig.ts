import {setRuntimeConfigDocument} from '../lib/runtimeConfig';
import type {RuntimeConfigDocument} from '../types/runtimeConfig.types';

/**
 * Put a test on the runtime-document path instead of the test fallback.
 *
 * Most specs need neither: under Vitest `import.meta.env.MODE` is `test` and no load has
 * happened, so every `configValue` answers from `vi.stubEnv`'d `VITE_*` variables and
 * nothing has to be seeded. Seed only when the document itself is the subject — a value
 * the fallback cannot express, or a read that must survive `MODE` being stubbed away from `test`.
 *
 * @param partial - Keys to serve. Merged over `version: 1`, so a caller never restates it.
 * @returns None.
 */
export function seedRuntimeConfig(partial?: Partial<RuntimeConfigDocument>): void {
  setRuntimeConfigDocument({version: 1, ...partial});
}

/**
 * Return to the unloaded state — what a production build throws from.
 *
 * The module-level document outlives a single `it`, so a spec that seeds must clear.
 *
 * @returns None.
 */
export function clearRuntimeConfig(): void {
  setRuntimeConfigDocument(undefined);
}
