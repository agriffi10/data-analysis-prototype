import {describe, it, expect, vi, beforeEach, afterEach, type MockedFunction} from 'vitest';

vi.mock('../../lib/s3Client', () => ({getS3Client: vi.fn()}));
vi.mock('../../lib/sqsClient', () => ({getSqsClient: vi.fn()}));
vi.mock('../../lib/awsCredentials', () => ({getIdToken: vi.fn()}));

import {getS3Client} from '../../lib/s3Client';
import {getSqsClient} from '../../lib/sqsClient';
import {getIdToken} from '../../lib/awsCredentials';
import {getNotifications, enqueueNotificationAction} from './notifications.service';
import type {Notification} from './notifications.types';

const mockGetS3 = getS3Client as unknown as MockedFunction<() => Promise<unknown>>;
const mockGetSqs = getSqsClient as unknown as MockedFunction<() => Promise<unknown>>;
const mockGetIdToken = getIdToken as unknown as MockedFunction<() => Promise<unknown>>;

const USER = 'alice';
const BUCKET = 'dat-prod-user-space';
const QUEUE = 'https://sqs.us-east-1.amazonaws.com/123/dat-prod-notifications-requests.fifo';

type Cmd = {input: Record<string, unknown>};

// Fake an S3 client whose GetObject returns the given body (or rejects). `body ===
// null` simulates a missing object body.
function fakeS3(opts: {body?: string | null; rejectWith?: unknown}) {
  const send = vi.fn();
  if (opts.rejectWith !== undefined) {
    send.mockRejectedValue(opts.rejectWith);
  } else {
    send.mockResolvedValue({
      Body: opts.body == null ? undefined : {transformToString: async () => opts.body}
    });
  }
  mockGetS3.mockResolvedValue({success: true, data: {send}});
  return {send};
}

function fakeQueue(rejectWith?: unknown) {
  const send = vi.fn<(cmd: Cmd) => Promise<{MessageId: string}>>();
  if (rejectWith !== undefined) send.mockRejectedValue(rejectWith);
  else send.mockResolvedValue({MessageId: 'm1'});
  mockGetSqs.mockResolvedValue({success: true, data: {send}});
  return {send};
}

const note = (over: Partial<Notification>): Notification => ({
  id: 'n1',
  message: 'hello',
  read: false,
  timestamp: '2026-06-28T00:00:00.000Z',
  ...over
});

beforeEach(() => {
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', BUCKET);
  vi.stubEnv('VITE_NOTIFICATIONS_QUEUE_URL', QUEUE);
  mockGetIdToken.mockResolvedValue({success: true, data: 'id-token-abc'});
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

describe('getNotifications', () => {
  it('reads from the per-user inbox key', async () => {
    const {send} = fakeS3({body: '[]'});
    await getNotifications(USER);
    expect(send).toHaveBeenCalledTimes(1);
    const cmd = send.mock.calls[0][0] as Cmd;
    expect(cmd.input).toMatchObject({Bucket: BUCKET, Key: 'alice/user_settings/notifications.json'});
  });

  it('returns rows newest-first', async () => {
    const older = note({id: 'old', timestamp: '2026-06-01T00:00:00.000Z'});
    const newer = note({id: 'new', timestamp: '2026-06-27T00:00:00.000Z'});
    fakeS3({body: JSON.stringify([older, newer])});
    const result = await getNotifications(USER);
    expect(result.success).toBe(true);
    if (result.success) expect(result.data.map((n) => n.id)).toEqual(['new', 'old']);
  });

  it('coerces a missing/odd read flag to a boolean', async () => {
    fakeS3({body: JSON.stringify([{id: 'a', message: 'm', timestamp: '2026-06-27T00:00:00.000Z'}])});
    const result = await getNotifications(USER);
    expect(result.success && result.data[0].read).toBe(false);
  });

  it('carries a link through to the reader, and drops a non-string one (SPEC-113 FR-008)', async () => {
    // `normalize` rebuilds each row field-by-field, so a field it doesn't name is
    // silently discarded. Without this test, dropping `link` there would make every
    // deep link vanish between S3 and the row with the whole suite still green —
    // the notification would arrive and simply not be clickable.
    fakeS3({
      body: JSON.stringify([
        note({id: 'linked', link: '/data-quality/alice/req-1'}),
        note({id: 'plain'}),
        {...note({id: 'bad-type'}), link: 42}
      ])
    });
    const result = await getNotifications(USER);
    expect(result.success).toBe(true);
    if (!result.success) return;
    const byId = Object.fromEntries(result.data.map((n) => [n.id, n]));
    expect(byId.linked.link).toBe('/data-quality/alice/req-1');
    expect(byId.plain).not.toHaveProperty('link');
    expect(byId['bad-type']).not.toHaveProperty('link');
  });

  it('drops malformed rows but keeps valid ones', async () => {
    fakeS3({body: JSON.stringify([{nope: true}, note({id: 'ok'})])});
    const result = await getNotifications(USER);
    expect(result.success).toBe(true);
    if (result.success) expect(result.data.map((n) => n.id)).toEqual(['ok']);
  });

  it('treats a 404 (missing inbox) as the empty state', async () => {
    fakeS3({rejectWith: {name: 'NoSuchKey'}});
    const result = await getNotifications(USER);
    expect(result).toEqual({success: true, data: []});
  });

  it('treats corrupt JSON as empty', async () => {
    fakeS3({body: '{not json'});
    const result = await getNotifications(USER);
    expect(result).toEqual({success: true, data: []});
  });

  it('treats a non-array root as empty', async () => {
    fakeS3({body: JSON.stringify({version: 1})});
    const result = await getNotifications(USER);
    expect(result).toEqual({success: true, data: []});
  });

  it('surfaces any other S3 error', async () => {
    fakeS3({rejectWith: {name: 'AccessDenied', message: 'no'}});
    const result = await getNotifications(USER);
    expect(result.success).toBe(false);
    if (!result.success) expect(result.error.code).toBe('AccessDenied');
  });
});

describe('enqueueNotificationAction', () => {
  it('sends markRead with id, the verified token, and MessageGroupId = username', async () => {
    const {send} = fakeQueue();
    const result = await enqueueNotificationAction({action: 'markRead', username: USER, id: 'n9'});
    expect(result.success).toBe(true);
    const cmd = send.mock.calls[0][0] as Cmd;
    expect(cmd.input.QueueUrl).toBe(QUEUE);
    expect(cmd.input.MessageGroupId).toBe(USER);
    expect(cmd.input.MessageDeduplicationId).toEqual(expect.any(String));
    expect(JSON.parse(cmd.input.MessageBody as string)).toEqual({
      action: 'markRead',
      idToken: 'id-token-abc',
      id: 'n9'
    });
  });

  it('sends markAllRead without an id', async () => {
    const {send} = fakeQueue();
    await enqueueNotificationAction({action: 'markAllRead', username: USER});
    const cmd = send.mock.calls[0][0] as Cmd;
    expect(JSON.parse(cmd.input.MessageBody as string)).toEqual({
      action: 'markAllRead',
      idToken: 'id-token-abc'
    });
  });

  it('never puts a client-asserted username in the body', async () => {
    const {send} = fakeQueue();
    await enqueueNotificationAction({action: 'markAllRead', username: USER});
    const body = JSON.parse((send.mock.calls[0][0] as Cmd).input.MessageBody as string);
    expect(body).not.toHaveProperty('username');
  });

  it('rejects markRead without an id and sends nothing', async () => {
    const {send} = fakeQueue();
    const result = await enqueueNotificationAction({action: 'markRead', username: USER});
    expect(result.success).toBe(false);
    expect(send).not.toHaveBeenCalled();
  });

  it('fails when the queue URL is not configured', async () => {
    vi.stubEnv('VITE_NOTIFICATIONS_QUEUE_URL', '');
    const {send} = fakeQueue();
    const result = await enqueueNotificationAction({action: 'markAllRead', username: USER});
    expect(result.success).toBe(false);
    expect(send).not.toHaveBeenCalled();
  });

  it('propagates an ID-token failure', async () => {
    fakeQueue();
    mockGetIdToken.mockResolvedValue({success: false, error: {message: 'no token'}});
    const result = await enqueueNotificationAction({action: 'markAllRead', username: USER});
    expect(result.success).toBe(false);
    if (!result.success) expect(result.error.message).toBe('no token');
  });

  it('returns a typed error when SendMessage fails', async () => {
    fakeQueue({name: 'Throttling', message: 'slow down'});
    const result = await enqueueNotificationAction({action: 'markAllRead', username: USER});
    expect(result.success).toBe(false);
    if (!result.success) expect(result.error.code).toBe('Throttling');
  });
});
