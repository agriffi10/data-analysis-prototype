import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import security from 'eslint-plugin-security';
import noUnsanitized from 'eslint-plugin-no-unsanitized';
import tseslint from 'typescript-eslint';
import {defineConfig, globalIgnores} from 'eslint/config';

// The browser makes NO AWS calls. Two mechanisms hold that, because neither catches the
// other's failure: this rule stops an import, and a test over package.json stops a
// dependency nobody has imported yet — which is how the next one arrives.
//
// SPREAD INTO EVERY no-restricted-imports CLAUSE BELOW, and that is not stylistic. Flat
// config REPLACES a rule's value at the last matching entry rather than merging it, so a
// single `src/**` clause would be silently switched off for every file the layering blocks
// also match. `eslintConfigShape.test.ts` enumerates the entries and fails if one omits it.
const AWS_SDK_IMPORTS = {
  group: ['@aws-sdk/*', '@aws-sdk/**'],
  message:
    'The browser makes no AWS calls. Go through the API — lib/apiClient.ts — or, for bytes, a ' +
    'presigned URL the API minted. aws-amplify is unaffected.'
};

// The server's one AWS client, and the only exception to the ban. The session store lives on the
// Next.js server, which needs it; nothing the browser bundles may import it, and `src/server/` is
// fenced off from every browser layer by SERVER_IMPORTS below, with `server-only` failing the build
// behind that. Every other @aws-sdk package stays banned there too.
const SERVER_AWS_SDK_IMPORTS = {
  group: ['@aws-sdk/*', '@aws-sdk/**', '!@aws-sdk/client-dynamodb'],
  message: 'The server holds one AWS client, @aws-sdk/client-dynamodb, for the session store, and no other.'
};

// The server's modules stay on the server. `src/server/` holds what reads the server's environment
// and what the request proxy runs; a browser module importing one would either fail the build at
// `server-only` or, for one that forgot it, ship server code to the browser.
//
// SPREAD INTO EVERY CLAUSE BELOW THAT GOVERNS features/, components/, lib/ or hooks/, for the
// AWS_SDK_IMPORTS reason above. RELATIVE patterns only: the rule matches the import SOURCE, which
// reaches src/server/ as `../server/…` or `../../server/…`, and a `**/server` pattern would also
// refuse `react-dom/server`.
const SERVER_IMPORTS = {
  group: ['../server', '../server/**', '../../server', '../../server/**', '../../../server', '../../../server/**'],
  message:
    "src/server/ is the Next.js server's alone. Nothing under features/, components/, lib/ or hooks/ " +
    'imports it; a value the browser needs reaches it through the runtime document or the API.'
};

// Navigation goes through one seam, `src/lib/navigation/`, because the App Router has no history
// state, no navigation type and no per-entry key, and react-router is only the catch-all's matcher
// until it retires. So nothing imports react-router but the seam, the route table that turns the
// area views into routes, and the test harness.
//
// SPREAD INTO EVERY CLAUSE BELOW but the two exemptions at the end, for the AWS_SDK_IMPORTS reason
// above. The rule sees only static imports: `vi.mock('react-router')`, a dynamic import and a type
// query all lint clean, so `src/test/reactRouterSweep.test.ts` holds the bare literal too.
export const REACT_ROUTER_IMPORTS = {
  group: ['react-router', 'react-router/*'],
  message:
    'Navigation goes through the seam: import it from src/lib/navigation. Only the seam, the route table ' +
    '(src/routes/table.tsx) and the test harness (src/test/) import react-router.'
};

/** The layering ban: the shared layers above `features/` never import a feature. */
const LAYERING_IMPORTS = {
  group: ['**/features/*', '**/features/**'],
  message:
    'components/, lib/ and hooks/ are the shared layers and must not import from features/. Move the shared piece into lib/, components/ or hooks/ — or move the caller into the feature that owns the concept.'
};

/**
 * What an App Router page may import statically is lib/ and hooks/, and a page's static imports are
 * evaluated at hydration, before the boot: so those two never reach the application graph either.
 * A type-only import is erased, so it is allowed.
 */
const PAGE_REACHABLE_IMPORTS = {
  group: ['**/components/*', '**/components/**', '**/routes/*', '**/routes/**'],
  allowTypeImports: true,
  message:
    "lib/ and hooks/ are what an App Router page may import statically, and a page's static imports run at hydration, before the boot, so they must not import components/ or routes/. Move the piece into lib/ or hooks/, or reach it from the page through next/dynamic."
};

export default defineConfig([
  {
    // Every file under src/, tests included. The three clauses below re-state
    // AWS_SDK_IMPORTS because each of them replaces this one for the files it matches.
    files: ['src/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': ['error', {patterns: [AWS_SDK_IMPORTS, REACT_ROUTER_IMPORTS]}]
    }
  },
  globalIgnores(['dist', 'coverage', '.next', 'next-env.d.ts', 'src/types/apiContract.generated.ts']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
      // SPEC-138 FR-003. The injection/XSS half of security scanning lives here rather
      // than in security.yml. It was put here because this pass blocked CI -- but ci.yml's
      // Lint step is disabled now to save Actions minutes, so it blocks the PRE-PUSH run
      // and nothing else. A dangerous sink stops a session that runs the gate and reaches
      // main behind a green PR when one does not. Everything else in SPEC-138 is report-only.
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
          patterns: [LAYERING_IMPORTS, AWS_SDK_IMPORTS, SERVER_IMPORTS, REACT_ROUTER_IMPORTS]
        }
      ]
    }
  },
  {
    // lib/ and hooks/ also stay off components/ and routes/, because a page imports them statically.
    // It replaces the clause above for these two trees, so it re-states every group of it.
    files: ['src/lib/**/*.{ts,tsx}', 'src/hooks/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [LAYERING_IMPORTS, PAGE_REACHABLE_IMPORTS, AWS_SDK_IMPORTS, SERVER_IMPORTS, REACT_ROUTER_IMPORTS]
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
      // The LAYERING rule is what these files are exempt from — not the SDK ban or the server
      // fence. A bare 'off' would exempt them from all three, and a test mocking
      // @aws-sdk/client-s3 is a test of a code path that no longer exists.
      'no-restricted-imports': ['error', {patterns: [AWS_SDK_IMPORTS, SERVER_IMPORTS, REACT_ROUTER_IMPORTS]}]
    }
  },
  {
    // Every feature, for the server fence. Placed BEFORE the sibling clause below, which replaces
    // it for the four features that clause names and therefore re-states SERVER_IMPORTS itself.
    files: ['src/features/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': ['error', {patterns: [AWS_SDK_IMPORTS, SERVER_IMPORTS, REACT_ROUTER_IMPORTS]}]
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
            },
            AWS_SDK_IMPORTS,
            SERVER_IMPORTS,
            REACT_ROUTER_IMPORTS
          ]
        }
      ]
    }
  },
  {
    // The first of the two places react-router may be imported: the seam, whose matcher it is. TWO
    // clauses, not one, because each replaces the rule for the files it matches: this one must keep
    // every other group of the clauses it overrides (the layering ban and the server fence from the
    // shared-layer clause, the SDK ban from all of them), and measured, a single exemption carrying
    // only the SDK group let a file in the seam import a feature and lint clean.
    files: ['src/lib/navigation/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {patterns: [LAYERING_IMPORTS, PAGE_REACHABLE_IMPORTS, AWS_SDK_IMPORTS, SERVER_IMPORTS]}
      ]
    }
  },
  {
    // The second: the route table, which turns the area views into react-router routes, and the test
    // harness, which composes routes for a test. They override only the `src/**` clause, so the SDK
    // ban is all they keep; the harness imports features by design.
    files: ['src/routes/table.tsx', 'src/test/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': ['error', {patterns: [AWS_SDK_IMPORTS]}]
    }
  },
  {
    // The server's modules, tests included. LAST, so it replaces the src/** clause for these files
    // rather than being replaced by it, and so it keeps that clause's react-router ban beside its own
    // narrowed SDK ban.
    files: ['src/server/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': ['error', {patterns: [SERVER_AWS_SDK_IMPORTS, REACT_ROUTER_IMPORTS]}]
    }
  }
]);
