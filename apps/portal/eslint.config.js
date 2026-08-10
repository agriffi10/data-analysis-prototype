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
  },
  {
    // SPEC-155 FR-005 — layering. `src/components/` is the shared presentation layer;
    // features compose it, not the other way round. Before this rule, ToastProvider and
    // Sidebar imported from `features/query/`, which made the query feature a de-facto
    // shared layer nobody had declared.
    //
    // `src/lib/` and `src/hooks/` are under it too, as of 2026-08-09. SPEC-155 left
    // `lib/queryClient.ts` importing `features/file-browser/fileBrowserKeys` — the same
    // inversion one layer lower, and the rule as written did not reach it. The import is
    // gone (`invalidateListing` moved into the feature, beside the keys it builds), so the
    // glob can widen. Widening it is the point: fixing the one file without extending the
    // rule leaves the next one to be found by hand. The test exemption below is what makes
    // the widening survive — `lib/support.test.ts` imports seven feature services by design.
    files: ['src/components/**/*.{ts,tsx}', 'src/lib/**/*.{ts,tsx}', 'src/hooks/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['**/features/*', '**/features/**'],
              message:
                'components/, lib/ and hooks/ are the shared layers and must not import from features/. Move the shared piece into lib/, components/ or hooks/ — or move the caller into the feature that owns the concept.'
            }
          ]
        }
      ]
    }
  },
  {
    // The two exemptions to the rule above, both deliberate.
    //
    // Header and ProtectedLayout are app chrome: they exist to wire features into the
    // shell, so they compose features by definition. Getting them under the rule would
    // mean a separate app-shell layer — a re-layering of its own, not an import fix.
    // They are named here rather than left as a silent violation; a third file needs an
    // explicit edit to this list.
    //
    // Tests mount real features by design (react.md §21: integration-style, mock only the
    // AWS boundary), so the rule can only produce noise on that glob.
    files: [
      'src/components/**/*.test.{ts,tsx}',
      'src/lib/**/*.test.{ts,tsx}',
      'src/hooks/**/*.test.{ts,tsx}',
      'src/components/Header.tsx',
      'src/components/ProtectedLayout.tsx'
    ],
    rules: {
      'no-restricted-imports': 'off'
    }
  }
]);
