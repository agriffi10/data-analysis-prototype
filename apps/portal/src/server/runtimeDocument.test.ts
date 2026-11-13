import {describe, expect, it, vi} from 'vitest';
import {OPTIONAL_CONFIG, REQUIRED_CONFIG} from '../types/runtimeConfig.types';
import {
  connectSource,
  refuseToStartWithoutConfiguration,
  renderRuntimeDocument,
  startupProblems
} from './runtimeDocument';

/** Every required variable set, plus a valid source list: a server that may start. */
function completeEnvironment(): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {PORTAL_CSP_CONNECT_SRC: "'self' https://api.portal.test"};
  for (const key of REQUIRED_CONFIG) env[`CONFIG_${key}`] = `value-of-${key}`;
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

  it('round-trips a value carrying a quote and a backslash byte for byte', () => {
    const awkward = 'a "quoted" \\ value';
    const document = renderRuntimeDocument({...completeEnvironment(), CONFIG_appUrl: awkward});

    expect(JSON.parse(JSON.stringify(document)).appUrl).toBe(awkward);
  });

  it('reads the classification rather than a key list of its own', () => {
    // The risk that replaced the old entrypoint's own KEYS list: the server growing a second copy
    // of the classification, which then drifts from the browser's in silence.
    const source = Object.values(
      import.meta.glob('./runtimeDocument.ts', {query: '?raw', import: 'default', eager: true})
    )[0] as string;
    // Bare or with the variable prefix: `CONFIG_appUrl` is the spelling a second list here would use.
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
    delete env.CONFIG_appUrl;
    env.CONFIG_cognitoDomain = '';
    env.CONFIG_apiBaseUrl = '  ';

    expect(startupProblems(env)).toEqual([
      {variable: 'CONFIG_apiBaseUrl', reason: 'unset-or-empty'},
      {variable: 'CONFIG_appUrl', reason: 'unset-or-empty'},
      {variable: 'CONFIG_cognitoDomain', reason: 'unset-or-empty'}
    ]);
    expect(renderRuntimeDocument(env)).not.toHaveProperty('apiBaseUrl');
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
