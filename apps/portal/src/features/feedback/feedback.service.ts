import {apiRequest} from '../../lib/apiClient';
import type {FeedbackSubmitResponse} from '../../types/apiContract.generated';
import type {ServiceResult} from '../../types/service.types';
import type {FeedbackCategory} from './feedback.types';

/**
 * Submit one piece of feedback.
 *
 * Write-only by design: nothing is read back, which is what keeps feedback out of every rendering
 * and escaping question in the app. The submitter is not a parameter — the API takes it from the
 * verified token, and a username this function could pass would be one a caller could choose.
 *
 * @param input - The category, the message, and the in-app path the dialog captured when it opened.
 * @returns The API's stamp, or the machine code the dialog maps to wording.
 */
export async function submitFeedback(input: {
  category: FeedbackCategory;
  message: string;
  route?: string;
}): Promise<ServiceResult<FeedbackSubmitResponse>> {
  return apiRequest('feedback.submit', {
    body: {
      category: input.category,
      message: input.message,
      ...(input.route === undefined ? {} : {route: input.route})
    }
  });
}
