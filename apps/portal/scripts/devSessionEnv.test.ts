/* eslint-disable security/detect-non-literal-fs-filename -- every path here is under a temporary directory this test made */
import {spawnSync} from 'node:child_process';
import {chmodSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {afterEach, beforeEach, describe, expect, it} from 'vitest';
import {loadEnvConfig} from '@next/env';
import {startupProblems} from '../src/server/runtimeDocument';
import {SESSION_VARIABLES} from '../src/server/session/config';
import {REQUIRED_CONFIG} from '../src/types/runtimeConfig.types';

const SCRIPT = join(__dirname, 'dev-session-env.mjs');
// Built at runtime, so nothing secret-shaped sits in the history.
const SENTINEL = ['planted', 'dev', 'secret', String(Date.now())].join('-');

let dir: string;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), 'dev-session-env-'));
  // An `aws` on PATH that prints the parameter this test planted and records how it was called.
  writeFileSync(join(dir, 'aws'), `#!/bin/sh\necho "$@" > "${dir}/aws-args"\ncat "${dir}/parameter"\n`);
  chmodSync(join(dir, 'aws'), 0o755);
});

afterEach(() => rmSync(dir, {recursive: true, force: true}));

/** The parameter as the infrastructure renders it: every variable the start-time check requires. */
function rendered(): Record<string, string> {
  const value: Record<string, string> = {PORTAL_CSP_CONNECT_SRC: "'self' https://bucket.example.test"};
  for (const key of REQUIRED_CONFIG) value[`CONFIG_${key}`] = `value-of-${key}`;
  for (const name of SESSION_VARIABLES) value[name] = `value-of-${name}`;
  return {
    ...value,
    PORTAL_ORIGIN: 'http://localhost:5173',
    API_ORIGIN: 'https://api.example.test',
    OIDC_TOKEN_URL: 'https://auth.example.test/oauth2/token',
    OIDC_REVOKE_URL: 'https://auth.example.test/oauth2/revoke',
    SESSION_MAX_AGE_SECONDS: '2592000',
    OIDC_CLIENT_SECRET: SENTINEL
  };
}

/** Run the script against the planted parameter, writing this test's `.env.local`. */
function run(parameter: string) {
  writeFileSync(join(dir, 'parameter'), parameter);
  const result = spawnSync(process.execPath, [SCRIPT, '--out', join(dir, '.env.local')], {
    encoding: 'utf8',
    env: {...process.env, PATH: `${dir}:${process.env.PATH}`}
  });
  return {
    status: result.status,
    output: `${result.stdout}${result.stderr}`,
    ran: result.stderr.startsWith('dev:session-env: ') || result.stdout.startsWith('dev:session-env: ')
  };
}

/**
 * `.env.local` as `next dev` reads it, with the process environment left as it was. Under `next dev`
 * `NODE_ENV` is `development`; the loader skips `.env.local` altogether when it is `test`, as it is here.
 */
function asNextReadsIt(): Record<string, string | undefined> {
  const before = {...process.env};
  try {
    process.env.NODE_ENV = 'development';
    return loadEnvConfig(dir, true, {info: () => {}, error: () => {}}, true).parsedEnv ?? {};
  } finally {
    for (const key of Object.keys(process.env)) if (!(key in before)) delete process.env[key];
    Object.assign(process.env, before);
  }
}

describe('npm run dev:session-env', () => {
  it('writes one marked block a local server can start from, keeps other lines, and prints no value', () => {
    writeFileSync(join(dir, '.env.local'), 'KEEP_ME=kept\n', {mode: 0o644});

    const first = run(JSON.stringify(rendered()));
    // An editor that turned the file to CRLF must not hide the block from the next run.
    writeFileSync(join(dir, '.env.local'), readFileSync(join(dir, '.env.local'), 'utf8').replace(/\n/g, '\r\n'));
    const runs = [first, run(JSON.stringify(rendered()))];

    for (const {status, output} of runs) {
      expect(status).toBe(0);
      expect(output).not.toContain(SENTINEL);
      expect(output).not.toContain('api.example.test');
    }
    expect(runs[1].output).toContain('OIDC_CLIENT_SECRET');
    const written = readFileSync(join(dir, '.env.local'), 'utf8');
    expect(written.match(/^# >>> npm run dev:session-env/gm)).toHaveLength(1);
    expect(written.match(/^# <<< npm run dev:session-env$/gm)).toHaveLength(1);
    expect(statSync(join(dir, '.env.local')).mode & 0o777).toBe(0o600);
    expect(readFileSync(join(dir, 'aws-args'), 'utf8')).toContain(
      'ssm get-parameter --name /dat-prod/portal/dev-session-env --with-decryption'
    );

    const env = asNextReadsIt();
    expect(env.KEEP_ME).toBe('kept');
    expect(env.OIDC_CLIENT_SECRET).toBe(SENTINEL);
    expect(env.PORTAL_CSP_CONNECT_SRC).toBe("'self' https://bucket.example.test");
    expect(startupProblems(env)).toEqual([]);
  });

  it('exits non-zero and prints nothing from a parameter it cannot write, writing nothing', () => {
    // Short, because a JSON parser's message quotes only the first few characters of what it could
    // not read: a long secret leaks a prefix, and a short one leaks whole.
    const short = `s${Date.now().toString(36).slice(-6)}`;
    const refused = run(short);
    expect([refused.status, refused.ran]).toEqual([1, true]);
    expect(refused.output).not.toContain(short);

    for (const parameter of [
      JSON.stringify({...rendered(), OIDC_CLIENT_SECRET: `${SENTINEL}$tail`}),
      JSON.stringify([SENTINEL])
    ]) {
      const {status, output, ran} = run(parameter);

      // The script's own refusal, not Node refusing to start it.
      expect([status, ran]).toEqual([1, true]);
      expect(output).not.toContain(SENTINEL);
    }
    expect(() => statSync(join(dir, '.env.local'))).toThrow();
  });
});
