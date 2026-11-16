import {describe, expect, it} from 'vitest';
import {GET} from './route';

describe('GET /healthz', () => {
  it('answers ok as plain text, which no page can be mistaken for', async () => {
    const response = GET();

    expect(response.status).toBe(200);
    expect(response.headers.get('content-type')).toBe('text/plain');
    expect(response.headers.get('cache-control')).toBe('no-store');
    expect(await response.text()).toBe('ok');
  });
});
