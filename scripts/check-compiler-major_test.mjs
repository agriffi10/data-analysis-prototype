/**
 * Prove `check-compiler-major.mjs` still refuses the states it exists for, and still stays quiet.
 *
 * WHY THIS FILE EXISTS. The guard beside it went wrong twice in one branch, the same way both
 * times: it read the compiler's version through a mechanism that was not the one npm uses, and
 * each fix opened a fresh hole while closing the last. The first cut asked
 * `require.resolve('typescript')` and passed a tree whose `.bin` shim was gone; the second walked
 * `.bin` but read whatever manifest sat above the shim, so a regular-file shim made it report the
 * CONSUMER's version — and pass outright once that unrelated field was a 7. Two reviews found
 * those by hand. A third would have found a third. This corpus is the structural answer: the
 * states are pinned here, so the next rewrite has to satisfy them rather than be re-derived.
 *
 * Each case asserts the REASON, not merely a boolean. Neighbouring branches all refuse, so a test
 * that checked only `ok === false` would pass while the guard refused for the wrong cause — which
 * is exactly how a gate goes quiet without anyone noticing.
 *
 * Run it when you change the guard:  node scripts/check-compiler-major_test.mjs
 */

import {mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync, chmodSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {checkCompilerMajor} from './check-compiler-major.mjs';

/**
 * Build an isolated fixture tree.
 *
 * @param {object} spec Shape of the tree to build.
 * @param {string | null} spec.declared Value for the workspace's `devDependencies.typescript`;
 *   `null` omits the key. NOT `undefined` — that re-triggers the default parameter, which is how
 *   two of these cases silently built the healthy tree and asserted nothing.
 * @param {boolean} spec.manifest Whether the workspace gets a package.json at all.
 * @param {string | null} spec.workspaceTs Version of typescript installed IN the workspace; `null`
 *   installs none.
 * @param {string | null} spec.rootTs Version hoisted to the fixture root; `null` installs none.
 * @param {'symlink' | 'file' | 'chain' | 'stray' | 'none'} spec.shim How the workspace's
 *   `.bin/tsc` is made. `stray` points it outside any package, which is the only way to reach the
 *   "resolves to no installed package" branch.
 * @param {boolean} spec.tsVersionField Whether the workspace typescript manifest has a `version`.
 * @returns {string} Absolute path to the workspace directory.
 */
function tree({
  declared = '~7.0.2',
  manifest = true,
  workspaceTs = '7.0.2',
  rootTs = '6.0.3',
  shim = 'symlink',
  tsVersionField = true,
}) {
  const root = mkdtempSync(join(tmpdir(), 'compiler-major-'));
  const workspace = join(root, 'apps', 'portal');
  mkdirSync(workspace, {recursive: true});

  if (manifest) {
    const pkg = {name: '@fixture/portal', version: '0.0.0'};
    if (declared !== null) pkg.devDependencies = {typescript: declared};
    writeFileSync(join(workspace, 'package.json'), JSON.stringify(pkg));
  }

  /** Install a typescript package under `at`, returning its bin path. */
  const install = (at, version) => {
    const pkgDir = join(at, 'node_modules', 'typescript');
    mkdirSync(join(pkgDir, 'bin'), {recursive: true});
    const body = {name: 'typescript'};
    if (tsVersionField) body.version = version;
    writeFileSync(join(pkgDir, 'package.json'), JSON.stringify(body));
    writeFileSync(join(pkgDir, 'bin', 'tsc'), '#!/usr/bin/env node\n');
    mkdirSync(join(at, 'node_modules', '.bin'), {recursive: true});
    return join(pkgDir, 'bin', 'tsc');
  };

  if (rootTs !== null) {
    const target = install(root, rootTs);
    symlinkSync(target, join(root, 'node_modules', '.bin', 'tsc'));
  }
  if (workspaceTs !== null) {
    const target = install(workspace, workspaceTs);
    const bin = join(workspace, 'node_modules', '.bin', 'tsc');
    if (shim === 'symlink') symlinkSync(target, bin);
    if (shim === 'chain') {
      const hop = join(workspace, 'node_modules', '.bin', 'tsc-hop');
      symlinkSync(target, hop);
      symlinkSync(hop, bin);
    }
    if (shim === 'stray') {
      // A hand-made link out of the tree: realpath lands somewhere with no package.json above it.
      const outside = join(root, 'stray-tsc');
      writeFileSync(outside, '#!/usr/bin/env node\n');
      symlinkSync(outside, bin);
    }
    if (shim === 'file') {
      // What npm writes on Windows and pnpm writes everywhere: a shell shim, not a symlink.
      writeFileSync(bin, '#!/bin/sh\nexec node "$@"\n');
      chmodSync(bin, 0o755);
    }
  }
  return workspace;
}

const CASES = [
  {
    name: 'a healthy split passes, and says nothing',
    spec: {},
    ok: true,
    reason: /^$/,
  },
  {
    name: 'the workspace shim gone falls through to the root copy — the failure it exists for',
    spec: {shim: 'none'},
    ok: false,
    reason: /declares typescript ~7\.0\.2 but .* is 6\.0\.3$/,
  },
  {
    name: 'a regular-file shim is refused by NAME, not by the consumer version it sits above',
    spec: {shim: 'file'},
    ok: false,
    reason: /resolves into @fixture\/portal, not typescript/,
  },
  {
    name: 'a symlink chain is followed to the package at the end of it',
    spec: {shim: 'chain'},
    ok: true,
    reason: /^$/,
  },
  {
    name: 'the right major installed in the wrong place is still the wrong compiler',
    spec: {workspaceTs: '6.9.9'},
    ok: false,
    reason: /declares typescript ~7\.0\.2 but .* is 6\.9\.9$/,
  },
  {
    name: 'no tsc anywhere above the workspace is a partial install, not a pass',
    spec: {shim: 'none', workspaceTs: null, rootTs: null},
    ok: false,
    reason: /no node_modules\/\.bin\/tsc above /,
  },
  {
    name: 'a workspace with no manifest cannot be checked, so it is refused',
    spec: {manifest: false},
    ok: false,
    reason: /no package\.json in /,
  },
  {
    name: 'a manifest declaring no typescript is refused rather than assumed fine',
    spec: {declared: null},
    ok: false,
    reason: /declares no typescript devDependency$/,
  },
  {
    name: 'a shim pointing outside any package is refused, not read as a version',
    spec: {shim: 'stray'},
    ok: false,
    reason: /resolves to no installed package/,
  },
  {
    name: 'a typescript manifest with no version refuses rather than comparing against nothing',
    spec: {tsVersionField: false},
    ok: false,
    reason: /but .* is undefined$/,
  },
];

let failures = 0;
for (const {name, spec, ok, reason} of CASES) {
  const workspace = tree(spec);
  const got = checkCompilerMajor(workspace);
  const bad = got.ok !== ok || !reason.test(got.reason);
  if (bad) {
    failures += 1;
    process.stderr.write(
      `FAIL ${name}\n  expected ok=${ok} reason~${reason}\n  got      ok=${got.ok} reason="${got.reason}"\n`
    );
  }
  rmSync(workspace.replace(/\/apps\/portal$/, ''), {recursive: true, force: true});
}

if (failures > 0) {
  process.stderr.write(`\n${failures} of ${CASES.length} guard cases failed.\n`);
  process.exit(1);
}
process.stdout.write(`check-compiler-major: ${CASES.length} cases pass.\n`);
