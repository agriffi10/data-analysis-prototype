import {beforeEach, describe, expect, it, vi} from 'vitest';
import {mockApi, apiFailure} from '../../test/apiMock';
import type {ApiMock} from '../../test/apiMock';
import {enqueueTableShare} from './tableShare.service';
import type {TableShareRequest} from './tableShare.types';

vi.mock('../../lib/apiClient', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/apiClient')>()),
  apiRequest: vi.fn()
}));

/**
 * The table-share enqueue, now over the API.
 *
 * **The dedup id is deliberately absent from this file.** It used to be computed here — a SHA-256
 * over the token, the request and a one-minute bucket — and every assertion about it (that a
 * double-submit collapses, that a different request does not, that recipient order does not
 * matter) moved to `lambdas/api/test_fifo_derivations.py`, where the derivation now lives and
 * where it is also pinned field by field. Asserting it here would be asserting a fake.
 *
 * It also got stronger in the move: the digest is keyed on the verified actor rather than on the
 * token, so a token refresh between two submits no longer produces two shares.
 */
describe('enqueueTableShare', () => {
  let api: ApiMock;

  const req: TableShareRequest = {
    source: {database: 'alice', table: 'orders'},
    tableName: 'orders_copy',
    recipients: [
      {kind: 'user', name: 'bob'},
      {kind: 'space', name: 'salesteam'}
    ]
  };

  beforeEach(async () => {
    const {apiRequest} = await import('../../lib/apiClient');
    api = mockApi(vi.mocked(apiRequest));
  });

  it('sends the share once, and names nobody', async () => {
    api.on('tableShare.enqueue', {success: true, data: {requestId: null}});

    const result = await enqueueTableShare(req);

    expect(result).toEqual({success: true, data: undefined});
    expect(api.routes()).toEqual(['tableShare.enqueue']);
    expect(api.bodyFor('tableShare.enqueue')).toEqual({
      source: {database: 'alice', table: 'orders'},
      tableName: 'orders_copy',
      recipients: req.recipients
    });
  });

  it('returns the failure as a result and never throws', async () => {
    api.on('tableShare.enqueue', apiFailure('ApiUnavailable'));

    const result = await enqueueTableShare(req);

    expect(result.success).toBe(false);
    expect(result.success === false && result.error.code).toBe('ApiUnavailable');
  });
});
