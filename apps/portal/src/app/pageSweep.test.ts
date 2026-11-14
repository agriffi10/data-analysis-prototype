import {describe, expect, it} from 'vitest';

/**
 * What the App Router's files may reach, read from their source.
 *
 * Next renders the root layout and every page on the server, and evaluates a page's static imports
 * in the browser at hydration, before the runtime document arrives. Vitest and `next dev` see none
 * of that: the test runner's configuration fallback answers every read, and a module that throws on
 * the server only fails a production build's requests. So the rules are held on the source, each by
 * a pure check proved against a fixture corpus that asserts its reason, then run over the tree.
 */

/** Every source file under `src/`, keyed `/src/…`. */
const SOURCES = import.meta.glob('/src/**/*.{ts,tsx}', {query: '?raw', import: 'default', eager: true}) as Record<
  string,
  string
>;

const isTest = (file: string) => /\.test\.tsx?$/.test(file);

/** The application graph a page must never reach statically. */
const APP_GRAPH = ['/src/features/', '/src/components/', '/src/routes/'];

/** The specifiers a file imports statically: `import … from`, `export … from` and bare imports. */
function staticImports(source: string): string[] {
  return [...source.matchAll(/^(?:import|export)\s[^'"(=;]*['"]([^'"]+)['"]/gm)].map(([, specifier]) => specifier);
}

/** A relative specifier resolved against the importing file, as `/src/…`; a package name as it is. */
function resolve(file: string, specifier: string): string {
  if (!specifier.startsWith('.')) return specifier;
  return new URL(specifier, `https://portal.invalid${file}`).pathname;
}

/** Every `dynamic(…)` call's argument text. */
function dynamicCalls(source: string): string[] {
  const calls: string[] = [];
  for (const match of source.matchAll(/\bdynamic\(/g)) {
    let depth = 0;
    let end = match.index + 'dynamic'.length;
    for (; end < source.length; end += 1) {
      if (source[end] === '(') depth += 1;
      if (source[end] === ')' && --depth === 0) break;
    }
    calls.push(source.slice(match.index, end + 1));
  }
  return calls;
}

/**
 * The rules for a page and the files in its directory: no static import of the application graph,
 * every view reached through `dynamic(…, {ssr: false})`, and no `params` or `searchParams` prop,
 * which a native navigation leaves stale.
 *
 * @param files - The page's directory, by file (`/src/app/…/page.tsx` and its neighbours).
 * @returns A finding per broken rule, naming the file and what broke it.
 */
export function pageFindings(files: Record<string, string>): string[] {
  const findings: string[] = [];
  let reachesAView = false;
  for (const [file, source] of Object.entries(files)) {
    for (const specifier of staticImports(source)) {
      const target = resolve(file, specifier);
      if (APP_GRAPH.some((root) => target.startsWith(root)) || /\/AppFrame(\.tsx)?$/.test(target)) {
        findings.push(`${file} imports ${specifier} statically`);
      }
    }
    for (const call of dynamicCalls(source)) {
      if (/ssr:\s*false/.test(call)) reachesAView = true;
      else findings.push(`${file} loads through next/dynamic without ssr: false`);
    }
    if (file.endsWith('/page.tsx')) {
      const declared = /export default (?:async )?function \w*\(([^)]*)\)/.exec(source);
      if (!declared) findings.push(`${file} has no default-exported page function`);
      else if (declared[1].trim()) findings.push(`${file} declares a parameter (${declared[1].trim()})`);
    }
  }
  if (!reachesAView) findings.push(`${Object.keys(files)[0]} reaches no view through dynamic(…, {ssr: false})`);
  return findings;
}

/**
 * The rules for the root layout and its mount: the layout reaches the boot only through
 * `PortalMount`, which reaches `PortalBoot` only through `dynamic(…, {ssr: false})`.
 *
 * @param layout - `src/app/layout.tsx`'s source.
 * @param mount - `src/app/PortalMount.tsx`'s source.
 * @returns A finding per broken rule.
 */
export function rootFindings(layout: string, mount: string): string[] {
  const findings: string[] = [];
  for (const specifier of staticImports(layout)) {
    const target = resolve('/src/app/layout.tsx', specifier);
    if ([...APP_GRAPH, '/src/lib/'].some((root) => target.startsWith(root)) || /\/PortalBoot(\.tsx)?$/.test(target)) {
      findings.push(`layout.tsx imports ${specifier} statically`);
    }
  }
  if (!staticImports(layout).includes('./PortalMount')) findings.push('layout.tsx does not render PortalMount');
  if (staticImports(mount).some((specifier) => /PortalBoot/.test(specifier)))
    findings.push('PortalMount.tsx imports PortalBoot statically');
  const calls = dynamicCalls(mount).filter((call) => /import\(['"]\.\.\/PortalBoot['"]\)/.test(call));
  if (calls.length === 0) findings.push('PortalMount.tsx does not load PortalBoot through next/dynamic');
  for (const call of calls)
    if (!/ssr:\s*false/.test(call)) findings.push('PortalMount.tsx loads PortalBoot without ssr: false');
  return findings;
}

/** A finding for each `metadata` or `generateMetadata` export, which overwrites a page's own title. */
export function metadataFindings(file: string, source: string): string[] {
  const exported =
    /export (?:const|let|var) metadata\b/.test(source) ||
    /export (?:async )?function generateMetadata\b/.test(source) ||
    [...source.matchAll(/export \{([^}]*)\}/g)].some(([, names]) => /\b(?:metadata|generateMetadata)\b/.test(names));
  return exported ? [`${file} exports metadata`] : [];
}

/** A finding for each React `key` in a file between the root layout and the chrome, which the proof does not render. */
export function keyFindings(file: string, source: string): string[] {
  return /\bkey=/.test(source) ? [`${file} sets a React key`] : [];
}

/** A finding for each `QueryClient` made at module scope, which a server would share across requests. */
export function moduleClientFindings(file: string, source: string): string[] {
  return source
    .split('\n')
    .filter(
      (line) =>
        line.includes('new QueryClient(') &&
        (/^(?:export )?(?:const|let|var) /.test(line) || line.startsWith('new QueryClient('))
    )
    .map(() => `${file} makes a QueryClient at module scope`);
}

const PAGE = '/src/app/(signed-in)/files/page.tsx';
const CONFORMING = `import dynamic from 'next/dynamic';
const FilesView = dynamic(() => import('../../../routes/areas/files').then((m) => m.FilesView), {ssr: false});
export default function FilesPage() {
  return <FilesView />;
}`;

describe('the page rules, against fixtures', () => {
  it('pass a page that reaches its view client-only and reads no props', () => {
    expect(pageFindings({[PAGE]: CONFORMING})).toEqual([]);
  });

  it('name a static import of a feature', () => {
    const source = `import {FilesView} from '../../../routes/areas/files';\n${CONFORMING}`;
    expect(pageFindings({[PAGE]: source})).toEqual([`${PAGE} imports ../../../routes/areas/files statically`]);
  });

  it('name a static import from a file beside the page', () => {
    const mount =
      "'use client';\nimport {Thing} from '../../../features/file-browser';\nexport function Mount() { return null; }";
    expect(pageFindings({[PAGE]: CONFORMING, '/src/app/(signed-in)/files/Mount.tsx': mount})).toEqual([
      '/src/app/(signed-in)/files/Mount.tsx imports ../../../features/file-browser statically'
    ]);
  });

  it('name next/dynamic without ssr: false', () => {
    const source = CONFORMING.replace(', {ssr: false}', '');
    expect(pageFindings({[PAGE]: source})).toEqual([
      `${PAGE} loads through next/dynamic without ssr: false`,
      `${PAGE} reaches no view through dynamic(…, {ssr: false})`
    ]);
  });

  it('name a declared parameter', () => {
    const source = CONFORMING.replace('FilesPage()', 'FilesPage({params}: {params: Promise<object>})');
    expect(pageFindings({[PAGE]: source})).toEqual([
      `${PAGE} declares a parameter ({params}: {params: Promise<object>})`
    ]);
  });

  it('name the root layout reaching the app, and a mount without ssr: false', () => {
    const layout = "import {PortalMount} from './PortalMount';\nimport {cx} from '../lib/cx';";
    const mount = "const PortalBoot = dynamic(() => import('../PortalBoot').then((m) => m.PortalBoot));";
    expect(rootFindings(layout, mount)).toEqual([
      'layout.tsx imports ../lib/cx statically',
      'PortalMount.tsx loads PortalBoot without ssr: false'
    ]);
  });

  it('name a metadata export, a key in the layout chain and a module-scope client, and pass their absence', () => {
    expect(metadataFindings('a.tsx', 'export const metadata = {title: "x"};')).toEqual(['a.tsx exports metadata']);
    expect(metadataFindings('a.tsx', 'export async function generateMetadata() {}')).toEqual([
      'a.tsx exports metadata'
    ]);
    expect(metadataFindings('a.tsx', 'const metadata = 1;')).toEqual([]);
    expect(keyFindings('a.tsx', '<Frame key={pathname}>')).toEqual(['a.tsx sets a React key']);
    expect(moduleClientFindings('a.ts', 'export const client = new QueryClient({});')).toEqual([
      'a.ts makes a QueryClient at module scope'
    ]);
    expect(moduleClientFindings('a.ts', 'export function make() {\n  return new QueryClient({});\n}')).toEqual([]);
  });
});

describe('the App Router’s files', () => {
  const appFiles = Object.keys(SOURCES).filter((file) => file.startsWith('/src/app/') && !isTest(file));
  const pages = appFiles.filter((file) => file.endsWith('/page.tsx'));

  it('include the catch-all page and the root layout', () => {
    expect(pages).toContain('/src/app/[[...slug]]/page.tsx');
    expect(appFiles).toContain('/src/app/layout.tsx');
  });

  it('keep every page and its neighbours off the application graph', () => {
    const findings = pages.flatMap((page) => {
      const directory = page.slice(0, page.lastIndexOf('/') + 1);
      const neighbours = appFiles.filter(
        (file) => file.startsWith(directory) && !file.slice(directory.length).includes('/') && /\.tsx?$/.test(file)
      );
      return pageFindings(Object.fromEntries(neighbours.map((file) => [file, SOURCES[file]])));
    });
    expect(findings).toEqual([]);
  });

  it('reach the boot only through the root layout’s client-only mount', () => {
    expect(rootFindings(SOURCES['/src/app/layout.tsx'], SOURCES['/src/app/PortalMount.tsx'])).toEqual([]);
  });

  it('export no metadata, so a page’s own title is the one the tab shows', () => {
    expect(appFiles.flatMap((file) => metadataFindings(file, SOURCES[file]))).toEqual([]);
    expect(SOURCES['/src/app/layout.tsx']).toMatch(/<title>Data Quarry<\/title>/);
  });

  it('set no React key between the root layout and the chrome', () => {
    const chain = ['/src/app/layout.tsx', '/src/app/PortalMount.tsx', '/src/PortalBoot.tsx', '/src/AppFrame.tsx'];
    expect(chain.flatMap((file) => keyFindings(file, SOURCES[file]))).toEqual([]);
  });
});

describe('the query client', () => {
  it('is never made at module scope', () => {
    const findings = Object.entries(SOURCES)
      .filter(([file]) => !isTest(file) && !file.startsWith('/src/test/'))
      .flatMap(([file, source]) => moduleClientFindings(file, source));
    expect(findings).toEqual([]);
  });
});
