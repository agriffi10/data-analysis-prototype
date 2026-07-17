import {SendMessageCommand} from '@aws-sdk/client-sqs';
import {getSqsClient} from '../../lib/sqsClient';
import {getIdToken} from '../../lib/awsCredentials';
import {withCredentialRetry} from '../../lib/credentialRetry';
import {toServiceError} from '../../lib/serviceResult';
import type {ServiceResult} from '../../types/service.types';
import type {DataQualityRequest} from './dataQuality.types';

/** Collapse a key to its canonical form so the same folder always hashes the same. */
function normalizeLocation(location: string): string {
  return location.trim().replace(/^\/+/, '').replace(/\/+$/, '');
}

/**
 * MessageGroupId = the SHA-256 hex digest (exactly 64 chars) of `{bucket}/{location}`.
 *
 * It is a HASH, never the raw location, and that is a requirement rather than a style
 * choice: SQS caps MessageGroupId at 128 characters while S3 keys reach 1024, so a raw
 * bucket-plus-prefix group id would fail the send IN THE BROWSER — for exactly the users
 * with the deepest folder structures. The other producers get away with a raw id only
 * because they group by a bounded catalog identifier (a database name, <= 63 chars by
 * CATALOG_IDENTIFIER_RE).
 *
 * Hashing the location also preserves the property the FIFO queue is here for: two checks
 * of the SAME location produce the same group id and serialize; different locations get
 * different group ids and run in parallel.
 */
async function locationGroupId(bucket: string, location: string): Promise<string> {
  const canonical = `${bucket}/${normalizeLocation(location)}`;
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical));
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

/**
 * Enqueue a data-quality check onto the data-quality FIFO queue — the browser's only
 * data-quality AWS call. The async control plane reads the data and writes the report, so
 * success means enqueued, not checked.
 *
 * The envelope carries the caller's ID token and NO username: validate-authorize derives
 * the actor from the verified claim, so a body cannot assert an identity.
 * MessageDeduplicationId = requestId (the queue has content-based dedup OFF, so this
 * explicit id is the only double-submit guard).
 */
export async function enqueueQualityCheck(req: DataQualityRequest): Promise<ServiceResult<{requestId: string}>> {
  // Read at call time (not module load) so tests can stub the env — a module-level
  // import.meta.env const is read before vi.stubEnv runs.
  const queueUrl = import.meta.env.VITE_DATA_QUALITY_QUEUE_URL as string | undefined;
  if (!queueUrl) {
    return {success: false, error: {message: 'Data quality checks are not configured'}};
  }

  const token = await getIdToken();
  if (!token.success) return token;

  const body = {
    requestId: req.requestId,
    idToken: token.data,
    space: req.space,
    location: req.location
  };
  const groupId = await locationGroupId(req.space.bucket, req.location);

  return withCredentialRetry(getSqsClient, async (client) => {
    try {
      await client.send(
        new SendMessageCommand({
          QueueUrl: queueUrl,
          MessageBody: JSON.stringify(body),
          MessageGroupId: groupId,
          MessageDeduplicationId: req.requestId
        })
      );
      return {success: true, data: {requestId: req.requestId}};
    } catch (err) {
      return toServiceError(err, 'Failed to submit the request');
    }
  });
}
