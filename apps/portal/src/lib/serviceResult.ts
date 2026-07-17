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
  const e = err as {message?: string; name?: string};
  return {success: false, error: {message: e.message ?? fallback, code: e.name}};
}
