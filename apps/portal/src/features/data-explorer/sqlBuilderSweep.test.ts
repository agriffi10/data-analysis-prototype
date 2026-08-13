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
    const files = import.meta.glob('./*.{ts,tsx}', {query: '?raw', import: 'default', eager: true}) as Record<
      string,
      string
    >;

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
