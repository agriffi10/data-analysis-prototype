/**
 * Refuse to build when the `tsc` on PATH is not the TypeScript the workspace declares.
 *
 * WHY THERE ARE TWO. TypeScript 7 is the native port and ships no programmatic API before 7.1, so
 * typescript-eslint still peer-pins `<6.1.0`. npm settles that by keeping the declared 7.x in
 * `apps/portal/node_modules` — where `tsc -b` finds it first — and hoisting a 6.x copy to the
 * workspace root for the linter. Both are load-bearing; neither is a mistake to clean up.
 *
 * THE FAILURE THIS EXISTS FOR. npm builds a lifecycle script's PATH by prepending
 * `node_modules/.bin` from EVERY ancestor directory, nearest first. So if the workspace's own
 * `.bin/tsc` is missing — an interrupted install, or a hand-deleted directory; `npm dedupe` was
 * measured NOT to do it, both copies survive — `tsc -b` silently runs the ROOT's 6.x and the build typechecks
 * against the wrong compiler, exiting 0. Nothing else notices: `check-local-install.mjs` finds a
 * `tsc` in the root `.bin` and passes, the bundle builds, and the suite is green. A 7-only type
 * error then reaches `main` behind a green PR.
 *
 * WHY IT WALKS `.bin` RATHER THAN RESOLVING THE MODULE. These are two different mechanisms and
 * they come apart: `require.resolve('typescript')` finds `node_modules/typescript` while the
 * binary is chosen through `.bin`. Measured — with only `apps/portal/node_modules/.bin/tsc` moved
 * aside, module resolution still answers 7.x while `tsc --version` answers 6.0.3. An earlier
 * version of this guard asked the module question and passed that case. The build runs the
 * BINARY, so that is the thing to measure.
 */

import {existsSync, readFileSync, realpathSync} from 'node:fs';
import {dirname, join, parse, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

/** Leading major of a range or a version — `~7.0.2` and `7.0.2` both give 7. */
const major = (spec) => Number(/(\d+)/.exec(spec)?.[1]);

/**
 * The `.bin/tsc` npm's PATH would select from `from`, i.e. the nearest one walking upward.
 *
 * @param {string} from Absolute directory to start the walk at.
 * @returns {string | undefined} Absolute path to the winning `.bin/tsc`, or undefined if the walk
 *   reaches the filesystem root without finding one.
 */
function nearestBinOnPath(from) {
  let dir = from;
  for (;;) {
    const candidate = join(dir, 'node_modules', '.bin', 'tsc');
    if (existsSync(candidate)) return candidate;
    const up = dirname(dir);
    if (up === dir || dir === parse(dir).root) return undefined;
    dir = up;
  }
}

/**
 * Identify the package that owns `file` by walking up to the nearest package.json.
 *
 * Returns the NAME as well as the version, and the caller checks it. Without that this walk is a
 * fail-open: `realpathSync` on a `.bin` entry that is a regular file — a shell shim rather than a
 * symlink, which is what npm writes on Windows and what pnpm writes everywhere — returns the file
 * itself, so the walk climbs out of `.bin/` and reads the CONSUMER's manifest instead. Measured:
 * with such a shim in place the guard reported the workspace's own `"version"`, and passed outright
 * once that field was edited to a 7. Whether the gate held then depended on a field in
 * `apps/portal/package.json` that nobody thinks of as load-bearing.
 *
 * @param {string} file Absolute path to a file inside an installed package.
 * @returns {{name: string, version: string} | undefined} The owning manifest's `name` and
 *   `version`, or undefined if no manifest is found before the filesystem root.
 */
function owningPackage(file) {
  let dir = dirname(file);
  for (;;) {
    const manifest = join(dir, 'package.json');
    if (existsSync(manifest)) {
      const {name, version} = JSON.parse(readFileSync(manifest, 'utf8'));
      return {name, version};
    }
    const up = dirname(dir);
    if (up === dir) return undefined;
    dir = up;
  }
}

/**
 * Compare the `tsc` a build in `workspace` would execute against the one it declares.
 *
 * Fails closed: every branch that cannot answer the question refuses rather than passing, because
 * a guard that cannot see the compiler is indistinguishable from one that saw the right one. Each
 * of those refusals is pinned by name in `check-compiler-major_test.mjs` — mutation-tested, since
 * several of them would otherwise still refuse via an uncaught throw and so could be deleted
 * without any test noticing.
 *
 * @param {string} workspace Absolute path to the workspace directory holding the package.json.
 * @returns {{ok: boolean, reason: string}} `ok` false with a one-line `reason` naming what was
 *   found; `ok` true and an empty `reason` when the majors agree.
 */
export function checkCompilerMajor(workspace) {
  const manifestPath = join(workspace, 'package.json');
  if (!existsSync(manifestPath)) {
    return {ok: false, reason: `no package.json in ${workspace}`};
  }
  const declared = JSON.parse(readFileSync(manifestPath, 'utf8')).devDependencies?.typescript;
  if (declared === undefined) {
    return {ok: false, reason: `${manifestPath} declares no typescript devDependency`};
  }

  const bin = nearestBinOnPath(workspace);
  if (bin === undefined) {
    return {ok: false, reason: `no node_modules/.bin/tsc above ${workspace}, so the install is partial`};
  }

  // The shim npm writes is a symlink into the package on this platform; realpath is what turns it
  // back into the copy it belongs to, and so into the version that will actually run.
  const owner = owningPackage(realpathSync(bin));
  if (owner === undefined) {
    return {ok: false, reason: `${bin} resolves to no installed package, so its version cannot be read`};
  }
  if (owner.name !== 'typescript') {
    return {
      ok: false,
      reason: `${bin} resolves into ${owner.name ?? 'a package with no name'}, not typescript, so the compiler version cannot be read from it`,
    };
  }

  if (major(owner.version) !== major(declared)) {
    return {
      ok: false,
      reason: `${workspace} declares typescript ${declared} but ${bin} is ${owner.version}`,
    };
  }
  return {ok: true, reason: ''};
}

const REMEDY = `
\`tsc -b\` would run a TypeScript this workspace does not declare — almost always the copy hoisted
to the repo root for typescript-eslint, which peer-pins an older major on purpose. npm builds a
script's PATH from every ancestor node_modules/.bin, so a missing shim here falls through to that
one and the build typechecks against the wrong compiler, exiting 0.

Fix it from the workspace root:

    npm ci

Diagnostic: \`npx tsc --version\` run from THIS directory prints what the build would use. Run from
the repo root it prints the linter's copy instead, which is not the same question.
`;

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const flag = process.argv.indexOf('--workspace');
  const workspace = flag === -1 ? process.cwd() : resolve(process.argv[flag + 1] ?? '');
  const {ok, reason} = checkCompilerMajor(workspace);
  if (!ok) {
    process.stderr.write(`[compiler-major] REFUSING: ${reason}\n${REMEDY}`);
    process.exit(1);
  }
}
