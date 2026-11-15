/**
 * Refuse to run a JS gate against a dependency tree this checkout does not own.
 *
 * THE FAILURE THIS EXISTS FOR. A git worktree starts with no `node_modules`. Node resolves a
 * module by walking UP the directory tree, so a worktree created INSIDE the main checkout
 * (`.claude/worktrees/...`, which is where agent sessions get put) silently borrows the main
 * checkout's dependencies. eslint, prettier and `tsc -b` then run and PASS — not by accident and
 * not with a warning, but honestly, against a real dependency tree that is not the branch's. If
 * the branch changes `package.json` or the lockfile, those gates validate the wrong dependencies
 * and report success. A worktree created OUTSIDE the checkout fails loudly instead
 * (`sh: prettier: command not found`), so which half you get depends only on where the worktree
 * happens to live.
 *
 * The lesson generalises the wrong way round: the more completely a dependency is hoisted, the
 * more silently this fails. A gate whose dependency had nothing in the parent to borrow fails
 * loudly; one whose dependency did, passes.
 *
 * A SECOND WAY TO BORROW, FOR THE COVERAGE GATE. Vitest imports its coverage provider BY NAME from
 * its own directory, `node_modules/vitest`, and resolution walks up from there, never down into a
 * workspace. A lockfile that installs `@vitest/coverage-v8` under `apps/portal/node_modules` while
 * `vitest` sits at the root hides the provider from the one package that loads it, and `npm ci`
 * reproduces that layout faithfully. Outside another checkout the run fails with `Cannot find
 * package '@vitest/coverage-v8'`; inside one it loads the PARENT's provider, at whatever version
 * that checkout last installed, prints a mixed-versions warning, and exits 0. A Dependabot group
 * bump has written exactly that lockfile, and nothing in its diff looked wrong. The check runs for
 * the coverage gate alone (`--coverage`), because no other gate imports the provider and refusing
 * them over it would block runs that work.
 *
 * WHY IT MATTERS MORE THAN IT USED TO. These gates no longer run in CI, so a green pre-push run
 * is the only evidence they were run at all. A gate that passes against the wrong tree is
 * indistinguishable from one that passed against the right one.
 */

import {existsSync, readFileSync} from 'node:fs';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

/** Workspace root as an absolute path, derived from this file's own location. */
const DEFAULT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

/**
 * Binaries the four guarded gates actually execute. Named rather than counted, because an
 * interrupted install leaves a `.bin` that exists and is populated with whatever got there first
 * -- "non-empty" would pass a tree that cannot run eslint. Naming them also lets the refusal say
 * which one is missing, and a rename here is a loud, correct failure rather than a silent one.
 */
const REQUIRED_BINARIES = ['eslint', 'prettier', 'vitest', 'tsc'];

/**
 * The package Vitest imports when a run asks for coverage. It must sit in the root `node_modules`
 * beside `vitest`, which the root `.bin/vitest` that REQUIRED_BINARIES demands already puts there:
 * npm links a package's binaries only into the `.bin` of the `node_modules` it is installed in.
 */
const COVERAGE_PROVIDER = '@vitest/coverage-v8';

/**
 * Decide whether `root` owns an installed dependency tree that can actually run the gates.
 *
 * Deliberately a filesystem check on the ROOT specifically, never a module resolution: resolution
 * is the thing that walks up and produces the false pass, so asking Node to resolve a binary
 * would answer the question this is trying to ask. The same reason is why the binaries are
 * checked by path rather than by spawning them -- npm builds a lifecycle script's PATH by
 * prepending `node_modules/.bin` from EVERY ancestor directory up to `/`, so a tree whose own
 * `.bin` is empty still runs eslint, from the parent checkout, and exits 0.
 *
 * @param {string} root Absolute path to the workspace root to inspect.
 * @param {{coverage?: boolean}} [options] `coverage` also demands COVERAGE_PROVIDER beside vitest.
 * @returns {{ok: boolean, reason: string, remedy: string}} `ok` false with a one-line `reason` and
 *   the `remedy` to print under it when the tree is missing, has no `.bin`, cannot supply one of
 *   REQUIRED_BINARIES, or (with `coverage`) has no COVERAGE_PROVIDER beside vitest; `ok` true and
 *   empty strings otherwise.
 */
export function checkLocalInstall(root, {coverage = false} = {}) {
  const modules = join(root, 'node_modules');
  if (!existsSync(modules)) {
    return {ok: false, reason: `no node_modules in ${root}`, remedy: REMEDY};
  }
  const bin = join(modules, '.bin');
  if (!existsSync(bin)) {
    return {
      ok: false,
      reason: `node_modules in ${root} has no .bin, so the install is partial`,
      remedy: REMEDY,
    };
  }
  const missing = REQUIRED_BINARIES.filter((name) => !existsSync(join(bin, name)));
  if (missing.length > 0) {
    return {
      ok: false,
      reason: `node_modules/.bin in ${root} is missing ${missing.join(', ')}, so the install is partial`,
      remedy: REMEDY,
    };
  }
  if (coverage) {
    return checkCoverageProvider(root);
  }
  return {ok: true, reason: '', remedy: ''};
}

/**
 * Decide whether the root's vitest can import COVERAGE_PROVIDER, and say why not.
 *
 * The verdict is the installed tree, because that is what the gate runs. The lockfile is read only
 * to tell the three causes apart, since they need different fixes: a provider the lockfile
 * installs at the root but the tree lacks is a stale or partial install, which `npm ci` repairs;
 * one the lockfile installs only inside a workspace is a lockfile defect that `npm ci` reproduces;
 * and one the lockfile does not install at all is a manifest that no install can repair.
 *
 * @param {string} root Absolute path to a workspace root whose `.bin` already passed.
 * @returns {{ok: boolean, reason: string, remedy: string}} Shaped as checkLocalInstall's result.
 */
function checkCoverageProvider(root) {
  if (existsSync(join(root, 'node_modules', COVERAGE_PROVIDER, 'package.json'))) {
    return {ok: true, reason: '', remedy: ''};
  }
  const placements = lockfilePlacements(root, COVERAGE_PROVIDER);
  if (placements.includes(`node_modules/${COVERAGE_PROVIDER}`)) {
    return {
      ok: false,
      reason: `node_modules/${COVERAGE_PROVIDER} is missing in ${root}, so vitest has no coverage provider beside it`,
      remedy: MISSING_PROVIDER_REMEDY,
    };
  }
  if (placements.length > 0) {
    return {
      ok: false,
      reason: `package-lock.json installs ${COVERAGE_PROVIDER} at ${placements.join(', ')}, where node_modules/vitest cannot import it`,
      remedy: NESTED_PROVIDER_REMEDY,
    };
  }
  return {
    ok: false,
    reason: `package-lock.json in ${root} does not install ${COVERAGE_PROVIDER} at all, so vitest has no coverage provider`,
    remedy: UNLOCKED_PROVIDER_REMEDY,
  };
}

/**
 * Every key under which `package-lock.json` installs `name`, such as `node_modules/<name>` or
 * `apps/portal/node_modules/<name>`.
 *
 * @param {string} root Absolute path to the workspace root.
 * @param {string} name Package name to look for.
 * @returns {string[]} The matching keys in lockfile order; empty when there is no lockfile.
 */
function lockfilePlacements(root, name) {
  const lockfile = join(root, 'package-lock.json');
  if (!existsSync(lockfile)) {
    return [];
  }
  const {packages = {}} = JSON.parse(readFileSync(lockfile, 'utf8'));
  const suffix = `node_modules/${name}`;
  return Object.keys(packages).filter((key) => key === suffix || key.endsWith(`/${suffix}`));
}

const REMEDY = `
This checkout has no dependency tree of its own, so a gate run here would either fail for a
reason unrelated to your diff or — if this worktree sits inside another checkout — silently
resolve UP into that checkout's node_modules and PASS against the wrong dependencies.

Fix it from the workspace root:

    npm ci

Diagnostic, if you want to see the state rather than trust it: \`npm ls eslint\` prints
"(empty)" in a borrowed tree while \`npx prettier --version\` still answers a version number.
The first is telling the truth about this checkout; the second is answering from the parent.
`;

const MISSING_PROVIDER_REMEDY = `
package-lock.json installs the coverage provider beside vitest, but this tree does not have it,
so the install is stale or partial. Inside another checkout the coverage run would load that
checkout's provider instead, at whatever version it last installed, and pass.

Fix it from the workspace root:

    npm ci
`;

const UNLOCKED_PROVIDER_REMEDY = `
No install can supply a package the lockfile does not name, so \`npm ci\` will not help. Add the
provider back to apps/portal's devDependencies at exactly the installed vitest's version, from
the workspace root:

    npm install -D @vitest/coverage-v8@$(node -p "require('./node_modules/vitest/package.json').version") -w apps/portal

An unpinned range such as ^5 lets npm resolve a newer Vitest family, which it nests inside the
workspace beside the root vitest it cannot replace. Then run this gate again: it also refuses if
npm placed the provider anywhere but beside vitest.
`;

const NESTED_PROVIDER_REMEDY = `
The lockfile is what is wrong here, so \`npm ci\` reproduces it. Vitest imports its coverage
provider from its own directory, node_modules/vitest, and resolution walks UP from there, never
down into a workspace. Outside another checkout the run fails with "Cannot find package"; inside
one it loads the parent checkout's provider and passes, warning only if the versions differ.

Fix package-lock.json by MOVING the nested entries, which keeps every version as it is: rename
each "<workspace>/node_modules/@vitest/<name>" key that has no "node_modules/@vitest/<name>"
twin to that root key, then run

    npm install --package-lock-only
    npm ci

and check that \`git diff package-lock.json\` moves those keys, at most adding "peer": true to
them, and changes no version. Deleting
the entries instead lets npm re-resolve them, and it takes the newest Vitest the ranges allow.
`;

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const flag = process.argv.indexOf('--root');
  const root = flag === -1 ? DEFAULT_ROOT : resolve(process.argv[flag + 1] ?? '');
  const coverage = process.argv.includes('--coverage');
  const {ok, reason, remedy} = checkLocalInstall(root, {coverage});
  if (!ok) {
    process.stderr.write(`[local-install] REFUSING: ${reason}\n${remedy}`);
    process.exit(1);
  }
}
