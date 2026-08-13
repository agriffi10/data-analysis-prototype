import {describe, it, expect, vi, beforeEach, afterEach, type MockedFunction} from 'vitest';

vi.mock('../../lib/sqsClient', () => ({getSqsClient: vi.fn()}));
vi.mock('../../lib/awsCredentials', () => ({getIdToken: vi.fn()}));

import {getSqsClient} from '../../lib/sqsClient';
import {getIdToken} from '../../lib/awsCredentials';
import {enqueueArchive, enqueueRestore} from './archive.service';
import type {ArchiveRequest, RestoreRequest} from '../../types/archive.types';

const mockGetSqs = getSqsClient as unknown as MockedFunction<() => Promise<unknown>>;
const mockGetIdToken = getIdToken as unknown as MockedFunction<() => Promise<unknown>>;

const QUEUE = 'https://sqs.us-east-1.amazonaws.com/123/dat-prod-archive-requests.fifo';

type Cmd = {input: Record<string, unknown>};

function fakeQueue(rejectWith?: unknown) {
  const send = vi.fn<(cmd: Cmd) => Promise<{MessageId: string}>>();
  if (rejectWith !== undefined) send.mockRejectedValue(rejectWith);
  else send.mockResolvedValue({MessageId: 'm1'});
  mockGetSqs.mockResolvedValue({success: true, data: {send}});
  return {send};
}

/** The digest a group id must equal, computed the same way the service does. */
async function sha256Hex(input: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(input));
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

function body(send: {mock: {calls: [Cmd][]}}, call = 0): Record<string, unknown> {
  return JSON.parse(send.mock.calls[call][0].input.MessageBody as string);
}

const archiveReq: ArchiveRequest = {
  requestId: '11111111-1111-4111-8111-111111111111',
  space: {kind: 'personal', name: 'alice'},
  items: [
    {kind: 'file', key: 'alice/reports/q1.csv'},
    {kind: 'folder', key: 'alice/reports/2026/'}
  ]
};

const restoreReq: RestoreRequest = {
  requestId: '22222222-2222-4222-8222-222222222222',
  space: {kind: 'personal', name: 'alice'},
  archiveId: '33333333-3333-4333-8333-333333333333'
};

beforeEach(() => {
  vi.stubEnv('VITE_ARCHIVE_QUEUE_URL', QUEUE);
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'dat-prod-user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'dat-prod-shared-space');
  mockGetIdToken.mockResolvedValue({success: true, data: 'id-token-abc'});
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

describe('enqueueArchive', () => {
  it('builds the SPEC-168 archive envelope exactly', async () => {
    const {send} = fakeQueue();

    const result = await enqueueArchive(archiveReq);

    expect(result.success).toBe(true);
    const cmd = send.mock.calls[0][0];
    expect(cmd.input.QueueUrl).toBe(QUEUE);
    expect(body(send)).toEqual({
      requestId: archiveReq.requestId,
      mode: 'archive',
      actor: 'id-token-abc',
      source: {space: {kind: 'personal', name: 'alice'}, items: archiveReq.items}
    });
  });

  it('puts the token at the TOP LEVEL, where the shared DLQ drain reads and redacts it', async () => {
    // Not a style point. dlq_drain._notify_one does body.get("actor") and _redacted replaces
    // TOP-LEVEL keys only, so a nested {actor: {idToken}} would notify nobody on a dead-lettered
    // archive AND write the raw JWT to CloudWatch. Every plane's envelope is flat for this.
    const {send} = fakeQueue();

    await enqueueArchive(archiveReq);

    expect(body(send).actor).toBe('id-token-abc');
  });

  it('never sends a username — the actor is derived from the verified token server-side', async () => {
    const {send} = fakeQueue();

    await enqueueArchive(archiveReq);

    const raw = send.mock.calls[0][0].input.MessageBody as string;
    expect(JSON.parse(raw)).not.toHaveProperty('username');
    // `alice` is legitimately present as the SPACE name; what must not appear is a claim about
    // who is asking. The space is authorized against the verified actor, not trusted from here.
    expect(body(send).source).toEqual({space: {kind: 'personal', name: 'alice'}, items: archiveReq.items});
  });

  it('keys the FIFO group on {spaceBucket}/{spaceRoot} so one space serializes', async () => {
    const {send} = fakeQueue();

    await enqueueArchive(archiveReq);

    expect(send.mock.calls[0][0].input.MessageGroupId).toBe(await sha256Hex('dat-prod-user-space/alice/'));
  });

  it('uses the shared-space bucket for a shared space, so the two namespaces cannot collide', async () => {
    // A space named `alice` and a user named `alice` can both exist — nothing checks a proposed
    // space name against the User Pool (arcommon.paths records this). Without the bucket in the
    // canonical string, their archives would serialize against each other for no reason.
    const {send} = fakeQueue();

    await enqueueArchive({
      ...archiveReq,
      space: {kind: 'shared', name: 'alice'},
      items: [{kind: 'file', key: 'alice/q.csv'}]
    });

    expect(send.mock.calls[0][0].input.MessageGroupId).toBe(await sha256Hex('dat-prod-shared-space/alice/'));
  });

  it('deduplicates on the requestId, which is also the archive’s permanent identity', async () => {
    const {send} = fakeQueue();

    await enqueueArchive(archiveReq);

    expect(send.mock.calls[0][0].input.MessageDeduplicationId).toBe(archiveReq.requestId);
  });

  it('refuses a selection over the item cap without calling SQS', async () => {
    const {send} = fakeQueue();

    const result = await enqueueArchive({
      ...archiveReq,
      items: Array.from({length: 201}, (_, i) => ({kind: 'file' as const, key: `alice/f${i}.csv`}))
    });

    expect(result).toEqual({success: false, error: {message: expect.any(String), code: 'SelectionTooLarge'}});
    expect(send).not.toHaveBeenCalled();
  });

  it('refuses a selection over the byte cap even when the count is legal', async () => {
    // The two caps bound different quantities: the count bounds per-item work, the bytes bound
    // what rides on the state and reaches the Pipe. A handful of very long keys passes one and
    // not the other.
    const {send} = fakeQueue();

    const result = await enqueueArchive({
      ...archiveReq,
      items: Array.from({length: 50}, (_, i) => ({kind: 'file' as const, key: `alice/${'k'.repeat(2000)}${i}.csv`}))
    });

    expect(result.success).toBe(false);
    expect(send).not.toHaveBeenCalled();
  });

  it('reports a user-safe message when the queue URL is unset', async () => {
    vi.stubEnv('VITE_ARCHIVE_QUEUE_URL', '');
    const {send} = fakeQueue();

    const result = await enqueueArchive(archiveReq);

    expect(result).toEqual({success: false, error: {message: 'Archiving is not configured', code: 'NotConfigured'}});
    expect(send).not.toHaveBeenCalled();
  });

  it('returns a ServiceResult rather than throwing when the send fails', async () => {
    fakeQueue(new Error('network down'));

    const result = await enqueueArchive(archiveReq);

    expect(result.success).toBe(false);
  });
});

describe('enqueueRestore', () => {
  it('builds the SPEC-170 restore envelope exactly, with no selection in it', async () => {
    const {send} = fakeQueue();

    const result = await enqueueRestore(restoreReq);

    expect(result.success).toBe(true);
    expect(body(send)).toEqual({
      requestId: restoreReq.requestId,
      mode: 'restore',
      actor: 'id-token-abc',
      space: {kind: 'personal', name: 'alice'},
      archiveId: restoreReq.archiveId
    });
  });

  it('sends requestId and archiveId as DIFFERENT values', async () => {
    // Conflating them is the obvious shortcut and is wrong in both directions: a refused restore
    // must be re-submittable under a new run id, and a second attempt at one archive is a new
    // request (SPEC-170 FR-001 AC2).
    const {send} = fakeQueue();

    await enqueueRestore(restoreReq);

    const sent = body(send);
    expect(sent.requestId).not.toBe(sent.archiveId);
  });

  it('keys the FIFO group on the ARCHIVE ROOT, so two restores of one archive serialize', async () => {
    const {send} = fakeQueue();

    await enqueueRestore(restoreReq);

    expect(send.mock.calls[0][0].input.MessageGroupId).toBe(
      await sha256Hex(`personal/alice/archive/${restoreReq.archiveId}/`)
    );
  });

  it('separates the two space kinds through the archive root’s own kind segment', async () => {
    // The `personal/`/`shared/` segment is what makes the archive root globally unique without
    // the bucket name — which the browser deliberately does not know (SPEC-168).
    const {send} = fakeQueue();

    await enqueueRestore({...restoreReq, space: {kind: 'shared', name: 'alice'}});

    expect(send.mock.calls[0][0].input.MessageGroupId).toBe(
      await sha256Hex(`shared/alice/archive/${restoreReq.archiveId}/`)
    );
  });

  it('never names the archive bucket, in the group id or anywhere else', async () => {
    // The browser has no relationship with that bucket by decision, and its name is not in this
    // app's build env at all — `test_archive_bucket_isolation.py` holds that from the other side.
    // This is the producer half: nothing here can reintroduce the name through a hash.
    const {send} = fakeQueue();

    await enqueueRestore(restoreReq);

    const cmd = send.mock.calls[0][0];
    expect(JSON.stringify(cmd.input)).not.toContain('archive-bucket');
    expect(cmd.input.MessageGroupId).not.toBe(
      await sha256Hex(`dat-prod-archive/personal/alice/archive/${restoreReq.archiveId}/`)
    );
  });

  it('sends the archive id through untouched — the normalising happens in the hook', async () => {
    // Stated because the obvious reading is wrong and a test once asserted the opposite while
    // being unable to fail: its fixture id was digits and hyphens only, so `toUpperCase()` was a
    // no-op on it and the service's pass-through looked like a lowercase. The real normalising is
    // `useRestoreArchive`'s, and it is asserted there, against an id that HAS letters in it.
    const {send} = fakeQueue();
    const mixed = '3F8A1C2E-9b4d-4A17-8c65-2E0D7B1F4A93';

    await enqueueRestore({...restoreReq, archiveId: mixed});

    expect(body(send).archiveId).toBe(mixed);
  });

  it('deduplicates on the RUN id, not the archive id', async () => {
    const {send} = fakeQueue();

    await enqueueRestore(restoreReq);

    expect(send.mock.calls[0][0].input.MessageDeduplicationId).toBe(restoreReq.requestId);
  });

  it('reports a user-safe message when the queue URL is unset', async () => {
    vi.stubEnv('VITE_ARCHIVE_QUEUE_URL', '');
    const {send} = fakeQueue();

    const result = await enqueueRestore(restoreReq);

    expect(result).toEqual({success: false, error: {message: 'Restoring is not configured', code: 'NotConfigured'}});
    expect(send).not.toHaveBeenCalled();
  });
});

describe('the two modes’ group ids', () => {
  it('differ for the same space, so an archive and a restore never serialize against each other', async () => {
    // One group id for both would make a restore wait behind an unrelated archive of the same
    // space — and, worse, would stop two restores of ONE archive from serializing, which is the
    // only thing the restore's group id is for.
    const {send} = fakeQueue();

    await enqueueArchive(archiveReq);
    await enqueueRestore(restoreReq);

    expect(send.mock.calls[0][0].input.MessageGroupId).not.toBe(send.mock.calls[1][0].input.MessageGroupId);
  });
});
