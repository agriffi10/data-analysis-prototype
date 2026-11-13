/**
 * Refuse to start, once, at server start, when the configuration the portal needs is missing.
 *
 * Node runtime only, and through a dynamic import, so the edge compilation of this file never
 * reaches the process-level code. `next build` does not run this hook, so the image builds with no
 * configuration in its environment.
 *
 * @returns Nothing; the process exits when a required value is unset, empty or unsafe.
 */
export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME !== 'nodejs') return;
  const {refuseToStartWithoutConfiguration} = await import('./server/runtimeDocument');
  refuseToStartWithoutConfiguration();
}
