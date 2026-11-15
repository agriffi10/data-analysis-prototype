import {describe, expect, it, vi} from 'vitest';
import {OPTIONAL_CONFIG, REQUIRED_CONFIG} from '../types/runtimeConfig.types';
import {SESSION_VARIABLES} from './session/config';
import {
  connectSource,
  refuseToStartWithoutConfiguration,
  renderRuntimeDocument,
  startupProblems
} from './runtimeDocument';

/** Every required variable set, a valid source list and usable session settings: a server that may start. */
function completeEnvironment(): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {PORTAL_CSP_CONNECT_SRC: "'self' https://api.portal.test"};
  for (const key of REQUIRED_CONFIG) env[`CONFIG_${key}`] = `value-of-${key}`;
  for (const name of SESSION_VARIABLES) env[name] = `value-of-${name}`;
  env.API_ORIGIN = 'https://api.portal.test';
  env.OIDC_TOKEN_URL = 'https://auth.portal.test/oauth2/token';
  env.OIDC_REVOKE_URL = 'https://auth.portal.test/oauth2/revoke';
  env.SESSION_MAX_AGE_SECONDS = '2592000';
  return env;
}

describe('the runtime document', () => {
  it('carries exactly version 1 and every classified key that is set, and nothing else', () => {
    const env = {
      ...completeEnvironment(),
      CONFIG_environment: 'prod',
      CONFIG_notAKey: 'published?',
      CONFIG_maxUploadBytes: ''
    };

    const document = renderRuntimeDocument(env);

    const expected: Record<string, unknown> = {version: 1, environment: 'prod'};
    for (const key of REQUIRED_CONFIG) expected[key] = `value-of-${key}`;
    expect(document).toEqual(expected);
  });

  it("publishes none of the session routes' server-only settings", () => {
    const env = completeEnvironment();
    for (const name of SESSION_VARIABLES) env[name] = `server-only-${name}`;

    const document = renderRuntimeDocument(env);

    expect(SESSION_VARIABLES.filter((name) => name.startsWith('CONFIG_'))).toEqual([]);
    expect(Object.keys(document).filter((key) => (SESSION_VARIABLES as readonly string[]).includes(key))).toEqual([]);
    expect(JSON.stringify(document)).not.toContain('server-only-');
  });

  it('round-trips a value carrying a quote and a backslash byte for byte', () => {
    const awkward = 'a "quoted" \\ value';
    const document = renderRuntimeDocument({...completeEnvironment(), CONFIG_environment: awkward});

    expect(JSON.parse(JSON.stringify(document)).environment).toBe(awkward);
  });

  it('reads the classification rather than a key list of its own', () => {
    // The risk that replaced the old entrypoint's own KEYS list: the server growing a second copy
    // of the classification, which then drifts from the browser's in silence.
    const source = Object.values(
      import.meta.glob('./runtimeDocument.ts', {query: '?raw', import: 'default', eager: true})
    )[0] as string;
    // Bare or with the variable prefix: `CONFIG_userSpaceBucket` is the spelling a second list here would use.
    const literals = new Set([...source.matchAll(/['"`](?:CONFIG_)?([A-Za-z]+)['"`]/g)].map(([, literal]) => literal));

    expect(source).toContain('REQUIRED_CONFIG');
    expect([...REQUIRED_CONFIG, ...OPTIONAL_CONFIG].filter((key) => literals.has(key))).toEqual([]);
  });
});

describe('the start-time refusal', () => {
  it('finds nothing wrong with a complete environment', () => {
    expect(startupProblems(completeEnvironment())).toEqual([]);
  });

  it('treats unset, empty and whitespace alike, and names every problem in one pass', () => {
    const env = completeEnvironment();
    env.CONFIG_userSpaceBucket = '  ';
    delete env.PORTAL_ORIGIN;
    env.API_ORIGIN = '';

    expect(startupProblems(env)).toEqual([
      {variable: 'CONFIG_userSpaceBucket', reason: 'unset-or-empty'},
      {variable: 'PORTAL_ORIGIN', reason: 'unset-or-empty'},
      {variable: 'API_ORIGIN', reason: 'unset-or-empty'}
    ]);
    expect(renderRuntimeDocument(env)).not.toHaveProperty('userSpaceBucket');
  });

  it.each([
    ['unset', undefined, 'unset-or-empty'],
    ['empty', '', 'unset-or-empty'],
    ['only whitespace', '   ', 'unset-or-empty'],
    ['carrying a quote', `'self" https://x`, 'invalid-characters'],
    ['carrying a semicolon', "'self'; script-src *", 'invalid-characters'],
    ['carrying a newline', "'self'\nX-Injected: 1", 'invalid-characters']
  ])('refuses PORTAL_CSP_CONNECT_SRC %s', (_label, value, reason) => {
    const env = completeEnvironment();
    if (value === undefined) delete env.PORTAL_CSP_CONNECT_SRC;
    else env.PORTAL_CSP_CONNECT_SRC = value;

    expect(startupProblems(env)).toEqual([{variable: 'PORTAL_CSP_CONNECT_SRC', reason}]);
  });

  it('exits 1 naming each variable on stderr, and never a value', () => {
    const env = completeEnvironment();
    env.CONFIG_userSpaceBucket = '';
    env.PORTAL_CSP_CONNECT_SRC = "'self'; secret-looking-value";
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    const exit = vi.fn() as unknown as (code: number) => never;

    refuseToStartWithoutConfiguration(env, exit);

    expect(exit).toHaveBeenCalledExactlyOnceWith(1);
    const lines = error.mock.calls.map(([line]) => String(line)).join('\n');
    expect(lines).toContain('CONFIG_userSpaceBucket');
    expect(lines).toContain('PORTAL_CSP_CONNECT_SRC');
    expect(lines).not.toContain('secret-looking-value');
    error.mockRestore();
  });

  it.each(SESSION_VARIABLES.map((name) => [name]))('exits 1 naming %s when that session setting is unset', (name) => {
    const env = completeEnvironment();
    delete env[name];
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    const exit = vi.fn() as unknown as (code: number) => never;

    refuseToStartWithoutConfiguration(env, exit);

    expect(exit).toHaveBeenCalledExactlyOnceWith(1);
    expect(error.mock.calls.map(([line]) => String(line))).toEqual([
      `portal: refusing to start. ${name} is unset or empty.`
    ]);
    error.mockRestore();
  });

  it('names a session setting the routes could not use, and not its value', () => {
    const env = completeEnvironment();
    env.API_ORIGIN = 'http://api.portal.test';
    env.SESSION_MAX_AGE_SECONDS = 'thirty days';

    expect(startupProblems(env)).toEqual([
      {variable: 'API_ORIGIN', reason: 'unusable'},
      {variable: 'SESSION_MAX_AGE_SECONDS', reason: 'unusable'}
    ]);
  });

  it('does not exit when the environment is complete', () => {
    const exit = vi.fn() as unknown as (code: number) => never;

    refuseToStartWithoutConfiguration(completeEnvironment(), exit);

    expect(exit).not.toHaveBeenCalled();
  });
});

describe('the connect-src the proxy reads per request', () => {
  it('is the validated variable', () => {
    expect(connectSource(completeEnvironment())).toBe("'self' https://api.portal.test");
  });

  it("fails closed to 'self' for a value the start-time check would have refused", () => {
    expect(connectSource({PORTAL_CSP_CONNECT_SRC: "'self'; script-src *"})).toBe("'self'");
    expect(connectSource({})).toBe("'self'");
    expect(connectSource({PORTAL_CSP_CONNECT_SRC: ' '})).toBe("'self'");
  });
});
