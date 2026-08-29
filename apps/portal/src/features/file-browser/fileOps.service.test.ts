import {beforeEach, describe, expect, it, vi} from 'vitest';
import {apiFailure, mockApi} from '../../test/apiMock';
import type {ApiMock} from '../../test/apiMock';
import {submitFileOperation} from './fileOps.service';
import type {FileOpRequest} from './fileOps.types';

vi.mock('../../lib/apiClient', () => ({apiRequest: vi.fn()}));

/**
 * The file-operations enqueue, now over the API.
 *
 * **The FIFO keys are deliberately absent from this file.** The group id — the digest of
 * `{bucket}/{spaceRoot}`, which this plane hashes a second time to key its per-space lock, and
 * which had to survive a space name arriving with a trailing slash — and the dedup id, which is
 * the request id and this plane's only double-submit guard, are computed server-side now and
 * replayed against vectors captured from this service in `lambdas/api/test_fifo_derivations.py`,
 * for a personal and a shared space and for a copy and a delete alike. So is the flat top-level
 * token the shared DLQ drain reads and redacts.
 *
 * What stays here is the browser's half: the two selection caps, still refused in this process
 * before anything is sent, and the shape of the body — which fields ride and which are omitted.
 */
type CopyRequest = Extract<FileOpRequest, {operation: 'copy' | 'move'}>;

function request(overrides: Partial<CopyRequest> = {}): CopyRequest {
  return {
    requestId: 'req-1',
    operation: 'copy',
    source: {space: {kind: 'personal', name: 'alice'}, items: [{kind: 'file', key: 'alice/q1.csv'}]},
    destination: {space: {kind: 'personal', name: 'alice'}, prefix: 'alice/out/'},
    onConflict: 'refuse',
    submittedAt: '2026-08-19T12:00:00Z',
    ...overrides
  };
}

describe('submitFileOperation', () => {
  let api: ApiMock;

  beforeEach(async () => {
    const {apiRequest} = await import('../../lib/apiClient');
    api = mockApi(vi.mocked(apiRequest));
  });

  it('sends the copy once, forwarding the conflict answer it was given unchanged', async () => {
    // Deliberately NOT titled "never sends an overwrite on a first submit". This service forwards
    // whatever the caller supplies, so nothing here can make a first submit incapable of carrying
    // `overwrite` — that is a property of the CALLER, and it is dischargeable only where the
    // gesture is built.
    api.on('fileOps.enqueue', {success: true, data: {requestId: 'req-1'}});

    const result = await submitFileOperation(request());
    await submitFileOperation(request({requestId: 'req-2', onConflict: 'overwrite'}));

    expect(result).toEqual({success: true, data: undefined});
    expect(api.routes()).toEqual(['fileOps.enqueue', 'fileOps.enqueue']);
    // `toEqual`, not `toMatchObject`: the absence of a claimed identity is the assertion. The API
    // refuses a body carrying `actor`, `identity` or `idToken` outright.
    expect(api.bodyFor('fileOps.enqueue')).toEqual({
      requestId: 'req-1',
      operation: 'copy',
      source: {space: {kind: 'personal', name: 'alice'}, items: [{kind: 'file', key: 'alice/q1.csv'}]},
      destination: {space: {kind: 'personal', name: 'alice'}, prefix: 'alice/out/'},
      onConflict: 'refuse',
      submittedAt: '2026-08-19T12:00:00Z'
    });
    expect((api.calls[1].body as {onConflict: string}).onConflict).toBe('overwrite');
  });

  it('omits the copy-only fields for a delete rather than sending nulls', async () => {
    // The plane REJECTS them on a delete rather than ignoring them, so an explicit null would
    // arrive as a field the contract forbids and the whole request would be refused. Gated on the
    // OPERATION, not on whether the fields happen to be set.
    api.on('fileOps.enqueue', {success: true, data: {requestId: 'req-2'}});

    await submitFileOperation({
      requestId: 'req-2',
      operation: 'delete',
      source: {space: {kind: 'personal', name: 'alice'}, items: [{kind: 'folder', key: 'alice/old/'}]}
    });

    expect(Object.keys(api.bodyFor('fileOps.enqueue') as object)).toEqual(['requestId', 'operation', 'source']);
  });

  it('returns the failure as a result and never throws', async () => {
    api.on('fileOps.enqueue', apiFailure('ApiUnavailable'));

    const result = await submitFileOperation(request());

    expect(result.success).toBe(false);
    expect(result.success === false && result.error.code).toBe('ApiUnavailable');
  });

  it('refuses a selection over the item cap without calling the API', async () => {
    const items = Array.from({length: 201}, (_, n) => ({kind: 'file' as const, key: `alice/${n}.csv`}));

    const result = await submitFileOperation(request({source: {space: {kind: 'personal', name: 'alice'}, items}}));

    expect(result.success === false && result.error.code).toBe('SelectionTooLarge');
    expect(api.calls).toEqual([]);
  });

  it('refuses a selection over the byte cap even when the item count is fine', async () => {
    // The count cannot stand in for the bytes: S3 keys are arbitrary UTF-8 and escaping expands a
    // control character to six bytes, so a selection well inside the item cap can be several times
    // the payload limit.
    const items = Array.from({length: 100}, (_, n) => ({kind: 'file' as const, key: `alice/${'k'.repeat(1000)}${n}`}));

    const result = await submitFileOperation(request({source: {space: {kind: 'personal', name: 'alice'}, items}}));

    expect(result.success === false && result.error.code).toBe('SelectionTooLarge');
    expect(api.calls).toEqual([]);
  });
});
