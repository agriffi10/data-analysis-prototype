import {describe, expect, it} from 'vitest';

/**
 * Nothing a request to the API passes through may consult the flags, because a flag gating a request
 * would be authorization. Held on the source: every route handler, the request proxy and the session
 * modules, followed through every relative import they make, statically or dynamically, must never
 * reach `src/server/featureFlags.ts`.
 */

/** Every source file under `src/`, keyed `/src/…`. */
const SOURCES = import.meta.glob('/src/**/*.{ts,tsx}', {query: '?raw', import: 'default', eager: true}) as Record<
  string,
  string
>;

const FLAGS_MODULE = '/src/server/featureFlags.ts';

const isTest = (file: string) => /\.test\.tsx?$/.test(file);

/** The files a request to the API passes through. */
function guarded(files: readonly string[]): string[] {
  return files.filter(
    (file) =>
      !isTest(file) &&
      ((file.startsWith('/src/app/') && /\/route\.tsx?$/.test(file)) ||
        file === '/src/proxy.ts' ||
        file.startsWith('/src/server/session/'))
  );
}

/**
 * Every relative specifier a source names: `import … from`, `export … from` and a bare import, indented
 * or not, and `import(…)` with any quote, a template literal included.
 */
function relativeSpecifiers(source: string): string[] {
  const written = [
    ...[...source.matchAll(/^\s*(?:import|export)\s[^'"`(=;]*['"`]([^'"`]+)['"`]/gm)].map(([, specifier]) => specifier),
    ...[...source.matchAll(/\bimport\(\s*['"`]([^'"`$]+)['"`]/g)].map(([, specifier]) => specifier)
  ];
  return written.filter((specifier) => specifier.startsWith('.'));
}

/** A relative specifier resolved to a source file present in `sources`, or undefined. */
function resolveIn(sources: Record<string, string>, from: string, specifier: string): string | undefined {
  const base = new URL(specifier, `https://portal.invalid${from}`).pathname;
  return [base, `${base}.ts`, `${base}.tsx`, `${base}/index.ts`, `${base}/index.tsx`].find((path) => path in sources);
}

/**
 * The guarded files that reach the flags module, each with the chain that reaches it.
 *
 * @param sources - Source text by `/src/…` path.
 * @returns One finding per guarded file that reaches it.
 */
export function fenceFindings(sources: Record<string, string>): string[] {
  const findings: string[] = [];
  for (const start of guarded(Object.keys(sources))) {
    const seen = new Map<string, string | undefined>([[start, undefined]]);
    const queue = [start];
    while (queue.length > 0) {
      const file = queue.shift()!;
      for (const specifier of relativeSpecifiers(sources[file])) {
        const target = resolveIn(sources, file, specifier);
        if (target === undefined || seen.has(target)) continue;
        seen.set(target, file);
        queue.push(target);
      }
    }
    if (!seen.has(FLAGS_MODULE)) continue;
    const chain = [FLAGS_MODULE];
    for (let at = seen.get(FLAGS_MODULE); at !== undefined; at = seen.get(at)) chain.unshift(at);
    findings.push(chain.join(' -> '));
  }
  return findings;
}

const ROUTE = '/src/app/api/[...path]/route.ts';
const FLAGS = {[FLAGS_MODULE]: "import 'server-only';\nexport function serverFeatureFlags() {}"};

describe('the pass-through fence, against fixtures', () => {
  it('names a route handler importing the flags, by any form', () => {
    for (const line of [
      "import {serverFeatureFlags} from '../../../server/featureFlags';",
      "export {serverFeatureFlags} from '../../../server/featureFlags';",
      "const flags = await import('../../../server/featureFlags');",
      'const flags = await import(`../../../server/featureFlags`);',
      "  import {serverFeatureFlags} from '../../../server/featureFlags';"
    ]) {
      expect(fenceFindings({...FLAGS, [ROUTE]: line})).toEqual([`${ROUTE} -> ${FLAGS_MODULE}`]);
    }
  });

  it('names a route handler written as .tsx', () => {
    const tsx = '/src/app/api/[...path]/route.tsx';
    expect(fenceFindings({...FLAGS, [tsx]: "import {x} from '../../../server/featureFlags';"})).toEqual([
      `${tsx} -> ${FLAGS_MODULE}`
    ]);
  });

  it('names the proxy and a session module reaching it through another module', () => {
    const between = '/src/server/between.ts';
    expect(
      fenceFindings({
        ...FLAGS,
        [between]: "import {serverFeatureFlags} from './featureFlags';",
        '/src/proxy.ts': "import {x} from './server/between';",
        '/src/server/session/forward.ts': "import {x} from '../between';"
      })
    ).toEqual([
      `/src/proxy.ts -> ${between} -> ${FLAGS_MODULE}`,
      `/src/server/session/forward.ts -> ${between} -> ${FLAGS_MODULE}`
    ]);
  });

  it('passes a route handler that imports something else, and a layout that imports the flags', () => {
    expect(
      fenceFindings({
        ...FLAGS,
        '/src/server/session/handlers.ts': 'export function route() {}',
        [ROUTE]: "import {route} from '../../../server/session/handlers';",
        '/src/app/(signed-in)/query/layout.tsx': "import {serverRouteGate} from '../../../server/featureFlags';"
      })
    ).toEqual([]);
  });
});

describe('the API pass-through', () => {
  it('guards the route handlers, the proxy and the session modules it claims to', () => {
    const files = guarded(Object.keys(SOURCES));
    expect(files).toEqual(expect.arrayContaining([ROUTE, '/src/proxy.ts', '/src/server/session/handlers.ts']));
    expect(files.filter((file) => file.endsWith('/route.ts')).length).toBeGreaterThan(5);
  });

  it('never reaches the flags module', () => {
    expect(fenceFindings(SOURCES)).toEqual([]);
  });
});
