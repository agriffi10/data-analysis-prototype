import {afterEach, describe, expect, it, vi} from 'vitest';
import {GET} from './route';

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('GET /config.json', () => {
  it('serves the document from the server environment, never cached', async () => {
    vi.stubEnv('CONFIG_appUrl', 'https://portal.test');
    vi.stubEnv('CONFIG_awsRegion', 'us-east-1');

    const response = GET();

    expect(response.status).toBe(200);
    expect(response.headers.get('content-type')).toContain('application/json');
    expect(response.headers.get('cache-control')).toBe('no-store');
    const body = (await response.json()) as Record<string, unknown>;
    expect(body).toMatchObject({version: 1, appUrl: 'https://portal.test', awsRegion: 'us-east-1'});
  });
});
