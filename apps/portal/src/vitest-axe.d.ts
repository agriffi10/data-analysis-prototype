// SPEC-045: type the `toHaveNoViolations` matcher onto Vitest's assertion.
// vitest-axe's own `extend-expect` augments the legacy global `Vi` namespace,
// which Vitest 4 no longer reads — it merges custom matchers via `declare module
// 'vitest'`. The runtime registration lives in `src/test-setup.ts`.
//
// Interface-merging augmentation is inherently a set of empty `extends` interfaces;
// the lint rules below don't apply to declaration merging.
/* eslint-disable @typescript-eslint/no-empty-object-type, @typescript-eslint/no-unused-vars, @typescript-eslint/no-explicit-any */
import type { AxeMatchers } from 'vitest-axe/matchers';

declare module 'vitest' {
  interface Assertion<T = any> extends AxeMatchers {}
  interface AsymmetricMatchersContaining extends AxeMatchers {}
}
