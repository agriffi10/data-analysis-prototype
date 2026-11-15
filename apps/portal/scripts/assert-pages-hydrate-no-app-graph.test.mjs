import {spawnSync} from 'node:child_process';
import {mkdirSync, mkdtempSync, rmSync, utimesSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {afterEach, describe, expect, it} from 'vitest';
import {
  chunkShape,
  exportAnalysis,
  graphFindings,
  hydrationOutputs,
  loaderFindings,
  reachFindings,
  run,
  shapeFindings
} from './page-hydration.mjs';

/**
 * The page gate's corpus: each check against an analysis shaped like the Files page's, each finding
 * asserted by its text, and each shape a page may hydrate asserted silent.
 */

const ROUTE = '/files';
const PAGE = 'src/app/(signed-in)/files/page.tsx';
const src = (path) => `[project]/apps/portal/${path}`;
const ident = (path, kind = '(ecmascript)') => `${path} [app-client] ${kind}`;
const lazy = (path) => ident(path, '(ecmascript, next/dynamic entry)');
const chunk = (name) => `[client-fs]/_next/static/chunks/${name}`;

/**
 * An analysis of one route, as `next analyze export` streams it: Next's bootstrap and runtime, the
 * root layout's mount, the page and its hook, and the view behind `next/dynamic`.
 *
 * @param {object} [change] - Edits: `modules` adds modules to a file with their parts, `bare` adds
 *   modules without one, as the analysis lists many, `parts` adds parts alone, as a module merged into
 *   another has, `loaders` adds lazy loads, and `groups` replaces the chunk groups.
 * @returns {object[]} The records.
 */
function analysis(change = {}) {
  const files = {
    'boot.js': {modules: ['[project]/node_modules/next/dist/client/app-next-turbopack.js'], coverage: 'exact'},
    'runtime.js': {modules: [], coverage: 'not_a_chunk', parts: ['[turbopack]/browser/runtime/base/runtime-base.ts']},
    'layout.js': {
      modules: [src('src/app/PortalMount.tsx')],
      loaders: [lazy(src('src/PortalBoot.tsx'))],
      coverage: 'exact'
    },
    'page.js': {
      modules: [src(PAGE), src('src/hooks/usePageTitle.ts')],
      parts: [src('src/lib/formatPageTitle.ts')],
      loaders: [lazy(src('src/routes/areas/files.tsx'))],
      coverage: 'exact'
    },
    'view.js': {
      modules: [src('src/routes/areas/files.tsx'), src('src/features/file-browser/index.ts')],
      coverage: 'exact'
    },
    'page.css': {modules: [src('src/index.css')], coverage: 'exact'}
  };
  for (const [name, edit] of Object.entries(change.files ?? {})) {
    files[name] = {
      modules: [...(files[name]?.modules ?? []), ...(edit.modules ?? [])],
      bare: [...(files[name]?.bare ?? []), ...(edit.bare ?? [])],
      parts: [...(files[name]?.parts ?? []), ...(edit.parts ?? [])],
      loaders: [...(files[name]?.loaders ?? []), ...(edit.loaders ?? [])],
      coverage: edit.coverage ?? files[name]?.coverage ?? 'exact'
    };
  }
  const groups = change.groups ?? [
    {
      kind: 'bootstrap',
      trigger: '[project]/node_modules/next/dist/client/app-next-turbopack.js',
      outputs: ['boot.js', 'runtime.js']
    },
    {kind: 'render_dependent', trigger: src('src/app/PortalMount.tsx'), outputs: ['layout.js', 'page.css']},
    {kind: 'render_dependent', trigger: src(PAGE), outputs: ['layout.js', 'page.js', 'page.css']},
    {kind: 'async', trigger: lazy(src('src/routes/areas/files.tsx')), outputs: ['view.js']}
  ];
  const paths = new Set(
    Object.values(files).flatMap((file) => [...file.modules, ...(file.bare ?? []), ...(file.loaders ?? [])])
  );
  paths.add(src(PAGE));
  for (const group of groups) paths.add(group.trigger.replace(/ \[app-client\].*$/, ''));
  return [
    {type: 'meta', schema_version: 1, snapshot_name: 'snap'},
    ...[...paths].map((path) => ({
      type: 'module',
      ident: path.includes(' [') ? path : ident(path),
      path: path.replace(/ \[app-client\].*$/, '')
    })),
    {type: 'route', route: ROUTE, coverage: {entries: 'exact', groups: 'exact'}},
    ...Object.entries(files).map(([name, file]) => ({
      type: 'output',
      route: ROUTE,
      filename: chunk(name),
      modules: [...file.modules, ...(file.bare ?? [])].map((path) => ident(path)),
      async_loaders: file.loaders ?? [],
      coverage: file.coverage
    })),
    ...Object.entries(files).flatMap(([name, file]) =>
      [...file.modules, ...(file.parts ?? [])].map((source) => ({
        type: 'part',
        route: ROUTE,
        filename: chunk(name),
        source_path: source
      }))
    ),
    ...groups.map((group, id) => ({
      type: 'group',
      route: ROUTE,
      id,
      kind: group.kind,
      trigger_module_ident: group.trigger.includes(' [') ? group.trigger : ident(group.trigger),
      outputs: group.outputs.map(chunk)
    }))
  ];
}

/** Every check that reads the analysis alone. */
const judged = (records) => {
  const outputs = hydrationOutputs(records);
  return [...reachFindings(outputs, [ROUTE]), ...graphFindings(outputs), ...loaderFindings(outputs)];
};

/** A source added to the page's chunk, in the analysis's parts only, as a module merged into another is. */
const inPageParts = (path) => analysis({files: {'page.js': {parts: [src(path)]}}});

describe('the page gate’s analysis checks', () => {
  it('pass the shape a page has today, and judge neither its view nor its stylesheet', () => {
    expect(judged(analysis())).toEqual([]);
    expect(hydrationOutputs(analysis()).map((output) => output.filename.split('/').pop())).toEqual([
      'boot.js',
      'runtime.js',
      'layout.js',
      'page.js'
    ]);
  });

  it('name each application-graph module a page hydrates, by route and the files that load it', () => {
    for (const path of [
      'src/AppFrame.tsx',
      'src/AppChrome.tsx',
      'src/PortalBoot.tsx',
      'src/AppShell.tsx',
      'src/features/file-browser/index.ts',
      'src/components/LoadingState.tsx',
      'src/routes/table.tsx',
      'src/server/runtimeDocument.ts'
    ]) {
      expect(judged(inPageParts(path))).toEqual([`${ROUTE} hydrates ${path}, in a chunk loaded with ${PAGE}`]);
    }
    expect(judged(analysis({files: {'page.js': {bare: [src('src/features/x/index.ts')]}}}))).toEqual([
      `${ROUTE} hydrates src/features/x/index.ts, in a chunk loaded with ${PAGE}`
    ]);
    expect(judged(analysis({files: {'layout.js': {parts: [src('src/AppFrame.tsx')]}}}))).toEqual([
      `${ROUTE} hydrates src/AppFrame.tsx, in a chunk loaded with ${PAGE}, src/app/PortalMount.tsx`
    ]);
    expect(judged(analysis({files: {'boot.js': {parts: [src('src/AppFrame.tsx')]}}}))).toEqual([
      `${ROUTE} hydrates src/AppFrame.tsx, in a chunk loaded with [project]/node_modules/next/dist/client/app-next-turbopack.js`
    ]);
    const untriggered = analysis({files: {'page.js': {parts: [src('src/AppFrame.tsx')]}}}).map((record) =>
      record.type === 'group' && record.kind === 'bootstrap'
        ? {...record, trigger_module_ident: null, outputs: [...record.outputs, chunk('page.js')]}
        : record
    );
    expect(judged(untriggered)).toEqual([`${ROUTE} hydrates src/AppFrame.tsx, in a chunk loaded with ${PAGE}`]);
  });

  it('pass what a page may hydrate: the App Router’s files, lib, hooks, types and packages', () => {
    for (const path of [
      'src/app/(signed-in)/files/_parts/Shell.tsx',
      'src/lib/navigation/address.ts',
      'src/hooks/usePageTitle.ts',
      'src/types/runtimeConfig.types.ts',
      'src/assets/hero.png'
    ]) {
      expect(judged(inPageParts(path))).toEqual([]);
    }
    const page = {
      files: {
        'page.js': {parts: ['[project]/node_modules/react/index.js', '[turbopack]/shared/runtime/runtime-utils.ts']}
      }
    };
    expect(judged(analysis(page))).toEqual([]);
  });

  it('judge a lazy group’s chunk once a hydration group lists it too', () => {
    const groups = [
      {kind: 'render_dependent', trigger: src(PAGE), outputs: ['layout.js', 'page.js', 'view.js']},
      {kind: 'async', trigger: lazy(src('src/routes/areas/files.tsx')), outputs: ['view.js']}
    ];
    expect(judged(analysis({groups}))).toEqual(
      [
        `${ROUTE} hydrates src/routes/areas/files.tsx, in a chunk loaded with ${PAGE}`,
        `${ROUTE} hydrates src/features/file-browser/index.ts, in a chunk loaded with ${PAGE}`
      ].sort()
    );
  });

  it('name a lazy load a page hydrates that is not next/dynamic, and pass one that is', () => {
    const loaders = [ident(src('src/features/notifications/index.ts'))];
    expect(judged(analysis({files: {'page.js': {loaders}}}))).toEqual([
      `${ROUTE} hydrates a lazy load of src/features/notifications/index.ts [app-client] (ecmascript) that is not next/dynamic`
    ]);
    expect(judged(analysis({files: {'page.js': {loaders: [lazy(src('src/routes/areas/help.tsx'))]}}}))).toEqual([]);
    const harmless = [ident(src('src/lib/cx.ts')), ident('[project]/node_modules/focus-trap-react/dist/index.js')];
    expect(judged(analysis({files: {'page.js': {loaders: harmless}}}))).toEqual([]);
  });

  it('refuse a route it cannot read: a file without a module list, and code none of which is the App Router’s', () => {
    expect(judged(analysis({files: {'page.js': {coverage: 'unsupported'}}}))).toEqual([
      `${ROUTE}: the analysis cannot list the modules in ${chunk('page.js')} (unsupported)`
    ]);
    const silent = analysis().filter((record) => !(record.type === 'output' && record.filename === chunk('page.js')));
    expect(judged(silent)).toEqual([
      `${ROUTE}: the analysis cannot list the modules in ${chunk('page.js')} (no record)`
    ]);
    const groups = [
      {
        kind: 'bootstrap',
        trigger: '[project]/node_modules/next/dist/client/app-next-turbopack.js',
        outputs: ['boot.js']
      }
    ];
    expect(judged(analysis({groups}))).toEqual([
      `${ROUTE}: the analysis attributes none of its hydration code to src/app/, so it cannot be judged`
    ]);
    expect(reachFindings(hydrationOutputs(analysis()), ['/help'])).toEqual([
      '/help: the analysis attributes none of its hydration code to src/app/, so it cannot be judged'
    ]);
  });
});

describe('the page gate’s tie to the shipped build', () => {
  const push = (body) =>
    `(globalThis.TURBOPACK||(globalThis.TURBOPACK=[])).push(["object"==typeof document?document.currentScript:void 0,${body}]);`;

  it('count a shipped chunk’s modules by factory, and a file that registers none as none', () => {
    expect(chunkShape(push('11,e=>{},22,33,44,e=>{},55,(e,t,r)=>{}'))).toBe(3);
    expect(chunkShape('self.TURBOPACK_RUNTIME=1;')).toBe('none');
    expect(chunkShape('var x = 1;')).toBe('none');
  });

  it('pass a build whose chunks the analysis describes, and name a route whose chunks it does not', () => {
    const outputs = hydrationOutputs(analysis());
    const shipped = {'a.js': 1, 'b.js': 'none', 'c.js': 2, 'd.js': 3};
    const stats = (files) => [{route: ROUTE, firstLoadChunkPaths: [...files, 'x.css']}];
    expect(shapeFindings(outputs, stats(['a.js', 'b.js', 'c.js', 'd.js']), (file) => shipped[file])).toEqual([]);
    expect(shapeFindings(outputs, stats(['a.js', 'b.js', 'c.js', 'c.js']), (file) => shipped[file])).toEqual([
      `${ROUTE}: the analysis does not describe the chunks this build ships (modules per chunk: 1, 2, 3, none analysed, 1, 2, 2, none shipped)`
    ]);
    expect(shapeFindings(outputs, [{route: '/help', firstLoadChunkPaths: ['a.js']}], (file) => shipped[file])).toEqual([
      '/help: the build ships this page, and the analysis has no hydration chunks for it'
    ]);
  });
});

describe('the page gate', () => {
  const dirs = [];
  afterEach(() => {
    for (const dir of dirs.splice(0)) rmSync(dir, {recursive: true, force: true});
  });

  const CHUNKS = ['a.js', 'b.js', 'c.js', 'd.js'].map((name) => `.next/static/chunks/${name}`);

  /**
   * A built portal on disk whose route ships four hydration chunks, matching the analysis.
   *
   * @param {object} [options] - What to date, list or leave out.
   * @param {string} [options.analysedAt] - The analysis snapshot's creation time.
   * @param {Date | null} [options.dataAt] - The analysis data's modification time; `null` leaves it out.
   * @param {string[]} [options.dataFiles] - The data files beside the snapshot's `metadata.json`.
   * @param {Date} [options.builtAt] - The route statistics' modification time.
   * @param {object[] | null} [options.stats] - The route statistics; `null` leaves the file out.
   * @param {boolean} [options.history] - Whether the analysis history exists.
   * @param {string[]} [options.missing] - Chunks to leave out.
   * @returns {string} The portal's directory.
   */
  function built({
    analysedAt = '2026-11-15T12:00:10.000Z',
    dataAt = new Date('2026-11-15T11:59:50.000Z'),
    dataFiles = ['modules.data', 'files/analyze.data'],
    builtAt = new Date('2026-11-15T12:00:00.000Z'),
    stats = [{route: ROUTE, firstLoadChunkPaths: CHUNKS}],
    history = true,
    missing = []
  } = {}) {
    const dir = mkdtempSync(join(tmpdir(), 'page-gate-'));
    dirs.push(dir);
    mkdirSync(join(dir, '.next/static/chunks'), {recursive: true});
    mkdirSync(join(dir, '.next/diagnostics/analyze/history'), {recursive: true});
    const bodies = ['1,e=>{}', null, '1,e=>{},2,e=>{}', '1,e=>{},2,e=>{},3,e=>{}'];
    CHUNKS.forEach((file, index) => {
      if (missing.includes(file)) return;
      const body = bodies[index];
      writeFileSync(
        join(dir, file),
        body === null ? 'self.x=1;' : `(globalThis.TURBOPACK||(globalThis.TURBOPACK=[])).push([null,${body}]);`
      );
    });
    const file = join(dir, '.next/diagnostics/route-bundle-stats.json');
    if (stats) {
      writeFileSync(file, JSON.stringify(stats));
      utimesSync(file, builtAt, builtAt);
    }
    if (dataAt) {
      mkdirSync(join(dir, '.next/diagnostics/analyze/data/files'), {recursive: true});
      for (const data of [...dataFiles, 'metadata.json']) {
        const path = join(dir, '.next/diagnostics/analyze/data', data);
        writeFileSync(path, '');
        const at = data.endsWith('.json') ? new Date(analysedAt) : dataAt;
        utimesSync(path, at, at);
      }
    }
    if (history) {
      writeFileSync(
        join(dir, '.next/diagnostics/analyze/history/history.json'),
        JSON.stringify({snapshots: [{name: 'snap', createdAt: analysedAt}]})
      );
    }
    return dir;
  }

  it('passes a build and its own analysis, and names a finding in it', () => {
    expect(run(built(), () => analysis())).toEqual({findings: [], routes: 1, chunks: 4});
    expect(run(built(), () => inPageParts('src/AppFrame.tsx')).findings).toEqual([
      `${ROUTE} hydrates src/AppFrame.tsx, in a chunk loaded with ${PAGE}`
    ]);
  });

  it('reports every check’s findings together: the shipped chunks, the reach, the graph and the lazy loads', () => {
    const stats = [
      {route: ROUTE, firstLoadChunkPaths: CHUNKS},
      {route: '/help', firstLoadChunkPaths: [CHUNKS[0]]}
    ];
    const loaders = [ident(src('src/features/x/index.ts'))];
    const records = analysis({files: {'page.js': {parts: [src('src/AppFrame.tsx')], loaders}}});
    expect(run(built({stats, missing: [CHUNKS[1]]}), () => records).findings).toEqual([
      `${ROUTE}: the analysis does not describe the chunks this build ships (modules per chunk: 1, 2, 4, none analysed, 1, 2, 3, missing shipped)`,
      '/help: the build ships this page, and the analysis has no hydration chunks for it',
      '/help: the analysis attributes none of its hydration code to src/app/, so it cannot be judged',
      `${ROUTE} hydrates src/AppFrame.tsx, in a chunk loaded with ${PAGE}`,
      `${ROUTE} hydrates a lazy load of src/features/x/index.ts [app-client] (ecmascript) that is not next/dynamic`
    ]);
  });

  it('refuses an analysis older than the build, one it cannot read, and a build with none', () => {
    const stale = run(built({analysedAt: '2026-11-15T11:59:59.000Z'}), () => analysis()).findings;
    expect(stale).toEqual([
      "the bundle analysis is not this build's (analysed snap, built 2026-11-15T12:00:00.000Z) — run `npm run build -- --analyze` first."
    ]);
    expect(
      run(built(), () => {
        throw new Error('next analyze export exited 1: Analyzer snapshot not found');
      }).findings
    ).toEqual(['the bundle analysis could not be read: next analyze export exited 1: Analyzer snapshot not found']);
    const bare = built({history: false});
    expect(run(bare, () => analysis()).findings).toEqual([
      `no bundle analysis to check: ${join(bare, '.next/diagnostics/analyze/history/history.json')} is unreadable — run \`npm run build -- --analyze\` first.`
    ]);
    const unbuilt = built({stats: null});
    expect(run(unbuilt, () => analysis()).findings).toEqual([
      `no build to check: ${join(unbuilt, '.next/diagnostics/route-bundle-stats.json')} is unreadable — run \`npm run build -- --analyze\` first.`
    ]);
    const renamed = analysis().map((record) => (record.type === 'meta' ? {...record, snapshot_name: 'other'} : record));
    expect(run(built(), () => renamed).findings).toEqual([
      "the bundle analysis is not this build's (analysed other, built 2026-11-15T12:00:00.000Z) — run `npm run build -- --analyze` first."
    ]);
    for (const data of [{dataAt: new Date('2026-11-15T12:00:05.000Z')}, {dataAt: null}, {dataFiles: []}]) {
      expect(run(built(data), () => analysis()).findings).toEqual([
        "the bundle analysis is not this build's (analysed snap, built 2026-11-15T12:00:00.000Z) — run `npm run build -- --analyze` first."
      ]);
    }
    expect(run(built({stats: []}), () => analysis()).findings).toEqual([
      'the build lists no routes, so there is nothing to judge.'
    ]);
  });

  it('reads the export whole, and refuses one that did not exit 0', () => {
    const stub = (script) => {
      const dir = mkdtempSync(join(tmpdir(), 'page-gate-next-'));
      dirs.push(dir);
      mkdirSync(join(dir, 'node_modules/next/dist/bin'), {recursive: true});
      writeFileSync(join(dir, 'package.json'), '{}');
      writeFileSync(join(dir, 'node_modules/next/dist/bin/next.js'), script);
      return dir;
    };
    const lines =
      'process.stdout.write(\'{"type":"meta","argv":"\' + process.argv.slice(2).join(" ") + \'"}\\n\\n{"type":"route"}\\n\');';
    expect(exportAnalysis(stub(lines))).toEqual([{type: 'meta', argv: 'analyze export'}, {type: 'route'}]);
    const partial = `${lines} process.stderr.write('Error: Invalid analyzer header\\n'); process.exitCode = 1;`;
    expect(() => exportAnalysis(stub(partial))).toThrow('next analyze export exited 1: Error: Invalid analyzer header');
  });

  it('exits 1 naming each finding, and 0 with a count of what it read', () => {
    // The suite runs from apps/portal, as every file-reading test here assumes.
    const cli = join(process.cwd(), 'scripts/assert-pages-hydrate-no-app-graph.mjs');
    const portal = (records) => {
      const dir = built();
      mkdirSync(join(dir, 'node_modules/next/dist/bin'), {recursive: true});
      writeFileSync(join(dir, 'package.json'), '{}');
      writeFileSync(join(dir, 'records.jsonl'), records.map((record) => JSON.stringify(record)).join('\n'));
      writeFileSync(
        join(dir, 'node_modules/next/dist/bin/next.js'),
        "process.stdout.write(require('fs').readFileSync(require('path').join(process.cwd(), 'records.jsonl'), 'utf8'));"
      );
      return dir;
    };
    const failing = spawnSync(process.execPath, [cli], {
      cwd: portal(inPageParts('src/AppFrame.tsx')),
      encoding: 'utf8'
    });
    expect(failing.status).toBe(1);
    expect(failing.stderr).toContain(`[pages] ${ROUTE} hydrates src/AppFrame.tsx, in a chunk loaded with ${PAGE}\n`);
    const passing = spawnSync(process.execPath, [cli], {cwd: portal(analysis()), encoding: 'utf8'});
    expect([passing.status, passing.stdout]).toEqual([
      0,
      '[pages] 1 route(s), 4 hydration chunk(s) checked: none carries the application graph.\n'
    ]);
  });
});
