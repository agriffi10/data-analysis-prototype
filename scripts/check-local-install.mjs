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
 * Vitest was the only gate that caught this on its own, and only because `@vitest/coverage-v8`
 * is not hoisted to the workspace root and so had nothing to borrow. The lesson generalises the
 * wrong way round: the more completely a dependency is hoisted, the more silently this fails.
 *
 * WHY IT MATTERS MORE THAN IT USED TO. These gates no longer run in CI, so a green pre-push run
 * is the only evidence they were run at all. A gate that passes against the wrong tree is
 * indistinguishable from one that passed against the right one.
 */

import {existsSync} from 'node:fs';
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
 * @returns {{ok: boolean, reason: string}} `ok` false with a one-line `reason` when the tree is
 *   missing, has no `.bin`, or cannot supply one of REQUIRED_BINARIES; `ok` true and an empty
 *   `reason` otherwise.
 */
export function checkLocalInstall(root) {
  const modules = join(root, 'node_modules');
  if (!existsSync(modules)) {
    return {ok: false, reason: `no node_modules in ${root}`};
  }
  const bin = join(modules, '.bin');
  if (!existsSync(bin)) {
    return {ok: false, reason: `node_modules in ${root} has no .bin, so the install is partial`};
  }
  const missing = REQUIRED_BINARIES.filter((name) => !existsSync(join(bin, name)));
  if (missing.length > 0) {
    return {
      ok: false,
      reason: `node_modules/.bin in ${root} is missing ${missing.join(', ')}, so the install is partial`,
    };
  }
  return {ok: true, reason: ''};
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

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const flag = process.argv.indexOf('--root');
  const root = flag === -1 ? DEFAULT_ROOT : resolve(process.argv[flag + 1] ?? '');
  const {ok, reason} = checkLocalInstall(root);
  if (!ok) {
    process.stderr.write(`[local-install] REFUSING: ${reason}\n${REMEDY}`);
    process.exit(1);
  }
}
