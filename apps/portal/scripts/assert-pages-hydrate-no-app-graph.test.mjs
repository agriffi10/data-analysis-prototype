import {spawnSync} from 'node:child_process';
import {mkdirSync, mkdtempSync, rmSync, utimesSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {afterEach, describe, expect, it} from 'vitest';
import {
  chunkShape,
  exportAnalysis,
  frameFindings,
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

/** What the frame's one file holds unless a case says otherwise: 210,000 bytes of the portal's own source, and a package. */
const FRAME_PARTS = [
  [src('src/components/Header.tsx'), 120_000],
  [src('src/lib/apiClient.ts'), 60_000],
  [src('src/features/help/helpContent.ts'), 30_000],
  ['[project]/node_modules/@tanstack/query-core/build/modern/query.js', 900_000]
];

/** What the boot's own file holds: 10,000 more, loaded on every page as the frame is. */
const BOOT_PARTS = [
  [src('src/PortalBoot.tsx'), 1_000],
  [src('src/lib/runtimeConfig.ts'), 9_000]
];
const FRAME_BYTES = 220_000;

/**
 * The records of what every page loads on one route: the boot's lazy group and the frame's, and
 * what their files hold.
 *
 * @param {object} [change] - Edits: `route` names the route, `boot` replaces the boot's files
 *   (`false` leaves its group out), `trigger` and `triggerPath` replace the module that loads the
 *   frame, and `files` replaces the frame's files (`null` leaves its group out). A file takes
 *   `parts` as `[source, size]` pairs, a `coverage`, `loaders` for what it loads lazily, and
 *   `output: false` to leave its output record out.
 * @returns {object[]} The records.
 */
function frame({
  route = ROUTE,
  boot = {'boot-lazy.js': {parts: BOOT_PARTS, loaders: [ident(src('src/AppFrame.tsx'))]}},
  trigger = ident(src('src/AppFrame.tsx')),
  triggerPath = src('src/AppFrame.tsx'),
  files = {'frame.js': {}}
} = {}) {
  const named = (name) => (name.startsWith('[') ? name : chunk(name));
  const records = [
    {type: 'module', ident: lazy(src('src/PortalBoot.tsx')), path: src('src/PortalBoot.tsx')},
    {type: 'module', ident: trigger, path: triggerPath}
  ];
  const groups = [
    [90, lazy(src('src/PortalBoot.tsx')), boot || null],
    [91, trigger, files]
  ];
  for (const [id, loadedBy, held] of groups) {
    if (!held) continue;
    records.push({
      type: 'group',
      route,
      id,
      kind: 'async',
      trigger_module_ident: loadedBy,
      outputs: Object.keys(held).map(named)
    });
    for (const [name, file] of Object.entries(held)) {
      if (file.output !== false) {
        records.push({
          type: 'output',
          route,
          filename: named(name),
          modules: [],
          async_loaders: file.loaders ?? [],
          coverage: file.coverage ?? 'exact'
        });
      }
      for (const [source, size] of file.parts ?? FRAME_PARTS) {
        records.push({type: 'part', route, filename: named(name), source_path: source, size});
      }
    }
  }
  return records;
}

/**
 * An analysis of one route, as `next analyze export` streams it: Next's bootstrap and runtime, the
 * root layout's mount, the page and its hook, the view behind `next/dynamic`, and the frame.
 *
 * @param {object} [change] - Edits: `modules` adds modules to a file with their parts, `bare` adds
 *   modules without one, as the analysis lists many, `parts` adds parts alone, as a module merged into
 *   another has, `loaders` adds lazy loads, `groups` replaces the chunk groups, and `frame` edits
 *   the frame as `frame` takes it (`false` leaves it and the boot's group out).
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
    })),
    ...(change.frame === false ? [] : frame(change.frame))
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

describe('the page gate’s frame check', () => {
  const framed = (change) => frameFindings(analysis({frame: change}));
  const withParts = (...parts) => ({files: {'frame.js': {parts: [...FRAME_PARTS, ...parts]}}});
  const explorer = [src('src/features/data-explorer/DataExplorerWorkspace.tsx'), 140_000];
  const over =
    "every page loads 360000 bytes of the portal's own source before its view, over the budget of 275000: the largest are features/data-explorer 140000, components 120000, lib 69000, features/help 30000";

  it('passes what every page loads today, and counts neither a package, nor what only the server is sent, nor a part twice', () => {
    expect(framed()).toEqual({findings: [], bytes: FRAME_BYTES});
    const server = '[output]/apps/portal/.next/server/chunks/ssr/frame.js';
    expect(
      framed({
        files: {'frame.js': {}, 'frame.css': {parts: []}, [server]: {parts: [[src('src/components/Big.tsx'), 900_000]]}}
      })
    ).toEqual({findings: [], bytes: FRAME_BYTES});
    expect(framed(withParts(...FRAME_PARTS))).toEqual({findings: [], bytes: FRAME_BYTES});
  });

  it('judges the boot’s own group with the frame’s, so code that moves between them moves no measure', () => {
    const moved = {
      boot: {'boot-lazy.js': {parts: [...BOOT_PARTS, explorer]}},
      files: {'frame.js': {}}
    };
    expect(framed(moved)).toEqual({findings: [`${over} (on /files)`], bytes: 360_000});
    expect(
      framed({
        boot: {'boot-lazy.js': {parts: [...BOOT_PARTS, [src('src/features/shared-spaces/memberStatus.ts'), 10]]}}
      }).findings
    ).toEqual(['every page loads src/features/shared-spaces/, a feature the shell is not known to use (on /files)']);
  });

  it('names what is over the budget by its largest folders, and what has fallen under the floor, to the byte', () => {
    expect(framed(withParts(explorer))).toEqual({findings: [`${over} (on /files)`], bytes: 360_000});
    // A boot file with none of the portal's own source, so the frame's one part is the whole measure.
    const bare = {'boot-lazy.js': {parts: [['[project]/node_modules/next/dist/client/app-dir/link.js', 1]]}};
    const sized = (bytes) =>
      framed({boot: bare, files: {'frame.js': {parts: [[src('src/components/Header.tsx'), bytes]]}}});
    expect(sized(275_000).findings).toEqual([]);
    expect(sized(275_001).findings).toEqual([
      "every page loads 275001 bytes of the portal's own source before its view, over the budget of 275000: the largest are components 275001 (on /files)"
    ]);
    expect(sized(197_000).findings).toEqual([]);
    expect(sized(196_999).findings).toEqual([
      "every page loads 196999 bytes of the portal's own source before its view, under the 197000 the budget of 275000 expects: either it shrank, and FRAME_BUDGET_BYTES and FRAME_FLOOR_BYTES are lowered to fit, or code moved into a group this does not read (on /files)"
    ]);
  });

  it('names a package, a folder and a feature the shell is not known to need, however small', () => {
    expect(
      framed(
        withParts(
          ['[project]/node_modules/monaco-editor/esm/vs/editor/editor.api.js', 10],
          ['[project]/node_modules/next/node_modules/prismjs/prism.js', 10],
          ['[project]/node_modules/next/dist/client/app-dir/link.js', 10],
          ['[turbopack-ecmascript]/worker/browser/createWorker.ts', 10],
          [src('src/routes/NotificationsPage.tsx'), 10],
          [src('src/features/shared-spaces/memberStatus.ts'), 10],
          [src('src/features/query-history/index.ts'), 10]
        )
      ).findings
    ).toEqual([
      "every page loads [turbopack-ecmascript]/worker/browser/createWorker.ts, which is neither the portal's nor a package's; the shell is not known to need it, so an import in the boot's or the shell's graph reaches it (on /files)",
      'every page loads src/features/query-history/, a feature the shell is not known to use (on /files)',
      'every page loads src/features/shared-spaces/, a feature the shell is not known to use (on /files)',
      'every page loads src/routes, which is not what the boot and the frame are built from: an import in their graph reaches it (on /files)',
      "every page loads the package monaco-editor; the shell is not known to need it, so an import in the boot's or the shell's graph reaches it (on /files)",
      "every page loads the package prismjs; the shell is not known to need it, so an import in the boot's or the shell's graph reaches it (on /files)"
    ]);
  });

  it('refuses a file it cannot measure, and says which and why', () => {
    const unmeasured = (file) => framed({files: {'frame.js': file}}).findings;
    const sizeless = ['a frame file cannot be measured: frame.js lists no source, or one without a size (on /files)'];
    expect(unmeasured({coverage: 'partial'})).toEqual([
      'a frame file cannot be measured: frame.js has coverage partial (on /files)'
    ]);
    expect(unmeasured({output: false})).toEqual([
      'a frame file cannot be measured: frame.js has coverage none (on /files)'
    ]);
    expect(unmeasured({parts: []})).toEqual(sizeless);
    for (const size of [undefined, '900000', Number.NaN, -1]) {
      expect(unmeasured({parts: [...FRAME_PARTS, [src('src/components/Big.tsx'), size]]})).toEqual(sizeless);
    }
    expect(framed({files: {'frame.js': {}, 'frame.mjs': {}}}).findings).toEqual([
      'a frame file cannot be measured: frame.mjs is neither a script nor a stylesheet (on /files)'
    ]);
    expect(framed({boot: {'boot-lazy.js': {coverage: 'partial'}}}).findings).toEqual([
      'a frame file cannot be measured: boot-lazy.js has coverage partial (on /files)'
    ]);
  });

  it('names a route that boots the portal without a frame, and a build in which nothing boots it', () => {
    const none = [
      'a route boots the portal and has no frame: no lazy group is loaded from src/AppFrame.tsx (on /files)'
    ];
    expect(framed({files: null}).findings).toEqual(none);
    // An ident can quote another module's path: the frame is the group whose TRIGGER is that module.
    const quoting = `${src('src/Other.tsx')} { MODULE => "${src('src/AppFrame.tsx')}" } [app-client] (ecmascript)`;
    expect(framed({trigger: quoting, triggerPath: src('src/Other.tsx')}).findings).toEqual(none);
    expect(
      framed({
        boot: {'[output]/server/boot.js': {}},
        files: {'[output]/apps/portal/.next/server/chunks/ssr/frame.js': {}}
      }).findings
    ).toEqual(none);
    expect(frameFindings(analysis({frame: false})).findings).toEqual([
      'no route boots the portal, so there is no frame to judge: no lazy group is loaded from src/PortalBoot.tsx'
    ]);
    expect(framed({boot: false}).findings).toEqual([
      'no route boots the portal, so there is no frame to judge: no lazy group is loaded from src/PortalBoot.tsx'
    ]);
    expect(frameFindings([...analysis(), ...frame({route: '/query', boot: false})]).findings).toEqual([
      'a route loads the frame without the boot: no lazy group is loaded from src/PortalBoot.tsx (on /query)'
    ]);
  });

  it('names a lazy load inside the boot or the frame that is not the frame itself, which would be a group nothing measures', () => {
    const page = ident(src('src/routes/DataQualityPage.tsx'));
    const inBoot = {'boot-lazy.js': {parts: BOOT_PARTS, loaders: [ident(src('src/AppFrame.tsx')), page]}};
    const named =
      'every page lazily loads src/routes/DataQualityPage.tsx from the boot or the frame, where only src/AppFrame.tsx may be: that is a group of its own on every page, and nothing measures it (on /files)';
    expect(framed({boot: inBoot}).findings).toEqual([named]);
    expect(framed({files: {'frame.js': {loaders: [page]}}}).findings).toEqual([named]);
  });

  it('names an own module every route’s hydration loads lazily, and passes the boot, the not-found page and a route’s own view', () => {
    // The same analysis on a second route, with a view of its own as every route has.
    const onRoute = (route, records) =>
      JSON.parse(JSON.stringify(records).replaceAll('routes/areas/files.tsx', 'routes/areas/query.tsx')).map(
        (record) => (record.route ? {...record, route} : record)
      );
    const widget = lazy(src('src/features/feedback/FeedbackDialog.tsx'));
    const shared = {files: {'layout.js': {loaders: [widget, lazy(src('src/routes/NotFoundPage.tsx'))]}}};
    const two = (first, second) => [...analysis(first), ...onRoute('/query', analysis(second))];

    expect(frameFindings(two(shared, shared)).findings).toEqual([
      "every route's hydration lazily loads src/features/feedback/FeedbackDialog.tsx: only the boot and the not-found page are loaded from every route, and this is a group on every page that nothing measures (on /files)"
    ]);
    expect(frameFindings(two(shared, {})).findings).toEqual([]);
    // One route cannot tell its own view from a load every route shares, so one route is not judged.
    expect(frameFindings(analysis(shared)).findings).toEqual([]);
  });

  it('names a package a page hydrates that is not the framework’s, and passes the framework’s and the runtime', () => {
    const hydrating = (...parts) => frameFindings(analysis({files: {'page.js': {parts}}})).findings;
    expect(
      hydrating('[project]/node_modules/@swc/helpers/esm/_interop.js', '[turbopack]/shared/runtime-utils.ts')
    ).toEqual([]);
    expect(hydrating('[project]/node_modules/zod/index.js')).toEqual([
      "a page's hydration carries the package zod: an import in what a page loads at once reaches it (on /files)"
    ]);
  });

  it('reports a defect once, naming the first route that has it and how many more do', () => {
    // Two files of the feature on each route: a finding names a route once however many parts raise it.
    const bad = withParts(
      explorer,
      [src('src/features/shared-spaces/memberStatus.ts'), 0],
      [src('src/features/shared-spaces/sharedSpaces.types.ts'), 0]
    );
    const records = [
      ...analysis({frame: bad}),
      ...frame({...bad, route: '/query'}),
      ...frame({...bad, route: '/explore'})
    ];
    expect(frameFindings(records).findings).toEqual([
      `${over} (on /explore and 2 more)`,
      'every page loads src/features/shared-spaces/, a feature the shell is not known to use (on /explore and 2 more)'
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
    expect(run(built(), () => analysis())).toEqual({findings: [], routes: 1, chunks: 4, frameBytes: FRAME_BYTES});
    expect(run(built(), () => inPageParts('src/AppFrame.tsx')).findings).toEqual([
      `${ROUTE} hydrates src/AppFrame.tsx, in a chunk loaded with ${PAGE}`
    ]);
  });

  it('reports every check’s findings together: the shipped chunks, the reach, the graph, the lazy loads and the frame', () => {
    const stats = [
      {route: ROUTE, firstLoadChunkPaths: CHUNKS},
      {route: '/help', firstLoadChunkPaths: [CHUNKS[0]]}
    ];
    const loaders = [ident(src('src/features/x/index.ts'))];
    const records = analysis({
      files: {'page.js': {parts: [src('src/AppFrame.tsx')], loaders}},
      frame: {files: {'frame.js': {coverage: 'partial'}}}
    });
    expect(run(built({stats, missing: [CHUNKS[1]]}), () => records).findings).toEqual([
      `${ROUTE}: the analysis does not describe the chunks this build ships (modules per chunk: 1, 2, 4, none analysed, 1, 2, 3, missing shipped)`,
      '/help: the build ships this page, and the analysis has no hydration chunks for it',
      '/help: the analysis attributes none of its hydration code to src/app/, so it cannot be judged',
      `${ROUTE} hydrates src/AppFrame.tsx, in a chunk loaded with ${PAGE}`,
      `${ROUTE} hydrates a lazy load of src/features/x/index.ts [app-client] (ecmascript) that is not next/dynamic`,
      `a frame file cannot be measured: frame.js has coverage partial (on ${ROUTE})`
    ]);
  });

  it('refuses an analysis older than the build, one it cannot read, and a build with none', () => {
    const stale = run(built({analysedAt: '2026-11-15T11:59:59.000Z'}), () => analysis()).findings;
    expect(stale).toEqual([
      "the bundle analysis is not this build's (analysed snap, built 2026-11-15T12:00:00.000Z) — run `npm run build -- --analyze` in apps/portal first."
    ]);
    expect(
      run(built(), () => {
        throw new Error('next analyze export exited 1: Analyzer snapshot not found');
      }).findings
    ).toEqual(['the bundle analysis could not be read: next analyze export exited 1: Analyzer snapshot not found']);
    const bare = built({history: false});
    expect(run(bare, () => analysis()).findings).toEqual([
      `no bundle analysis to check: ${join(bare, '.next/diagnostics/analyze/history/history.json')} is unreadable — run \`npm run build -- --analyze\` in apps/portal first.`
    ]);
    const unbuilt = built({stats: null});
    expect(run(unbuilt, () => analysis()).findings).toEqual([
      `no build to check: ${join(unbuilt, '.next/diagnostics/route-bundle-stats.json')} is unreadable — run \`npm run build -- --analyze\` in apps/portal first.`
    ]);
    const renamed = analysis().map((record) => (record.type === 'meta' ? {...record, snapshot_name: 'other'} : record));
    expect(run(built(), () => renamed).findings).toEqual([
      "the bundle analysis is not this build's (analysed other, built 2026-11-15T12:00:00.000Z) — run `npm run build -- --analyze` in apps/portal first."
    ]);
    for (const data of [{dataAt: new Date('2026-11-15T12:00:05.000Z')}, {dataAt: null}, {dataFiles: []}]) {
      expect(run(built(data), () => analysis()).findings).toEqual([
        "the bundle analysis is not this build's (analysed snap, built 2026-11-15T12:00:00.000Z) — run `npm run build -- --analyze` in apps/portal first."
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
    const portal = (records, options) => {
      const dir = built(options);
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
    expect(failing.stderr).toContain('[pages] A page reaches its view only through next/dynamic');
    const stale = spawnSync(process.execPath, [cli], {
      cwd: portal(analysis(), {analysedAt: '2026-11-15T11:59:59.000Z'}),
      encoding: 'utf8'
    });
    expect([stale.status, stale.stderr]).toEqual([
      1,
      "[pages] the bundle analysis is not this build's (analysed snap, built 2026-11-15T12:00:00.000Z) — run `npm run build -- --analyze` in apps/portal first.\n"
    ]);
    const passing = spawnSync(process.execPath, [cli], {cwd: portal(analysis()), encoding: 'utf8'});
    expect([passing.status, passing.stdout]).toEqual([
      0,
      '[pages] 1 route(s), 4 hydration chunk(s) checked: none carries the application graph.\n' +
        `[pages] every page loads ${FRAME_BYTES} bytes of the portal's own source before its view.\n`
    ]);
  });
});
