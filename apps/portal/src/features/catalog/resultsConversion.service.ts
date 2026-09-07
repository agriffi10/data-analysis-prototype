import {apiRequest} from '../../lib/apiClient';
import type {ServiceResult} from '../../types/service.types';
import type {ResultsConversionEnqueueRequest} from '../../types/apiContract.generated';

/**
 * Enqueue one results conversion onto the results-conversion FIFO queue.
 *
 * The plane reads the execution's results object, writes the file under a conditional
 * `PutObject` and notifies. Success here means **enqueued**, not converted — nothing is written
 * when this resolves, which is why the caller invalidates no listing and the notification is the
 * completion channel.
 *
 * The identity and the FIFO keys are the API's. The caller's own `requestId` is the double-submit
 * guard, minted per submit, and is echoed back so nothing above this has to learn where it came
 * from — the shape every enqueue service in this repo has.
 *
 * @param request - The enqueue body, whose type is the generated one.
 * @returns The request id, or the route's failure with its code intact.
 */
export async function enqueueResultsConversion(
  request: ResultsConversionEnqueueRequest
): Promise<ServiceResult<{requestId: string}>> {
  const result = await apiRequest('resultsConversion.enqueue', {body: request});
  return result.success ? {success: true, data: {requestId: request.requestId}} : result;
}
