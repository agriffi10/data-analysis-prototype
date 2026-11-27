import {describe, expect, it, vi} from 'vitest';
import {createQueryClient} from './queryClient';

/** A read that always fails with `code`, and how many times the client sent it. */
async function sendsOf(code: string | undefined): Promise<number> {
  const read = vi.fn(async () => {
    throw Object.assign(new Error('refused'), code === undefined ? {} : {code});
  });
  const client = createQueryClient();
  await expect(client.fetchQuery({queryKey: ['read', code], queryFn: read, retryDelay: 0})).rejects.toThrow('refused');
  client.clear();
  return read.mock.calls.length;
}

describe('the app’s default retry', () => {
  it.each([
    'InvalidRequest',
    'SessionExpired',
    'AccessDenied',
    'NotFound',
    'Conflict',
    'PayloadTooLarge',
    'UnsupportedMediaType',
    'QuerySyntaxError',
    'UnsendableParameter',
    'DocumentTooLarge'
  ])('sends a read refused as %s once, since sending it again cannot change the answer', async (code) => {
    expect(await sendsOf(code)).toBe(1);
  });

  it.each([
    'NetworkUnavailable',
    'RequestTimeout',
    'ApiUnavailable',
    'RateLimited',
    'InternalError',
    'IdentityUnavailable',
    'QueryNotFinished'
  ])('sends a read that failed as %s a second time, since the next attempt may get through', async (code) => {
    expect(await sendsOf(code)).toBe(2);
  });

  it('sends a read that failed with no code a second time, as it always has', async () => {
    expect(await sendsOf(undefined)).toBe(2);
  });
});
