import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import security from 'eslint-plugin-security';
import noUnsanitized from 'eslint-plugin-no-unsanitized';
import tseslint from 'typescript-eslint';
import {defineConfig, globalIgnores} from 'eslint/config';

export default defineConfig([
  globalIgnores(['dist', 'coverage', 'src/types/apiContract.generated.ts']),
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
  },
  {
    // SPEC-176 FR-006 — the companion clause. The rule above governs the shared layers
    // above `features/`; this one governs two SIBLINGS. The Query workspace and the Data
    // Explorer both read the Glue catalog and run Athena queries, and the cheap way to
    // build the second is to import the first — which is exactly the undeclared shared
    // layer SPEC-155 spent a spec dismantling, one directory over. What they share is
    // `features/catalog/`, and importing IT is deliberately never restricted — it appears in
    // no `group` pattern below.
    //
    // `features/data-explorer/` does not exist yet. It is named anyway so the first file
    // created there lands under a guard that is already working rather than one added
    // afterwards.
    //
    // Tests are NOT exempt here, unlike the shared-layer rule above. That exemption
    // exists because integration-style tests mount real features by design (react.md
    // §21) — but a Query test reaching into the Data Explorer is the coupling itself,
    // not a mount of the tree under test.
    //
    // The RELATIVE forms are the load-bearing ones and the `**/features/…` forms alone
    // are inert: `no-restricted-imports` matches the literal import SOURCE, and one
    // sibling feature reaches another as `../query/queryKeys`, which contains no
    // `features/` segment at all. The rule above works only because `components/` and
    // `lib/` sit above `features/` and must name it. Written with the `features/` globs
    // alone this clause read correctly and caught nothing — which is why FR-006 requires
    // it be verified by committing a violation in each direction, not by reading it.
    // `features/catalog/` is under this rule too, in the one direction that matters: it is
    // the layer BELOW both, so it may import neither. FR-001 AC2 asserts that and this is
    // what keeps it true for SPEC-177 onward — a catalog module reaching back into
    // `features/query/` is the inversion the whole arc exists to prevent, and it was reached
    // on the very first file moved (`useSchema` -> `DatabaseSchema`).
    //
    // `features/saved-queries/` joins on the same footing (SPEC-177 FR-004): the `.sql`
    // store is below the Query workspace and the Data Explorer, and both save and load
    // through it. The direction that stays OPEN is the other one — `features/query/`
    // importing the store is how the workspace keeps working, so `saved-queries` appears in
    // no `group` pattern below.
    files: [
      'src/features/query/**/*.{ts,tsx}',
      'src/features/data-explorer/**/*.{ts,tsx}',
      'src/features/catalog/**/*.{ts,tsx}',
      'src/features/saved-queries/**/*.{ts,tsx}'
    ],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: [
                '../query',
                '../query/**',
                '../../query',
                '../../query/**',
                '../data-explorer',
                '../data-explorer/**',
                '../../data-explorer',
                '../../data-explorer/**',
                '**/features/query',
                '**/features/query/**',
                '**/features/data-explorer',
                '**/features/data-explorer/**'
              ],
              message:
                'features/query/ and features/data-explorer/ are siblings and must not import from each other, and the layers below them (features/catalog/, features/saved-queries/) may import neither. Anything both need belongs in features/catalog/ (SPEC-176) or features/saved-queries/ (SPEC-177).'
            }
          ]
        }
      ]
    }
  }
]);
