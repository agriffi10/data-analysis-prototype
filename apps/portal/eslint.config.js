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
    files: ['src/components/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['**/features/*', '**/features/**'],
              message:
                'components/ is the shared presentation layer and must not import from features/. Move the shared piece into lib/, components/ or hooks/ instead.'
            }
          ]
        }
      ]
    }
  },
  {
    // The two exemptions to the rule above, both deliberate.
    //
    // App chrome (Header, ProtectedLayout, Sidebar, SpacesList, UsernameCombobox) lives
    // in components/ but is composition, not a primitive: it exists to wire features into
    // the shell. Moving it would be a re-layering of its own, so it is named here rather
    // than left as a silent violation — a sixth file needs an explicit edit to this list.
    //
    // Tests mount real features by design (react.md §21: integration-style, mock only the
    // AWS boundary), so the rule can only produce noise on that glob.
    files: [
      'src/components/**/*.test.{ts,tsx}',
      'src/components/Header.tsx',
      'src/components/ProtectedLayout.tsx',
      'src/components/Sidebar.tsx',
      'src/components/SpacesList.tsx',
      'src/components/UsernameCombobox.tsx'
    ],
    rules: {
      'no-restricted-imports': 'off'
    }
  }
]);
