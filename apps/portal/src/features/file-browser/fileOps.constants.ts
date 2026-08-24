/**
 * The plane's own bounds, as the browser needs them.
 *
 * Mirrored values, never independently chosen: a test under `lambdas/` reads the Terraform back
 * and fails if the two drift, because the failure is otherwise invisible — an in-flight entry
 * expiring early tells the user an operation is over while it is still running, and one expiring
 * late holds the per-space gate past the point where anything could still settle it.
 */

/**
 * The state machine's `TimeoutSeconds`, from `infra/modules/file-ops/locals.tf`.
 *
 * The outer bound on an in-flight entry: past it the execution is gone, so a notification is no
 * longer coming and there is nothing left to correlate. It is a belt-and-braces bound, not the
 * mechanism — an entry normally settles when a notification carrying its `requestId` arrives.
 */
export const FILE_OPS_MACHINE_TIMEOUT_SECONDS = 10_800;
