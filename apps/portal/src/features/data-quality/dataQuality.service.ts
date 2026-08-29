import {apiRequest} from '../../lib/apiClient';
import type {ServiceResult} from '../../types/service.types';
import type {DataQualityRequest} from './dataQuality.types';

/**
 * Enqueue a data-quality check onto the data-quality FIFO queue — the browser's only
 * data-quality write. The async control plane reads the data and writes the report, so
 * success means enqueued, not checked.
 *
 * The identity and the FIFO keys are the API's. The caller's own `requestId` is still the
 * double-submit guard and is still minted per submit — it is echoed back here so nothing above
 * this function has to learn where it came from.
 */
export async function enqueueQualityCheck(req: DataQualityRequest): Promise<ServiceResult<{requestId: string}>> {
  const result = await apiRequest('dataQuality.enqueue', {
    body: {requestId: req.requestId, space: req.space, location: req.location}
  });
  return result.success ? {success: true, data: {requestId: req.requestId}} : result;
}
