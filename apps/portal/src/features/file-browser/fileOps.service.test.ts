import {SendMessageCommand} from '@aws-sdk/client-sqs';
import {beforeEach, describe, expect, it, vi, type MockedFunction} from 'vitest';
import {submitFileOperation} from './fileOps.service';
import type {FileOpRequest} from './fileOps.types';

vi.mock('../../lib/sqsClient', () => ({getSqsClient: vi.fn()}));
vi.mock('../../lib/awsCredentials', () => ({getIdToken: vi.fn()}));

import {getIdToken} from '../../lib/awsCredentials';
import {getSqsClient} from '../../lib/sqsClient';

const send = vi.fn();
const mockGetSqs = getSqsClient as unknown as MockedFunction<() => Promise<unknown>>;
const mockGetIdToken = getIdToken as unknown as MockedFunction<() => Promise<unknown>>;

/**
 * The pinned cross-runtime vector. The plane's own suite asserts the identical pair, and both were
 * computed independently in Node and Python rather than copied from either — a value copied from
 * one runtime asserts only that that runtime is self-consistent, which is not the property that
 * matters.
 */
const VECTOR_DIGEST = 'fdeab79570d11a19a05ce52dba54a66b83597ae4fb6eecfd1a378e83b1b6a039';

function request(overrides: Partial<FileOpRequest> = {}): FileOpRequest {
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

function body() {
  return JSON.parse(send.mock.calls[0][0].input.MessageBody);
}

describe('submitFileOperation', () => {
  beforeEach(() => {
    send.mockReset();
    send.mockResolvedValue({MessageId: 'm1'});
    mockGetSqs.mockResolvedValue({success: true, data: {send}});
    mockGetIdToken.mockResolvedValue({success: true, data: 'id-token'});
    vi.stubEnv('VITE_FILE_OPS_QUEUE_URL', 'https://sqs.us-east-1.amazonaws.com/1/dat-prod-file-ops-requests.fifo');
    vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'dat-prod-user-space');
    vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'dat-prod-shared-space');
  });

  it('enqueues the request and reports success as ENQUEUED', async () => {
    const result = await submitFileOperation(request());

    expect(result).toEqual({success: true, data: undefined});
    expect(send.mock.calls[0][0]).toBeInstanceOf(SendMessageCommand);
  });

  it('rides the token as a FLAT top-level actor', async () => {
    // Nested, the shared DLQ drain would neither notify anyone about a dead-lettered request nor
    // redact the field — writing the raw JWT to CloudWatch.
    await submitFileOperation(request());

    expect(body().actor).toBe('id-token');
  });

  it('groups by the SHA-256 of {bucket}/{spaceRoot}, matching the plane digest for digest', async () => {
    await submitFileOperation(request());

    expect(send.mock.calls[0][0].input.MessageGroupId).toBe(VECTOR_DIGEST);
  });

  it('dedups on the requestId, which is the only double-submit guard', async () => {
    // Content-based dedup is OFF on the queue, so two byte-identical operations a user genuinely
    // repeats are not silently absorbed by a five-minute window.
    await submitFileOperation(request());

    expect(send.mock.calls[0][0].input.MessageDeduplicationId).toBe('req-1');
  });

  it('omits the copy-only fields for a delete rather than sending nulls', async () => {
    // The plane REJECTS them on a delete rather than ignoring them, so an explicit null would
    // arrive as a field the contract forbids and the whole request would be refused.
    await submitFileOperation({
      requestId: 'req-2',
      operation: 'delete',
      source: {space: {kind: 'personal', name: 'alice'}, items: [{kind: 'folder', key: 'alice/old/'}]}
    });

    expect(Object.keys(body())).toEqual(['requestId', 'actor', 'operation', 'source']);
  });

  it('never sends an overwrite on a first submit', async () => {
    // `overwrite` is reachable only from the conflict round trip, where the user has been shown
    // what collided — and even then the plane bounds it by `submittedAt`.
    await submitFileOperation(request());

    expect(body().onConflict).toBe('refuse');
  });

  it('refuses a selection over the item cap without calling AWS', async () => {
    const items = Array.from({length: 201}, (_, n) => ({kind: 'file' as const, key: `alice/${n}.csv`}));

    const result = await submitFileOperation(request({source: {space: {kind: 'personal', name: 'alice'}, items}}));

    expect(result.success).toBe(false);
    expect(send).not.toHaveBeenCalled();
  });

  it('refuses a selection over the byte cap even when the item count is fine', async () => {
    // The count cannot stand in for the bytes: S3 keys are arbitrary UTF-8 and escaping expands a
    // control character to six bytes, so a selection well inside the item cap can be several times
    // the payload limit.
    const items = Array.from({length: 100}, (_, n) => ({kind: 'file' as const, key: `alice/${'k'.repeat(1000)}${n}`}));

    const result = await submitFileOperation(request({source: {space: {kind: 'personal', name: 'alice'}, items}}));

    expect(result.success).toBe(false);
    expect(send).not.toHaveBeenCalled();
  });

  it('reports a user-safe message when the queue URL is unset', async () => {
    vi.stubEnv('VITE_FILE_OPS_QUEUE_URL', undefined);

    const result = await submitFileOperation(request());

    expect(result).toEqual({
      success: false,
      error: {message: 'File operations are not configured', code: 'NotConfigured'}
    });
  });

  it('resolves a shared space to the shared bucket', async () => {
    await submitFileOperation(
      request({source: {space: {kind: 'shared', name: 'sales'}, items: [{kind: 'file', key: 'sales/q1.csv'}]}})
    );

    const digest = send.mock.calls[0][0].input.MessageGroupId;

    expect(digest).not.toBe(VECTOR_DIGEST);
    expect(digest).toMatch(/^[0-9a-f]{64}$/);
  });
});
