import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import security from 'eslint-plugin-security';
import noUnsanitized from 'eslint-plugin-no-unsanitized';
import tseslint from 'typescript-eslint';
import {defineConfig, globalIgnores} from 'eslint/config';

export default defineConfig([
  globalIgnores(['dist', 'coverage']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
      // SPEC-138 FR-003. The injection/XSS half of security scanning lives here rather
      // than in security.yml, because this pass already blocks CI: a dangerous sink in
      // code being written now stops the PR, instead of becoming a line in a report
      // nobody reads. Everything else in SPEC-138 ships report-only; these two do not.
      security.configs.recommended,
      noUnsanitized.configs.recommended
    ],
    languageOptions: {
      globals: globals.browser
    },
    rules: {
      // Fires on every computed member access — `obj[key]` — which this codebase does
      // constantly against typed records. The plugin's own docs call it high-noise and
      // suggest disabling it outside of code handling untrusted keys. Left on it would
      // mean either hundreds of inline disables or a rule set nobody reads; both are
      // worse than not having it.
      'security/detect-object-injection': 'off'
    }
  },
  {
    // Test files and the shared test harness legitimately export non-component
    // helpers (render utilities, fixtures) — the Fast Refresh rule doesn't apply.
    files: ['**/*.test.{ts,tsx}', 'src/test/**/*.{ts,tsx}'],
    rules: {
      'react-refresh/only-export-components': 'off',
      // The rule exists to catch untrusted input reaching the RegExp constructor. Every
      // use here builds a Testing Library matcher from an in-repo constant (HELP_SECTIONS,
      // the data-quality note strings) or from the test's own fixture, escaped first.
      // There is no untrusted value in a test's own arrange step, so the rule can only
      // produce noise on this glob.
      'security/detect-non-literal-regexp': 'off'
    }
  }
]);
