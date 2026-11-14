import 'server-only';

/** A signal that aborts after a bound, and a way to stand it down once the bounded work is done. */
export type Deadline = {signal: AbortSignal; clear: () => void};

/**
 * A signal that aborts after a bound. Built on `setTimeout`, so a test's fake clock drives it.
 *
 * Callers clear it once the bounded step is over, so a signal still attached to a response body
 * cannot cut that body off after the step it bounded has finished.
 *
 * @param milliseconds - The bound.
 * @returns The signal and its `clear`.
 */
export function deadline(milliseconds: number): Deadline {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new DOMException('deadline passed', 'TimeoutError')), milliseconds);
  (timer as {unref?: () => void}).unref?.();
  return {signal: controller.signal, clear: () => clearTimeout(timer)};
}
