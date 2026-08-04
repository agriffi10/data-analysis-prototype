import {enqueueFifoRequest} from '../../lib/enqueueFifo';
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
  const requestId = crypto.randomUUID();
  return enqueueFifoRequest<void>({
    // Read at call time (not module load) so tests can stub the env — a module-level
    // import.meta.env const is read before vi.stubEnv runs.
    queueUrl: import.meta.env.VITE_TABLE_BUILD_QUEUE_URL as string | undefined,
    notConfiguredMessage: 'Table creation is not configured',
    build: (idToken) => ({
      // The body is built field by field, so a new request field is NOT forwarded by
      // being added to the type: `mode` (SPEC-143) is deliberately absent here, and the
      // server reads its absence as 'create'. SPEC-145 adds it with the refresh caller.
      body: {
        idToken,
        space: req.space,
        tableName: req.tableName,
        partitionKeys: req.partitionKeys ?? [],
        requestId
      },
      messageGroupId: req.space.database,
      deduplicationId: requestId,
      data: undefined
    })
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
