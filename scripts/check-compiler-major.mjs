/**
 * Refuse to build when `tsc` is not the TypeScript the workspace declares.
 *
 * WHY THERE ARE TWO. TypeScript 7 is the native port and ships no programmatic API before 7.1, so
 * typescript-eslint still peer-pins `<6.1.0`. npm settles that by keeping the declared 7.x in
 * `apps/portal/node_modules` — where `tsc -b` finds it first — and hoisting a 6.x copy to the
 * workspace root for the linter. Both are load-bearing; neither is a mistake to clean up.
 *
 * THE FAILURE THIS EXISTS FOR. Node resolves `typescript` by walking UP, so if the workspace copy
 * goes missing — a partial install, a hand-deleted directory, an `npm dedupe` that collapses the
 * "duplicate" — `tsc` silently resolves to the root's 6.x and the build typechecks against the
 * WRONG COMPILER, exiting 0. Nothing else notices: `check-local-install.mjs` finds a `tsc` in the
 * root `.bin` and passes (reproduced, with the workspace copy renamed away), the bundle builds and
 * the suite is green. The only tell is `npx tsc --version` printing a 6, which nobody runs on a
 * green branch. A 7-only type error would then reach `main` behind a green PR.
 *
 * This is the one install check that MUST use module resolution rather than a filesystem probe —
 * the opposite of `check-local-install.mjs`, and for the same underlying reason. Walking up is what
 * produces the wrong answer here, so the question can only be asked by walking up and seeing where
 * it lands. Asking the filesystem whether a path exists would answer a different question.
 */

import {createRequire} from 'node:module';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

/** Leading major of a range or a version — `~7.0.2` and `7.0.2` both give 7. */
const major = (spec) => Number(/(\d+)/.exec(spec)?.[1]);

/**
 * Compare the TypeScript a build in `workspace` would resolve against the one it declares.
 *
 * @param {string} workspace Absolute path to the workspace directory holding the package.json.
 * @returns {{ok: boolean, reason: string}} `ok` false with a one-line `reason` naming both
 *   versions when they disagree; `ok` true and an empty `reason` otherwise.
 */
export function checkCompilerMajor(workspace) {
  const require = createRequire(resolve(workspace, 'package.json'));

  const declared = require('./package.json').devDependencies?.typescript;
  if (declared === undefined) {
    return {ok: false, reason: `${workspace}/package.json declares no typescript devDependency`};
  }

  let resolved;
  try {
    resolved = require('typescript/package.json').version;
  } catch {
    return {ok: false, reason: `no typescript resolves from ${workspace} at all`};
  }

  if (major(resolved) !== major(declared)) {
    return {
      ok: false,
      reason: `${workspace} declares typescript ${declared} but resolves ${resolved}`,
    };
  }
  return {ok: true, reason: ''};
}

const REMEDY = `
\`tsc -b\` would run a TypeScript this workspace does not declare — almost always the copy hoisted
to the repo root for typescript-eslint, which peer-pins an older major on purpose. The build would
typecheck against the wrong compiler and exit 0.

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

