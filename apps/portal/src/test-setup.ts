import '@testing-library/jest-dom';

// Accessibility matcher (SPEC-045). `expect.extend` registers `toHaveNoViolations`
// at runtime so every test can assert axe results without a per-file import; its
// TypeScript types are declared in `src/vitest-axe.d.ts`.
import { expect } from 'vitest';
import * as axeMatchers from 'vitest-axe/matchers';

expect.extend(axeMatchers);
