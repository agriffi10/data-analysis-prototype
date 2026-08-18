import {enqueueFifoRequest} from '../../lib/enqueueFifo';
import type {ServiceResult} from '../../types/service.types';
import type {TableShareRequest} from './tableShare.types';

/** Dedup window: double-submits of the identical request inside one bucket collapse. */
const DEDUP_BUCKET_MS = 60_000;

/**
 * Stable per-request dedup id: a SHA-256 of the caller's token +
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
  return enqueueFifoRequest<void>({
    // Read at call time (not module load) so tests can stub the env — a module-level
    // import.meta.env const is read before vi.stubEnv runs.
    queueUrl: import.meta.env.VITE_TABLE_SHARE_QUEUE_URL as string | undefined,
    notConfiguredMessage: 'Table sharing is not configured',
    build: async (idToken) => ({
      body: {
        actor: idToken,
        source: req.source,
        tableName: req.tableName,
        recipients: req.recipients
      },
      messageGroupId: `${req.source.database}.${req.source.table}`,
      deduplicationId: await dedupId(idToken, req),
      data: undefined
    })
  });
}
