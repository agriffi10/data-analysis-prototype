import {
  describe,
  it,
  expect,
  vi,
  beforeEach,
  afterEach,
  type MockedFunction,
} from 'vitest';

vi.mock('../../lib/sqsClient', () => ({ getSqsClient: vi.fn() }));
vi.mock('../../lib/awsCredentials', () => ({ getIdToken: vi.fn() }));

import { getSqsClient } from '../../lib/sqsClient';
import { getIdToken } from '../../lib/awsCredentials';
import { enqueueSharedSpaceRequest } from './sharedSpaces.service';

const mockGetClient = getSqsClient as unknown as MockedFunction<
  () => Promise<unknown>
>;
const mockGetIdToken = getIdToken as unknown as MockedFunction<
  () => Promise<unknown>
>;

const QUEUE = 'https://sqs.us-east-1.amazonaws.com/123/dat-prod-shared-space-requests.fifo';

type SqsCommand = { input: Record<string, unknown> };

function fakeQueue() {
  const send = vi.fn<(cmd: SqsCommand) => Promise<{ MessageId: string }>>();
  send.mockResolvedValue({ MessageId: 'm1' });
  mockGetClient.mockResolvedValue({ success: true, data: { send } });
  return { send };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv('VITE_SHARED_SPACE_QUEUE_URL', QUEUE);
  mockGetIdToken.mockResolvedValue({ success: true, data: 'id-token-xyz' });
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('enqueueSharedSpaceRequest', () => {
  it('sends exactly one well-formed create message and returns the requestId', async () => {
    const { send } = fakeQueue();

    const result = await enqueueSharedSpaceRequest({
      action: 'create',
      actor: 'alice',
      space: 'sales_data',
    });

    expect(result.success).toBe(true);
    expect(send).toHaveBeenCalledTimes(1);

    const input = send.mock.calls[0][0].input;
    expect(input.QueueUrl).toBe(QUEUE);
    expect(input.MessageGroupId).toBe('shared-space'); // constant -> serial intake
    const body = JSON.parse(input.MessageBody as string);
    expect(body).toMatchObject({
      schemaVersion: 1,
      action: 'create',
      actor: 'alice',
      space: 'sales_data',
      payload: {},
      idToken: 'id-token-xyz',
    });
    expect(body.requestId).toEqual(expect.any(String));
    // The dedup id is the requestId so an accidental resend is collapsed.
    expect(input.MessageDeduplicationId).toBe(body.requestId);
    if (result.success) expect(result.data.requestId).toBe(body.requestId);
  });

  it('does not trust the body actor for auth — still carries the verified idToken', async () => {
    const { send } = fakeQueue();
    await enqueueSharedSpaceRequest({ action: 'create', actor: 'alice', space: 's' });
    const body = JSON.parse(
      send.mock.calls[0][0].input.MessageBody as string,
    );
    expect(body.idToken).toBe('id-token-xyz');
  });

  it('fails (no send) when the queue URL is not configured', async () => {
    vi.stubEnv('VITE_SHARED_SPACE_QUEUE_URL', '');
    const { send } = fakeQueue();
    const result = await enqueueSharedSpaceRequest({
      action: 'create',
      actor: 'alice',
      space: 's',
    });
    expect(result.success).toBe(false);
    expect(send).not.toHaveBeenCalled();
  });

  it('fails (no send) when the ID token cannot be obtained', async () => {
    mockGetIdToken.mockResolvedValue({
      success: false,
      error: { message: 'No ID token — sign in required' },
    });
    const { send } = fakeQueue();
    const result = await enqueueSharedSpaceRequest({
      action: 'create',
      actor: 'alice',
      space: 's',
    });
    expect(result.success).toBe(false);
    expect(send).not.toHaveBeenCalled();
  });

  it('returns a ServiceResult error (never throws) when SendMessage fails', async () => {
    const send = vi.fn<(cmd: SqsCommand) => Promise<never>>();
    send.mockRejectedValue(
      Object.assign(new Error('network'), { name: 'NetworkError' }),
    );
    mockGetClient.mockResolvedValue({ success: true, data: { send } });
    const result = await enqueueSharedSpaceRequest({
      action: 'create',
      actor: 'alice',
      space: 's',
    });
    expect(result).toEqual({
      success: false,
      error: { message: 'network', code: 'NetworkError' },
    });
  });
});
