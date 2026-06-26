import { SendMessageCommand } from '@aws-sdk/client-sqs';
import { getSqsClient } from '../../lib/sqsClient';
import { getIdToken } from '../../lib/awsCredentials';
import { withCredentialRetry } from '../../lib/credentialRetry';
import type { ServiceResult } from '../../types/service.types';
import type { SharedSpaceAction, SharedSpaceRequest } from './sharedSpaces.types';

// The browser's ONLY shared-space write: enqueue a request onto the FIFO control
// queue (SPEC-051/056). A constant MessageGroupId serializes ALL requests so two
// users can't create the same name concurrently (SPEC-050); the requestId is the
// dedup id so an accidental resend is collapsed. The trusted actor is derived
// server-side from the verified idToken — the body `actor` is advisory.
const MESSAGE_GROUP_ID = 'shared-space';

export type EnqueueInput = {
  action: SharedSpaceAction;
  actor: string;
  space: string;
  payload?: Record<string, unknown>;
};

// Send one shared-space request. Returns the generated requestId on success.
// Never throws — returns the ServiceResult error shape.
export async function enqueueSharedSpaceRequest(
  input: EnqueueInput,
): Promise<ServiceResult<{ requestId: string }>> {
  // Read at call time (not module load) so tests can stub the env (the SPEC-040
  // lesson: a module-level import.meta.env const is read before vi.stubEnv runs).
  const queueUrl = import.meta.env.VITE_SHARED_SPACE_QUEUE_URL as
    | string
    | undefined;
  if (!queueUrl) {
    return {
      success: false,
      error: { message: 'Shared connections are not configured' },
    };
  }

  const token = await getIdToken();
  if (!token.success) return token;

  const requestId = crypto.randomUUID();
  const body: SharedSpaceRequest = {
    schemaVersion: 1,
    requestId,
    action: input.action,
    actor: input.actor,
    space: input.space,
    payload: input.payload ?? {},
    idToken: token.data,
  };

  return withCredentialRetry(getSqsClient, async (client) => {
    try {
      await client.send(
        new SendMessageCommand({
          QueueUrl: queueUrl,
          MessageBody: JSON.stringify(body),
          MessageGroupId: MESSAGE_GROUP_ID,
          MessageDeduplicationId: requestId,
        }),
      );
      return { success: true, data: { requestId } };
    } catch (err) {
      const e = err as { message?: string; name?: string };
      return {
        success: false,
        error: {
          message: e.message ?? 'Failed to submit the request',
          code: e.name,
        },
      };
    }
  });
}
