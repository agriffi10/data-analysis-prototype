import type {ServiceResult} from '../types/service.types';

/**
 * Return a `ServiceResult`'s data, or throw its error — the queryFn/mutationFn adapter.
 *
 * TanStack Query wants a value or a thrown error, but services return a `ServiceResult`.
 * This is the one place that bridges them: on failure it throws an `Error` carrying the
 * original `message` and `code` (so `toUserMessage` can still map by code at the render
 * boundary); on success it returns the data. Replaces the `if (!r.success) throw new
 * Error(r.error.message); return r.data;` pair repeated across every read/mutation hook.
 *
 * @param result - The `ServiceResult` returned by a service call.
 * @returns The success data.
 * @throws Error (with `.code`) when `result` is a failure.
 *
 * @example
 * queryFn: async () => unwrap(await listFiles(bucket, prefix))
 */
export function unwrap<T>(result: ServiceResult<T>): T {
  if (!result.success) {
    throw Object.assign(new Error(result.error.message), {code: result.error.code});
  }
  return result.data;
}

/**
 * Map a thrown value to the failure branch of a `ServiceResult`.
 *
 * The canonical adapter for the service layer's "never throw — return a result"
 * convention: unwrap an unknown error's `message`/`name`, falling back to `fallback`
 * when the thrown value carries no message. Callers keep only their fallback wording.
 *
 * @param err - The caught value (typed `unknown`; narrowed internally).
 * @param fallback - User-facing-safe message when `err` has no `.message`.
 *
 * @example
 * try {
 *   await s3.send(command);
 *   return {success: true, data};
 * } catch (err) {
 *   return toServiceError(err, 'Failed to list files');
 * }
 */
export function toServiceError(
  err: unknown,
  fallback: string
): {success: false; error: {message: string; code?: string}} {
  // `throw null` and `throw 'oops'` are legal, and this runs INSIDE a catch in a
  // function documented as never throwing — dereferencing the caught value
  // unguarded would raise a TypeError from the one place that must not.
  const e = (typeof err === 'object' && err !== null ? err : {}) as {message?: string; name?: string};
  return {success: false, error: {message: e.message ?? fallback, code: e.name}};
}
