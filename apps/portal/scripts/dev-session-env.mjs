#!/usr/bin/env node
// Write the local portal server's environment into `apps/portal/.env.local`, between two marker lines.
//
// `npm run dev` serves the portal on http://localhost:5173 and signs in through the server's own
// session routes, with the local-development app client. Everything that server needs, the dev
// client's secret included, is one SSM SecureString the infrastructure renders from the same values
// as the deployed task's environment. This reads it with your AWS credentials and writes it here.
//
// IT PRINTS NAMES, NEVER VALUES, on success and on every failure, because the values include a client
// secret and this runs in terminals that are shared, recorded and pasted. A failure names the reason
// and, at most, a variable's name.
//
// ONLY THE MARKED BLOCK IS ITS OWN. Every other line of `.env.local` is kept as it was. The block is
// appended at the end, because the loader `next dev` uses takes the LAST of two lines naming one
// variable: a line written after the block overrides it.
//
// Usage: npm run dev:session-env [-- --parameter <name>] [--region <region>] [--out <path>]
import {execFileSync} from 'node:child_process';
import {chmodSync, existsSync, readFileSync, renameSync, writeFileSync} from 'node:fs';
import {dirname, join, relative} from 'node:path';
import {fileURLToPath} from 'node:url';

const PORTAL = join(dirname(fileURLToPath(import.meta.url)), '..');
const DEFAULTS = {
  parameter: '/dat-prod/portal/dev-session-env',
  region: 'us-east-1',
  // Not `--env-file`: Node reads that flag as its own even after the script's name.
  out: join(PORTAL, '.env.local')
};
const BEGIN = '# >>> npm run dev:session-env (generated; do not edit between these lines)';
const END = '# <<< npm run dev:session-env';

/** A variable name a `.env` file can hold. */
const NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;

/**
 * What a double-quoted `.env` value cannot carry as written: a line break ends it, `"` closes it, `\`
 * escapes, and `$` is expanded by the loader `next dev` uses, so `a$b` would arrive as `a`.
 */
const UNWRITABLE = /[\r\n"\\$]/;

/** Stop with a reason that names no value. */
function fail(reason) {
  console.error(`dev:session-env: ${reason}`);
  process.exit(1);
}

/** The options, from `--name value` pairs. */
function options(argv) {
  const chosen = {...DEFAULTS};
  for (let i = 0; i < argv.length; i += 2) {
    const flag = argv[i]?.replace(/^--/, '');
    if (!(flag in DEFAULTS) || argv[i + 1] === undefined) fail(`unknown or incomplete option ${argv[i]}`);
    chosen[flag] = argv[i + 1];
  }
  return chosen;
}

/** The parameter's value, read with the caller's own AWS credentials. */
function readParameter({parameter, region}) {
  try {
    return execFileSync(
      'aws',
      [
        'ssm',
        'get-parameter',
        '--name',
        parameter,
        '--with-decryption',
        '--query',
        'Parameter.Value',
        '--output',
        'text',
        '--region',
        region
      ],
      {encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe']}
    );
  } catch (error) {
    // The AWS CLI's own message names the parameter and the error, never the value.
    const detail = typeof error?.stderr === 'string' ? error.stderr.trim() : '';
    fail(`could not read ${parameter} (are your AWS credentials current?)${detail ? `\n${detail}` : ''}`);
  }
}

/** The variables, refusing anything that is not exactly an object of writable strings. */
function variables(text) {
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    // Not the parser's message: it quotes the text it could not read, and the text holds the secret.
    fail('the parameter is not JSON');
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed))
    fail('the parameter is not a JSON object');
  const entries = Object.entries(parsed);
  if (entries.length === 0) fail('the parameter names no variables');
  for (const [name, value] of entries) {
    if (!NAME.test(name)) fail('the parameter names a variable a .env file cannot hold');
    if (typeof value !== 'string') fail(`${name} is not a string`);
    if (UNWRITABLE.test(value))
      fail(`${name} carries a line break, a quote, a backslash or a $, which .env.local cannot hold`);
  }
  return entries.sort(([a], [b]) => a.localeCompare(b));
}

/** The file with its block replaced, or appended when it has none. */
function withBlock(existing, entries) {
  const block = [BEGIN, ...entries.map(([name, value]) => `${name}="${value}"`), END].join('\n');
  const lines = existing.split('\n');
  const begins = lines.filter((line) => line === BEGIN).length;
  const ends = lines.filter((line) => line === END).length;
  if (begins !== ends || begins > 1) fail('.env.local holds a damaged generated block; delete it and run this again');
  if (begins === 0) {
    const kept = existing.replace(/\n*$/, '');
    return `${kept}${kept ? '\n\n' : ''}${block}\n`;
  }
  const from = lines.indexOf(BEGIN);
  const to = lines.indexOf(END);
  if (to < from) fail('.env.local holds a damaged generated block; delete it and run this again');
  return [...lines.slice(0, from), block, ...lines.slice(to + 1)].join('\n');
}

const chosen = options(process.argv.slice(2));
const entries = variables(readParameter(chosen).trim());
const target = chosen.out;
const existing = existsSync(target) ? readFileSync(target, 'utf8') : '';
// Written beside the target and renamed over it, so a failure part-way never leaves half a file, and
// owner-only from the first byte.
const staged = `${target}.${process.pid}.tmp`;
writeFileSync(staged, withBlock(existing, entries), {mode: 0o600});
renameSync(staged, target);
chmodSync(target, 0o600);

const shown = relative(process.cwd(), target) || target;
console.log(
  `dev:session-env: wrote ${entries.length} variables to ${shown}: ${entries.map(([name]) => name).join(', ')}`
);
