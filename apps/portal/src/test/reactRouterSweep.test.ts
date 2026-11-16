import {readFileSync} from 'node:fs';
import {describe, expect, it} from 'vitest';

/**
 * react-router is gone, and these two checks keep it out: no source under `src/` names it as a
 * module specifier, in any form a lint rule would miss (a dynamic import, a `vi.mock`, a type query),
 * and no manifest declares it. The name is built here rather than spelled, so neither finds itself.
 */

const PACKAGE = ['react', 'router'].join('-');

/** Every source under `src/`, and this file's own, which a glob leaves out of the module it runs in. */
const SOURCES = {
  ...(import.meta.glob('/src/**/*.{ts,tsx}', {query: '?raw', import: 'default', eager: true}) as Record<
    string,
    string
  >),
  // The suite runs from apps/portal, as every file-reading test here assumes.
  '/src/test/reactRouterSweep.test.ts': readFileSync('src/test/reactRouterSweep.test.ts', 'utf8')
};

const MANIFESTS = import.meta.glob(['/package.json', '/../../package.json'], {
  query: '?raw',
  import: 'default',
  eager: true
}) as Record<string, string>;

/** A quoted specifier that begins with the name: the package, a path beneath it, or a package named after it. */
const SPECIFIER = new RegExp(`(['"\`])@?${PACKAGE}[\\w./@-]*\\1`);

/**
 * Whether a source names react-router, or any package whose name begins with it, as a quoted module
 * specifier, its subpaths and its `-dom` sibling alike. Prose that merely starts with the name, in a
 * comment or a sentence in quotes, is not a specifier.
 *
 * @param source - A file's source.
 * @returns True when a quoted specifier begins with the name.
 */
export function namesReactRouter(source: string): boolean {
  return SPECIFIER.test(source);
}

/**
 * The packages a manifest declares whose name begins with react-router, in any dependency map.
 *
 * @param manifest - A `package.json`'s text.
 * @returns The names found.
 */
export function declaredReactRouter(manifest: string): string[] {
  const parsed = JSON.parse(manifest) as Record<string, Record<string, string> | undefined>;
  return ['dependencies', 'devDependencies', 'peerDependencies', 'optionalDependencies'].flatMap((map) =>
    Object.keys(parsed[map] ?? {}).filter((name) => name.startsWith(PACKAGE) || name.startsWith(`@${PACKAGE}/`))
  );
}

describe('the react-router specifier', () => {
  it('is caught in every form, and not in prose', () => {
    expect(namesReactRouter(`import {Routes} from '${PACKAGE}';`)).toBe(true);
    expect(namesReactRouter(`vi.mock('${PACKAGE}', async () => ({}));`)).toBe(true);
    expect(namesReactRouter(`const r = await import("${PACKAGE}");`)).toBe(true);
    expect(namesReactRouter(`type R = typeof import(\`${PACKAGE}\`);`)).toBe(true);
    expect(namesReactRouter(`import {x} from '${PACKAGE}/dom';`)).toBe(true);
    expect(namesReactRouter(`import x from '${PACKAGE}-dom';`)).toBe(true);
    expect(namesReactRouter(`import x from '${PACKAGE}-dom-ish';`)).toBe(true);
    expect(namesReactRouter(`import x from '@${PACKAGE}/dev';`)).toBe(true);
    expect(namesReactRouter(`// ${PACKAGE} renders a sibling route into the same slot`)).toBe(false);
    expect(namesReactRouter(`describe('${PACKAGE}’s exemption clauses', () => {});`)).toBe(false);
  });

  it('appears nowhere under src/, this file included', () => {
    const named = Object.entries(SOURCES)
      .filter(([, source]) => namesReactRouter(source))
      .map(([file]) => file);

    expect(Object.keys(SOURCES).length).toBeGreaterThan(100);
    expect(SOURCES['/src/test/reactRouterSweep.test.ts']).toContain('namesReactRouter');
    expect(named).toEqual([]);
  });
});

describe('the manifests', () => {
  it('are both read, the app’s and the workspace root’s', () => {
    expect(Object.keys(MANIFESTS)).toHaveLength(2);
    for (const manifest of Object.values(MANIFESTS)) expect(manifest).toContain('"name"');
    expect(Object.values(MANIFESTS).join('\n')).toContain('"next"');
  });

  it('find a react-router package in any dependency map, and nothing else', () => {
    const planted = (map: string, name: string) => JSON.stringify({name: 'x', [map]: {next: '1', [name]: '1'}});

    expect(declaredReactRouter(planted('dependencies', PACKAGE))).toEqual([PACKAGE]);
    expect(declaredReactRouter(planted('devDependencies', `${PACKAGE}-dom`))).toEqual([`${PACKAGE}-dom`]);
    expect(declaredReactRouter(planted('peerDependencies', PACKAGE))).toEqual([PACKAGE]);
    expect(declaredReactRouter(planted('devDependencies', `@${PACKAGE}/dev`))).toEqual([`@${PACKAGE}/dev`]);
    expect(declaredReactRouter(planted('dependencies', 'react-dom'))).toEqual([]);
  });

  it('declare no react-router package', () => {
    expect(Object.values(MANIFESTS).flatMap(declaredReactRouter)).toEqual([]);
  });
});
