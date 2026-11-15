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
const REBUILD = 'run `npm run build -- --analyze` first';

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

/**
 * Every check, run against the build and its analysis in `dir/.next`.
 *
 * @param {string} dir - The portal's directory.
 * @param {(dir: string) => object[]} exportGraph - Reads the analysis; `exportAnalysis` but in a test.
 * @returns {{findings: string[], routes: number, chunks: number}} What failed, and what was read.
 */
export function run(dir, exportGraph = exportAnalysis) {
  const statsFile = join(dir, '.next/diagnostics/route-bundle-stats.json');
  const historyFile = join(dir, '.next/diagnostics/analyze/history/history.json');
  const none = (finding) => ({findings: [finding], routes: 0, chunks: 0});
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
  return {
    findings: [
      ...shapeFindings(outputs, stats, shapeOf),
      ...reachFindings(outputs, routes),
      ...graphFindings(outputs),
      ...loaderFindings(outputs)
    ],
    routes: new Set(outputs.map((output) => output.route)).size,
    chunks: outputs.length
  };
}
