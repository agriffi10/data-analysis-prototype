import {QueryClient} from '@tanstack/react-query';
import type {ApiClientCode} from './apiClient';
import type {ApiErrorCode} from '../types/apiContract.generated';

/**
 * The refusals a second send cannot change: the request is wrong, the caller may not have it, it is
 * not there, or it is too large to read. `DocumentTooLarge` is the document reader's own code.
 *
 * Everything else is sent once more, an unknown code and an error with none included: a timeout is
 * often a function waking up, and the second attempt is what gets through.
 */
const FINAL_CODES: ReadonlySet<string> = new Set([
  'InvalidRequest',
  'SessionExpired',
  'AccessDenied',
  'NotFound',
  'Conflict',
  'PayloadTooLarge',
  'UnsupportedMediaType',
  'QuerySyntaxError',
  'UnsendableParameter',
  'DocumentTooLarge'
] as const satisfies readonly (ApiErrorCode | ApiClientCode | 'DocumentTooLarge')[]);

/**
 * Whether a failed read is sent again: once, unless its code says the answer is final.
 *
 * @param failureCount - How many times the read has failed before this one.
 * @param error - What the read threw; a service's failure carries its `code`.
 * @returns True to send the read again.
 */
function retryUnlessFinal(failureCount: number, error: unknown): boolean {
  const code = (error as {code?: unknown} | null)?.code;
  return failureCount < 1 && !(typeof code === 'string' && FINAL_CODES.has(code));
}

/**
 * The app's QueryClient — all server state (S3 reads/writes) lives in it — made by the frame once
 * per mount, never at module scope: a client shared by the module would be shared across server
 * requests the day anything renders it there, and this file is the one home of its defaults.
 *
 * Defaults: staleTime 30s (avoids refetch storms when navigating back into a
 * recently viewed prefix); one retry for a failure that may pass, none for a refusal that
 * cannot (`retryUnlessFinal`); refetchOnWindowFocus off. A hook that sets its own `retry`
 * replaces the default whole, and a route's retry policy does not read the code.
 *
 * The focus default is a floor, not a rule, and two queries deliberately opt out of it. The
 * notifications inbox always did. The FILE LISTING joined them once file operations moved onto a
 * control plane: the folder in view can change minutes after the browser stops watching, so a
 * listing that only refetches on navigation is stale for as long as the user stays put.
 *
 * This module knows nothing about any feature. `invalidateListing` used to live
 * here and imported `features/file-browser`'s key factory to do it — the same
 * layering inversion the `components/` ESLint rule forbids one layer up. It now
 * sits in `features/file-browser/invalidateListing.ts`, beside the keys it builds.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: retryUnlessFinal,
        refetchOnWindowFocus: false
      }
    }
  });
}
