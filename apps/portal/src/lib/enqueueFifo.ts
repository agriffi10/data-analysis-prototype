import {SendMessageCommand} from '@aws-sdk/client-sqs';
import {getSqsClient} from './sqsClient';
import {getIdToken} from './awsCredentials';
import {withCredentialRetry} from './credentialRetry';
import {toServiceError} from './serviceResult';
import type {ServiceResult} from '../types/service.types';

/** The per-request parts a caller supplies; `data` is the success payload to return. */
export type FifoMessage<T> = {
  /** The message body (JSON-stringified by the helper). */
  body: unknown;
  /** FIFO ordering key (per-user, per-target, or a constant serializer). */
  messageGroupId: string;
  /** FIFO dedup id (a requestId, a content hash, or a fresh UUID). */
  deduplicationId: string;
  /** Value for the success `ServiceResult` (`undefined` for the void enqueues). */
  data: T;
};

/**
 * Enqueue one message onto a FIFO SQS control-plane queue — the shared skeleton every
 * feature's "enqueue a request" service repeated (table-builder / table-share /
 * shared-spaces / notifications / data-quality).
 *
 * Guards the (call-time-read) queue URL, fetches the caller's Cognito ID token and hands
 * it to `build` so the body/group/dedup can embed it, sends via `withCredentialRetry`,
 * and maps any failure through `toServiceError`. The browser's only write to these
 * queues; success means *enqueued*, not processed.
 *
 * @param queueUrl - The queue's configured URL, read at call time (may be undefined).
 * @param notConfiguredMessage - User-safe error when the queue URL is unset.
 * @param build - Given the verified ID token, returns the body + FIFO keys + success data.
 *
 * @example
 * return enqueueFifoRequest({
 *   queueUrl: configValue('tableBuildQueueUrl'),
 *   notConfiguredMessage: 'Table creation is not configured',
 *   build: (idToken) => ({body: {idToken, ...}, messageGroupId: db, deduplicationId: id, data: undefined}),
 * });
 */
export async function enqueueFifoRequest<T>(opts: {
  queueUrl: string | undefined;
  notConfiguredMessage: string;
  build: (idToken: string) => FifoMessage<T> | Promise<FifoMessage<T>>;
}): Promise<ServiceResult<T>> {
  const {queueUrl, notConfiguredMessage, build} = opts;
  if (!queueUrl) {
    // The code is what carries the wording to the user: `toUserMessage` keys on
    // `code ?? name`, so a failure without one falls through to GENERIC.
    return {success: false, error: {message: notConfiguredMessage, code: 'NotConfigured'}};
  }
  const token = await getIdToken();
  if (!token.success) return token;

  const {body, messageGroupId, deduplicationId, data} = await build(token.data);
  return withCredentialRetry(getSqsClient, async (client) => {
    try {
      await client.send(
        new SendMessageCommand({
          QueueUrl: queueUrl,
          MessageBody: JSON.stringify(body),
          MessageGroupId: messageGroupId,
          MessageDeduplicationId: deduplicationId
        })
      );
      return {success: true, data};
    } catch (err) {
      return toServiceError(err, 'Failed to submit the request');
    }
  });
}
