import {SendMessageCommand} from '@aws-sdk/client-sqs';
import {getSqsClient} from '../../lib/sqsClient';
import {getIdToken} from '../../lib/awsCredentials';
import {withCredentialRetry} from '../../lib/credentialRetry';
import type {ServiceResult} from '../../types/service.types';
import type {TableShareRequest} from './tableShare.types';

function toServiceError(err: unknown, fallback: string) {
  const e = err as {message?: string; name?: string};
  return {success: false as const, error: {message: e.message ?? fallback, code: e.name}};
}

/** Dedup window: double-submits of the identical request inside one bucket collapse. */
const DEDUP_BUCKET_MS = 60_000;

/**
 * Stable per-request dedup id (SPEC-089 FR-001): a SHA-256 of the caller's token +
 * the request content + a one-minute time bucket, so an accidental double-submit
 * dedupes on the FIFO queue while a deliberate re-share later goes through (the
 * queue has content-based dedup OFF — this id is the only guard).
 */
async function dedupId(token: string, req: TableShareRequest): Promise<string> {
  const recipients = [...req.recipients].map((r) => `${r.kind}:${r.name}`).sort();
  const bucket = Math.floor(Date.now() / DEDUP_BUCKET_MS);
  const canonical = JSON.stringify([token, req.source, req.tableName, recipients, bucket]);
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical));
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

/**
 * Enqueue a share-table request onto the table-share FIFO queue — the browser's
 * only table-share AWS call. The async control plane copies the data and creates
 * the recipient tables, so success means enqueued, not shared.
 *
 * MessageGroupId = the source `database.table` (repeated shares of one source
 * serialize; different sources run in parallel); MessageDeduplicationId is the
 * stable content hash above.
 */
export async function enqueueTableShare(req: TableShareRequest): Promise<ServiceResult<void>> {
  // Read at call time (not module load) so tests can stub the env — a module-level
  // import.meta.env const is read before vi.stubEnv runs.
  const queueUrl = import.meta.env.VITE_TABLE_SHARE_QUEUE_URL as string | undefined;
  if (!queueUrl) {
    return {success: false, error: {message: 'Table sharing is not configured'}};
  }

  const token = await getIdToken();
  if (!token.success) return token;

  const body = {
    actor: token.data,
    source: req.source,
    tableName: req.tableName,
    recipients: req.recipients
  };
  const deduplicationId = await dedupId(token.data, req);

  return withCredentialRetry(getSqsClient, async (client) => {
    try {
      await client.send(
        new SendMessageCommand({
          QueueUrl: queueUrl,
          MessageBody: JSON.stringify(body),
          MessageGroupId: `${req.source.database}.${req.source.table}`,
          MessageDeduplicationId: deduplicationId
        })
      );
      return {success: true, data: undefined};
    } catch (err) {
      return toServiceError(err, 'Failed to submit the request');
    }
  });
}
