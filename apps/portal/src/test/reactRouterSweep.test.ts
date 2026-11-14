import {describe, expect, it} from 'vitest';
import {REACT_ROUTER_IMPORTS} from '../../eslint.config.js';

/**
 * The half of the navigation fence the lint rule cannot see.
 *
 * `no-restricted-imports` reads static imports only: `await import(…)`, `vi.mock(…, …)` and
 * `typeof import(…)` of react-router all lint clean (measured on ESLint 10.10.0). So the bare
 * specifier, in any quote, is held to the same three places the rule exempts: the seam, the route
 * table and this harness. The name is read from the lint config rather than spelled here.
 */

const PACKAGE = REACT_ROUTER_IMPORTS.group[0];

/** The places that may name react-router, as path prefixes under `/src/`. */
const EXEMPT = ['/src/lib/navigation/', '/src/routes/table.tsx', '/src/test/'];

const SOURCES = import.meta.glob('/src/**/*.{ts,tsx}', {query: '?raw', import: 'default', eager: true}) as Record<
  string,
  string
>;

/**
 * Whether a source names react-router as a module specifier, in any quote and in any form.
 *
 * @param source - A file's source.
 * @returns True when the specifier, or one beneath it, appears quoted.
 */
function namesReactRouter(source: string): boolean {
  return [`'${PACKAGE}`, `"${PACKAGE}`, `\`${PACKAGE}`].some((opening) => {
    for (let at = source.indexOf(opening); at >= 0; at = source.indexOf(opening, at + 1)) {
      const next = source[at + opening.length];
      if (next === opening[0] || next === '/') return true;
    }
    return false;
  });
}

describe('the react-router specifier', () => {
  it('is caught in every form the lint rule misses, and not in prose', () => {
    expect(namesReactRouter(`vi.mock('${PACKAGE}', async () => ({}));`)).toBe(true);
    expect(namesReactRouter(`const r = await import("${PACKAGE}");`)).toBe(true);
    expect(namesReactRouter(`type R = typeof import(\`${PACKAGE}\`);`)).toBe(true);
    expect(namesReactRouter(`import {x} from '${PACKAGE}/dom';`)).toBe(true);
    expect(namesReactRouter(`// ${PACKAGE} renders a sibling route into the same slot`)).toBe(false);
    expect(namesReactRouter(`import x from '${PACKAGE}-dom-ish';`)).toBe(false);
  });

  it('appears nowhere under src/ but the seam, the route table and the harness', () => {
    const named = Object.entries(SOURCES)
      .filter(([file]) => !EXEMPT.some((place) => file.startsWith(place)))
      .filter(([, source]) => namesReactRouter(source))
      .map(([file]) => file);

    expect(Object.keys(SOURCES).length).toBeGreaterThan(100);
    expect(named).toEqual([]);
  });
});
