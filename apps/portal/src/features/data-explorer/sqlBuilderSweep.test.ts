import {describe, expect, it} from 'vitest';

/**
 * SPEC-178 FR-002 AC6 — one SQL builder, enforced by a sweep rather than described.
 *
 * SPEC-165's precedent: the destination-key tests could only ever prove the ONE builder
 * right, so a sweep forbids a second. The same holds here and the stakes are higher — a
 * second SQL fragment built somewhere else is a second place presentation state could
 * leak into a query, which is the one rule this whole feature is organised around.
 *
 * **Scope: this feature, not the repo.** FR-002 AC6 says "any module outside this one",
 * and a literal repo-wide sweep is not achievable and never was: `useTableActions.tsx`,
 * `useRunDdl.ts` and `CreateViewDialog.tsx` build real DDL for the Query workspace today,
 * and `query.constants.ts`'s `DEFAULT_SQL` is `SELECT 1;`. A sweep that had to exempt
 * three legitimate builders would prove nothing about the fourth. SPEC-165's rule is
 * one-builder within the package that owns the concept, and that is what this asserts.
 */

// Full-line comments and block comments only — an inline `//` inside a string literal is
// left alone, so stripping can never widen what the sweep sees. Docstrings are where the
// FROM/WHERE prose legitimately lives (the type docs, the alias constant's rationale).
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
}

const SQL_FRAGMENT_RE = /\b(SELECT|FROM|WHERE|ORDER\s+BY|GROUP\s+BY)\b/;

describe('renderExplorationSql is the only SQL builder in the feature (FR-002 AC6)', () => {
  it('no other module in features/data-explorer/ builds a SQL fragment', () => {
    // RECURSIVE. Every feature in the repo is flat today, so `./*` would pass — and would
    // silently stop covering the first module SPEC-179/180 put in a subdirectory, which is
    // exactly when a grid component starts wanting to build a fragment.
    const files = import.meta.glob('./**/*.{ts,tsx}', {query: '?raw', import: 'default', eager: true}) as Record<
      string,
      string
    >;

    // A glob that matches nothing makes every assertion below vacuous, and it would still
    // be green.
    expect(Object.keys(files).length).toBeGreaterThan(0);

    const offenders = Object.entries(files)
      // The builder's own declaration, exempted by identity rather than by pattern.
      .filter(([path]) => !path.endsWith('renderExplorationSql.ts'))
      // Tests are exempt, and this is the one place they must be: a test that asserts the
      // builder's output necessarily contains that output. Forbidding SQL in a test file
      // would forbid testing the builder at all. Every non-test module is covered, which
      // is where the hazard actually lives — a hook or a component composing a fragment.
      .filter(([path]) => !/\.test\.tsx?$/.test(path))
      .filter(([, body]) => SQL_FRAGMENT_RE.test(stripComments(body)))
      .map(([path]) => path);

    expect(offenders).toEqual([]);
  });

  it('the sweep can fail — it detects a fragment in a module body', () => {
    // A guard-the-guard. The sweep above passes trivially the moment its regex or its
    // comment-stripping stops matching anything, and it would keep passing forever. This
    // pins that both halves still work on a body shaped like a real violation.
    const violation = `
      // Builds the ORDER BY — a comment, so this line alone must NOT trip it.
      export function sortClause(column: string) {
        return \`ORDER BY "\${column}"\`;
      }
    `;
    expect(SQL_FRAGMENT_RE.test(stripComments(violation))).toBe(true);

    const commentOnly = `
      // SELECT, FROM, WHERE, ORDER BY, GROUP BY — all in prose.
      /* And a block comment with SELECT * FROM t in it. */
      export const ALIAS = 't';
    `;
    expect(SQL_FRAGMENT_RE.test(stripComments(commentOnly))).toBe(false);
  });
});

// Every relative specifier a module imports from, `import type` included — a type-only
// import is still an import edge, and a renderer that took a `FormattingState` parameter
// would be reachable by presentation whatever the emitted JS looked like.
const IMPORT_RE = /(?:from|import)\s*\(?\s*'(\.[^']*)'/g;

/**
 * Resolves a relative specifier against a glob record's keys, trying the extensions Vite
 * would. Returns null for anything outside the record — a `../../lib/` import, say.
 */
function resolveSpecifier(from: string, specifier: string, files: Record<string, string>): string | null {
  const segments = from.split('/').slice(0, -1).concat(specifier.split('/'));
  const resolved: string[] = [];
  for (const segment of segments) {
    if (segment === '.' && resolved.length > 0) continue;
    if (segment === '..') resolved.pop();
    else resolved.push(segment);
  }
  const base = resolved.join('/');
  return ['.ts', '.tsx', '/index.ts'].map((suffix) => `${base}${suffix}`).find((path) => path in files) ?? null;
}

/** Every module reachable from `entry` by relative imports, `entry` included. */
function importClosure(entry: string, files: Record<string, string>): Set<string> {
  const seen = new Set<string>();
  const pending = [entry];
  while (pending.length > 0) {
    const path = pending.pop() as string;
    if (seen.has(path)) continue;
    seen.add(path);
    for (const [, specifier] of files[path].matchAll(IMPORT_RE)) {
      const target = resolveSpecifier(path, specifier, files);
      if (target !== null) pending.push(target);
    }
  }
  return seen;
}

describe('presentation cannot reach the renderer (SPEC-184 FR-001 AC2)', () => {
  // The far side of SPEC-178's central rule. The renderer's SIGNATURE already excludes
  // presentation state, but a signature is a promise about ONE function — this asserts the
  // property the spec actually needs, which is that no module SPEC-184 added is reachable
  // from the renderer at all. A rule evaluator the renderer cannot see is a rule evaluator
  // that cannot cost anyone a query.
  const FORMATTING_MODULES = ['./formatting.ts', './urlTransformer.ts'];

  const files = import.meta.glob('./**/*.{ts,tsx}', {query: '?raw', import: 'default', eager: true}) as Record<
    string,
    string
  >;

  it('no SPEC-184 module is in renderExplorationSql.ts’s import closure', () => {
    const closure = importClosure('./renderExplorationSql.ts', files);

    // Guards against a resolver that resolves nothing: the renderer really does import
    // this one, so a closure of size 1 is a broken walk rather than a clean result.
    expect(closure).toContain('./dataExplorer.constants.ts');

    for (const module of FORMATTING_MODULES) {
      // The module must EXIST for its absence from the closure to mean anything.
      expect(Object.keys(files)).toContain(module);
      expect([...closure]).not.toContain(module);
    }
  });

  it('the closure walk can fail — it finds a formatting import one hop away', () => {
    // A guard-the-guard over a synthetic graph shaped like the violation: the renderer
    // importing a helper that imports the evaluator. Both hops matter, because the
    // realistic mistake is indirect.
    const synthetic = {
      './renderExplorationSql.ts': "import {helper} from './helper';",
      './helper.ts': "import {computePageFormatting} from './formatting';",
      './formatting.ts': 'export const x = 1;'
    };
    expect([...importClosure('./renderExplorationSql.ts', synthetic)]).toContain('./formatting.ts');

    // And a type-only edge, which is the one an `import type` would quietly slip through.
    const typeOnly = {
      './renderExplorationSql.ts': "import type {FormattingState} from './formatting';",
      './formatting.ts': 'export type FormattingState = {a: 1};'
    };
    expect([...importClosure('./renderExplorationSql.ts', typeOnly)]).toContain('./formatting.ts');
  });
});
