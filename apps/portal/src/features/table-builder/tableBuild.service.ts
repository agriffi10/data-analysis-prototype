import {SendMessageCommand} from '@aws-sdk/client-sqs';
import {getSqsClient} from '../../lib/sqsClient';
import {getIdToken} from '../../lib/awsCredentials';
import {withCredentialRetry} from '../../lib/credentialRetry';
import {toServiceError} from '../../lib/serviceResult';
import {CATALOG_IDENTIFIER_RE} from '../query/query.constants';
import type {ServiceResult} from '../../types/service.types';
import type {TableBuildRequest} from './tableBuild.types';

/**
 * Enqueue a create-table request onto the table-builder FIFO queue — the browser's
 * only table-builder AWS call. The async control plane creates the table and
 * notifies the actor of the outcome, so success means enqueued, not created.
 *
 * The body carries the caller's ID token (the server derives the actor from the
 * verified claim — a body username is never trusted). MessageGroupId = the target
 * database (per-DB serialization closes the duplicate-name race); a fresh requestId
 * is the dedup id.
 */
export async function enqueueTableBuild(req: TableBuildRequest): Promise<ServiceResult<void>> {
  // Read at call time (not module load) so tests can stub the env — a module-level
  // import.meta.env const is read before vi.stubEnv runs.
  const queueUrl = import.meta.env.VITE_TABLE_BUILD_QUEUE_URL as string | undefined;
  if (!queueUrl) {
    return {success: false, error: {message: 'Table creation is not configured'}};
  }

  const token = await getIdToken();
  if (!token.success) return token;

  const requestId = crypto.randomUUID();
  const body = {
    idToken: token.data,
    space: req.space,
    tableName: req.tableName,
    partitionKeys: req.partitionKeys ?? [],
    requestId
  };

  return withCredentialRetry(getSqsClient, async (client) => {
    try {
      await client.send(
        new SendMessageCommand({
          QueueUrl: queueUrl,
          MessageBody: JSON.stringify(body),
          MessageGroupId: req.space.database,
          MessageDeduplicationId: requestId
        })
      );
      return {success: true, data: undefined};
    } catch (err) {
      return toServiceError(err, 'Failed to submit the request');
    }
  });
}

/**
 * Derive a suggested, catalog-safe table name from a folder name: lowercase,
 * non-conforming chars → `_`, leading letter ensured, trimmed to the max length.
 * UX only — the field stays editable and the name is re-checked client- and
 * server-side, so an edge-case suggestion just leaves Confirm disabled.
 */
export function suggestTableName(folderName: string): string {
  let s = folderName.toLowerCase().replace(/[^a-z0-9_]+/g, '_');
  s = s.replace(/^_+/, ''); // drop leading junk so a real letter can lead
  if (!/^[a-z]/.test(s)) s = `t_${s}`;
  s = s.replace(/_+$/, ''); // cosmetic: no trailing underscore
  if (s.length > 63) s = s.slice(0, 63).replace(/_+$/, '');
  return s;
}

/** The single client-side table-name check (UX only — the server re-validates). */
export function isValidTableName(name: string): boolean {
  return CATALOG_IDENTIFIER_RE.test(name);
}
