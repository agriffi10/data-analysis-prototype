import {SendMessageCommand} from '@aws-sdk/client-sqs';
import {getSqsClient} from '../../lib/sqsClient';
import {getIdToken} from '../../lib/awsCredentials';
import {withCredentialRetry} from '../../lib/credentialRetry';
import {CATALOG_IDENTIFIER_RE} from '../query/query.constants';
import type {ServiceResult} from '../../types/service.types';
import type {TableBuildRequest} from './tableBuild.types';

// SPEC-071: the browser's ONE table-builder AWS call. It enqueues a create-table
// request onto the SPEC-066 FIFO queue and never creates the table itself — the
// async control plane (validate → check → inspect → infer → execute) does that and
// notifies the actor of the outcome (SPEC-072). Success here means ENQUEUED, not
// created. Returns ServiceResult and never throws (CLAUDE.md service rule).

function toServiceError(err: unknown, fallback: string) {
  const e = err as {message?: string; name?: string};
  return {success: false as const, error: {message: e.message ?? fallback, code: e.name}};
}

// FR-003: build the SPEC-067 envelope, attach the caller's verified ID token (the
// server derives the actor from it — a body username is never trusted), and send
// FIFO with MessageGroupId = the target database (per-DB serialization closes the
// duplicate-name race, architecture §2) and a fresh requestId as the dedup id.
export async function enqueueTableBuild(req: TableBuildRequest): Promise<ServiceResult<void>> {
  // Read at call time (not module load) so tests can stub the env (the SPEC-040
  // lesson: a module-level import.meta.env const is read before vi.stubEnv runs).
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

// FR-002: derive a suggested, catalog-safe table name from the current folder name.
// Lowercase, non-conforming chars → `_`, a leading letter ensured, trimmed to the
// max length. This is UX only — the field stays editable and the name is re-checked
// against CATALOG_IDENTIFIER_RE (and authoritatively server-side, SPEC-067), so a
// too-short/edge suggestion just leaves Confirm disabled until the user fixes it.
export function suggestTableName(folderName: string): string {
  let s = folderName.toLowerCase().replace(/[^a-z0-9_]+/g, '_');
  s = s.replace(/^_+/, ''); // drop leading junk so a real letter can lead
  if (!/^[a-z]/.test(s)) s = `t_${s}`;
  s = s.replace(/_+$/, ''); // cosmetic: no trailing underscore
  if (s.length > 63) s = s.slice(0, 63).replace(/_+$/, '');
  return s;
}

// Shared with the dialog + tests: the single client-side name check (UX only).
export function isValidTableName(name: string): boolean {
  return CATALOG_IDENTIFIER_RE.test(name);
}
