import {afterEach, describe, expect, it, vi} from 'vitest';
import {SESSION_VARIABLES, SessionConfigError, sessionConfig} from './config';

afterEach(() => {
  vi.unstubAllEnvs();
});

/** Every session variable set to a usable value, with the three credential URLs given. */
function environment(urls: {api: string; token: string; revoke: string}) {
  for (const name of SESSION_VARIABLES) vi.stubEnv(name, 'value');
  vi.stubEnv('SESSION_MAX_AGE_SECONDS', '2592000');
  vi.stubEnv('API_ORIGIN', urls.api);
  vi.stubEnv('OIDC_TOKEN_URL', urls.token);
  vi.stubEnv('OIDC_REVOKE_URL', urls.revoke);
}

describe('the session configuration', () => {
  it('refuses plain HTTP for each URL the server sends a credential to, unless it is loopback', () => {
    const secure = {
      api: 'https://api.test',
      token: 'https://auth.test/oauth2/token',
      revoke: 'https://auth.test/oauth2/revoke'
    };
    const cases: [keyof typeof secure, string][] = [
      ['api', 'API_ORIGIN'],
      ['token', 'OIDC_TOKEN_URL'],
      ['revoke', 'OIDC_REVOKE_URL']
    ];
    for (const [key, variable] of cases) {
      for (const insecure of ['http://auth.test/x', 'ftp://auth.test/x', 'not a url']) {
        environment({...secure, [key]: insecure});
        expect(() => sessionConfig()).toThrow(new SessionConfigError(variable));
      }
    }

    environment(secure);
    expect(sessionConfig()).toMatchObject({apiOrigin: secure.api, tokenUrl: secure.token, revokeUrl: secure.revoke});
    environment({api: 'http://127.0.0.1:9100', token: 'http://localhost:9100/t', revoke: 'http://[::1]:9100/r'});
    expect(sessionConfig().tokenUrl).toBe('http://localhost:9100/t');
  });
});
