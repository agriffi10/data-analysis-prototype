import {describe, expect, it} from 'vitest';
import {GET, HEAD} from './route';

describe('a /_next/ path that matched no built file', () => {
  it('is an honest plain-text 404, for GET and HEAD alike', async () => {
    for (const handler of [GET, HEAD]) {
      const response = handler();

      expect(response.status).toBe(404);
      expect(response.headers.get('content-type')).not.toContain('text/html');
      expect(response.headers.get('cache-control')).toBe('no-store');
    }
    expect(await GET().text()).toBe('not found\n');
  });
});
