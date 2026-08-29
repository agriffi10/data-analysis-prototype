import type {ErrorParams} from '../types/apiContract.generated';
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
 * The success branch of a `ServiceResult`, as a one-word expression.
 *
 * `toServiceError`'s counterpart. Worth having only where a result is built somewhere
 * other than a `return` — `lib/s3Json.ts`'s `parse` callbacks, where six call sites had
 * otherwise written `{success: true, data: parseX(body)}` by hand.
 *
 * @example
 * parse: (body) => ok(parseStore(body))
 */
export function ok<T>(data: T): {success: true; data: T} {
  return {success: true, data};
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

/**
 * Turns an `apiRequest` failure into a service failure, keeping the machine code.
 *
 * **Not `toServiceError`.** That one is for a caught AWS exception and reads `e.message ?? fallback`
 * — and `??` does not fall back on the empty string, which is exactly what `apiRequest` returns for
 * `message`. Passing an API failure through it yields a blank message and a lost code, so every
 * caller downstream renders nothing and `toUserMessage` has nothing to map. The repo has paid for
 * that operator before: `cx()` returning `''` cost nine dialogs their width.
 *
 * @param error - The failure `apiRequest` returned.
 * @param fallback - The caller's user-safe wording, used when nothing better is known.
 * @returns The service failure, carrying the code and any typed params.
 */
export function fromApiFailure(
  error: {message: string; code?: string; params?: ErrorParams},
  fallback: string
): {success: false; error: {message: string; code?: string; params?: ErrorParams}} {
  return {
    success: false,
    error: {message: error.message || fallback, code: error.code, ...(error.params ? {params: error.params} : {})}
  };
}

/**
 * Drops a successful result's payload, keeping the failure as it is.
 *
 * The enqueue routes all answer `{requestId}`, but six of the services that call them have always
 * returned `ServiceResult<void>` and their callers are written against that. Rather than widen six
 * signatures — which would touch every hook and dialog above them for a value none of them reads —
 * the payload is discarded here.
 *
 * @param result - The result to narrow.
 * @returns The same result with its payload dropped.
 */
export function discardPayload<T>(result: ServiceResult<T>): ServiceResult<void> {
  return result.success ? {success: true, data: undefined} : result;
}
