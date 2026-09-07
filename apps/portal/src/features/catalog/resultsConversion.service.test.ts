import {beforeEach, describe, expect, it, vi} from 'vitest';
import {mockApi, apiFailure} from '../../test/apiMock';
import type {ApiMock} from '../../test/apiMock';
import {apiRetryPolicy} from '../../lib/apiClient';
import {enqueueResultsConversion} from './resultsConversion.service';

vi.mock('../../lib/apiClient', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/apiClient')>()),
  apiRequest: vi.fn()
}));

/**
 * The browser's half of the results-conversion enqueue.
 *
 * What the plane does with the request is asserted in `lambdas/results-conversion-*`; what is
 * asserted here is the request itself — because the one field the two disagree about most easily
 * is `destination.prefix`, which is relative to the space root on the plane's side and absolute
 * on the picker's.
 */
describe('enqueueResultsConversion', () => {
  let api: ApiMock;

  beforeEach(async () => {
    const {apiRequest} = await import('../../lib/apiClient');
    api = mockApi(vi.mocked(apiRequest));
  });

  const request = {
    requestId: 'req-1',
    queryExecutionId: 'exec-1',
    format: 'parquet' as const,
    destination: {space: {kind: 'shared' as const, name: 'salesdata'}, prefix: 'reports/', filename: 'q1.parquet'},
    onConflict: 'refuse' as const,
    submittedAt: '2026-09-07T10:00:00.000Z'
  };

  it('sends the request verbatim and echoes the caller’s request id back', async () => {
    api.on('resultsConversion.enqueue', {success: true, data: {requestId: 'server-side-id'}});

    const result = await enqueueResultsConversion(request);

    expect(api.bodyFor('resultsConversion.enqueue')).toEqual(request);
    // The CALLER's id, not the route's: it is the double-submit guard the caller minted, and
    // the caller is the only thing that can settle its own record against it.
    expect(result).toEqual({success: true, data: {requestId: 'req-1'}});
  });

  it('returns the route’s failure with its code intact, so a surface can map wording to it', async () => {
    api.on('resultsConversion.enqueue', apiFailure('InvalidRequest'));

    const result = await enqueueResultsConversion(request);

    expect(result.success).toBe(false);
    expect(result.success === false && result.error.code).toBe('InvalidRequest');
  });

  it('is declared non-idempotent, so nothing retries an enqueue', () => {
    // Read through the function that DECIDES the retry rather than off the generated table:
    // the table is what this repo generates, and asserting it against itself would pass on a
    // route whose policy nothing consults.
    expect(apiRetryPolicy('resultsConversion.enqueue')).toBe(false);
  });
});
