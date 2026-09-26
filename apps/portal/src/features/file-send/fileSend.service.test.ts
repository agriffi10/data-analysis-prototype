import {beforeEach, describe, expect, it, vi} from 'vitest';
import {apiFailure, mockApi} from '../../test/apiMock';
import type {ApiMock} from '../../test/apiMock';
import {enqueueFileSend, SEND_MAX_RECIPIENTS} from './fileSend.service';
import {toUserText} from '../../lib/errorMessages';
import type {FileSendRequest} from './fileSend.types';

vi.mock('../../lib/apiClient', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/apiClient')>()),
  apiRequest: vi.fn()
}));

/**
 * The file-send enqueue, now over the API.
 *
 * **The FIFO keys are deliberately absent from this file.** The group id — the digest of
 * `{sourceBucket}/{spaceRoot}`, which orders the starts of two sends out of one space and lets
 * two different spaces run in parallel — and the dedup id, which is the request id and this plane's
 * only double-submit guard, are computed server-side now and replayed against vectors captured
 * from this service in `lambdas/api/test_fifo_derivations.py`, for a personal and a shared source
 * alike. So is the flat top-level token the shared DLQ drain reads and redacts.
 *
 * The field allowlist moved too, and got teeth it did not have here: the API refuses an unknown
 * field rather than forwarding it, and refuses a body claiming an identity outright
 * (`lambdas/api/test_enqueue_routes.py`).
 *
 * What stays is the browser's half — the two caps, which are still refused in this process before
 * anything is sent, and which exist because a request too large for `StartExecution` never
 * reaches the verb that would refuse it.
 */
const req: FileSendRequest = {
  requestId: 'req-abc',
  space: {kind: 'personal', name: 'alice'},
  items: [
    {kind: 'file', key: 'alice/reports/q1.csv'},
    {kind: 'folder', key: 'alice/reports/2026/'}
  ],
  recipients: [
    {kind: 'user', name: 'bob'},
    {kind: 'space', name: 'finance'}
  ]
};

describe('enqueueFileSend', () => {
  let api: ApiMock;

  beforeEach(async () => {
    const {apiRequest} = await import('../../lib/apiClient');
    api = mockApi(vi.mocked(apiRequest));
  });

  it('sends the request once, carrying the source selection and the recipients', async () => {
    api.on('fileSend.enqueue', {success: true, data: {requestId: 'req-abc'}});

    const result = await enqueueFileSend(req);

    // The route answers `{requestId}` and the caller's signature is `ServiceResult<void>`.
    expect(result).toEqual({success: true, data: undefined});
    expect(api.routes()).toEqual(['fileSend.enqueue']);
    // `toEqual`, not `toMatchObject`: the absence of a claimed identity is the assertion.
    expect(api.bodyFor('fileSend.enqueue')).toEqual({
      requestId: 'req-abc',
      source: {space: {kind: 'personal', name: 'alice'}, items: req.items},
      recipients: req.recipients
    });
  });

  it('returns the failure as a result and never throws', async () => {
    api.on('fileSend.enqueue', apiFailure('ApiUnavailable'));

    const result = await enqueueFileSend(req);

    expect(result.success).toBe(false);
    expect(result.success === false && result.error.code).toBe('ApiUnavailable');
  });

  it('refuses a selection too large to start an execution, without calling the API', async () => {
    // The verb enforces the same cap, but it runs in the machine's FIRST TASK — and a request too
    // large for StartExecution never gets there, because the Pipe cannot start the execution at
    // all. Without this the user waits for a DLQ-drain notification instead of being told now.
    const huge = Array.from({length: 200}, (_, i) => ({
      kind: 'file' as const,
      key: 'alice/' + '"'.repeat(600) + i
    }));

    const result = await enqueueFileSend({...req, items: huge});

    expect(result.success === false && result.error.code).toBe('SelectionTooLarge');
    expect(api.calls).toEqual([]);
    // And the wording reaches the user: without a rule in errorMessages the refusal presents as
    // "Something went wrong", which is the one thing a fixable limit must not say.
    if (!result.success) expect(toUserText(result.error)).toContain('too large');
  });

  it('refuses more recipients than the plane accepts, now and in words, without calling the API', async () => {
    const everyone = Array.from({length: SEND_MAX_RECIPIENTS + 1}, (_, i) => ({
      kind: 'user' as const,
      name: `user_${i}`
    }));

    const result = await enqueueFileSend({...req, recipients: everyone});

    expect(api.calls).toEqual([]);
    if (!result.success) {
      expect(toUserText(result.error)).toBe(
        `You can send to at most ${SEND_MAX_RECIPIENTS} recipients at a time. Send to the rest in a second request.`
      );
    } else expect.unreachable('an over-cap send was requested');
  });

  it('refuses more items than the plane accepts, without calling the API', async () => {
    const many = Array.from({length: 201}, (_, i) => ({kind: 'file' as const, key: `alice/f${i}.csv`}));

    const result = await enqueueFileSend({...req, items: many});

    expect(result.success === false && result.error.code).toBe('SelectionTooLarge');
    expect(api.calls).toEqual([]);
  });

  it('sends an ordinary full selection without complaint', async () => {
    // The other side of both caps: a selection sitting exactly ON the item limit is legal, so a
    // cap written as `>=` would refuse a request the plane accepts.
    api.on('fileSend.enqueue', {success: true, data: {requestId: 'req-abc'}});
    const full = Array.from({length: 200}, (_, i) => ({
      kind: 'file' as const,
      key: `alice/reports/2026/q1/file-${i}.csv`
    }));

    const result = await enqueueFileSend({...req, items: full});

    expect(result.success).toBe(true);
    expect(api.countOf('fileSend.enqueue')).toBe(1);
  });
});
