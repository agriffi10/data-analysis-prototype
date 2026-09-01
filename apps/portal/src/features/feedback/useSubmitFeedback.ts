import {useMutation} from '@tanstack/react-query';
import {apiRetryPolicy} from '../../lib/apiClient';
import type {FeedbackSubmitResponse} from '../../types/apiContract.generated';
import type {ServiceResult} from '../../types/service.types';
import {submitFeedback} from './feedback.service';
import type {FeedbackCategory} from './feedback.types';

type SubmitInput = {category: FeedbackCategory; message: string; route?: string};

/**
 * The mutation behind the feedback dialog's Send button.
 *
 * `retry` comes from `apiRetryPolicy`, which reads the route's own `idempotent` declaration and
 * yields `false` here. It is not written as a literal on purpose: a submission retried by the
 * transport is a second entry in the day's file with no way to tell it from a deliberate one, and
 * a literal is a decision a hook can get wrong locally — the Data Explorer once carried `retry: 1`
 * on a billed, stateful call because it looked like a read.
 *
 * The service never throws, so the mutation resolves with the `ServiceResult` and the caller
 * branches on it. Nothing is invalidated afterwards: there is no read surface to refresh.
 *
 * @returns The mutation; `mutateAsync` resolves to the service result.
 *
 * @example
 * const submit = useSubmitFeedback();
 * const result = await submit.mutateAsync({category: 'bug', message, route});
 */
export function useSubmitFeedback() {
  return useMutation<ServiceResult<FeedbackSubmitResponse>, Error, SubmitInput>({
    mutationFn: submitFeedback,
    retry: apiRetryPolicy('feedback.submit')
  });
}
