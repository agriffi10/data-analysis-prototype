// The checks behind `npm run check:pages` (`assert-pages-hydrate-no-app-graph.mjs`), which says what
// they hold and why. Kept apart from that entry point so the corpus imports them without running it.
import {spawnSync} from 'node:child_process';
import {readdirSync, readFileSync, statSync} from 'node:fs';
import {createRequire} from 'node:module';
import {join} from 'node:path';
import vm from 'node:vm';

/** The prefix the analysis gives every source file in the portal's workspace. */
export const WORKSPACE = '[project]/apps/portal/';

/**
 * The portal's own source a page may hydrate: the App Router's files, what lint keeps off the graph,
 * the types `src/lib/` reads constants from, and media, which is not code.
 */
export const HYDRATION_ROOTS = ['src/app/', 'src/lib/', 'src/hooks/', 'src/types/', 'src/assets/'];

/** How to make the analysis this check reads. */
const REBUILD = 'run `npm run build -- --analyze` in apps/portal first';

/**
 * Whether a source file is the portal's own and outside what a page may hydrate.
 *
 * @param {string} source - A source path or module ident as the analysis names it.
 * @returns {boolean} True for a file of the portal's workspace outside `HYDRATION_ROOTS`.
 */
export function outsideHydrationRoots(source) {
  if (!source.startsWith(WORKSPACE)) return false;
  const path = source.slice(WORKSPACE.length);
  return !HYDRATION_ROOTS.some((root) => path.startsWith(root));
}

/**
 * Every JavaScript file each route loads at hydration, with what the analysis says it holds.
 *
 * A file is loaded at hydration when any of the route's chunk groups but a lazy one lists it; a file
 * a lazy group lists as well is still loaded at hydration.
 *
 * @param {object[]} records - The analysis, one record per line of `next analyze export`.
 * @returns {{route: string, filename: string, coverage: string | null, members: number,
 *   sources: Set<string>, loaders: string[], triggers: Set<string>}[]} One entry per route and file.
 */
export function hydrationOutputs(records) {
  const paths = new Map(
    records.filter((record) => record.type === 'module').map((record) => [record.ident, record.path])
  );
  const outputs = new Map();
  const key = (route, filename) => `${route}\u0000${filename}`;
  for (const group of records) {
    if (group.type !== 'group' || group.kind === 'async') continue;
    for (const filename of group.outputs) {
      if (!filename.endsWith('.js')) continue;
      const id = key(group.route, filename);
      if (!outputs.has(id)) {
        outputs.set(id, {
          route: group.route,
          filename,
          coverage: null,
          members: 0,
          sources: new Set(),
          loaders: [],
          triggers: new Set()
        });
      }
      if (group.trigger_module_ident) {
        outputs.get(id).triggers.add(paths.get(group.trigger_module_ident) ?? group.trigger_module_ident);
      }
    }
  }
  for (const record of records) {
    const output = outputs.get(key(record.route, record.filename));
    if (!output) continue;
    if (record.type === 'output') {
      output.coverage = record.coverage;
      output.members = record.modules.length + record.async_loaders.length;
      output.loaders = record.async_loaders;
      for (const ident of record.modules) output.sources.add(paths.get(ident) ?? ident);
    }
    if (record.type === 'part') output.sources.add(record.source_path);
  }
  return [...outputs.values()];
}

/** A source path as a reader of the portal finds it. */
const display = (source) => (source.startsWith(WORKSPACE) ? source.slice(WORKSPACE.length) : source);

/** The portal's files whose chunk groups list an output, or, without one, every trigger. */
function loadedWith(output) {
  const triggers = [...output.triggers].map(display);
  const own = triggers.filter((trigger) => trigger.startsWith('src/'));
  return (own.length > 0 ? own : triggers).sort().join(', ');
}

/**
 * The portal's own modules outside `HYDRATION_ROOTS` that a route hydrates.
 *
 * @param {ReturnType<typeof hydrationOutputs>} outputs - The routes' hydration files.
 * @returns {string[]} A finding per route, module and file, naming the files that load it.
 */
export function graphFindings(outputs) {
  const findings = new Set();
  for (const output of outputs) {
    for (const source of output.sources) {
      if (outsideHydrationRoots(source)) {
        findings.add(`${output.route} hydrates ${display(source)}, in a chunk loaded with ${loadedWith(output)}`);
      }
    }
  }
  return [...findings].sort();
}

/**
 * The lazy loads a route hydrates of the portal's own code outside `HYDRATION_ROOTS` that are not
 * `next/dynamic` ones. A lazy load of a package, or of what a page may hydrate anyway, is no escape.
 *
 * @param {ReturnType<typeof hydrationOutputs>} outputs - The routes' hydration files.
 * @returns {string[]} A finding per route and loaded module.
 */
export function loaderFindings(outputs) {
  const findings = new Set();
  for (const output of outputs) {
    for (const loader of output.loaders) {
      if (outsideHydrationRoots(loader) && !/next\/dynamic entry\)$/.test(loader)) {
        findings.add(`${output.route} hydrates a lazy load of ${display(loader)} that is not next/dynamic`);
      }
    }
  }
  return [...findings];
}

/**
 * The routes whose hydration code the analysis cannot be trusted to have described.
 *
 * A route that ships must have hydration files the analysis lists modules for, and some of that code
 * must be the App Router's own: without either, the checks above would pass a route they never read.
 *
 * @param {ReturnType<typeof hydrationOutputs>} outputs - The routes' hydration files.
 * @param {string[]} routes - The routes the build ships to a browser.
 * @returns {string[]} A finding per route or file that cannot be judged.
 */
export function reachFindings(outputs, routes) {
  const findings = [];
  for (const output of outputs) {
    if (output.coverage !== 'exact' && output.coverage !== 'not_a_chunk') {
      findings.push(
        `${output.route}: the analysis cannot list the modules in ${output.filename} (${output.coverage ?? 'no record'})`
      );
    }
  }
  for (const route of routes) {
    const own = outputs.some(
      (output) =>
        output.route === route && [...output.sources].some((source) => source.startsWith(`${WORKSPACE}src/app/`))
    );
    if (!own)
      findings.push(`${route}: the analysis attributes none of its hydration code to src/app/, so it cannot be judged`);
  }
  return findings;
}

/**
 * How many modules a shipped chunk registers, or `'none'` for a file that registers none.
 *
 * A Turbopack chunk pushes `[script, id, factory, id, id, factory, …]`: several ids before one factory
 * are one module the bundler merged, which the analysis lists once, so factories are what is counted.
 * The code runs in an empty context, where pushing an array is all a chunk does at load.
 *
 * @param {string} code - The chunk's source.
 * @returns {number | 'none'} The number of module factories it pushes.
 */
export function chunkShape(code) {
  const context = vm.createContext({});
  try {
    vm.runInContext(code, context, {timeout: 1000});
  } catch {
    return 'none';
  }
  const pushed = context.TURBOPACK;
  if (!Array.isArray(pushed)) return 'none';
  return pushed.reduce((count, entry) => count + entry.slice(1).filter((item) => typeof item === 'function').length, 0);
}

/**
 * The routes whose hydration chunks, as the analysis describes them, are not the ones the build ships.
 *
 * @param {ReturnType<typeof hydrationOutputs>} outputs - The routes' hydration files.
 * @param {{route: string, firstLoadChunkPaths: string[]}[]} stats - The build's route statistics.
 * @param {(file: string) => number | string} shapeOf - A shipped file's module count, by its path.
 * @returns {string[]} A finding per route that does not match.
 */
export function shapeFindings(outputs, stats, shapeOf) {
  const findings = [];
  for (const {route, firstLoadChunkPaths} of stats) {
    const analysed = outputs
      .filter((output) => output.route === route)
      .map((output) => (output.coverage === 'exact' ? output.members : 'none'))
      .sort();
    const shipped = firstLoadChunkPaths
      .filter((file) => file.endsWith('.js'))
      .map(shapeOf)
      .sort();
    if (analysed.length === 0) {
      findings.push(`${route}: the build ships this page, and the analysis has no hydration chunks for it`);
    } else if (JSON.stringify(analysed) !== JSON.stringify(shipped)) {
      findings.push(
        `${route}: the analysis does not describe the chunks this build ships (modules per chunk: ${analysed.join(', ')} analysed, ${shipped.join(', ')} shipped)`
      );
    }
  }
  return findings;
}

/**
 * The analysis as `next analyze export` streams it.
 *
 * @param {string} dir - The portal's directory.
 * @returns {object[]} One record per line.
 * @throws {Error} When the export does not exit 0, which is the only sign its output is whole.
 */
export function exportAnalysis(dir) {
  const next = createRequire(join(dir, 'package.json')).resolve('next/dist/bin/next');
  const result = spawnSync(process.execPath, [next, 'analyze', 'export'], {
    cwd: dir,
    encoding: 'utf8',
    maxBuffer: 1 << 28,
    env: {...process.env, NEXT_TELEMETRY_DISABLED: '1'}
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(
      `next analyze export exited ${result.status}: ${result.stderr.trim().split('\n').slice(-2).join(' ')}`
    );
  }
  return result.stdout
    .split('\n')
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line));
}

/**
 * When the analysis's data was last written, or `NaN` when it has none.
 *
 * A build writes the data, then its route statistics, then the snapshot `next analyze export` reads;
 * `next analyze`, which builds nothing, writes data and a snapshot after the statistics it leaves.
 * So an analysis is the build's own only when the statistics fall between its data and its snapshot.
 *
 * @param {string} dir - The portal's directory.
 * @returns {number} The newest data file's modification time, in whole milliseconds.
 */
function analysedFrom(dir) {
  const data = join(dir, '.next/diagnostics/analyze/data');
  try {
    const times = readdirSync(data, {recursive: true})
      .map(String)
      .filter((file) => file.endsWith('.data'))
      .map((file) => statSync(join(data, file)).mtimeMs);
    return times.length > 0 ? Math.floor(Math.max(...times)) : NaN;
  } catch {
    return NaN;
  }
}

/** The module the boot loads once the configuration is in hand: the providers, the chrome, the shell. */
const FRAME = `${WORKSPACE}src/AppFrame.tsx`;

/** The module that loads it, behind `next/dynamic`, on every page. Its own lazy group is on every page too. */
const BOOT = `${WORKSPACE}src/PortalBoot.tsx`;

/**
 * The most of the portal's own source the boot and the frame may carry between them, in bytes
 * before compression.
 *
 * Both are loaded on every page, the signed-out landing page included, so a feature's page that
 * arrives in either is paid for by everyone. That happens without any import of the page: the shell
 * takes one hook through a feature's barrel, and a bundler not told the modules are free of side
 * effects keeps everything the barrel re-exports.
 *
 * THE RULE BOTH NUMBERS FOLLOW: the measure `check:pages` prints on a passing build, plus a sixth
 * for the budget and less a sixth for the floor, each rounded to the thousand. Re-derive from that
 * line, not from a figure written here. A sixth is room for a few shell components. It is NOT
 * smaller than every feature: several fit inside it whole, which is why the features and folders
 * allowed here are named below and fail at any size.
 */
export const FRAME_BUDGET_BYTES = 275_000;

/**
 * The least they are expected to carry. A budget only fires for something larger than its headroom,
 * so once the measure falls well below it the budget has gone quiet without anyone deciding that.
 * Falling under this has two causes and the finding names both: the frame really shrank (lower both
 * numbers), or code moved out of the two groups this reads into another one every page loads.
 */
export const FRAME_FLOOR_BYTES = 197_000;

/**
 * The packages the shell needs: server state, the focus trap its dialogs and drawers use, and the
 * framework, whose `next/dynamic` and navigation the boot and the seam import. A package is named
 * by the innermost `node_modules` folder its path passes through.
 */
export const FRAME_PACKAGES = [
  '@tanstack/query-core',
  '@tanstack/react-query',
  'focus-trap',
  'focus-trap-react',
  'tabbable',
  'next'
];

/**
 * What of `src/` the boot and the frame are built from. A page lives under `routes/` and nothing
 * here may import one, so anything else of the portal's own fails at any size.
 */
export const FRAME_FOLDERS = [
  'AppChrome.tsx',
  'AppFrame.tsx',
  'PortalBoot.tsx',
  'components',
  'features',
  'hooks',
  'lib',
  'types'
];

/**
 * The features the shell uses a piece of: its providers, its header's controls, its background
 * hooks. One not named has no business on every page at any size. One that IS named can still leak
 * its page, and only the budget sees that: a named feature smaller than the headroom can arrive
 * whole and pass, which is this check's known limit.
 */
export const FRAME_FEATURES = [
  'auth',
  'catalog',
  'data-explorer',
  'feature-flags',
  'feedback',
  'file-browser',
  'help',
  'notifications',
  'query',
  'table-builder'
];

/** The own modules every route's hydration may load lazily: the boot, and the page for an address no route serves. */
const EVERY_ROUTE_LOADS = [BOOT, `${WORKSPACE}src/routes/NotFoundPage.tsx`];

/** The packages a page hydrates with: the framework and its compiler's helpers. Turbopack's runtime is not a package. */
export const HYDRATION_PACKAGES = ['next', '@swc/helpers'];

/** Where a source comes from: one of the portal's folders, a package, or neither. */
function frameOrigin(source) {
  if (source.startsWith(`${WORKSPACE}src/`)) {
    const [first, second] = source.slice(`${WORKSPACE}src/`.length).split('/');
    return {own: true, folder: first, name: first === 'features' ? `features/${second}` : first};
  }
  const packaged = [...source.matchAll(/node_modules\/((?:@[^/]+\/)?[^/]+)/g)].pop();
  return {
    own: false,
    name: packaged ? `the package ${packaged[1]}` : `${source}, which is neither the portal's nor a package's`
  };
}

/**
 * What every page loads before its own view, on each route that boots the portal: the boot's lazy
 * group and the frame's, judged together. Read apart, code that moves from the frame into the
 * boot's group would lower the measure while staying on every page.
 *
 * Judged by what they may not hold at all (a package, a folder of `src/` or a feature the shell
 * does not use), by how much of the portal's own source they hold, and by whether they could be
 * measured.
 *
 * AND BY THEIR LAZY EDGES, which is what closes the set. Two groups are read because two modules
 * are known to load them. A third group on every page can only come from a lazy load nobody named,
 * so every lazy load in what is read must be a named one: inside the boot's and the frame's files
 * only the frame itself, and from every route's hydration only the boot and the not-found page.
 * Anything else is a finding at any size, and it names the module, not the group.
 *
 * Hydration's packages are named too (`HYDRATION_PACKAGES`): a package a page imports through
 * `src/lib/` is on every page before any of this runs.
 *
 * A group is the boot's or the frame's when the MODULE its trigger names is that file, read from
 * the module's own record: an ident can quote another module's path. Only what the browser is
 * served is counted, and a part the analysis lists twice for one file, as it does on a route with
 * two entries, is counted once. NOT judged: a lazy load shared by several routes and not by all.
 *
 * @param {object[]} records - The analysis, one record per line of `next analyze export`.
 * @returns {{findings: string[], bytes: number}} A finding per defect, naming the first route that
 *   has it and how many more do, and the most own source any route carries there.
 */
export function frameFindings(records) {
  const paths = new Map(
    records.filter((record) => record.type === 'module').map((record) => [record.ident, record.path])
  );
  const boots = new Set();
  const framed = new Set();
  const loaded = new Map();
  for (const group of records) {
    if (group.type !== 'group' || group.kind !== 'async') continue;
    const trigger = paths.get(group.trigger_module_ident);
    if (trigger !== BOOT && trigger !== FRAME) continue;
    (trigger === BOOT ? boots : framed).add(group.route);
    const served = group.outputs.filter((file) => file.startsWith('[client-fs]/'));
    loaded.set(group.route, new Set([...(loaded.get(group.route) ?? []), ...served]));
  }
  if (boots.size === 0) {
    return {
      findings: [
        'no route boots the portal, so there is no frame to judge: no lazy group is loaded from src/PortalBoot.tsx'
      ],
      bytes: 0
    };
  }

  const where = new Map();
  const report = (finding, route) => where.set(finding, (where.get(finding) ?? new Set()).add(route));
  const short = (file) => file.split('/').pop();
  const moduleOf = (ident) => paths.get(ident) ?? ident.replace(/ \[.*$/, '');

  // What every route hydrates: its lazy loads of the portal's own code, and its packages.
  const hydrated = new Map();
  for (const output of hydrationOutputs(records)) {
    for (const loader of output.loaders.map(moduleOf)) {
      if (loader.startsWith(WORKSPACE)) hydrated.set(loader, (hydrated.get(loader) ?? new Set()).add(output.route));
    }
    for (const source of output.sources) {
      const origin = frameOrigin(source);
      if (origin.own || source.startsWith(WORKSPACE) || source.startsWith('[turbopack]/')) continue;
      if (!HYDRATION_PACKAGES.some((name) => origin.name === `the package ${name}`)) {
        report(
          `a page's hydration carries ${origin.name}: an import in what a page loads at once reaches it`,
          output.route
        );
      }
    }
  }
  // With one route there is nothing to compare: its own view is loaded from "every" route too.
  for (const [loader, routes] of boots.size > 1 ? hydrated : []) {
    if (EVERY_ROUTE_LOADS.includes(loader) || ![...boots].every((route) => routes.has(route))) continue;
    report(
      `every route's hydration lazily loads ${display(loader)}: only the boot and the not-found page are loaded from every route, and this is a group on every page that nothing measures`,
      [...routes].sort()[0]
    );
  }

  let most = 0;
  for (const route of [...new Set([...boots, ...framed])].sort()) {
    const served = loaded.get(route) ?? new Set();
    const files = new Set([...served].filter((file) => file.endsWith('.js')));
    if (!boots.has(route)) {
      report('a route loads the frame without the boot: no lazy group is loaded from src/PortalBoot.tsx', route);
      continue;
    }
    if (!framed.has(route) || ![...files].length) {
      report('a route boots the portal and has no frame: no lazy group is loaded from src/AppFrame.tsx', route);
      continue;
    }
    let measurable = true;
    for (const file of served) {
      if (!file.endsWith('.js') && !file.endsWith('.css')) {
        report(`a frame file cannot be measured: ${short(file)} is neither a script nor a stylesheet`, route);
        measurable = false;
      }
    }
    const coverage = new Map();
    const parts = new Map();
    for (const record of records) {
      if (record.route !== route || !files.has(record.filename)) continue;
      if (record.type === 'output') {
        coverage.set(record.filename, record.coverage);
        for (const loader of (record.async_loaders ?? []).map(moduleOf)) {
          if (loader === FRAME) continue;
          report(
            `every page lazily loads ${display(loader)} from the boot or the frame, where only src/AppFrame.tsx may be: that is a group of its own on every page, and nothing measures it`,
            route
          );
        }
      }
      if (record.type === 'part') {
        parts.set(`${record.filename}\u0000${record.source_path}\u0000${record.size}`, record);
      }
    }
    for (const file of files) {
      const sizes = [...parts.values()].filter((part) => part.filename === file).map((part) => part.size);
      if (coverage.get(file) !== 'exact') {
        report(`a frame file cannot be measured: ${short(file)} has coverage ${coverage.get(file) ?? 'none'}`, route);
        measurable = false;
      } else if (sizes.length === 0 || !sizes.every((size) => Number.isFinite(size) && size >= 0)) {
        report(`a frame file cannot be measured: ${short(file)} lists no source, or one without a size`, route);
        measurable = false;
      }
    }
    if (!measurable) continue;

    const folders = new Map();
    for (const part of parts.values()) {
      const origin = frameOrigin(part.source_path);
      if (!origin.own) {
        if (!FRAME_PACKAGES.some((name) => origin.name === `the package ${name}`)) {
          report(
            `every page loads ${origin.name}; the shell is not known to need it, so an import in the boot's or the shell's graph reaches it`,
            route
          );
        }
        continue;
      }
      if (!FRAME_FOLDERS.includes(origin.folder)) {
        report(
          `every page loads src/${origin.folder}, which is not what the boot and the frame are built from: an import in their graph reaches it`,
          route
        );
      } else if (origin.folder === 'features' && !FRAME_FEATURES.includes(origin.name.slice('features/'.length))) {
        report(`every page loads src/${origin.name}/, a feature the shell is not known to use`, route);
      }
      folders.set(origin.name, (folders.get(origin.name) ?? 0) + part.size);
    }
    const total = [...folders.values()].reduce((sum, size) => sum + size, 0);
    most = Math.max(most, total);
    if (total > FRAME_BUDGET_BYTES) {
      const largest = [...folders]
        .sort(([, a], [, b]) => b - a)
        .slice(0, 4)
        .map(([name, size]) => `${name} ${size}`)
        .join(', ');
      report(
        `every page loads ${total} bytes of the portal's own source before its view, over the budget of ${FRAME_BUDGET_BYTES}: the largest are ${largest}`,
        route
      );
    } else if (total < FRAME_FLOOR_BYTES) {
      report(
        `every page loads ${total} bytes of the portal's own source before its view, under the ${FRAME_FLOOR_BYTES} the budget of ${FRAME_BUDGET_BYTES} expects: either it shrank, and FRAME_BUDGET_BYTES and FRAME_FLOOR_BYTES are lowered to fit, or code moved into a group this does not read`,
        route
      );
    }
  }
  const findings = [...where].map(([finding, routes]) => {
    const [first, ...rest] = routes;
    return `${finding} (on ${first}${rest.length > 0 ? ` and ${rest.length} more` : ''})`;
  });
  return {findings: findings.sort(), bytes: most};
}

/**
 * Every check, run against the build and its analysis in `dir/.next`.
 *
 * @param {string} dir - The portal's directory.
 * @param {(dir: string) => object[]} exportGraph - Reads the analysis; `exportAnalysis` but in a test.
 * @returns {{findings: string[], routes: number, chunks: number, frameBytes: number}} What failed,
 *   and what was read.
 */
export function run(dir, exportGraph = exportAnalysis) {
  const statsFile = join(dir, '.next/diagnostics/route-bundle-stats.json');
  const historyFile = join(dir, '.next/diagnostics/analyze/history/history.json');
  const none = (finding) => ({findings: [finding], routes: 0, chunks: 0, frameBytes: 0});
  let stats;
  let history;
  try {
    stats = JSON.parse(readFileSync(statsFile, 'utf8'));
  } catch {
    return none(`no build to check: ${statsFile} is unreadable — ${REBUILD}.`);
  }
  try {
    history = JSON.parse(readFileSync(historyFile, 'utf8'));
  } catch {
    return none(`no bundle analysis to check: ${historyFile} is unreadable — ${REBUILD}.`);
  }
  let records;
  try {
    records = exportGraph(dir);
  } catch (error) {
    return none(`the bundle analysis could not be read: ${error.message}`);
  }
  const name = records.find((record) => record.type === 'meta')?.snapshot_name;
  const createdAt = Date.parse(history.snapshots?.find((snapshot) => snapshot.name === name)?.createdAt);
  const builtAt = Math.floor(statSync(statsFile).mtimeMs);
  if (!(analysedFrom(dir) <= builtAt && createdAt >= builtAt)) {
    return none(
      `the bundle analysis is not this build's (analysed ${name ?? 'never'}, built ${new Date(builtAt).toISOString()}) — ${REBUILD}.`
    );
  }
  if (stats.length === 0) return none('the build lists no routes, so there is nothing to judge.');
  const outputs = hydrationOutputs(records);
  const shapeOf = (file) => {
    try {
      return chunkShape(readFileSync(join(dir, file), 'utf8'));
    } catch {
      return 'missing';
    }
  };
  const routes = stats.map((entry) => entry.route);
  const frame = frameFindings(records);
  return {
    findings: [
      ...shapeFindings(outputs, stats, shapeOf),
      ...reachFindings(outputs, routes),
      ...graphFindings(outputs),
      ...loaderFindings(outputs),
      ...frame.findings
    ],
    routes: new Set(outputs.map((output) => output.route)).size,
    chunks: outputs.length,
    frameBytes: frame.bytes
  };
}
