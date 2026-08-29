import {apiRequest} from '../../lib/apiClient';
import {discardPayload} from '../../lib/serviceResult';
import type {ServiceResult} from '../../types/service.types';
import type {TableShareRequest} from './tableShare.types';

/**
 * Enqueue a share-table request onto the table-share FIFO queue — the browser's
 * only table-share write. The async control plane copies the data and creates
 * the recipient tables, so success means enqueued, not shared.
 *
 * The FIFO keys are the API's now. Its dedup digest is keyed on the VERIFIED ACTOR rather than
 * on the ID token this used to hash, which closes a guard that lapsed silently: two submits a
 * minute apart with a token refresh between them used to be two shares.
 */
export async function enqueueTableShare(req: TableShareRequest): Promise<ServiceResult<void>> {
  return discardPayload(
    await apiRequest('tableShare.enqueue', {
      body: {source: req.source, tableName: req.tableName, recipients: req.recipients}
    })
  );
}
