import {afterEach, describe, expect, it, vi} from 'vitest';
import {SESSION_VARIABLES} from './config';

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('the session route modules with no session configuration', () => {
  it('load, and answer 503 rather than failing', async () => {
    for (const name of SESSION_VARIABLES) vi.stubEnv(name, '');
    vi.spyOn(console, 'error').mockImplementation(() => undefined);

    const [sessionRoute, login, callback, logout, refresh, api] = await Promise.all([
      import('../../app/auth/session/route'),
      import('../../app/auth/login/route'),
      import('../../app/auth/callback/route'),
      import('../../app/auth/logout/route'),
      import('../../app/auth/refresh/route'),
      import('../../app/api/[...path]/route')
    ]);
    const response = await sessionRoute.GET(new Request('https://portal.example.test/auth/session'));

    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({error: {code: 'ApiUnavailable'}});
    for (const handler of [login.GET, callback.GET, logout.POST, refresh.POST, api.GET, api.POST]) {
      expect(handler).toBeTypeOf('function');
    }
  });
});
